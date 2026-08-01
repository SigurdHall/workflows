"""Codex CLI runner: headless `codex exec`.

The invocation contract, verified against the installed CLI, is documented
in `runners/README.md`. Four details are load-bearing and each is here for a
reason that was observed, not assumed:

* The prompt goes on **stdin**. Passed as an argv string, a prompt
  containing JSON braces and quotes is mangled by the shell before Codex
  ever sees it.
* stdout and stderr are captured **separately**. Merged, a single stderr
  line lands inside the JSONL event stream and corrupts it. Unparseable
  stdout lines are skipped rather than treated as failures.
* `--ignore-user-config` keeps the run reproducible: the composed prompt
  should be the only input, and a machine's personal configuration is not
  part of a run's record.
* An `item.completed` with `item.type == "error"` is not a failed call —
  the CLI emits those for non-fatal warnings and still exits zero.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from workflows import schema as schema_module
from workflows.runners import RunnerCall, RunnerResult, Telemetry, TokenUsage

NAME = "codex"
EFFORT_CONFIG_KEY = "model_reasoning_effort"


@dataclass
class CodexRunner:
    """Invoke `codex exec` once per call."""

    executable: str = "codex"
    name: str = NAME
    ignore_user_config: bool = True
    extra_args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    registry: Any = None
    bypass_sandbox: bool = False
    """Run the model without the provider's sandbox.

    Off by default. Turn it on only where the provider's sandbox refuses
    writes a producing role legitimately needs — on some hosts
    `workspace-write` still reports a read-only workspace, and a worker that
    cannot write produces an empty candidate.

    What bounds the risk when it is on is not the provider: it is that the
    worker runs in a worktree this flow created from a frozen base, and that
    the scope, protected-hash and base-identity gates check every path it
    touched afterwards. The sandbox is defence in depth; the gates are the
    check. Never turn this on for a worktree you have not framed that way.
    """

    def resolve_executable(self) -> str:
        """Find the launcher on PATH before spawning it.

        On Windows an npm-installed CLI is a `.cmd`/`.ps1` shim, and
        `CreateProcess` does not apply PATHEXT to a bare name — the first
        live smoke test of this runner failed with WinError 2 for exactly
        that reason. `shutil.which` applies PATHEXT; if it finds nothing the
        bare name is passed through so the failure is still reported as
        `command_not_found` rather than raised here.
        """
        if Path(self.executable).parent != Path("."):
            return self.executable  # already a path, not a bare name
        return shutil.which(self.executable) or self.executable

    def argv(self, call: RunnerCall, schema_path: Path) -> list[str]:
        argv = [
            self.resolve_executable(),
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--ephemeral",
            "-C",
            str(call.cwd),
            "-s",
            call.sandbox,
            "--output-schema",
            str(schema_path),
            "-m",
            call.model,
            "-c",
            f"{EFFORT_CONFIG_KEY}={call.effort}",
        ]
        if self.ignore_user_config:
            argv.append("--ignore-user-config")
        if self.bypass_sandbox:
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        argv.extend(self.extra_args)
        argv.append("-")  # read the prompt from stdin
        return argv

    def invoke(self, call: RunnerCall) -> RunnerResult:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="workflows-codex-") as scratch:
            schema_path = Path(scratch) / "output-schema.json"
            # Flattened before it leaves the process: the provider will not
            # follow a reference out of the document, and rejects references
            # that are not to a top-level definition. Our schemas are layered
            # on a shared $defs library, so what validates here is not what a
            # provider can be handed.
            schema_path.write_text(
                json.dumps(
                    provider_schema(call.output_schema, self.registry),
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            try:
                completed = subprocess.run(
                    self.argv(call, schema_path),
                    input=call.prompt,
                    cwd=str(call.cwd),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=call.timeout_seconds,
                    env=self.env,
                )
            except FileNotFoundError as exc:
                return self._failure(
                    call, started, "command_not_found", f"{self.executable!r}: {exc}"
                )
            except subprocess.TimeoutExpired:
                return self._failure(
                    call,
                    started,
                    "timeout",
                    f"the call exceeded {call.timeout_seconds}s and was terminated",
                )

        events = parse_events(completed.stdout)
        usage, usage_events = call_usage(events)
        telemetry = Telemetry(
            runner=self.name,
            model=call.model,
            effort=call.effort,
            dry=False,
            duration_ms=_elapsed_ms(started),
            tokens=usage,
            lens_id=call.lens_id,
            usage_events=usage_events,
        )

        if completed.returncode != 0:
            # The provider's own message arrives as an event, not on stderr.
            # Reporting "exit 1" alone throws away the only sentence that says
            # what went wrong.
            reported = reported_error(events) or completed.stderr.strip()
            return RunnerResult(
                status="FAILED",
                reason_code="nonzero_exit",
                telemetry=telemetry,
                detail=f"exit {completed.returncode}: {reported[:2000]}",
                raw=completed.stdout,
            )

        message = final_message(events)
        if message is None:
            return RunnerResult(
                status="FAILED",
                reason_code="no_output",
                telemetry=telemetry,
                detail="the call produced no agent message",
                raw=completed.stdout,
            )
        try:
            output = json.loads(message)
        except json.JSONDecodeError as exc:
            return RunnerResult(
                status="FAILED",
                reason_code="unparseable_output",
                telemetry=telemetry,
                detail=f"the final message is not JSON: {exc}",
                raw=message,
            )
        if not isinstance(output, dict):
            return RunnerResult(
                status="FAILED",
                reason_code="unparseable_output",
                telemetry=telemetry,
                detail="the final message is JSON but not an object",
                raw=message,
            )
        return RunnerResult(
            status="COMPLETED",
            reason_code="clean",
            telemetry=telemetry,
            output=drop_nulls(output),
            raw=message,
        )

    def _failure(
        self, call: RunnerCall, started: float, reason_code: str, detail: str
    ) -> RunnerResult:
        return RunnerResult(
            status="FAILED",
            reason_code=reason_code,
            telemetry=Telemetry(
                runner=self.name,
                model=call.model,
                effort=call.effort,
                dry=False,
                duration_ms=_elapsed_ms(started),
                tokens=TokenUsage(),
                lens_id=call.lens_id,
            ),
            detail=detail,
        )


@dataclass
class DryRunner:
    """Materializes the call and returns a stub. Calls no provider, ever.

    The stub is built from the output schema so downstream validation sees a
    document of the right shape; the telemetry says ``dry`` so nothing
    downstream can mistake it for evidence.
    """

    name: str = "dry"
    calls: list[RunnerCall] = field(default_factory=list)
    registry: Any = None

    def invoke(self, call: RunnerCall) -> RunnerResult:
        self.calls.append(call)
        return RunnerResult(
            status="COMPLETED",
            reason_code="dry_run",
            telemetry=Telemetry(
                runner=self.name,
                model=call.model,
                effort=call.effort,
                dry=True,
                duration_ms=0,
                tokens=TokenUsage(),
                lens_id=call.lens_id,
            ),
            output=_honest_stub(call.output_schema, self.registry),
            detail="dry run: the prompt was composed and recorded, no model was called",
        )


UNSUPPORTED_BY_PROVIDER = frozenset(
    {
        "uniqueItems",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
        "examples",
        "default",
        "deprecated",
        "title",
    }
)


def provider_schema(schema: dict[str, Any], registry: Any = None) -> dict[str, Any]:
    """The output schema as a provider will accept it.

    Two transformations, both forced by what the provider rejects: every
    ``$ref`` is expanded, because it will not follow one out of the document
    and refuses any that is not a top-level definition; and the constraint
    keywords outside its subset are dropped, because it rejects the whole
    request rather than ignoring them.

    What is dropped is *not* unenforced. The schema sent to the provider
    shapes the answer; the authoritative check is this repository's own
    validator, which sees the full schema and buys exactly one retry when the
    answer misses it. Treating the provider's copy as the gate would be
    trusting the party being checked.
    """
    registry = registry if registry is not None else schema_module.default_registry()
    flat = schema_module.inline(schema, registry=registry)
    return _strip_unsupported(flat)


def _strip_unsupported(schema: Any) -> Any:
    """Drop rejected keywords, and make every property required.

    The provider requires `required` to name every declared property — it has
    no notion of an optional field. An optional field therefore becomes a
    required nullable one, and the runner drops the nulls again before the
    answer reaches this repository's own validator.
    """
    if not isinstance(schema, dict):
        return schema
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key in UNSUPPORTED_BY_PROVIDER:
            continue
        if key == "properties" and isinstance(value, dict):
            result[key] = {name: _strip_unsupported(child) for name, child in value.items()}
        elif key in ("items", "additionalProperties") and isinstance(value, dict):
            result[key] = _strip_unsupported(value)
        else:
            result[key] = value

    properties = result.get("properties")
    if isinstance(properties, dict) and properties:
        required = list(result.get("required", []))
        optional = [name for name in properties if name not in required]
        for name in optional:
            properties[name] = _nullable(properties[name])
        result["required"] = required + optional
    return result


def _nullable(schema: Any) -> Any:
    """Let a field carry null, so the provider can require it and mean nothing."""
    if not isinstance(schema, dict):
        return schema
    declared = schema.get("type")
    if declared is None:
        return schema
    names = [declared] if isinstance(declared, str) else list(declared)
    if "null" not in names:
        names = names + ["null"]
    return {**schema, "type": names}


def _honest_stub(schema: dict[str, Any], registry: Any) -> Any:
    """A stub that claims nothing.

    ``stub_for`` picks the first allowed enum value, and for a result field
    that is PASS. A dry run that returns PASS-shaped stubs invites every
    consumer downstream to read a materialization exercise as a judgment, so
    any result the schema lets us leave unclaimed is set to NOT_RUN.
    """
    stub = stub_for(schema, registry)
    if not isinstance(stub, dict) or stub.get("result") not in ("PASS", "FAIL"):
        return stub
    candidate = {**stub, "result": "NOT_RUN"}
    registry = registry if registry is not None else schema_module.default_registry()
    if schema_module.validate(candidate, schema, registry=registry):
        return stub  # this schema does not allow an unclaimed result
    return candidate


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def parse_events(stdout: str) -> list[dict[str, Any]]:
    """Parse the JSONL event stream, skipping anything that is not an event.

    Lines that are not JSON objects are ignored rather than fatal: the CLI
    can interleave diagnostics, and a diagnostic is not a reason to lose a
    completed call.
    """
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "type" in event:
            events.append(event)
    return events


def final_message(events: Sequence[dict[str, Any]]) -> str | None:
    """The last agent message, which is the structured answer."""
    message: str | None = None
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item") or {}
        if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            message = item["text"]
    return message


def drop_nulls(value: Any) -> Any:
    """Remove null-valued keys, the provider's way of saying "absent".

    Optional fields are sent as required-and-nullable, so the answer comes
    back with explicit nulls where the model had nothing to say. None of this
    repository's model-facing schemas accepts a null, so removing them is
    lossless and turns "present and empty" back into "absent".
    """
    if isinstance(value, dict):
        return {
            key: drop_nulls(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [drop_nulls(item) for item in value if item is not None]
    return value


def reported_error(events: Sequence[dict[str, Any]]) -> str | None:
    """The provider's own account of a failure, from the event stream.

    A failed turn and a fatal error item both carry a message; stderr often
    carries nothing at all. The last one wins, because a turn that failed
    after a warning failed for the later reason.
    """
    message: str | None = None
    for event in events:
        if event.get("type") == "turn.failed":
            error = event.get("error") or {}
            if isinstance(error, dict) and error.get("message"):
                message = str(error["message"])
        elif event.get("type") == "error" and event.get("message"):
            message = str(event["message"])
    return message


def call_usage(events: Sequence[dict[str, Any]]) -> tuple[TokenUsage, int]:
    """Token usage for one call: the **final** usage figure, never a sum.

    The source telemetry carries both cumulative and per-turn numbers, and
    adding them together is the aggregation trap this repository was
    designed around — the motivating experiments logged ~29.6M "registered"
    tokens for a run whose real work was an order of magnitude smaller. The
    count of usage events is recorded alongside, so an undercount would be
    visible rather than silent.
    """
    usages = [
        event["usage"]
        for event in events
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict)
    ]
    if not usages:
        return TokenUsage(), 0
    last = usages[-1]
    return (
        TokenUsage(
            new_input=int(last.get("input_tokens", 0) or 0),
            cached_input=int(last.get("cached_input_tokens", 0) or 0),
            output=int(last.get("output_tokens", 0) or 0),
            cache_write_input=_optional_int(last.get("cache_write_input_tokens")),
            reasoning_output=_optional_int(last.get("reasoning_output_tokens")),
        ),
        len(usages),
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def stub_for(schema: dict[str, Any], registry: Any = None, document: Any = None) -> Any:
    """A minimal document satisfying the required parts of an output schema.

    References are resolved, because a stub that ignored ``$ref`` would be
    the wrong shape exactly where the shared definitions live — and a dry
    run whose stub fails validation tells you nothing about the flow.
    """
    if document is None:
        # The document is what same-document "#/$defs/..." references resolve
        # against; losing it one level down turns a valid schema into an
        # unresolvable reference.
        document = schema
    if "$ref" in schema:
        registry = registry if registry is not None else schema_module.default_registry()
        target, owner = schema_module._resolve_ref(schema["$ref"], document, registry)
        merged = {key: value for key, value in schema.items() if key != "$ref"}
        return stub_for({**target, **merged}, registry, owner)
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = kind[0]
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if kind == "object":
        properties = schema.get("properties", {})
        return {
            name: stub_for(properties.get(name, {}), registry, document)
            for name in schema.get("required", [])
        }
    if kind == "array":
        item = schema.get("items", {})
        minimum = schema.get("minItems", 0)
        return [stub_for(item, registry, document) for _ in range(minimum)]
    if kind == "integer" or kind == "number":
        return schema.get("minimum", 0)
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return _stub_string(schema)


def _stub_string(schema: dict[str, Any]) -> str:
    pattern = schema.get("pattern")
    minimum = schema.get("minLength", 0)
    if pattern:
        seed = _pattern_seed(pattern)
        if seed is not None:
            return seed
    text = "dry-run-stub"
    if len(text) < minimum:
        text = text + "-" * (minimum - len(text))
    return text


_KNOWN_PATTERN_SEEDS = {
    "^sha256:[0-9a-f]{64}$": "sha256:" + "0" * 64,
    "^[0-9a-f]{40}$": "0" * 40,
}


def _pattern_seed(pattern: str) -> str | None:
    if pattern in _KNOWN_PATTERN_SEEDS:
        return _KNOWN_PATTERN_SEEDS[pattern]
    if pattern.startswith("^[0-9]{4}-"):  # timestamp
        return "2026-01-01T00:00:00Z"
    if "workflows" in pattern:
        return None
    return "dry-run-stub"
