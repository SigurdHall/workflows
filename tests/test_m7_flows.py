"""Adjudication, and assure in goal mode.

Two flows for the cases where certainty is weakest: two reviewers that
disagree, and a goal no hash can answer. Both are tested on the rule that
makes them worth having — a disputed claim must be probed, and a goal
verdict must separate what was checked from what was judged.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests import support
from tests.gitrepo import TempRepo
from tests.test_flows import CONTRACT_REF, ScriptedRunner
from workflows.flows import adjudicate, assure, base
from workflows.flows.base import FlowContext, FlowError, Profile
from workflows.flows.ladder import Escalation
from workflows.runners.codex import DryRunner
from workflows.runs import RunDirectory
from workflows.semantics import check_document

GOAL_CONTRACT = {
    "schema_version": "workflows.goal-contract.v1",
    "contract_id": "goal-example",
    "contract_revision": 1,
    "contract_type": "goal",
    "goal": "Establish whether the migration achieved parity with the system it replaced.",
    "subgoals": [
        {"id": "SG-1", "statement": "Every published figure is reproducible."},
        {"id": "SG-2", "statement": "Every deliverable named in the brief exists."},
    ],
    "evidence_requirements": [
        {
            "id": "ER-1",
            "statement": "The comparison report exists.",
            "check": "artifact_exists",
            "target": "docs/guide.md",
        },
        {
            "id": "ER-2",
            "statement": "Every reference resolves.",
            "check": "reference_resolves",
            "target": "docs/guide.md",
        },
        {
            "id": "ER-3",
            "statement": "The reader judges whether the narrative answers the brief.",
            "check": "manual_judgment",
        },
    ],
    "attainment_rubric": {
        "levels": [
            {"id": "attained", "statement": "Every obligation is met and evidenced."},
            {"id": "partial", "statement": "Deliverables exist but claims are unsourced."},
            {"id": "not-attained", "statement": "Obligations are unmet or untraceable."},
        ]
    },
}

TASK_CONTRACT = {
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


def attainment_output(level: str = "attained", **overrides):
    document = {
        "schema_version": "workflows.attainment-result.v1",
        "attainment_level": level,
        "summary": "Judged the two subgoals against the deliverables that exist.",
        "judged": [
            {
                "subgoal_id": "SG-1",
                "met": "PASS",
                "assessment": "Every figure traces to a source in the guide.",
                "evidence_refs": ["read-guide"],
            },
            {
                "subgoal_id": "SG-2",
                "met": "PASS",
                "assessment": "Each named deliverable is present.",
                "evidence_refs": ["read-guide"],
            },
        ],
        "findings": [],
        "evidence": [
            {"id": "read-guide", "kind": "file", "ref": "docs/guide.md", "excerpt": "..."}
        ],
        "non_claims": ["Only the subgoals stated in the contract were considered."],
    }
    document.update(overrides)
    return document


def adjudication_output(**overrides):
    document = {
        "schema_version": "workflows.adjudication-result.v1",
        "summary": "Probed each disputed claim.",
        "resolutions": [],
        "evidence": [
            {
                "id": "probe-reorder",
                "kind": "probe",
                "ref": "probes/test_reorder.py::test_digest_stable",
                "exit_code": 1,
            }
        ],
        "non_claims": ["Only the claims the two envelopes disputed were considered."],
    }
    document.update(overrides)
    return document


def envelope(result: str, findings=(), criteria=(), envelope_id="env-a"):
    return {
        "schema_version": "workflows.envelope.v1",
        "envelope_id": envelope_id,
        "run_id": "run-x",
        "step_id": envelope_id,
        "step_kind": "review",
        "status": "COMPLETED",
        "terminal": True,
        "result": result,
        "dry_run": False,
        "produced_at": "2026-07-31T12:00:00Z",
        "contract_ref": CONTRACT_REF,
        "evidence": [
            {"id": "probe-1", "kind": "probe", "ref": "probes/test_a.py", "exit_code": 1}
        ],
        "criterion_results": list(criteria),
        "findings": list(findings),
        "non_claims": ["A test fixture."],
        "side_effects": [{"kind": "none", "target": "none"}],
    }


def a_finding(claim: str, severity: str = "HIGH", location: str = "src/a.py"):
    return {
        "id": "F-1",
        "severity": severity,
        "status": "OPEN",
        "claim": claim,
        "location": location,
        "evidence_refs": ["probe-1"],
        "required_action": "Fix it.",
        "negative_path_claim": False,
    }


class DisputeEnumerationTest(unittest.TestCase):
    def test_a_finding_only_one_envelope_raised_is_disputed(self) -> None:
        claims = adjudicate.disputed_claims(
            envelope("FAIL", [a_finding("the digest changes under reordering")]),
            envelope("PASS", envelope_id="env-b"),
        )
        kinds = {claim["kind"] for claim in claims}
        self.assertIn("finding_only_in_one_envelope", kinds)
        self.assertIn("result_disagreement", kinds)

    def test_a_severity_disagreement_is_disputed(self) -> None:
        claim = a_finding("the digest changes under reordering")
        claims = adjudicate.disputed_claims(
            envelope("FAIL", [dict(claim, severity="CRITICAL")]),
            envelope("FAIL", [dict(claim, severity="LOW")], envelope_id="env-b"),
        )
        self.assertEqual([c["kind"] for c in claims], ["severity_disagreement"])
        self.assertEqual(claims[0]["positions"], ["CRITICAL", "LOW"])

    def test_a_criterion_disagreement_is_disputed(self) -> None:
        outcome = {
            "criterion_id": "AC-1",
            "evidence_refs": [],
            "negative_path_claim": False,
        }
        claims = adjudicate.disputed_claims(
            envelope("PASS", criteria=[dict(outcome, result="PASS")]),
            envelope("PASS", criteria=[dict(outcome, result="FAIL")], envelope_id="env-b"),
        )
        self.assertEqual([c["kind"] for c in claims], ["criterion_disagreement"])

    def test_identical_envelopes_dispute_nothing(self) -> None:
        one = envelope("PASS")
        self.assertEqual(adjudicate.disputed_claims(one, dict(one, envelope_id="env-b")), [])

    def test_the_same_finding_worded_differently_is_not_a_dispute(self) -> None:
        claims = adjudicate.disputed_claims(
            envelope("FAIL", [a_finding("The digest  changes under reordering")]),
            envelope(
                "FAIL",
                [a_finding("the digest changes under REORDERING")],
                envelope_id="env-b",
            ),
        )
        self.assertEqual(claims, [])


class FlowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)
        self.base = self.repo.seed()
        self.registry = support.registry()
        self._runs = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._runs.cleanup)
        self.runs_root = Path(self._runs.name)
        self.ticks = 0

    def clock(self) -> str:
        self.ticks += 1
        return f"2026-07-31T14:{self.ticks // 60:02d}:{self.ticks % 60:02d}Z"

    def context(self, runner, contract, *, run_id="run-m7", **overrides) -> FlowContext:
        directory = RunDirectory(self.runs_root / run_id)
        if not directory.exists:
            directory.create(
                {
                    "schema_version": "workflows.run-manifest.v1",
                    "run_id": run_id,
                    "kind": "flow",
                    "dry_run": False,
                    "created_at": self.clock(),
                    "updated_at": self.clock(),
                    "contract_ref": CONTRACT_REF,
                    "base": [{"repo_id": "target", "commit": self.base}],
                    "steps": [],
                }
            )
        settings = {
            "contract": contract,
            "contract_ref": CONTRACT_REF,
            "worktree": self.repo.path,
            "base": self.base,
            "run": directory,
            "run_id": run_id,
            "runner": runner,
            "profile": Profile(),
            "escalation": Escalation(max_repair_rounds=0),
            "registry": self.registry,
            "clock": self.clock,
        }
        settings.update(overrides)
        return FlowContext(**settings)

    def assert_valid(self, context, verdict) -> None:
        errors = check_document(verdict, base.VERDICT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [])
        for path in sorted(context.run.envelopes.glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            errors = check_document(document, base.ENVELOPE_SCHEMA, registry=self.registry)
            self.assertEqual([str(e) for e in errors], [], path.name)


class AdjudicateFlowTest(FlowTestCase):
    def dispute(self):
        return (
            envelope("FAIL", [a_finding("the digest changes under reordering")]),
            envelope("PASS", envelope_id="env-b"),
        )

    def test_every_disputed_claim_must_be_probed(self) -> None:
        left, right = self.dispute()
        claims = adjudicate.disputed_claims(left, right)
        unprobed = adjudication_output(
            resolutions=[
                {
                    "claim_id": claim["claim_id"],
                    "resolution": "UPHELD",
                    "rationale": "The second reviewer was more thorough about it.",
                    "evidence_refs": [],
                }
                for claim in claims
            ]
        )
        runner = ScriptedRunner(self.repo, [(None, unprobed), (None, unprobed)])
        context = self.context(runner, TASK_CONTRACT)
        verdict = adjudicate.run(context, left=left, right=right)
        self.assertEqual(len(runner.calls), 2, "exactly one bounded retry")
        self.assertIn("resolution_requires_probe", runner.calls[1].prompt)
        self.assertEqual(verdict["result"], "INCONCLUSIVE")

    def test_a_probed_resolution_is_accepted(self) -> None:
        left, right = self.dispute()
        claims = adjudicate.disputed_claims(left, right)
        probed = adjudication_output(
            resolutions=[
                {
                    "claim_id": claim["claim_id"],
                    "resolution": "UPHELD",
                    "rationale": "Reordering the same set changed the digest when probed.",
                    "evidence_refs": ["probe-reorder"],
                    "severity": "HIGH",
                }
                for claim in claims
            ]
        )
        context = self.context(ScriptedRunner(self.repo, [(None, probed)]), TASK_CONTRACT)
        verdict = adjudicate.run(context, left=left, right=right)
        self.assert_valid(context, verdict)
        self.assertEqual(verdict["result"], "FAIL")
        self.assertEqual(verdict["ladder_levels_run"], [0, 3])

    def test_unresolved_needs_no_probe_but_is_declared(self) -> None:
        left, right = self.dispute()
        claims = adjudicate.disputed_claims(left, right)
        undecided = adjudication_output(
            resolutions=[
                {
                    "claim_id": claim["claim_id"],
                    "resolution": "UNRESOLVED",
                    "rationale": "No probe distinguishes the two positions here.",
                    "evidence_refs": [],
                }
                for claim in claims
            ]
        )
        context = self.context(ScriptedRunner(self.repo, [(None, undecided)]), TASK_CONTRACT)
        verdict = adjudicate.run(context, left=left, right=right)
        self.assert_valid(context, verdict)
        self.assertEqual(verdict["result"], "INCONCLUSIVE")
        self.assertTrue(
            any("UNRESOLVED" in claim for claim in verdict["non_claims"]),
            "an undecided dispute must be visible in the verdict",
        )

    def test_a_claim_left_unanswered_is_rejected(self) -> None:
        left, right = self.dispute()
        partial = adjudication_output(
            resolutions=[
                {
                    "claim_id": "claim-result",
                    "resolution": "UPHELD",
                    "rationale": "Probed the overall result only.",
                    "evidence_refs": ["probe-reorder"],
                }
            ]
        )
        runner = ScriptedRunner(self.repo, [(None, partial), (None, partial)])
        context = self.context(runner, TASK_CONTRACT)
        adjudicate.run(context, left=left, right=right)
        self.assertIn("unresolved_claims_missing", runner.calls[1].prompt)

    def test_the_disputed_claims_are_recorded_before_the_model_sees_them(self) -> None:
        left, right = self.dispute()
        claims = adjudicate.disputed_claims(left, right)
        probed = adjudication_output(
            resolutions=[
                {
                    "claim_id": claim["claim_id"],
                    "resolution": "REJECTED",
                    "rationale": "The probe did not reproduce the claimed behaviour.",
                    "evidence_refs": ["probe-reorder"],
                }
                for claim in claims
            ]
        )
        context = self.context(ScriptedRunner(self.repo, [(None, probed)]), TASK_CONTRACT)
        adjudicate.run(context, left=left, right=right)
        recorded = context.run.read_artifact("disputed-claims.json")
        self.assertEqual(len(recorded["claims"]), len(claims))
        self.assertEqual(recorded["envelopes"], ["env-a", "env-b"])

    def test_agreeing_envelopes_are_refused(self) -> None:
        one = envelope("PASS")
        context = self.context(ScriptedRunner(self.repo, []), TASK_CONTRACT)
        with self.assertRaises(FlowError):
            adjudicate.run(context, left=one, right=dict(one, envelope_id="env-b"))


class GoalModeTest(FlowTestCase):
    def test_the_verdict_separates_what_was_checked_from_what_was_judged(self) -> None:
        context = self.context(
            ScriptedRunner(self.repo, [(None, attainment_output())]), GOAL_CONTRACT
        )
        verdict = assure.run(context)
        self.assert_valid(context, verdict)

        joined = " ".join(verdict["non_claims"])
        self.assertIn("no deterministic oracle", joined)
        self.assertIn("ER-3", joined, "the obligation left to judgment is named")
        self.assertIn("An obligation met is not a goal achieved", joined)

        checked = [
            outcome["criterion_id"]
            for outcome in verdict["criterion_results"]
            if "evidence_obligations/" in outcome["criterion_id"]
        ]
        judged = [
            outcome["criterion_id"]
            for outcome in verdict["criterion_results"]
            if outcome["criterion_id"].endswith("SG-1")
            or outcome["criterion_id"].endswith("SG-2")
        ]
        self.assertEqual(len(checked), 3, "one outcome per evidence obligation")
        self.assertEqual(len(judged), 2, "one outcome per subgoal")

    def test_a_grade_outside_the_rubric_is_rejected(self) -> None:
        invented = attainment_output(level="excellent")
        runner = ScriptedRunner(self.repo, [(None, invented), (None, invented)])
        context = self.context(runner, GOAL_CONTRACT)
        verdict = assure.run(context)
        self.assertEqual(len(runner.calls), 2)
        self.assertIn("grade_outside_the_rubric", runner.calls[1].prompt)
        self.assertEqual(verdict["result"], "BLOCKED")

    def test_a_subgoal_left_unjudged_is_rejected(self) -> None:
        partial = attainment_output(judged=[attainment_output()["judged"][0]])
        runner = ScriptedRunner(self.repo, [(None, partial), (None, partial)])
        context = self.context(runner, GOAL_CONTRACT)
        assure.run(context)
        self.assertIn("subgoal_not_judged", runner.calls[1].prompt)
        self.assertIn("SG-2", runner.calls[1].prompt)

    def test_a_subgoal_judged_met_with_no_evidence_is_rejected(self) -> None:
        vacuous = attainment_output()
        vacuous["judged"][0]["evidence_refs"] = []
        runner = ScriptedRunner(self.repo, [(None, vacuous), (None, vacuous)])
        context = self.context(runner, GOAL_CONTRACT)
        assure.run(context)
        self.assertIn("pass_requires_evidence", runner.calls[1].prompt)

    def test_unmet_obligations_stop_the_flow_before_any_judgment(self) -> None:
        contract = dict(GOAL_CONTRACT)
        contract["evidence_requirements"] = [
            {
                "id": "ER-1",
                "statement": "The report exists.",
                "check": "artifact_exists",
                "target": "docs/absent.md",
            }
        ]
        runner = ScriptedRunner(self.repo, [])
        context = self.context(runner, contract)
        verdict = assure.run(context)
        self.assertEqual(verdict["result"], "FAIL")
        self.assertEqual(runner.calls, [])
        self.assertTrue(
            any("nothing traceable to judge against" in c for c in verdict["non_claims"])
        )

    def test_one_unmet_obligation_does_not_condemn_the_others(self) -> None:
        contract = dict(GOAL_CONTRACT)
        contract["evidence_requirements"] = [
            {
                "id": "ER-missing",
                "statement": "The report exists.",
                "check": "artifact_exists",
                "target": "docs/absent.md",
            },
            {
                "id": "ER-present",
                "statement": "The guide exists.",
                "check": "artifact_exists",
                "target": "docs/guide.md",
            },
        ]
        context = self.context(ScriptedRunner(self.repo, []), contract)
        assure.run(context)
        gate = context.run.read_artifact(
            "gates/gates-evidence/evidence_obligations.1.json"
        )
        outcomes = {check["id"]: check["result"] for check in gate["checks"]}
        self.assertEqual(outcomes, {"ER-missing": "FAIL", "ER-present": "PASS"})
        self.assertEqual(len(gate["findings"]), 1)

    def test_a_goal_dry_run_never_claims_attainment(self) -> None:
        context = self.context(
            DryRunner(registry=self.registry), GOAL_CONTRACT, run_id="run-goal-dry", dry_run=True
        )
        verdict = assure.run(context)
        self.assert_valid(context, verdict)
        self.assertNotEqual(verdict["result"], "PASS")
        self.assertTrue(any("Dry run" in claim for claim in verdict["non_claims"]))


if __name__ == "__main__":
    unittest.main()
