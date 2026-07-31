"""The runner interface: the only way a flow reaches a model.

A call carries model, effort, composed prompt, expected output schema,
working directory, sandbox policy and timeout; a result carries structured
output plus telemetry. Flows name ladder levels and worker classes;
a deployment profile resolves them to concrete models, so adding a
cross-family runner is a module, not a refactor (ADR 0005).

Two disciplines live here rather than in any single runner, so every runner
inherits them identically:

* **Bounded retry.** Output that fails its schema buys exactly one more
  attempt, carrying the validation errors. Then the call is FAILED. Never a
  silent pass, never an unbounded loop.
* **Honest telemetry.** New input, cached input and output tokens are
  recorded separately and never summed into one number — an aggregate that
  mixes cached and new input overstates cost several-fold. Within one call,
  exactly one usage figure is recorded: the final one. Cumulative and
  per-turn figures are never added together.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, Sequence

from workflows.schema import SchemaRegistry, ValidationError, validate

MAX_ATTEMPTS = 2
"""One call, plus exactly one bounded retry."""

SANDBOXES = ("read-only", "workspace-write", "danger-full-access")


class RunnerError(RuntimeError):
    """The runner was configured wrongly — an author error, not a model error."""


@dataclass(frozen=True)
class TokenUsage:
    new_input: int = 0
    cached_input: int = 0
    output: int = 0
    cache_write_input: int | None = None
    reasoning_output: int | None = None

    def to_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "new_input": self.new_input,
            "cached_input": self.cached_input,
            "output": self.output,
        }
        if self.cache_write_input is not None:
            document["cache_write_input"] = self.cache_write_input
        if self.reasoning_output is not None:
            document["reasoning_output"] = self.reasoning_output
        return document


@dataclass(frozen=True)
class Telemetry:
    runner: str
    model: str
    effort: str
    dry: bool
    duration_ms: int
    tokens: TokenUsage
    lens_id: str | None = None
    attempt: int = 1
    usage_events: int = 0

    def to_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "runner": self.runner,
            "model": self.model,
            "effort": self.effort,
            "dry": self.dry,
            "duration_ms": self.duration_ms,
            "tokens": self.tokens.to_document(),
            "attempt": self.attempt,
        }
        if self.lens_id:
            document["lens_id"] = self.lens_id
        return document

    def to_record(self, **extra: Any) -> dict[str, Any]:
        """One line for telemetry.jsonl, including the fields the schema omits."""
        return {**self.to_document(), "usage_events": self.usage_events, **extra}


@dataclass(frozen=True)
class RunnerCall:
    prompt: str
    output_schema: dict[str, Any]
    model: str
    effort: str
    cwd: Path
    sandbox: str = "read-only"
    timeout_seconds: int = 900
    lens_id: str | None = None
    step_id: str = "call"

    def __post_init__(self) -> None:
        if self.sandbox not in SANDBOXES:
            raise RunnerError(f"unknown sandbox {self.sandbox!r}; expected one of {SANDBOXES}")
        if not self.prompt.strip():
            raise RunnerError("refusing to call a model with an empty prompt")


@dataclass(frozen=True)
class RunnerResult:
    """One invocation. ``output`` is None unless the model returned an object."""

    status: str  # COMPLETED | FAILED
    reason_code: str
    telemetry: Telemetry
    output: dict[str, Any] | None = None
    detail: str | None = None
    raw: str | None = None

    @property
    def completed(self) -> bool:
        return self.status == "COMPLETED"


@dataclass(frozen=True)
class ValidatedResult:
    """The outcome of a call plus its bounded retry."""

    status: str
    reason_code: str
    attempts: tuple[RunnerResult, ...]
    errors: tuple[ValidationError, ...] = ()
    output: dict[str, Any] | None = None
    detail: str | None = None

    @property
    def completed(self) -> bool:
        return self.status == "COMPLETED"

    @property
    def telemetry(self) -> Telemetry:
        return self.attempts[-1].telemetry

    @property
    def records(self) -> list[dict[str, Any]]:
        return [attempt.telemetry.to_record(step_id="") for attempt in self.attempts]


class Runner(Protocol):
    """What a flow may assume about any runner."""

    name: str

    def invoke(self, call: RunnerCall) -> RunnerResult: ...


RETRY_HEADER = (
    "## Previous attempt rejected\n\n"
    "Your previous response did not validate against the required output "
    "schema. The validator reported:\n\n"
)
RETRY_FOOTER = (
    "\n\nReturn one corrected JSON object. This is the final attempt: another "
    "invalid response ends the step as FAILED.\n"
)


def retry_prompt(prompt: str, errors: Sequence[ValidationError]) -> str:
    """The retry prompt: the original, plus exactly what was wrong with the answer."""
    listing = "\n".join(f"- {error}" for error in errors[:20])
    return prompt.rstrip() + "\n\n" + RETRY_HEADER + listing + RETRY_FOOTER


def invoke_validated(
    runner: Runner,
    call: RunnerCall,
    *,
    registry: SchemaRegistry | None = None,
) -> ValidatedResult:
    """Invoke, validate, and retry once at most.

    A model that answers with the wrong shape twice has told you something;
    a driver that keeps asking has not.
    """
    attempts: list[RunnerResult] = []
    errors: tuple[ValidationError, ...] = ()
    current = call

    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = runner.invoke(current)
        result = replace(result, telemetry=replace(result.telemetry, attempt=attempt))
        attempts.append(result)

        if not result.completed:
            # A transport failure is not a schema failure: retrying a timeout
            # with a validation complaint attached would be nonsense.
            return ValidatedResult(
                status="FAILED",
                reason_code=result.reason_code,
                attempts=tuple(attempts),
                detail=result.detail,
            )

        errors = tuple(
            validate(result.output, call.output_schema, registry=registry)
        )
        if not errors:
            return ValidatedResult(
                status="COMPLETED",
                reason_code="clean",
                attempts=tuple(attempts),
                output=result.output,
            )

        if attempt == MAX_ATTEMPTS:
            break
        current = replace(call, prompt=retry_prompt(call.prompt, errors))

    return ValidatedResult(
        status="FAILED",
        reason_code="schema_invalid",
        attempts=tuple(attempts),
        errors=errors,
        detail="; ".join(str(error) for error in errors[:20]),
    )


def failed_envelope(
    result: ValidatedResult,
    *,
    run_id: str,
    step_id: str,
    step_kind: str,
    contract_ref: dict[str, Any],
    produced_at: str,
    dry_run: bool,
    lens_id: str | None = None,
    ladder_level: int | None = None,
) -> dict[str, Any]:
    """The envelope a failed model call produces. A failure is a record, not an exception."""
    evidence = [
        {
            "id": f"call/attempt-{index + 1}",
            "kind": "log",
            "ref": f"telemetry.jsonl#{step_id}/attempt-{index + 1}",
            "excerpt": (attempt.detail or attempt.reason_code)[:4000],
        }
        for index, attempt in enumerate(result.attempts)
    ]
    envelope: dict[str, Any] = {
        "schema_version": "workflows.envelope.v1",
        "envelope_id": f"{run_id}/{step_id}",
        "run_id": run_id,
        "step_id": step_id,
        "step_kind": step_kind,
        "status": "FAILED",
        "terminal": True,
        "result": "NOT_RUN" if result.reason_code != "schema_invalid" else "FAIL",
        "dry_run": dry_run,
        "produced_at": produced_at,
        "contract_ref": contract_ref,
        "evidence": evidence,
        "criterion_results": [],
        "findings": [
            {
                "id": f"{step_id}-failed",
                "severity": "HIGH",
                "status": "OPEN",
                "claim": f"The model call failed: {result.reason_code}."
                + (f" {result.detail}" if result.detail else ""),
                "evidence_refs": [item["id"] for item in evidence] or [],
                "required_action": "Re-run the step, or fix the call that produced it.",
                "negative_path_claim": False,
                **({"lens_id": lens_id} if lens_id else {}),
            }
        ],
        "non_claims": [
            "This step produced no usable output; nothing about the candidate "
            "was established by it.",
            f"Attempts made: {len(result.attempts)} of {MAX_ATTEMPTS} allowed.",
        ],
        "side_effects": [{"kind": "none", "target": "none"}],
        "telemetry": result.telemetry.to_document(),
    }
    if lens_id:
        envelope["lens_id"] = lens_id
    if ladder_level is not None:
        envelope["ladder_level"] = ladder_level
    if not envelope["findings"][0]["evidence_refs"]:
        envelope["evidence"] = [
            {"id": "call/no-attempt", "kind": "log", "ref": "telemetry.jsonl"}
        ]
        envelope["findings"][0]["evidence_refs"] = ["call/no-attempt"]
    return envelope


__all__ = [
    "MAX_ATTEMPTS",
    "Runner",
    "RunnerCall",
    "RunnerError",
    "RunnerResult",
    "Telemetry",
    "TokenUsage",
    "ValidatedResult",
    "failed_envelope",
    "invoke_validated",
    "retry_prompt",
]
