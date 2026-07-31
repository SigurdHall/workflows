"""Gates, tested on their failure paths first.

Every mandatory case in the M2 section of docs/test-charter.md is here, plus
the invariant that binds them together: whatever a gate concludes, the
result it emits validates against gate-result.schema.json, and the envelope
the runner folds them into validates against envelope.schema.json including
its semantic rules.
"""

from __future__ import annotations

import json
import sys
import unittest

from tests import support
from tests.gitrepo import TempRepo
from workflows import gates
from workflows.semantics import check_document

FIXED_CLOCK = "2026-07-31T12:00:00Z"

CONTRACT = {
    "schema_version": "workflows.task-contract.v1",
    "contract_id": "contract-example",
    "contract_revision": 1,
    "contract_type": "task",
    "goal": "Keep the calculator correct while leaving the test suite untouched.",
    "scope": {"allowed_paths": ["src/example/**", "docs/guide.md"]},
    "protected": ["tests/**"],
    "acceptance": [{"id": "AC-1", "statement": "The verification command exits zero."}],
    "verification": {"command": ["git", "--version"], "expect_exit_code": 0},
}

CONTRACT_REF = {
    "contract_id": "contract-example",
    "contract_revision": 1,
    "digest": "sha256:" + "3" * 64,
}


class GateTestCase(unittest.TestCase):
    """Shared setup, plus the invariant every gate result must satisfy."""

    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)
        self.base = self.repo.seed()
        self.registry = support.registry()

    def context(self, **overrides) -> gates.GateContext:
        settings = {
            "worktree": self.repo.path,
            "base": self.base,
            "clock": lambda: FIXED_CLOCK,
            "registry": self.registry,
        }
        settings.update(overrides)
        return gates.GateContext(**settings)

    def check(self, result: gates.GateResult) -> gates.GateResult:
        """Every gate result is a valid envelope fragment."""
        errors = check_document(
            result.to_document(), gates.GATE_SCHEMA, registry=self.registry
        )
        self.assertEqual([str(error) for error in errors], [], result.to_document())
        return result

    def run_gate(self, name: str, contract=None, **overrides) -> gates.GateResult:
        return self.check(
            gates.GATES[name](contract or CONTRACT, self.context(**overrides))
        )


class ScopeGateTest(GateTestCase):
    def test_clean_worktree_passes(self) -> None:
        result = self.run_gate("scope")
        self.assertEqual((result.result, result.reason_code), ("PASS", "clean"))

    def test_change_inside_scope_passes(self) -> None:
        self.repo.write("src/example/calc.py", "def add(a, b):\n    return b + a\n")
        self.assertTrue(self.run_gate("scope").passed)

    def test_modified_file_outside_scope_fails(self) -> None:
        self.repo.write("README.txt", "top level\n")
        self.repo.commit("add readme")
        self.repo.write("README.txt", "changed\n")
        result = self.run_gate("scope", base=self.base)
        self.assertEqual((result.result, result.reason_code), ("FAIL", "out_of_scope_change"))
        self.assertIn("README.txt", result.detail)

    def test_added_untracked_file_outside_scope_fails(self) -> None:
        # git diff never mentions untracked files; a scope gate that only read
        # the diff would let a worker create anything, anywhere.
        self.repo.write("secrets/notes.txt", "added out of scope\n")
        result = self.run_gate("scope")
        self.assertEqual((result.result, result.reason_code), ("FAIL", "out_of_scope_change"))
        self.assertIn("secrets/notes.txt", result.detail)

    def test_rename_crossing_the_scope_boundary_fails(self) -> None:
        self.repo.git("mv", "src/example/util.py", "util.py")
        result = self.run_gate("scope")
        self.assertEqual((result.result, result.reason_code), ("FAIL", "out_of_scope_change"))
        self.assertIn("util.py", result.detail)

    def test_rename_inside_scope_passes(self) -> None:
        self.repo.git("mv", "src/example/util.py", "src/example/constants.py")
        self.assertTrue(self.run_gate("scope").passed)

    def test_deleting_a_file_outside_scope_fails(self) -> None:
        self.repo.delete("tests/test_calc.py")
        result = self.run_gate("scope")
        self.assertEqual((result.result, result.reason_code), ("FAIL", "out_of_scope_change"))

    def test_deleting_a_file_inside_scope_passes(self) -> None:
        self.repo.delete("docs/guide.md")
        self.assertTrue(self.run_gate("scope").passed)

    def test_a_contract_without_scope_is_an_author_error(self) -> None:
        with self.assertRaises(gates.GateError):
            gates.scope({"scope": {"allowed_paths": []}}, self.context())


class ProtectedHashGateTest(GateTestCase):
    def test_untouched_protected_files_pass(self) -> None:
        result = self.run_gate("protected_hash")
        self.assertEqual((result.result, result.reason_code), ("PASS", "clean"))

    def test_single_byte_change_fails(self) -> None:
        self.repo.write("tests/test_calc.py", "def test_add():\n    assert True \n")
        result = self.run_gate("protected_hash")
        self.assertEqual((result.result, result.reason_code), ("FAIL", "protected_modified"))
        self.assertEqual(result.findings[0]["severity"], "CRITICAL")

    def test_whitespace_only_change_fails(self) -> None:
        self.repo.write("tests/test_calc.py", "def test_add():\n\n    assert True\n")
        self.assertEqual(self.run_gate("protected_hash").reason_code, "protected_modified")

    def test_deleted_protected_file_fails(self) -> None:
        self.repo.delete("tests/test_calc.py")
        result = self.run_gate("protected_hash")
        self.assertEqual((result.result, result.reason_code), ("FAIL", "protected_deleted"))

    def test_a_new_file_under_a_protected_path_fails(self) -> None:
        self.repo.write("tests/test_extra.py", "def test_extra():\n    assert True\n")
        self.assertEqual(self.run_gate("protected_hash").reason_code, "protected_modified")

    def test_a_protected_file_that_does_not_exist_at_base_fails(self) -> None:
        contract = dict(CONTRACT, protected=["tests/**", "evaluator.py"])
        result = self.run_gate("protected_hash", contract=contract)
        self.assertEqual(result.reason_code, "protected_missing_at_base")

    def test_a_wildcard_matching_nothing_is_allowed(self) -> None:
        contract = dict(CONTRACT, protected=["benchmarks/**"])
        self.assertTrue(self.run_gate("protected_hash", contract=contract).passed)

    def test_no_protected_paths_is_reported_not_hidden(self) -> None:
        contract = dict(CONTRACT, protected=[])
        result = self.run_gate("protected_hash", contract=contract)
        self.assertEqual((result.result, result.reason_code), ("NOT_RUN", "not_applicable"))
        self.assertTrue(result.non_claims)


class BaseIdentityGateTest(GateTestCase):
    def test_clean_worktree_at_base_passes(self) -> None:
        self.assertTrue(self.run_gate("base_identity").passed)

    def test_one_commit_on_top_of_base_passes(self) -> None:
        self.repo.write("src/example/calc.py", "def add(a, b):\n    return b + a\n")
        self.repo.commit("work")
        self.assertTrue(self.run_gate("base_identity").passed)

    def test_wrong_parent_commit_fails(self) -> None:
        self.repo.write("src/example/calc.py", "one\n")
        self.repo.commit("first")
        self.repo.write("src/example/calc.py", "two\n")
        self.repo.commit("second")
        result = self.run_gate("base_identity")
        self.assertEqual((result.result, result.reason_code), ("FAIL", "base_mismatch"))
        self.assertEqual(result.findings[0]["severity"], "CRITICAL")

    def test_dirty_worktree_fails(self) -> None:
        self.repo.write("src/example/calc.py", "uncommitted\n")
        result = self.run_gate("base_identity")
        self.assertEqual((result.result, result.reason_code), ("FAIL", "dirty_worktree"))

    def test_dirty_worktree_is_expected_after_work(self) -> None:
        self.repo.write("src/example/calc.py", "uncommitted\n")
        self.assertTrue(self.run_gate("base_identity", require_clean=False).passed)

    def test_unknown_base_fails(self) -> None:
        result = self.run_gate("base_identity", base="b" * 40)
        self.assertEqual((result.result, result.reason_code), ("FAIL", "unknown_base"))


class VerificationGateTest(GateTestCase):
    def test_zero_exit_passes(self) -> None:
        self.assertTrue(self.run_gate("verification_command").passed)

    def test_nonzero_exit_fails(self) -> None:
        contract = dict(
            CONTRACT,
            verification={
                "command": [sys.executable, "-c", "raise SystemExit(1)"],
                "expect_exit_code": 0,
            },
        )
        result = self.run_gate("verification_command", contract=contract)
        self.assertEqual((result.result, result.reason_code), ("FAIL", "nonzero_exit"))

    def test_missing_command_fails_closed_with_its_own_reason(self) -> None:
        # The Windows Store alias class of failure: the command is absent.
        # It must never be reported as skipped, and never as green.
        contract = dict(
            CONTRACT,
            verification={"command": ["definitely-not-a-real-command-xyz"], "expect_exit_code": 0},
        )
        result = self.run_gate("verification_command", contract=contract)
        self.assertEqual(result.result, "FAIL")
        self.assertEqual(result.reason_code, "command_not_found")
        self.assertNotIn(result.result, ("PASS", "NOT_RUN"))
        self.assertEqual(result.findings[0]["severity"], "CRITICAL")

    def test_an_expected_nonzero_exit_code_passes(self) -> None:
        contract = dict(
            CONTRACT,
            verification={
                "command": [sys.executable, "-c", "raise SystemExit(3)"],
                "expect_exit_code": 3,
            },
        )
        self.assertTrue(self.run_gate("verification_command", contract=contract).passed)

    def test_timeout_fails_with_its_own_reason(self) -> None:
        contract = dict(
            CONTRACT,
            verification={
                "command": [sys.executable, "-c", "import time; time.sleep(30)"],
                "expect_exit_code": 0,
                "timeout_seconds": 1,
            },
        )
        result = self.run_gate("verification_command", contract=contract)
        self.assertEqual((result.result, result.reason_code), ("FAIL", "timeout"))

    def test_a_contract_without_verification_is_an_author_error(self) -> None:
        with self.assertRaises(gates.GateError):
            gates.verification_command({"scope": {}}, self.context())


class SchemaGateTest(GateTestCase):
    def documents(self, fixture: str, name: str, schema: str) -> gates.DocumentRef:
        payload = json.loads(
            (support.FIXTURE_ROOT / fixture).read_text(encoding="utf-8")
        )["data"]
        self.repo.write(name, json.dumps(payload, indent=2))
        return gates.DocumentRef(path=name, schema=schema)

    def test_valid_envelope_passes(self) -> None:
        reference = self.documents(
            "m1/valid/envelope-review.json", "out/envelope.json", "envelope.schema.json"
        )
        result = self.run_gate("schema", documents=(reference,))
        self.assertEqual((result.result, result.reason_code), ("PASS", "clean"))

    def test_the_m1_invalid_fixtures_fail_through_the_gate(self) -> None:
        cases = [
            "m1/invalid/envelope-empty-non-claims.json",
            "m1/invalid/envelope-unknown-field.json",
            "m1/invalid/envelope-status-outside-enum.json",
            "m1/invalid/envelope-digest-missing-prefix.json",
            "m1/invalid/envelope-missing-schema-version.json",
            "m1/invalid/envelope-vacuous-pass.json",
            "m1/invalid/envelope-unknown-evidence-ref.json",
        ]
        for fixture in cases:
            with self.subTest(fixture=fixture):
                reference = self.documents(
                    fixture, "out/candidate.json", "envelope.schema.json"
                )
                result = self.run_gate("schema", documents=(reference,))
                self.assertEqual(result.result, "FAIL")
                self.assertEqual(result.reason_code, "schema_invalid")
                self.assertTrue(result.findings)

    def test_unreadable_document_fails(self) -> None:
        self.repo.write("out/broken.json", "{not json")
        reference = gates.DocumentRef(path="out/broken.json", schema="envelope.schema.json")
        result = self.run_gate("schema", documents=(reference,))
        self.assertEqual((result.result, result.reason_code), ("FAIL", "schema_invalid"))

    def test_no_documents_is_reported_not_hidden(self) -> None:
        result = self.run_gate("schema")
        self.assertEqual((result.result, result.reason_code), ("NOT_RUN", "not_applicable"))


class EvidenceObligationsGateTest(GateTestCase):
    def contract(self, requirements) -> dict:
        return {
            "schema_version": "workflows.goal-contract.v1",
            "contract_id": "goal-example",
            "contract_revision": 1,
            "contract_type": "goal",
            "goal": "Establish whether the deliverables exist and their references resolve.",
            "subgoals": [{"id": "SG-1", "statement": "Deliverables exist and resolve."}],
            "evidence_requirements": requirements,
            "attainment_rubric": {
                "levels": [
                    {"id": "attained", "statement": "Every obligation is met."},
                    {"id": "not-attained", "statement": "Obligations are unmet."},
                ]
            },
        }

    def test_existing_artifact_passes(self) -> None:
        contract = self.contract(
            [{"id": "ER-1", "statement": "The guide exists.", "check": "artifact_exists", "target": "docs/guide.md"}]
        )
        self.assertTrue(self.run_gate("evidence_obligations", contract=contract).passed)

    def test_missing_artifact_fails(self) -> None:
        contract = self.contract(
            [{"id": "ER-1", "statement": "The report exists.", "check": "artifact_exists", "target": "docs/report.md"}]
        )
        result = self.run_gate("evidence_obligations", contract=contract)
        self.assertEqual((result.result, result.reason_code), ("FAIL", "missing_artifact"))

    def test_empty_artifact_fails(self) -> None:
        self.repo.write("docs/report.md", "")
        contract = self.contract(
            [{"id": "ER-1", "statement": "The report exists.", "check": "artifact_exists", "target": "docs/report.md"}]
        )
        result = self.run_gate("evidence_obligations", contract=contract)
        self.assertEqual((result.result, result.reason_code), ("FAIL", "empty_artifact"))

    def test_unresolved_reference_fails(self) -> None:
        self.repo.write("docs/report.md", "See [missing](../src/example/gone.py).\n")
        contract = self.contract(
            [{"id": "ER-2", "statement": "References resolve.", "check": "reference_resolves", "target": "docs/report.md"}]
        )
        result = self.run_gate("evidence_obligations", contract=contract)
        self.assertEqual((result.result, result.reason_code), ("FAIL", "unresolved_reference"))

    def test_resolving_references_pass(self) -> None:
        contract = self.contract(
            [{"id": "ER-2", "statement": "References resolve.", "check": "reference_resolves", "target": "docs/guide.md"}]
        )
        self.assertTrue(self.run_gate("evidence_obligations", contract=contract).passed)

    def test_judgment_obligations_are_not_run_and_named(self) -> None:
        """The gate settles the checkable half and says what it left alone.

        NOT_RUN rather than INCONCLUSIVE: there is no check to run, so the
        gate did not fail to conclude. Reporting otherwise would let one
        unanswerable obligation block every goal verdict.
        """
        contract = self.contract(
            [
                {"id": "ER-1", "statement": "The guide exists.", "check": "artifact_exists", "target": "docs/guide.md"},
                {"id": "ER-3", "statement": "The narrative answers the brief.", "check": "manual_judgment"},
            ]
        )
        result = self.run_gate("evidence_obligations", contract=contract)
        self.assertEqual((result.result, result.reason_code), ("PASS", "clean"))
        self.assertTrue(any("ER-3" in claim for claim in result.non_claims))
        outcomes = {check["id"]: check["result"] for check in result.checks}
        self.assertEqual(outcomes, {"ER-1": "PASS", "ER-3": "NOT_RUN"})

    def test_one_unmet_obligation_does_not_condemn_the_others(self) -> None:
        contract = self.contract(
            [
                {"id": "ER-absent", "statement": "The report exists.", "check": "artifact_exists", "target": "docs/absent.md"},
                {"id": "ER-present", "statement": "The guide exists.", "check": "artifact_exists", "target": "docs/guide.md"},
            ]
        )
        result = self.run_gate("evidence_obligations", contract=contract)
        outcomes = {check["id"]: check["result"] for check in result.checks}
        self.assertEqual(outcomes, {"ER-absent": "FAIL", "ER-present": "PASS"})
        self.assertEqual(len(result.findings), 1)


class GateRunnerTest(GateTestCase):
    GATE_LIST = ("base_identity", "scope", "protected_hash", "verification_command")

    def test_runs_every_gate_in_order(self) -> None:
        results = gates.run_gates(self.GATE_LIST, CONTRACT, self.context())
        self.assertEqual([result.gate_id for result in results], list(self.GATE_LIST))
        for result in results:
            self.check(result)

    def test_unknown_gate_name_raises(self) -> None:
        with self.assertRaises(gates.GateError):
            gates.run_gates(["not_a_gate"], CONTRACT, self.context())

    def test_a_failing_gate_does_not_stop_the_others(self) -> None:
        # Every gate reports; the flow decides what to do with the set.
        self.repo.write("tests/test_calc.py", "tampered\n")
        self.repo.write("secrets/x.txt", "out of scope\n")
        results = gates.run_gates(self.GATE_LIST, CONTRACT, self.context(require_clean=False))
        failed = {result.gate_id for result in results if result.failed}
        self.assertEqual(failed, {"scope", "protected_hash"})

    def test_aggregate_result(self) -> None:
        def make(result: str) -> gates.GateResult:
            return gates.GateResult("g", result, "clean", FIXED_CLOCK)

        self.assertEqual(gates.aggregate_result([make("PASS"), make("NOT_RUN")]), "PASS")
        self.assertEqual(gates.aggregate_result([make("PASS"), make("FAIL")]), "FAIL")
        self.assertEqual(
            gates.aggregate_result([make("INCONCLUSIVE"), make("PASS")]), "INCONCLUSIVE"
        )
        self.assertEqual(gates.aggregate_result([make("FAIL"), make("INCONCLUSIVE")]), "FAIL")
        self.assertEqual(gates.aggregate_result([make("NOT_RUN")]), "NOT_RUN")

    def test_the_envelope_the_runner_folds_is_schema_valid(self) -> None:
        results = gates.run_gates(self.GATE_LIST, CONTRACT, self.context())
        envelope = gates.gate_envelope(
            results,
            run_id="run-0001",
            step_id="gates-level-0",
            contract_ref=CONTRACT_REF,
            dry_run=False,
            produced_at=FIXED_CLOCK,
        )
        errors = check_document(envelope, "envelope.schema.json", registry=self.registry)
        self.assertEqual([str(error) for error in errors], [])
        self.assertEqual(envelope["result"], "PASS")

    def test_a_failing_envelope_is_also_schema_valid_and_carries_the_findings(self) -> None:
        self.repo.write("tests/test_calc.py", "tampered\n")
        results = gates.run_gates(self.GATE_LIST, CONTRACT, self.context(require_clean=False))
        envelope = gates.gate_envelope(
            results,
            run_id="run-0001",
            step_id="gates-level-0",
            contract_ref=CONTRACT_REF,
            dry_run=False,
            produced_at=FIXED_CLOCK,
        )
        errors = check_document(envelope, "envelope.schema.json", registry=self.registry)
        self.assertEqual([str(error) for error in errors], [])
        self.assertEqual(envelope["result"], "FAIL")
        self.assertTrue(envelope["findings"])
        self.assertEqual(envelope["ladder_level"], 0)

    def test_the_envelope_says_what_gates_do_not_claim(self) -> None:
        results = gates.run_gates(("protected_hash",), dict(CONTRACT, protected=[]), self.context())
        envelope = gates.gate_envelope(
            results,
            run_id="run-0001",
            step_id="gates-level-0",
            contract_ref=CONTRACT_REF,
            dry_run=False,
            produced_at=FIXED_CLOCK,
        )
        joined = " ".join(envelope["non_claims"])
        self.assertIn("no model judged this candidate", joined)
        self.assertIn("protected_hash", joined)


if __name__ == "__main__":
    unittest.main()
