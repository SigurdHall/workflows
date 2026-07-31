"""Prompt composition: deterministic, and blind where it must be."""

from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

from workflows import lenses, prompts

LENS_TEXT = """<!-- lens: review/closed-contract v3 -->

# Closed contract

## Targets

Fields accepted where the contract is closed.

## Method

Probe with an undeclared field and record the outcome.

## Does not cover

Determinism and ordering, which belong to another lens.

## Output obligations

Every finding names the field and the probe that produced it.
"""

CONTRACT = {
    "schema_version": "workflows.task-contract.v1",
    "contract_id": "contract-example",
    "goal": "Reject undeclared fields at every boundary.",
    "scope": {"allowed_paths": ["src/**"]},
}

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["result"],
    "properties": {"result": {"type": "string", "enum": ["PASS", "FAIL"]}},
}


class PromptTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        (root / "review").mkdir(parents=True)
        (root / "review" / "closed-contract.md").write_text(LENS_TEXT, encoding="utf-8")
        self.lens = lenses.load("review/closed-contract", root)


class DeterminismTest(PromptTestCase):
    def test_the_same_inputs_compose_byte_identical_prompts(self) -> None:
        first = prompts.work(
            contract=CONTRACT,
            lens=self.lens,
            output_schema=OUTPUT_SCHEMA,
            focus_hint="Watch the digest under reordering.",
        )
        second = prompts.work(
            contract=CONTRACT,
            lens=self.lens,
            output_schema=OUTPUT_SCHEMA,
            focus_hint="Watch the digest under reordering.",
        )
        self.assertEqual(first, second)
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))

    def test_key_insertion_order_does_not_leak_into_the_prompt(self) -> None:
        reordered = {key: CONTRACT[key] for key in reversed(list(CONTRACT))}
        self.assertNotEqual(list(reordered), list(CONTRACT))
        self.assertEqual(
            prompts.work(contract=CONTRACT, lens=self.lens, output_schema=OUTPUT_SCHEMA),
            prompts.work(contract=reordered, lens=self.lens, output_schema=OUTPUT_SCHEMA),
        )

    def test_a_different_focus_hint_gives_a_different_prompt(self) -> None:
        without = prompts.work(contract=CONTRACT, lens=self.lens, output_schema=OUTPUT_SCHEMA)
        with_hint = prompts.work(
            contract=CONTRACT, lens=self.lens, output_schema=OUTPUT_SCHEMA, focus_hint="Narrow it."
        )
        self.assertNotEqual(without, with_hint)
        self.assertIn("Narrow it.", with_hint)

    def test_the_lens_is_injected_verbatim(self) -> None:
        composed = prompts.work(contract=CONTRACT, lens=self.lens, output_schema=OUTPUT_SCHEMA)
        self.assertIn(LENS_TEXT.strip(), composed)
        self.assertIn("review/closed-contract v3", composed)


class BlindnessTest(PromptTestCase):
    def test_a_review_prompt_has_nowhere_to_put_producer_dialogue(self) -> None:
        """Blindness is structural: there is no parameter to pass it through."""
        parameters = set(inspect.signature(prompts.review).parameters)
        self.assertEqual(
            parameters,
            {"contract", "lens", "output_schema", "candidate", "focus_hint"},
        )

    def test_a_review_prompt_carries_the_candidate_and_the_contract(self) -> None:
        composed = prompts.review(
            contract=CONTRACT,
            lens=self.lens,
            output_schema=OUTPUT_SCHEMA,
            candidate="diff --git a/src/x.py b/src/x.py\n+VALUE = 2\n",
        )
        self.assertIn("VALUE = 2", composed)
        self.assertIn("contract-example", composed)
        self.assertIn("## Candidate", composed)
        self.assertIn("## Required output", composed)

    def test_a_repair_prompt_does_not_take_the_failed_candidate(self) -> None:
        parameters = set(inspect.signature(prompts.repair).parameters)
        self.assertEqual(
            parameters, {"contract", "lens", "output_schema", "findings", "focus_hint"}
        )
        composed = prompts.repair(
            contract=CONTRACT,
            lens=self.lens,
            output_schema=OUTPUT_SCHEMA,
            findings=[{"id": "F-1", "claim": "A protected file changed."}],
        )
        self.assertIn("Build from the original base", composed)
        self.assertIn("F-1", composed)


class OutputInstructionTest(PromptTestCase):
    def test_the_schema_is_embedded_and_prose_is_forbidden(self) -> None:
        composed = prompts.work(contract=CONTRACT, lens=self.lens, output_schema=OUTPUT_SCHEMA)
        self.assertIn(json.dumps(OUTPUT_SCHEMA, indent=2, sort_keys=True), composed)
        self.assertIn("No prose", composed)

    def test_the_prompt_version_is_stated(self) -> None:
        composed = prompts.work(contract=CONTRACT, lens=self.lens, output_schema=OUTPUT_SCHEMA)
        self.assertIn(prompts.PROMPT_VERSION, composed)


if __name__ == "__main__":
    unittest.main()
