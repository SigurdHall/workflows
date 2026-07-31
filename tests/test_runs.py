"""The run directory: append-only artifacts, one mutable manifest.

A resume that replays completed model calls because nothing recorded their
completion is the failure this module exists to prevent, so the tests are
about what survives a kill and what refuses to be rewritten.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import support
from workflows import runs
from workflows.semantics import check_document

NOW = "2026-07-31T12:00:00Z"

MANIFEST = {
    "schema_version": "workflows.run-manifest.v1",
    "run_id": "run-0001",
    "kind": "flow",
    "flow": "implement",
    "dry_run": True,
    "created_at": NOW,
    "updated_at": NOW,
    "base": [{"repo_id": "target", "commit": "a" * 40}],
    "steps": [],
}


class RunDirectoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.run = runs.RunDirectory(Path(self._tmp.name) / "run-0001").create(dict(MANIFEST))
        self.registry = support.registry()

    def test_layout_and_manifest(self) -> None:
        for directory in (self.run.envelopes, self.run.prompts, self.run.gates):
            self.assertTrue(directory.is_dir())
        self.assertEqual(self.run.read_manifest()["run_id"], "run-0001")
        self.assertTrue(self.run.exists)

    def test_creating_twice_refuses(self) -> None:
        with self.assertRaises(runs.RunError):
            self.run.create(dict(MANIFEST))

    def test_writing_the_same_artifact_twice_is_idempotent(self) -> None:
        first = self.run.write_artifact("envelopes/work-1.json", {"a": 1})
        second = self.run.write_artifact("envelopes/work-1.json", {"a": 1})
        self.assertEqual(first, second)
        self.assertEqual(self.run.read_artifact("envelopes/work-1.json"), {"a": 1})

    def test_rewriting_an_artifact_with_different_content_refuses(self) -> None:
        self.run.write_artifact("envelopes/work-1.json", {"a": 1})
        with self.assertRaises(runs.RunError):
            self.run.write_artifact("envelopes/work-1.json", {"a": 2})
        self.assertEqual(self.run.read_artifact("envelopes/work-1.json"), {"a": 1})

    def test_telemetry_appends(self) -> None:
        self.run.append_telemetry({"call": 1, "tokens": {"new_input": 10}})
        self.run.append_telemetry({"call": 2, "tokens": {"new_input": 20}})
        records = self.run.telemetry()
        self.assertEqual([record["call"] for record in records], [1, 2])

    def test_step_records_are_inserted_then_updated(self) -> None:
        self.run.record_step(
            {"step_id": "work-1", "kind": "work", "state": "RUNNING", "attempt": 1},
            now=NOW,
        )
        self.assertFalse(self.run.is_completed("work-1"))
        self.run.record_step(
            {"step_id": "work-1", "state": "COMPLETED", "finished_at": NOW}, now=NOW
        )
        self.assertTrue(self.run.is_completed("work-1"))
        steps = self.run.read_manifest()["steps"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["kind"], "work")  # merged, not replaced

    def test_unknown_step_is_not_completed(self) -> None:
        self.assertIsNone(self.run.step("never-existed"))
        self.assertFalse(self.run.is_completed("never-existed"))

    def test_the_manifest_stays_schema_valid_as_steps_are_recorded(self) -> None:
        self.run.record_step(
            {
                "step_id": "gates-level-0",
                "kind": "gate",
                "state": "COMPLETED",
                "attempt": 1,
                "started_at": NOW,
                "finished_at": NOW,
                "envelope_path": "envelopes/gates-level-0.json",
            },
            now=NOW,
        )
        errors = check_document(
            self.run.read_manifest(), runs.MANIFEST_SCHEMA, registry=self.registry
        )
        self.assertEqual([str(error) for error in errors], [])

    def test_gate_results_are_written_into_the_run(self) -> None:
        from workflows import gates

        results = [
            gates.GateResult("scope", "PASS", "clean", NOW),
            gates.GateResult("protected_hash", "FAIL", "protected_modified", NOW),
        ]
        written = gates.write_gate_results(results, self.run, step_id="gates-pre", attempt=1)
        self.assertEqual(
            written, ["gates/gates-pre/scope.1.json", "gates/gates-pre/protected_hash.1.json"]
        )
        for relative, result in zip(written, results):
            document = self.run.read_artifact(relative)
            self.assertEqual(document["gate_id"], result.gate_id)
            errors = check_document(document, gates.GATE_SCHEMA, registry=self.registry)
            self.assertEqual([str(error) for error in errors], [])

    def test_a_second_attempt_does_not_overwrite_the_first(self) -> None:
        from workflows import gates

        gates.write_gate_results(
            [gates.GateResult("scope", "FAIL", "out_of_scope_change", NOW)],
            self.run,
            step_id="gates-post",
            attempt=1,
        )
        gates.write_gate_results(
            [gates.GateResult("scope", "PASS", "clean", NOW)],
            self.run,
            step_id="gates-post",
            attempt=2,
        )
        self.assertEqual(self.run.read_artifact("gates/gates-post/scope.1.json")["result"], "FAIL")
        self.assertEqual(self.run.read_artifact("gates/gates-post/scope.2.json")["result"], "PASS")

    def test_the_same_gate_in_different_steps_does_not_collide(self) -> None:
        from workflows import gates

        result = gates.GateResult("base_identity", "PASS", "clean", NOW)
        gates.write_gate_results([result], self.run, step_id="gates-pre")
        gates.write_gate_results([result], self.run, step_id="gates-post-r0")
        self.assertTrue((self.run.gates / "gates-pre" / "base_identity.1.json").is_file())
        self.assertTrue((self.run.gates / "gates-post-r0" / "base_identity.1.json").is_file())

    def test_no_temporary_file_survives_a_manifest_write(self) -> None:
        self.run.record_step({"step_id": "s", "kind": "gate", "state": "PENDING", "attempt": 1})
        leftovers = list(self.run.root.glob("*.tmp"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
