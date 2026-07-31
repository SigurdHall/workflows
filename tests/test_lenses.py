"""Lens loading: a lens without stable identity cannot be measured, and a
lens without a "does not cover" section is how ten perspectives converge on
three findings.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflows import lenses

VALID = """<!-- lens: review/determinism v2 -->

# Determinism

## Targets

Order-dependent canonicalization and identity that changes under reordering.

## Method

Reorder inputs that denote the same set and compare digests.

## Does not cover

Closed-contract violations, which belong to another lens.

## Output obligations

Each finding names the reordering that produced it.
"""


class LensLoadingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "review").mkdir(parents=True)
        (self.root / "work").mkdir(parents=True)
        lenses._load.cache_clear()

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_valid_lens_loads_with_its_identity(self) -> None:
        self.write("review/determinism.md", VALID)
        lens = lenses.load("review/determinism", self.root)
        self.assertEqual((lens.id, lens.version), ("review/determinism", 2))
        self.assertEqual((lens.family, lens.name), ("review", "determinism"))
        self.assertEqual(lens.reference, "review/determinism v2")
        self.assertEqual(lens.text, VALID)

    def test_a_missing_header_is_refused(self) -> None:
        self.write("review/determinism.md", VALID.split("\n", 1)[1])
        with self.assertRaises(lenses.LensError):
            lenses.load("review/determinism", self.root)

    def test_a_header_that_disagrees_with_the_path_is_refused(self) -> None:
        self.write("review/boundary.md", VALID)
        with self.assertRaises(lenses.LensError) as ctx:
            lenses.load("review/boundary", self.root)
        self.assertIn("path says", str(ctx.exception))

    def test_every_required_section_is_enforced(self) -> None:
        for section in lenses.REQUIRED_SECTIONS:
            with self.subTest(section=section):
                lenses._load.cache_clear()
                self.write(
                    "review/determinism.md", VALID.replace(f"## {section}", "## Something else")
                )
                with self.assertRaises(lenses.LensError) as ctx:
                    lenses.load("review/determinism", self.root)
                self.assertIn(section, str(ctx.exception))

    def test_an_unknown_family_is_refused(self) -> None:
        with self.assertRaises(lenses.LensError):
            lenses.load("nonsense/whatever", self.root)

    def test_a_missing_file_is_refused(self) -> None:
        with self.assertRaises(lenses.LensError):
            lenses.load("review/absent", self.root)

    def test_an_empty_file_is_refused(self) -> None:
        self.write("review/determinism.md", "")
        with self.assertRaises(lenses.LensError):
            lenses.load("review/determinism", self.root)

    def test_the_catalog_is_sorted_and_family_filtered(self) -> None:
        self.write("review/determinism.md", VALID)
        self.write(
            "review/closed-contract.md",
            VALID.replace("review/determinism v2", "review/closed-contract v1"),
        )
        self.write(
            "work/spec-fidelity.md", VALID.replace("review/determinism v2", "work/spec-fidelity v1")
        )
        self.assertEqual(
            [lens.id for lens in lenses.catalog(directory=self.root)],
            ["work/spec-fidelity", "review/closed-contract", "review/determinism"],
        )
        self.assertEqual(
            [lens.id for lens in lenses.catalog("review", self.root)],
            ["review/closed-contract", "review/determinism"],
        )

    def test_load_many_preserves_the_requested_order(self) -> None:
        self.write("review/determinism.md", VALID)
        self.write(
            "review/closed-contract.md",
            VALID.replace("review/determinism v2", "review/closed-contract v1"),
        )
        loaded = lenses.load_many(
            ["review/determinism", "review/closed-contract"], self.root
        )
        self.assertEqual([lens.id for lens in loaded], ["review/determinism", "review/closed-contract"])


if __name__ == "__main__":
    unittest.main()
