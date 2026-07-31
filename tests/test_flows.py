"""The implement and assure flows.

Every mandatory M4 case in docs/test-charter.md is here: repair provenance
verified by hash rather than by reading a diff, reviewer blindness asserted
on the composed prompt, the negative-path probe rule enforced against a
reviewer that asserts an unprobed property, and a kill/resume that re-runs
nothing already completed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests import support
from tests.gitrepo import TempRepo
from workflows import gitcmd, runners
from workflows.flows import assure, base, implement, ladder
from workflows.flows.base import FlowContext, Profile
from workflows.flows.ladder import Escalation
from workflows.runners.codex import DryRunner
from workflows.runs import RunDirectory
from workflows.semantics import check_document

CONTRACT = {
    "schema_version": "workflows.task-contract.v1",
    "contract_id": "contract-example",
    "contract_revision": 1,
    "contract_type": "task",
    "goal": "Keep the calculator correct while leaving the test suite untouched.",
    "scope": {"allowed_paths": ["src/example/**"]},
    "protected": ["tests/**"],
    "acceptance": [{"id": "AC-1", "statement": "The verification command exits zero."}],
    "verification": {"command": [sys.executable, "-c", "pass"], "expect_exit_code": 0},
}

CONTRACT_REF = {
    "contract_id": "contract-example",
    "contract_revision": 1,
    "digest": "sha256:" + "5" * 64,
}

WORK_OUTPUT = {
    "schema_version": "workflows.work-result.v1",
    "summary": "Rewrote the constant so the calculator agrees with the contract.",
    "changed_paths": ["src/example/util.py"],
    "decisions": [
        {
            "id": "D-1",
            "statement": "Kept the existing function signature.",
            "rationale": "The contract does not ask for a new interface.",
        }
    ],
    "non_claims": ["No performance claim is made about this change."],
}

PROBE = {
    "id": "probe-1",
    "kind": "probe",
    "ref": "probes/test_boundary.py::test_empty_input",
    "exit_code": 0,
}


def review_output(result: str = "PASS", findings=(), *, negative_path=False, evidence=(PROBE,)):
    return {
        "schema_version": "workflows.review-result.v1",
        "result": result,
        "summary": "Reviewed the candidate against the contract.",
        "criterion_results": [
            {
                "criterion_id": "AC-1",
                "result": result if result in ("PASS", "FAIL") else "INCONCLUSIVE",
                "evidence_refs": [item["id"] for item in evidence],
                "negative_path_claim": negative_path,
            }
        ],
        "findings": list(findings),
        "evidence": list(evidence),
        "non_claims": ["Only the contract's own criteria were considered."],
    }


def finding(severity: str = "HIGH", identifier: str = "F-1"):
    return {
        "id": identifier,
        "severity": severity,
        "status": "OPEN",
        "claim": "A protected test was weakened so that it can no longer fail.",
        "evidence_refs": ["probe-1"],
        "required_action": "Restore the test to its base content.",
        "negative_path_claim": False,
    }


class ScriptedRunner:
    """A fake runner that can also change the worktree, like a real worker."""

    name = "scripted"

    def __init__(self, repo: TempRepo, script) -> None:
        self.repo = repo
        self.script = list(script)
        self.calls: list[runners.RunnerCall] = []
        self.index = 0

    def invoke(self, call: runners.RunnerCall) -> runners.RunnerResult:
        self.calls.append(call)
        if self.index >= len(self.script):
            raise AssertionError(f"unscripted call: {call.step_id}")
        mutate, output = self.script[self.index]
        self.index += 1
        if mutate is not None:
            mutate(self.repo)
        if isinstance(output, runners.RunnerResult):
            return output
        return runners.RunnerResult(
            status="COMPLETED",
            reason_code="clean",
            telemetry=runners.Telemetry(
                runner=self.name,
                model=call.model,
                effort=call.effort,
                dry=False,
                duration_ms=1,
                tokens=runners.TokenUsage(new_input=10, cached_input=0, output=5),
                lens_id=call.lens_id,
            ),
            output=output,
        )


class FlowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)
        self.base = self.repo.seed()
        self.registry = support.registry()
        self._runs = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._runs.cleanup)
        self.runs_root = Path(self._runs.name)
        self.clock_ticks = 0

    def clock(self) -> str:
        self.clock_ticks += 1
        return f"2026-07-31T12:{self.clock_ticks // 60:02d}:{self.clock_ticks % 60:02d}Z"

    def run_directory(self, run_id: str = "run-0001") -> RunDirectory:
        directory = RunDirectory(self.runs_root / run_id)
        if not directory.exists:
            directory.create(
                {
                    "schema_version": "workflows.run-manifest.v1",
                    "run_id": run_id,
                    "kind": "flow",
                    "flow": "implement",
                    "dry_run": False,
                    "created_at": self.clock(),
                    "updated_at": self.clock(),
                    "contract_ref": CONTRACT_REF,
                    "base": [{"repo_id": "target", "commit": self.base}],
                    "steps": [],
                }
            )
        return directory

    def context(self, runner, *, run_id: str = "run-0001", **overrides) -> FlowContext:
        settings = {
            "contract": CONTRACT,
            "contract_ref": CONTRACT_REF,
            "worktree": self.repo.path,
            "base": self.base,
            "run": self.run_directory(run_id),
            "run_id": run_id,
            "runner": runner,
            "profile": Profile(),
            "escalation": Escalation(max_repair_rounds=1),
            "registry": self.registry,
            "work_lenses": ("work/spec-fidelity",),
            "review_lenses": ("review/scope-integrity",),
            "clock": self.clock,
        }
        settings.update(overrides)
        return FlowContext(**settings)

    def assert_run_directory_is_valid(self, context: FlowContext, verdict: dict) -> None:
        errors = check_document(verdict, base.VERDICT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [], "verdict must validate")
        manifest = context.run.read_manifest()
        errors = check_document(manifest, "run-manifest.schema.json", registry=self.registry)
        self.assertEqual([str(e) for e in errors], [], "manifest must validate")
        envelopes = sorted(context.run.envelopes.glob("*.json"))
        self.assertTrue(envelopes, "a run must record its envelopes")
        for path in envelopes:
            document = json.loads(path.read_text(encoding="utf-8"))
            errors = check_document(document, base.ENVELOPE_SCHEMA, registry=self.registry)
            self.assertEqual([str(e) for e in errors], [], f"{path.name} must validate")


class DryRunTest(FlowTestCase):
    def test_implement_dry_run_materializes_a_complete_resumable_run(self) -> None:
        runner = DryRunner(registry=self.registry)
        context = self.context(runner, dry_run=True)
        verdict = implement.run(context)

        self.assert_run_directory_is_valid(context, verdict)
        self.assertTrue(context.run.telemetry(), "a dry run still records telemetry")
        self.assertTrue(all(record["dry"] for record in context.run.telemetry()))
        self.assertTrue(list(context.run.prompts.glob("*.json")), "prompts are materialized")
        self.assertTrue(
            list(context.run.gates.glob("*/*.json")), "gate results are written per step"
        )
        steps = context.run.read_manifest()["steps"]
        self.assertTrue(all(step["state"] == "COMPLETED" for step in steps))

    def test_a_dry_run_never_reports_a_pass(self) -> None:
        context = self.context(DryRunner(registry=self.registry), dry_run=True)
        verdict = implement.run(context)
        self.assertNotEqual(verdict["result"], "PASS")
        self.assertTrue(verdict["dry_run"])
        self.assertTrue(any("no model was called" in claim for claim in verdict["non_claims"]))

    def test_assure_dry_run_materializes_a_complete_run(self) -> None:
        context = self.context(
            DryRunner(registry=self.registry), run_id="run-assure", dry_run=True
        )
        verdict = assure.run(context)
        self.assert_run_directory_is_valid(context, verdict)
        self.assertEqual(verdict["flow"], "assure")
        self.assertTrue(
            any("did not build" in claim for claim in verdict["non_claims"]),
            "assure must say it produced nothing",
        )

    def test_a_dry_run_starts_no_provider_process(self) -> None:
        runner = DryRunner(registry=self.registry)
        implement.run(self.context(runner, dry_run=True))
        self.assertTrue(runner.calls)
        self.assertTrue(all(call.prompt.strip() for call in runner.calls))


class HappyPathTest(FlowTestCase):
    def edit_in_scope(self, repo: TempRepo) -> None:
        repo.write("src/example/util.py", "VALUE = 2\n")

    def test_a_clean_candidate_passes_after_one_review(self) -> None:
        runner = ScriptedRunner(
            self.repo, [(self.edit_in_scope, WORK_OUTPUT), (None, review_output("PASS"))]
        )
        context = self.context(runner)
        verdict = implement.run(context)
        self.assert_run_directory_is_valid(context, verdict)
        self.assertEqual(verdict["result"], "PASS")
        self.assertEqual(verdict["ladder_levels_run"], [0, 1])
        self.assertEqual(len(runner.calls), 2, "no escalation without a signal")

    def test_level_4_is_always_a_non_claim(self) -> None:
        runner = ScriptedRunner(
            self.repo, [(self.edit_in_scope, WORK_OUTPUT), (None, review_output("PASS"))]
        )
        verdict = implement.run(self.context(runner))
        self.assertTrue(
            any("level 4" in claim.lower() for claim in verdict["non_claims"]),
            "an unimplemented ladder level must be declared, not skipped silently",
        )

    def test_the_review_prompt_carries_no_producer_dialogue(self) -> None:
        runner = ScriptedRunner(
            self.repo, [(self.edit_in_scope, WORK_OUTPUT), (None, review_output("PASS"))]
        )
        context = self.context(runner)
        implement.run(context)
        review_call = next(call for call in runner.calls if "review" in call.step_id)
        self.assertIn("VALUE = 2", review_call.prompt, "the reviewer sees the candidate")
        self.assertIn("contract-example", review_call.prompt, "and the contract")
        self.assertNotIn(WORK_OUTPUT["summary"], review_call.prompt)
        self.assertNotIn("Kept the existing function signature", review_call.prompt)


class EscalationTest(FlowTestCase):
    def edit_in_scope(self, repo: TempRepo) -> None:
        repo.write("src/example/util.py", "VALUE = 2\n")

    def test_a_high_finding_escalates_to_level_2(self) -> None:
        runner = ScriptedRunner(
            self.repo,
            [
                (self.edit_in_scope, WORK_OUTPUT),
                (None, review_output("FAIL", [finding("HIGH")])),
                (None, review_output("FAIL", [finding("HIGH", "F-2")])),
                (self.edit_in_scope, WORK_OUTPUT),
                (None, review_output("PASS")),
            ],
        )
        context = self.context(runner)
        verdict = implement.run(context)
        self.assert_run_directory_is_valid(context, verdict)
        self.assertIn(2, verdict["ladder_levels_run"])
        self.assertTrue(
            any("Escalations recorded" in claim for claim in verdict["non_claims"])
        )

    def test_a_low_finding_does_not_escalate(self) -> None:
        runner = ScriptedRunner(
            self.repo,
            [
                (self.edit_in_scope, WORK_OUTPUT),
                (None, review_output("PASS", [finding("LOW")])),
            ],
        )
        verdict = implement.run(self.context(runner))
        self.assertEqual(verdict["ladder_levels_run"], [0, 1])

    def test_disagreement_between_gates_and_reviewer_escalates(self) -> None:
        self.assertEqual(
            ladder.escalate_to_level_2([{"result": "PASS"}], "FAIL", Escalation()),
            "the reviewer passed a candidate the gates failed",
        )
        self.assertEqual(
            ladder.escalate_to_level_2([{"result": "FAIL"}], "PASS", Escalation()),
            "the gates passed the candidate the reviewer failed",
        )

    def test_thresholds_come_from_the_plan_and_fall_back_to_defaults(self) -> None:
        settings = Escalation.from_plan(
            {
                "level_2_on_severity": "MEDIUM",
                "level_3_on_conflict": False,
                "stop_on_severity": "HIGH",
                "max_repair_rounds": 0,
                "dryness_rounds": 3,
            }
        )
        self.assertEqual(settings.level_2_on_severity, "MEDIUM")
        self.assertFalse(settings.level_3_on_conflict)
        self.assertEqual(settings.max_repair_rounds, 0)
        self.assertEqual(settings.dryness_rounds, 3)
        self.assertEqual(Escalation.from_plan(None), Escalation())
        self.assertEqual(
            Escalation.from_plan({"stop_on_severity": "MEDIUM"}).level_2_on_severity,
            Escalation().level_2_on_severity,
        )

    def test_a_lower_threshold_escalates_where_the_default_would_not(self) -> None:
        low = [{"result": "FAIL", "findings": [finding("MEDIUM")]}]
        self.assertIsNone(ladder.escalate_to_level_2(low, "FAIL", Escalation()))
        self.assertIsNotNone(
            ladder.escalate_to_level_2(low, "FAIL", Escalation(level_2_on_severity="MEDIUM"))
        )

    def test_zero_repair_rounds_means_no_repair(self) -> None:
        runner = ScriptedRunner(
            self.repo,
            [
                (self.edit_in_scope, WORK_OUTPUT),
                (None, review_output("FAIL", [finding("HIGH")])),
                (None, review_output("FAIL", [finding("HIGH", "F-2")])),
            ],
        )
        context = self.context(runner, escalation=Escalation(max_repair_rounds=0))
        verdict = implement.run(context)
        self.assertEqual(verdict["result"], "FAIL")
        self.assertFalse([call for call in runner.calls if "repair" in call.step_id])

    def test_level_3_runs_only_on_an_unresolved_conflict(self) -> None:
        settings = Escalation()
        self.assertIsNone(
            ladder.escalate_to_level_3([{"result": "FAIL"}], [{"result": "FAIL"}], settings)
        )
        self.assertIsNotNone(
            ladder.escalate_to_level_3([{"result": "FAIL"}], [{"result": "PASS"}], settings)
        )
        self.assertIsNone(
            ladder.escalate_to_level_3(
                [{"result": "FAIL"}], [{"result": "PASS"}], Escalation(level_3_on_conflict=False)
            )
        )


class RepairProvenanceTest(FlowTestCase):
    def tamper_with_a_protected_test(self, repo: TempRepo) -> None:
        repo.write("src/example/util.py", "VALUE = 2\n")
        repo.write("tests/test_calc.py", "def test_add():\n    assert True  # TAMPER-MARKER\n")

    def repair_properly(self, repo: TempRepo) -> None:
        repo.write("src/example/util.py", "VALUE = 2\n")

    def test_the_repaired_candidate_is_rebuilt_from_the_original_base(self) -> None:
        """Verified by hash against the base, not by reading the diff.

        Reverting an illegal change on top of the failed candidate would
        leave it in that candidate's history. The repair starts again from
        the frozen base, so the change is absent rather than undone.
        """
        base_hash = gitcmd.blob_hash_at(self.repo.path, self.base, "tests/test_calc.py")
        runner = ScriptedRunner(
            self.repo,
            [
                (self.tamper_with_a_protected_test, WORK_OUTPUT),
                (self.repair_properly, WORK_OUTPUT),
                (None, review_output("PASS")),
            ],
        )
        context = self.context(runner)
        verdict = implement.run(context)

        self.assert_run_directory_is_valid(context, verdict)
        after = gitcmd.blob_hash_now(self.repo.path, "tests/test_calc.py")
        self.assertEqual(after, base_hash, "the protected file is byte-identical to the base")
        self.assertTrue(
            any(step["step_id"] == "repair-r1" for step in context.run.read_manifest()["steps"])
        )
        self.assertEqual(verdict["result"], "PASS")

    def test_a_reviewer_never_sees_a_candidate_that_failed_its_gates(self) -> None:
        runner = ScriptedRunner(
            self.repo,
            [
                (self.tamper_with_a_protected_test, WORK_OUTPUT),
                (self.repair_properly, WORK_OUTPUT),
                (None, review_output("PASS")),
            ],
        )
        implement.run(self.context(runner))
        review_calls = [call for call in runner.calls if "review" in call.step_id]
        self.assertEqual(len(review_calls), 1)
        self.assertNotIn("TAMPER-MARKER", review_calls[0].prompt)

    def test_an_unrepaired_protected_change_fails_without_a_review(self) -> None:
        runner = ScriptedRunner(
            self.repo,
            [
                (self.tamper_with_a_protected_test, WORK_OUTPUT),
                (self.tamper_with_a_protected_test, WORK_OUTPUT),
            ],
        )
        context = self.context(runner)
        verdict = implement.run(context)
        self.assertEqual(verdict["result"], "FAIL")
        self.assertTrue(
            any("never became gate-clean" in claim for claim in verdict["non_claims"])
        )
        self.assertFalse([call for call in runner.calls if "review" in call.step_id])


class NegativePathRuleTest(FlowTestCase):
    def edit_in_scope(self, repo: TempRepo) -> None:
        repo.write("src/example/util.py", "VALUE = 2\n")

    def test_an_unprobed_negative_path_claim_is_rejected_and_retried_once(self) -> None:
        """The observed reviewer failure mode: asserting a safety property
        nobody probed, on the one candidate where it was false."""
        unprobed = review_output(
            "PASS",
            negative_path=True,
            evidence=[{"id": "doc-1", "kind": "citation", "ref": "README.md"}],
        )
        runner = ScriptedRunner(
            self.repo,
            [
                (self.edit_in_scope, WORK_OUTPUT),
                (None, unprobed),
                (None, unprobed),
            ],
        )
        context = self.context(runner)
        verdict = implement.run(context)

        self.assert_run_directory_is_valid(context, verdict)
        review_calls = [call for call in runner.calls if "review" in call.step_id]
        self.assertEqual(len(review_calls), 2, "exactly one bounded retry")
        self.assertIn("negative_path_requires_probe", review_calls[1].prompt)
        # A review that never concluded is not a finding to repair.
        self.assertEqual(verdict["result"], "BLOCKED")
        self.assertTrue(
            any("never judged" in claim for claim in verdict["non_claims"])
        )

    def test_a_probed_negative_path_claim_is_accepted(self) -> None:
        runner = ScriptedRunner(
            self.repo,
            [
                (self.edit_in_scope, WORK_OUTPUT),
                (None, review_output("PASS", negative_path=True)),
            ],
        )
        verdict = implement.run(self.context(runner))
        self.assertEqual(verdict["result"], "PASS")


class ResumeTest(FlowTestCase):
    def edit_in_scope(self, repo: TempRepo) -> None:
        repo.write("src/example/util.py", "VALUE = 2\n")

    def test_resume_reruns_nothing_that_completed(self) -> None:
        killed = ScriptedRunner(self.repo, [(self.edit_in_scope, WORK_OUTPUT)])
        with self.assertRaises(AssertionError):
            implement.run(self.context(killed))

        completed_before = {
            step["step_id"]
            for step in self.run_directory().read_manifest()["steps"]
            if step["state"] == "COMPLETED"
        }
        self.assertIn("work-1", completed_before)

        resumed = ScriptedRunner(self.repo, [(None, review_output("PASS"))])
        context = self.context(resumed)
        verdict = implement.run(context)

        self.assertEqual(
            [call.step_id for call in resumed.calls],
            ["review-l1-scope-integrity-r0"],
            "resume calls the model only for steps that had not completed",
        )
        self.assertEqual(verdict["result"], "PASS")
        self.assert_run_directory_is_valid(context, verdict)

    def test_a_completed_step_returns_its_recorded_envelope(self) -> None:
        runner = ScriptedRunner(
            self.repo, [(self.edit_in_scope, WORK_OUTPUT), (None, review_output("PASS"))]
        )
        context = self.context(runner)
        implement.run(context)
        first = context.run.read_artifact("envelopes/work-1.json")

        again = ScriptedRunner(self.repo, [])
        second_context = self.context(again)
        envelope = base.step(
            second_context, "work-1", "work", lambda: (_ for _ in ()).throw(AssertionError())
        )
        self.assertEqual(envelope, first)
        self.assertEqual(again.calls, [])


class ReviewRegressionTest(FlowTestCase):
    """Counter-examples an independent review of M4 found passing as clean."""

    def edit_in_scope(self, repo: TempRepo) -> None:
        repo.write("src/example/util.py", "VALUE = 2\n")

    def test_an_envelope_written_before_the_crash_is_adopted_not_recomputed(self) -> None:
        """The kill window: envelope on disk, manifest still RUNNING.

        Trusting the manifest alone re-invokes a model that already answered.
        """
        runner = ScriptedRunner(
            self.repo, [(self.edit_in_scope, WORK_OUTPUT), (None, review_output("PASS"))]
        )
        context = self.context(runner)
        implement.run(context)
        recorded = context.run.read_artifact("envelopes/work-1.json")

        # Rewind the manifest to the crash window, keeping the envelope.
        manifest = context.run.read_manifest()
        for step in manifest["steps"]:
            if step["step_id"] == "work-1":
                step["state"] = "RUNNING"
                step.pop("envelope_path", None)
        context.run.write_manifest(manifest)

        silent = ScriptedRunner(self.repo, [])
        adopted = base.step(
            self.context(silent),
            "work-1",
            "work",
            lambda: (_ for _ in ()).throw(AssertionError("re-invoked a completed step")),
        )
        self.assertEqual(adopted, recorded)
        self.assertEqual(silent.calls, [])
        self.assertTrue(self.context(silent).run.is_completed("work-1"))

    def test_a_repair_already_on_disk_is_not_reset_away(self) -> None:
        runner = ScriptedRunner(
            self.repo,
            [
                (
                    lambda repo: (
                        repo.write("src/example/util.py", "VALUE = 2\n"),
                        repo.write("tests/test_calc.py", "tampered\n"),
                    ),
                    WORK_OUTPUT,
                ),
                (self.edit_in_scope, WORK_OUTPUT),
                (None, review_output("PASS")),
            ],
        )
        context = self.context(runner)
        implement.run(context)
        produced = (self.repo.path / "src" / "example" / "util.py").read_text(encoding="utf-8")

        manifest = context.run.read_manifest()
        for step in manifest["steps"]:
            if step["step_id"] == "repair-r1":
                step["state"] = "RUNNING"
        context.run.write_manifest(manifest)

        silent = ScriptedRunner(self.repo, [])
        second = self.context(silent)
        self.assertTrue(base.already_produced(second, "repair-r1"))
        implement.run(second)
        self.assertEqual(
            (self.repo.path / "src" / "example" / "util.py").read_text(encoding="utf-8"),
            produced,
            "a repair on disk must not be reset away and redone",
        )
        self.assertEqual(silent.calls, [])

    def test_a_review_may_not_dispose_of_its_own_finding(self) -> None:
        for status in ("ACCEPTED_RISK", "WITHDRAWN", "RESOLVED"):
            with self.subTest(status=status):
                self.setUp()
                dismissed = review_output(
                    "PASS", [dict(finding("CRITICAL"), status=status)]
                )
                runner = ScriptedRunner(
                    self.repo,
                    [
                        (self.edit_in_scope, WORK_OUTPUT),
                        (None, dismissed),
                        (None, dismissed),
                    ],
                )
                context = self.context(runner)
                verdict = implement.run(context)
                retry = [call for call in runner.calls if "review" in call.step_id][1]
                self.assertIn("review_may_not_dispose_of_its_own_finding", retry.prompt)
                self.assertEqual(verdict["result"], "BLOCKED")

    def test_a_pass_with_no_criteria_at_all_is_rejected(self) -> None:
        vacuous = dict(review_output("PASS"), criterion_results=[])
        runner = ScriptedRunner(
            self.repo,
            [(self.edit_in_scope, WORK_OUTPUT), (None, vacuous), (None, vacuous)],
        )
        context = self.context(runner)
        verdict = implement.run(context)
        retry = [call for call in runner.calls if "review" in call.step_id][1]
        self.assertIn("pass_without_criteria", retry.prompt)
        self.assertEqual(verdict["result"], "BLOCKED")

    def test_a_candidate_identical_to_the_base_fails_its_gates(self) -> None:
        runner = ScriptedRunner(
            self.repo, [(None, dict(WORK_OUTPUT, changed_paths=[]))]
        )
        context = self.context(runner, escalation=Escalation(max_repair_rounds=0))
        verdict = implement.run(context)
        self.assertEqual(verdict["result"], "FAIL")
        self.assertFalse([call for call in runner.calls if "review" in call.step_id])
        gate = context.run.read_artifact("gates/gates-post-r0/candidate_changed.1.json")
        self.assertEqual((gate["result"], gate["reason_code"]), ("FAIL", "empty_candidate"))

    def test_an_inconclusive_review_escalates_for_a_second_opinion(self) -> None:
        runner = ScriptedRunner(
            self.repo,
            [
                (self.edit_in_scope, WORK_OUTPUT),
                (None, review_output("INCONCLUSIVE")),
                (None, review_output("FAIL", [finding("MEDIUM")])),
                (self.edit_in_scope, WORK_OUTPUT),
                (None, review_output("PASS")),
            ],
        )
        context = self.context(runner)
        verdict = implement.run(context)
        self.assertIn(2, verdict["ladder_levels_run"])
        self.assertTrue(
            any("could not conclude" in claim for claim in verdict["non_claims"])
        )

    def test_a_producer_does_not_grade_its_own_work(self) -> None:
        runner = ScriptedRunner(
            self.repo, [(self.edit_in_scope, WORK_OUTPUT), (None, review_output("PASS"))]
        )
        context = self.context(runner)
        implement.run(context)
        work = context.run.read_artifact("envelopes/work-1.json")
        self.assertEqual(work["result"], "NOT_RUN")
        self.assertEqual(work["status"], "COMPLETED")

    def test_a_finished_run_is_not_re_decided(self) -> None:
        runner = ScriptedRunner(
            self.repo, [(self.edit_in_scope, WORK_OUTPUT), (None, review_output("PASS"))]
        )
        context = self.context(runner)
        first = implement.run(context)
        again = implement.run(self.context(ScriptedRunner(self.repo, [])))
        self.assertEqual(again, first, "a verdict is terminal; a rerun returns it")


class BlockedBaseTest(FlowTestCase):
    def test_a_dirty_base_stops_the_flow_before_any_model_call(self) -> None:
        self.repo.write("src/example/util.py", "uncommitted\n")
        runner = ScriptedRunner(self.repo, [])
        context = self.context(runner)
        verdict = implement.run(context)
        self.assertEqual(verdict["result"], "BLOCKED")
        self.assertEqual(runner.calls, [])
        self.assertTrue(
            any("before any model was called" in claim for claim in verdict["non_claims"])
        )
        self.assert_run_directory_is_valid(context, verdict)


if __name__ == "__main__":
    unittest.main()
