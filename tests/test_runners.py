"""The runner interface: bounded retries, honest telemetry, and a dry run
that touches no provider.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tests import support
from workflows import runners
from workflows.runners import codex
from workflows.semantics import check_document

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["result", "notes"],
    "properties": {
        "result": {"type": "string", "enum": ["PASS", "FAIL"]},
        "notes": {"type": "string", "minLength": 1},
    },
}

VALID_OUTPUT = {"result": "PASS", "notes": "nothing to report"}
INVALID_OUTPUT = {"result": "MAYBE", "notes": "nothing to report"}

CONTRACT_REF = {
    "contract_id": "contract-example",
    "contract_revision": 1,
    "digest": "sha256:" + "4" * 64,
}
NOW = "2026-07-31T12:00:00Z"


def telemetry(**overrides) -> runners.Telemetry:
    settings = {
        "runner": "fake",
        "model": "worker-class",
        "effort": "medium",
        "dry": False,
        "duration_ms": 10,
        "tokens": runners.TokenUsage(new_input=100, cached_input=50, output=10),
    }
    settings.update(overrides)
    return runners.Telemetry(**settings)


class FakeRunner:
    """Records every call and returns scripted results."""

    name = "fake"

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[runners.RunnerCall] = []

    def invoke(self, call: runners.RunnerCall) -> runners.RunnerResult:
        self.calls.append(call)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, runners.RunnerResult):
            return outcome
        return runners.RunnerResult(
            status="COMPLETED", reason_code="clean", telemetry=telemetry(), output=outcome
        )


def a_call(**overrides) -> runners.RunnerCall:
    settings = {
        "prompt": "compose me",
        "output_schema": OUTPUT_SCHEMA,
        "model": "worker-class",
        "effort": "medium",
        "cwd": Path("."),
        "lens_id": "review/closed-contract",
        "step_id": "review-level-1",
    }
    settings.update(overrides)
    return runners.RunnerCall(**settings)


class CallValidationTest(unittest.TestCase):
    def test_an_unknown_sandbox_is_an_author_error(self) -> None:
        with self.assertRaises(runners.RunnerError):
            a_call(sandbox="anything-goes")

    def test_an_empty_prompt_is_refused(self) -> None:
        with self.assertRaises(runners.RunnerError):
            a_call(prompt="   ")


class BoundedRetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = support.registry()

    def test_valid_output_needs_no_retry(self) -> None:
        runner = FakeRunner(VALID_OUTPUT)
        result = runners.invoke_validated(runner, a_call(), registry=self.registry)
        self.assertTrue(result.completed)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(result.output, VALID_OUTPUT)

    def test_invalid_output_buys_exactly_one_retry_that_carries_the_error(self) -> None:
        runner = FakeRunner(INVALID_OUTPUT, VALID_OUTPUT)
        result = runners.invoke_validated(runner, a_call(), registry=self.registry)
        self.assertTrue(result.completed)
        self.assertEqual(len(runner.calls), 2)
        retry = runner.calls[1].prompt
        self.assertIn("Previous attempt rejected", retry)
        self.assertIn("enum", retry)
        self.assertIn("/result", retry)
        self.assertTrue(retry.startswith("compose me"))

    def test_twice_invalid_fails_and_never_loops(self) -> None:
        runner = FakeRunner(INVALID_OUTPUT, INVALID_OUTPUT)
        result = runners.invoke_validated(runner, a_call(), registry=self.registry)
        self.assertFalse(result.completed)
        self.assertEqual(result.reason_code, "schema_invalid")
        self.assertEqual(len(runner.calls), runners.MAX_ATTEMPTS)
        self.assertEqual(len(result.attempts), runners.MAX_ATTEMPTS)
        self.assertIsNone(result.output)
        self.assertTrue(result.errors)

    def test_attempts_are_numbered_in_telemetry(self) -> None:
        runner = FakeRunner(INVALID_OUTPUT, VALID_OUTPUT)
        result = runners.invoke_validated(runner, a_call(), registry=self.registry)
        self.assertEqual([a.telemetry.attempt for a in result.attempts], [1, 2])

    def test_a_transport_failure_is_not_retried_as_a_schema_problem(self) -> None:
        failure = runners.RunnerResult(
            status="FAILED",
            reason_code="timeout",
            telemetry=telemetry(),
            detail="the call exceeded 900s",
        )
        runner = FakeRunner(failure)
        result = runners.invoke_validated(runner, a_call(), registry=self.registry)
        self.assertFalse(result.completed)
        self.assertEqual(result.reason_code, "timeout")
        self.assertEqual(len(runner.calls), 1)

    def test_a_failed_call_produces_a_schema_valid_envelope(self) -> None:
        for reason, outcomes in (
            ("schema_invalid", (INVALID_OUTPUT, INVALID_OUTPUT)),
            (
                "timeout",
                (
                    runners.RunnerResult(
                        status="FAILED",
                        reason_code="timeout",
                        telemetry=telemetry(),
                        detail="the call exceeded 900s",
                    ),
                ),
            ),
        ):
            with self.subTest(reason=reason):
                result = runners.invoke_validated(
                    FakeRunner(*outcomes), a_call(), registry=self.registry
                )
                envelope = runners.failed_envelope(
                    result,
                    run_id="run-0001",
                    step_id="review-level-1",
                    step_kind="review",
                    contract_ref=CONTRACT_REF,
                    produced_at=NOW,
                    dry_run=False,
                    lens_id="review/closed-contract",
                    ladder_level=1,
                )
                errors = check_document(
                    envelope, "envelope.schema.json", registry=self.registry
                )
                self.assertEqual([str(error) for error in errors], [])
                self.assertEqual(envelope["status"], "FAILED")
                self.assertTrue(envelope["non_claims"])
                self.assertIn(reason, envelope["findings"][0]["claim"])


class DryRunTest(unittest.TestCase):
    def test_a_dry_run_starts_no_process_at_all(self) -> None:
        runner = codex.DryRunner()
        with mock.patch.object(
            subprocess, "run", side_effect=AssertionError("a dry run called a provider")
        ):
            result = runner.invoke(a_call())
        self.assertTrue(result.completed)
        self.assertTrue(result.telemetry.dry)
        self.assertEqual(result.telemetry.tokens.to_document()["new_input"], 0)

    def test_a_dry_run_records_the_composed_call(self) -> None:
        runner = codex.DryRunner()
        runner.invoke(a_call(prompt="the exact composed prompt"))
        self.assertEqual(runner.calls[0].prompt, "the exact composed prompt")

    def test_the_stub_satisfies_the_output_schema(self) -> None:
        runner = codex.DryRunner()
        result = runners.invoke_validated(runner, a_call(), registry=support.registry())
        self.assertTrue(result.completed, result.detail)

    def test_stub_for_covers_the_shapes_the_schemas_use(self) -> None:
        stub = codex.stub_for(
            {
                "type": "object",
                "required": ["digest", "count", "flag", "items", "kind"],
                "properties": {
                    "digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                    "count": {"type": "integer", "minimum": 2},
                    "flag": {"type": "boolean"},
                    "items": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                    "kind": {"type": "string", "enum": ["a", "b"]},
                },
            }
        )
        self.assertTrue(stub["digest"].startswith("sha256:"))
        self.assertEqual(stub["count"], 2)
        self.assertIs(stub["flag"], False)
        self.assertEqual(len(stub["items"]), 1)
        self.assertEqual(stub["kind"], "a")


class TelemetryParsingTest(unittest.TestCase):
    def test_usage_takes_the_final_figure_and_never_the_sum(self) -> None:
        """The aggregation trap: cumulative and per-turn numbers are never added."""
        events = [
            {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 5}},
            {"type": "turn.completed", "usage": {"input_tokens": 250, "output_tokens": 12}},
            {"type": "turn.completed", "usage": {"input_tokens": 400, "output_tokens": 20}},
        ]
        usage, count = codex.call_usage(events)
        self.assertEqual(usage.new_input, 400)
        self.assertEqual(usage.output, 20)
        self.assertNotEqual(usage.new_input, 100 + 250 + 400)
        self.assertEqual(count, 3)

    def test_cached_input_is_never_folded_into_new_input(self) -> None:
        events = [
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 17907,
                    "cached_input_tokens": 9100,
                    "cache_write_input_tokens": 12,
                    "output_tokens": 15,
                    "reasoning_output_tokens": 3,
                },
            }
        ]
        usage, _ = codex.call_usage(events)
        document = usage.to_document()
        self.assertEqual(document["new_input"], 17907)
        self.assertEqual(document["cached_input"], 9100)
        self.assertEqual(document["cache_write_input"], 12)
        self.assertEqual(document["reasoning_output"], 3)

    def test_no_usage_events_gives_zeros_not_a_crash(self) -> None:
        usage, count = codex.call_usage([{"type": "thread.started"}])
        self.assertEqual((usage.new_input, usage.output, count), (0, 0, 0))

    def test_non_json_lines_in_the_stream_are_skipped(self) -> None:
        stdout = "\n".join(
            [
                '{"type":"thread.started","thread_id":"x"}',
                "2026-07-31T18:29:22Z ERROR transport: worker quit with fatal",
                "not json at all",
                '{"type":"turn.completed","usage":{"input_tokens":7,"output_tokens":1}}',
            ]
        )
        events = codex.parse_events(stdout)
        self.assertEqual([event["type"] for event in events], ["thread.started", "turn.completed"])

    def test_the_final_agent_message_wins_and_error_items_are_ignored(self) -> None:
        events = [
            {"type": "item.completed", "item": {"id": "0", "type": "error", "message": "a warning"}},
            {"type": "item.completed", "item": {"id": "1", "type": "agent_message", "text": '{"a":1}'}},
            {"type": "item.completed", "item": {"id": "2", "type": "agent_message", "text": '{"a":2}'}},
        ]
        self.assertEqual(codex.final_message(events), '{"a":2}')

    def test_no_agent_message_is_reported_not_guessed(self) -> None:
        self.assertIsNone(codex.final_message([{"type": "turn.started"}]))


class CodexInvocationTest(unittest.TestCase):
    def test_the_argv_matches_the_documented_invocation_contract(self) -> None:
        runner = codex.CodexRunner()
        argv = runner.argv(a_call(cwd=Path("/work")), Path("/tmp/schema.json"))
        # argv[0] is resolved through PATHEXT, so it may be codex.CMD on
        # Windows and a bare name where nothing is installed.
        self.assertEqual(Path(argv[0]).stem.lower(), "codex")
        self.assertEqual(argv[1:3], ["exec", "--json"])
        self.assertIn("--skip-git-repo-check", argv)
        self.assertIn("--ephemeral", argv)
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--output-schema", argv)
        self.assertIn("-s", argv)
        self.assertIn("read-only", argv)
        self.assertIn(f"{codex.EFFORT_CONFIG_KEY}=medium", argv)
        self.assertEqual(argv[-1], "-", "the prompt goes on stdin, never in argv")

    def test_the_prompt_is_never_an_argv_element(self) -> None:
        runner = codex.CodexRunner()
        prompt = 'Return {"answer":"pong"} and nothing else.'
        argv = runner.argv(a_call(prompt=prompt), Path("/tmp/schema.json"))
        self.assertNotIn(prompt, argv)

    def test_the_launcher_is_resolved_through_pathext(self) -> None:
        # An npm-installed CLI on Windows is a .cmd shim, and CreateProcess
        # does not apply PATHEXT to a bare name. The first live smoke test of
        # this runner failed with WinError 2 for exactly this reason.
        runner = codex.CodexRunner(executable="whatever-is-not-installed")
        self.assertEqual(runner.resolve_executable(), "whatever-is-not-installed")
        with mock.patch.object(codex.shutil, "which", return_value="/opt/bin/codex.CMD"):
            self.assertEqual(runner.resolve_executable(), "/opt/bin/codex.CMD")

    def test_an_executable_given_as_a_path_is_used_as_given(self) -> None:
        given = str(Path("opt") / "codex" / "bin" / "codex")
        runner = codex.CodexRunner(executable=given)
        with mock.patch.object(codex.shutil, "which", return_value="elsewhere/codex"):
            self.assertEqual(runner.resolve_executable(), given)

    def test_a_missing_executable_fails_with_telemetry(self) -> None:
        runner = codex.CodexRunner(executable="definitely-not-codex-xyz")
        result = runner.invoke(a_call())
        self.assertEqual((result.status, result.reason_code), ("FAILED", "command_not_found"))
        self.assertFalse(result.telemetry.dry)
        self.assertEqual(result.telemetry.runner, "codex")

    def test_a_timeout_fails_with_telemetry_instead_of_hanging(self) -> None:
        runner = codex.CodexRunner()
        with mock.patch.object(
            codex.subprocess, "run", side_effect=subprocess.TimeoutExpired("codex", 1)
        ):
            result = runner.invoke(a_call(timeout_seconds=1))
        self.assertEqual((result.status, result.reason_code), ("FAILED", "timeout"))
        self.assertGreaterEqual(result.telemetry.duration_ms, 0)

    def test_stdout_and_stderr_are_read_separately(self) -> None:
        runner = codex.CodexRunner()
        completed = subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout='{"type":"item.completed","item":{"type":"agent_message","text":"{\\"result\\":\\"PASS\\",\\"notes\\":\\"ok\\"}"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":9,"output_tokens":2}}\n',
            stderr="ERROR transport: unrelated diagnostic\n",
        )
        with mock.patch.object(codex.subprocess, "run", return_value=completed) as run:
            result = runner.invoke(a_call())
            self.assertIs(run.call_args.kwargs["capture_output"], True)
        self.assertTrue(result.completed)
        self.assertEqual(result.output, {"result": "PASS", "notes": "ok"})
        self.assertEqual(result.telemetry.tokens.new_input, 9)

    def test_a_nonzero_exit_is_a_failed_call(self) -> None:
        runner = codex.CodexRunner()
        completed = subprocess.CompletedProcess(
            args=["codex"], returncode=2, stdout="", stderr="bad flag"
        )
        with mock.patch.object(codex.subprocess, "run", return_value=completed):
            result = runner.invoke(a_call())
        self.assertEqual((result.status, result.reason_code), ("FAILED", "nonzero_exit"))

    def test_a_non_json_final_message_is_a_failed_call_not_a_guess(self) -> None:
        runner = codex.CodexRunner()
        completed = subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout='{"type":"item.completed","item":{"type":"agent_message","text":"Sure! Here you go."}}\n',
            stderr="",
        )
        with mock.patch.object(codex.subprocess, "run", return_value=completed):
            result = runner.invoke(a_call())
        self.assertEqual((result.status, result.reason_code), ("FAILED", "unparseable_output"))

    def test_the_output_schema_is_written_for_the_cli_to_read(self) -> None:
        runner = codex.CodexRunner()
        seen: dict[str, object] = {}

        def capture(argv, **kwargs):
            index = argv.index("--output-schema")
            seen["schema"] = json.loads(Path(argv[index + 1]).read_text(encoding="utf-8"))
            seen["stdin"] = kwargs["input"]
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

        with mock.patch.object(codex.subprocess, "run", side_effect=capture):
            runner.invoke(a_call(prompt="the composed prompt"))
        self.assertEqual(seen["schema"], OUTPUT_SCHEMA)
        self.assertEqual(seen["stdin"], "the composed prompt")


if __name__ == "__main__":
    unittest.main()
