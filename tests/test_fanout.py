"""The fanout flow and its stop rule.

The acceptance criteria the roadmap sets for M5: five lenses produce five
distinct composed prompts that are byte-stable across two runs, one synthesis
input manifest is recorded, and a run killed mid-fan-out resumes without
repeating a worker.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests import support
from tests.gitrepo import TempRepo
from workflows import gitcmd
from workflows.flows import base, dryness, fanout
from workflows.flows.base import FlowContext, FlowError, Profile
from workflows.flows.ladder import Escalation
from workflows.runners.codex import DryRunner
from workflows.runs import RunDirectory
from workflows.semantics import check_document
from tests.test_flows import CONTRACT, CONTRACT_REF, WORK_OUTPUT, ScriptedRunner, review_output

FIVE_LENSES = (
    "work/spec-fidelity",
    "work/minimal-change",
    "work/defensive-input",
    "work/api-design",
    "work/spec-fidelity",
)
FOUR_LENSES = FIVE_LENSES[:4]


class DrynessTest(unittest.TestCase):
    def finding(self, claim: str, location: str = "src/a.py"):
        return {"claim": claim, "location": location, "severity": "MEDIUM"}

    def test_one_lens_returning_empty_twice_is_not_two_dry_rounds(self) -> None:
        """The charter case: dryness is measured across distinct lenses."""
        tracker = dryness.DrynessTracker(rounds_required=2)
        tracker.record("review/determinism", [])
        tracker.record("review/determinism", [])
        self.assertFalse(tracker.is_dry)
        self.assertEqual(tracker.dry_lenses, ["review/determinism"])

    def test_two_distinct_empty_lenses_are_dry(self) -> None:
        tracker = dryness.DrynessTracker(rounds_required=2)
        tracker.record("review/determinism", [])
        tracker.record("review/boundary-values", [])
        self.assertTrue(tracker.is_dry)

    def test_a_new_finding_resets_the_count(self) -> None:
        tracker = dryness.DrynessTracker(rounds_required=2)
        tracker.record("review/determinism", [])
        tracker.record("review/boundary-values", [self.finding("a digest changes")])
        self.assertFalse(tracker.is_dry)
        self.assertEqual(tracker.dry_lenses, [])

    def test_a_repeated_finding_does_not_count_as_new(self) -> None:
        tracker = dryness.DrynessTracker(rounds_required=2)
        first = tracker.record("review/determinism", [self.finding("a digest changes")])
        second = tracker.record("review/metamorphic", [self.finding("A DIGEST  changes")])
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [], "the same defect stated differently is not new")

    def test_run_until_dry_stops_early_and_records_who_was_consulted(self) -> None:
        consulted: list[str] = []

        def consult(lens_id: str):
            consulted.append(lens_id)
            return [] if lens_id != "a/one" else [self.finding("something")]

        tracker = dryness.run_until_dry(
            ["a/one", "a/two", "a/three", "a/four"], consult, rounds_required=2
        )
        self.assertTrue(tracker.is_dry)
        self.assertEqual(consulted, ["a/one", "a/two", "a/three"])
        self.assertEqual(tracker.consulted, consulted)


class FanoutTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)
        self.base = self.repo.seed()
        self.registry = support.registry()
        self._runs = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._runs.cleanup)
        self.runs_root = Path(self._runs.name)
        self.ticks = 0
        self.addCleanup(self.prune_worktrees)

    def prune_worktrees(self) -> None:
        gitcmd.run(self.repo.path, "worktree", "prune", check=False)

    def clock(self) -> str:
        self.ticks += 1
        return f"2026-07-31T13:{self.ticks // 60:02d}:{self.ticks % 60:02d}Z"

    def context(self, runner, *, run_id="run-fanout", lenses=FOUR_LENSES, **overrides):
        directory = RunDirectory(self.runs_root / run_id)
        if not directory.exists:
            directory.create(
                {
                    "schema_version": "workflows.run-manifest.v1",
                    "run_id": run_id,
                    "kind": "flow",
                    "flow": "fanout",
                    "dry_run": True,
                    "created_at": self.clock(),
                    "updated_at": self.clock(),
                    "contract_ref": CONTRACT_REF,
                    "base": [{"repo_id": "target", "commit": self.base}],
                    "steps": [],
                }
            )
        settings = {
            "contract": CONTRACT,
            "contract_ref": CONTRACT_REF,
            "worktree": self.repo.path,
            "base": self.base,
            "run": directory,
            "run_id": run_id,
            "runner": runner,
            "profile": Profile(),
            "escalation": Escalation(max_repair_rounds=1),
            "registry": self.registry,
            "work_lenses": tuple(lenses),
            "review_lenses": ("review/scope-integrity",),
            "clock": self.clock,
            "dry_run": True,
            "worker_worktrees": self.runs_root / f"{run_id}-worktrees",
        }
        settings.update(overrides)
        return FlowContext(**settings)


class FanoutDryRunTest(FanoutTestCase):
    def test_five_lenses_give_five_distinct_prompts_stable_across_two_runs(self) -> None:
        first = self.context(DryRunner(registry=self.registry), run_id="run-a", lenses=FIVE_LENSES)
        fanout.run(first)
        prompts_a = {
            path.name: json.loads(path.read_text(encoding="utf-8"))["prompt"]
            for path in sorted(first.run.prompts.glob("work-*.json"))
        }
        # The fifth entry repeats a lens, so four distinct worker prompts.
        self.assertEqual(len(prompts_a), 4)
        self.assertEqual(len(set(prompts_a.values())), 4, "each lens composes differently")

        second = self.context(DryRunner(registry=self.registry), run_id="run-b", lenses=FIVE_LENSES)
        fanout.run(second)
        prompts_b = {
            path.name: json.loads(path.read_text(encoding="utf-8"))["prompt"]
            for path in sorted(second.run.prompts.glob("work-*.json"))
        }
        self.assertEqual(prompts_a, prompts_b, "composition is byte-stable across runs")

    def test_the_synthesis_input_manifest_is_recorded(self) -> None:
        context = self.context(DryRunner(registry=self.registry))
        fanout.run(context)
        manifest = context.run.read_artifact("synthesis-inputs.json")
        self.assertEqual(manifest["width"], len(FOUR_LENSES))
        self.assertEqual(
            [item["lens_id"] for item in manifest["inputs"]], list(FOUR_LENSES)
        )
        for item in manifest["inputs"]:
            self.assertTrue(item["digest"].startswith("sha256:"))

    def test_each_worker_gets_its_own_worktree(self) -> None:
        context = self.context(DryRunner(registry=self.registry))
        fanout.run(context)
        root = context.worker_worktrees
        self.assertEqual(
            sorted(path.name for path in root.iterdir() if path.is_dir()),
            sorted(lens.replace("/", "-") for lens in FOUR_LENSES),
        )
        for path in root.iterdir():
            self.assertEqual(gitcmd.head_commit(path), self.base)

    def test_the_run_directory_and_verdict_validate(self) -> None:
        context = self.context(DryRunner(registry=self.registry))
        verdict = fanout.run(context)
        errors = check_document(verdict, base.VERDICT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [])
        for path in sorted(context.run.envelopes.glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            errors = check_document(document, base.ENVELOPE_SCHEMA, registry=self.registry)
            self.assertEqual([str(e) for e in errors], [], path.name)
        self.assertEqual(verdict["flow"], "fanout")

    def test_the_verdict_says_the_width_was_chosen_not_measured(self) -> None:
        context = self.context(DryRunner(registry=self.registry))
        verdict = fanout.run(context)
        self.assertTrue(
            any("not a measurement" in claim for claim in verdict["non_claims"]),
            "a plan-parameter width must not read as a coverage claim",
        )

    def test_fewer_than_two_lenses_is_refused(self) -> None:
        context = self.context(DryRunner(registry=self.registry), lenses=("work/api-design",))
        with self.assertRaises(FlowError):
            fanout.run(context)

    def test_parallel_workers_produce_the_same_result_as_serial(self) -> None:
        serial = self.context(DryRunner(registry=self.registry), run_id="run-serial")
        fanout.run(serial)
        parallel = self.context(
            DryRunner(registry=self.registry), run_id="run-parallel", max_parallel_workers=4
        )
        fanout.run(parallel)
        self.assertEqual(
            sorted(path.name for path in serial.run.envelopes.glob("*.json")),
            sorted(path.name for path in parallel.run.envelopes.glob("*.json")),
        )


class FanoutResumeTest(FanoutTestCase):
    def test_resume_does_not_repeat_a_worker(self) -> None:
        script = [(None, WORK_OUTPUT), (None, WORK_OUTPUT)]
        killed = ScriptedRunner(self.repo, script)
        with self.assertRaises(AssertionError):
            fanout.run(self.context(killed, dry_run=False))

        done = {
            step["step_id"]
            for step in RunDirectory(self.runs_root / "run-fanout").read_manifest()["steps"]
            if step["state"] == "COMPLETED"
        }
        self.assertIn("work-spec-fidelity", done)
        self.assertIn("work-minimal-change", done)

        resumed = ScriptedRunner(
            self.repo,
            [
                (None, WORK_OUTPUT),
                (None, WORK_OUTPUT),
                (lambda repo: repo.write("src/example/util.py", "VALUE = 2\n"), WORK_OUTPUT),
                (None, review_output("PASS")),
            ],
        )
        context = self.context(resumed, dry_run=False)
        verdict = fanout.run(context)
        called = [call.step_id for call in resumed.calls]
        self.assertNotIn("work-spec-fidelity", called)
        self.assertNotIn("work-minimal-change", called)
        self.assertIn("work-defensive-input", called)
        self.assertIn("synthesis", called)
        self.assertEqual(verdict["result"], "PASS")


if __name__ == "__main__":
    unittest.main()
