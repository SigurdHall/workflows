"""The lens set this repository ships.

A lens is data the flows depend on, so the catalog is held to the same
standard as a schema: every file parses, every identity is unique, and every
lens says which territory it leaves to its siblings. Overlap without a
stated boundary is what turned ten perspectives into three findings in the
motivating experiment.
"""

from __future__ import annotations

import re
import unittest

from workflows import lenses, prompts

EXPECTED_WORK = {
    "work/spec-fidelity",
    "work/minimal-change",
    "work/defensive-input",
    "work/api-design",
}
EXPECTED_REVIEW = {
    "review/closed-contract",
    "review/determinism",
    "review/boundary-values",
    "review/metamorphic",
    "review/scope-integrity",
    "review/negative-path",
}

OUTPUT_SCHEMA = {"type": "object", "required": [], "properties": {}}


def does_not_cover(lens: lenses.Lens) -> str:
    match = re.search(
        r"^#+\s*Does not cover\s*$(.*?)(?=^#+\s|\Z)",
        lens.text,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    return match.group(1) if match else ""


class CatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = lenses.catalog()
        self.by_id = {lens.id: lens for lens in self.catalog}

    def test_the_starter_set_is_present(self) -> None:
        self.assertEqual(set(self.by_id), EXPECTED_WORK | EXPECTED_REVIEW)

    def test_the_two_families_stay_separate(self) -> None:
        self.assertEqual({l.id for l in lenses.catalog("work")}, EXPECTED_WORK)
        self.assertEqual({l.id for l in lenses.catalog("review")}, EXPECTED_REVIEW)

    def test_every_lens_is_versioned_and_unique(self) -> None:
        self.assertEqual(len(self.by_id), len(self.catalog))
        for lens in self.catalog:
            with self.subTest(lens=lens.id):
                self.assertGreaterEqual(lens.version, 1)

    def test_every_lens_names_the_territory_it_leaves_to_a_sibling(self) -> None:
        for lens in self.catalog:
            siblings = (EXPECTED_WORK | EXPECTED_REVIEW) - {lens.id}
            section = does_not_cover(lens)
            with self.subTest(lens=lens.id):
                self.assertTrue(section.strip(), "the section may not be empty")
                named = [sibling for sibling in siblings if sibling in section]
                self.assertTrue(
                    named,
                    "a boundary that names no neighbour is not a boundary",
                )

    def test_review_lenses_demand_probed_evidence(self) -> None:
        for lens in lenses.catalog("review"):
            with self.subTest(lens=lens.id):
                self.assertIn("evidence_refs", lens.text)

    def test_every_lens_composes_into_a_prompt(self) -> None:
        contract = {"contract_id": "c", "goal": "g"}
        for lens in self.catalog:
            with self.subTest(lens=lens.id):
                composed = (
                    prompts.work(contract=contract, lens=lens, output_schema=OUTPUT_SCHEMA)
                    if lens.family == "work"
                    else prompts.review(
                        contract=contract,
                        lens=lens,
                        output_schema=OUTPUT_SCHEMA,
                        candidate="diff",
                    )
                )
                self.assertIn(lens.text.strip(), composed)

    def test_no_lens_carries_environment_specific_content(self) -> None:
        forbidden = re.compile(r"[A-Za-z]:\\\\|[A-Za-z]:\\Users|@[a-z0-9-]+\.[a-z]{2,}")
        for lens in self.catalog:
            with self.subTest(lens=lens.id):
                self.assertIsNone(forbidden.search(lens.text))


if __name__ == "__main__":
    unittest.main()
