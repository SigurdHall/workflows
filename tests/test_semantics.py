"""Semantic rules not exercised by the fixture corpus, plus the ordering rule.

The fixture corpus covers one violation per rule end to end. These tests
cover the remaining rules and the contract between schema validation and
semantic validation.
"""

from __future__ import annotations

import json
import unittest

from tests import support
from workflows import semantics


def data(name: str) -> dict:
    return json.loads((support.FIXTURE_ROOT / name).read_text(encoding="utf-8"))["data"]


def rules(document: dict, schema: str) -> list[tuple[str, str]]:
    return sorted(
        (error.path, error.keyword)
        for error in semantics.check_document(document, schema, registry=support.registry())
    )


class OrderingTest(unittest.TestCase):
    def test_semantic_rules_do_not_run_on_a_schema_invalid_document(self) -> None:
        """One cause, reported once: a broken shape is not also a broken rule."""
        document = data("m1/valid/verdict-fail.json")
        document["result"] = "PASS"          # would trip pass_with_open_blocking_finding
        document.pop("non_claims")           # schema violation
        found = rules(document, "verdict.schema.json")
        self.assertEqual(found, [("/non_claims", "required")])

    def test_sub_schema_references_have_no_semantic_rules(self) -> None:
        finding = data("core/valid/finding-minimal.json")
        self.assertEqual(
            semantics.semantic_errors(finding, "core.defs.schema.json#/$defs/finding"), []
        )


class EnvelopeRuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.envelope = data("m1/valid/envelope-review.json")

    def test_duplicate_finding_id(self) -> None:
        self.envelope["findings"].append(dict(self.envelope["findings"][0]))
        self.assertIn(
            ("/findings/1/id", "semantic:duplicate_finding_id"),
            rules(self.envelope, "envelope.schema.json"),
        )

    def test_duplicate_criterion_id(self) -> None:
        self.envelope["criterion_results"][1]["criterion_id"] = "AC-1"
        self.assertIn(
            ("/criterion_results/1/criterion_id", "semantic:duplicate_criterion_id"),
            rules(self.envelope, "envelope.schema.json"),
        )

    def test_criterion_negative_path_without_probe(self) -> None:
        self.envelope["criterion_results"][1]["evidence_refs"] = ["cmd-verification"]
        self.assertIn(
            ("/criterion_results/1", "semantic:negative_path_requires_probe"),
            rules(self.envelope, "envelope.schema.json"),
        )

    def test_a_resolved_high_finding_does_not_block_a_pass(self) -> None:
        self.envelope["result"] = "PASS"
        self.envelope["findings"][0]["status"] = "RESOLVED"
        self.envelope["criterion_results"][1]["result"] = "PASS"
        self.assertEqual(rules(self.envelope, "envelope.schema.json"), [])

    def test_an_open_medium_finding_does_not_block_a_pass(self) -> None:
        self.envelope["result"] = "PASS"
        self.envelope["findings"][0]["severity"] = "MEDIUM"
        self.envelope["criterion_results"][1]["result"] = "PASS"
        self.assertEqual(rules(self.envelope, "envelope.schema.json"), [])


class PlanRuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = data("m1/valid/plan-three-tasks.json")

    def test_duplicate_repo_id(self) -> None:
        self.plan["base"].append(dict(self.plan["base"][0]))
        self.assertIn(
            ("/base/1/repo_id", "semantic:duplicate_repo_id"),
            rules(self.plan, "plan.schema.json"),
        )

    def test_multi_repo_plan_requires_every_task_to_name_its_repo(self) -> None:
        self.plan["base"].append({"repo_id": "docs-site", "commit": "b" * 40})
        self.plan["tasks"][0].pop("repo_id")
        self.assertIn(
            ("/tasks/0/repo_id", "semantic:ambiguous_repo"),
            rules(self.plan, "plan.schema.json"),
        )

    def test_single_repo_plan_may_omit_the_repo_id(self) -> None:
        for task in self.plan["tasks"]:
            task.pop("repo_id")
        self.assertEqual(rules(self.plan, "plan.schema.json"), [])

    def test_tasks_in_different_repositories_may_share_a_scope(self) -> None:
        self.plan["base"].append({"repo_id": "docs-site", "commit": "b" * 40})
        self.plan["tasks"][1]["repo_id"] = "docs-site"
        self.plan["tasks"][1]["write_scope"] = ["src/parser/**"]
        self.assertEqual(rules(self.plan, "plan.schema.json"), [])


class ContractRuleTest(unittest.TestCase):
    def test_goal_contract_duplicate_ids(self) -> None:
        contract = data("m1/valid/goal-contract.json")
        contract["subgoals"][1]["id"] = "SG-1"
        contract["evidence_requirements"][1]["id"] = "ER-1"
        contract["attainment_rubric"]["levels"][1]["id"] = "attained"
        found = rules(contract, "goal-contract.schema.json")
        self.assertEqual(
            found,
            sorted(
                [
                    ("/subgoals/1/id", "semantic:duplicate_subgoal_id"),
                    ("/evidence_requirements/1/id", "semantic:duplicate_requirement_id"),
                    (
                        "/attainment_rubric/levels/1/id",
                        "semantic:duplicate_rubric_level_id",
                    ),
                ]
            ),
        )

    def test_manual_judgment_may_omit_a_target(self) -> None:
        contract = data("m1/valid/goal-contract.json")
        self.assertEqual(rules(contract, "goal-contract.schema.json"), [])

    def test_protected_subtree_outside_scope_is_fine(self) -> None:
        contract = data("m1/valid/task-contract.json")
        contract["protected"] = ["tests/**"]
        self.assertEqual(rules(contract, "task-contract.schema.json"), [])


if __name__ == "__main__":
    unittest.main()
