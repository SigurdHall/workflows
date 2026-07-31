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
        argv.extend(self.extra_args)
        argv.append("-")  # read the prompt from stdin
        return argv

    def invoke(self, call: RunnerCall) -> RunnerResult:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="workflows-codex-") as scratch:
            schema_path = Path(scratch) / "output-schema.json"
            schema_path.write_text(
                json.dumps(call.output_schema, indent=2, sort_keys=True), encoding="utf-8"
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
            return RunnerResult(
                status="FAILED",
                reason_code="nonzero_exit",
                telemetry=telemetry,
                detail=f"exit {completed.returncode}: {completed.stderr.strip()[:2000]}",
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
            output=output,
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
    if "$ref" in schema:
        registry = registry if registry is not None else schema_module.default_registry()
        target, owner = schema_module._resolve_ref(schema["$ref"], document or schema, registry)
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
