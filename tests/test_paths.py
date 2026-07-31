"""Scope pattern matching.

Scope is what a human approves and a gate enforces, so the matching rules
are tested directly rather than through their callers.
"""

from __future__ import annotations

import unittest

from workflows import paths


class MatchTest(unittest.TestCase):
    def test_literal_path_covers_itself_and_its_children(self) -> None:
        self.assertTrue(paths.matches("docs", "docs"))
        self.assertTrue(paths.matches("docs", "docs/guide.md"))
        self.assertTrue(paths.matches("docs", "docs/a/b.md"))
        self.assertFalse(paths.matches("docs", "documents/guide.md"))
        self.assertFalse(paths.matches("docs", "src/docs.md"))

    def test_single_star_stays_inside_one_segment(self) -> None:
        self.assertTrue(paths.matches("src/*.py", "src/main.py"))
        self.assertFalse(paths.matches("src/*.py", "src/pkg/main.py"))
        self.assertFalse(paths.matches("*.md", "docs/readme.md"))

    def test_double_star_spans_segments(self) -> None:
        self.assertTrue(paths.matches("src/**", "src/main.py"))
        self.assertTrue(paths.matches("src/**", "src/a/b/c.py"))
        self.assertFalse(paths.matches("src/**", "src"))
        self.assertFalse(paths.matches("src/**", "srcx/main.py"))

    def test_double_star_in_the_middle_matches_zero_segments(self) -> None:
        self.assertTrue(paths.matches("src/**/test_*.py", "src/test_a.py"))
        self.assertTrue(paths.matches("src/**/test_*.py", "src/pkg/deep/test_a.py"))
        self.assertFalse(paths.matches("src/**/test_*.py", "src/pkg/a.py"))

    def test_trailing_slash_means_everything_under(self) -> None:
        self.assertTrue(paths.matches("src/", "src/main.py"))
        self.assertFalse(paths.matches("src/", "src"))

    def test_matches_any(self) -> None:
        allowed = ["src/parser/**", "docs/parser.md"]
        self.assertTrue(paths.matches_any(allowed, "src/parser/lex.py"))
        self.assertTrue(paths.matches_any(allowed, "docs/parser.md"))
        self.assertFalse(paths.matches_any(allowed, "src/report/render.py"))


class OverlapTest(unittest.TestCase):
    def test_sibling_subtrees_are_disjoint(self) -> None:
        self.assertFalse(paths.overlaps("src/parser/**", "src/report/**"))
        self.assertFalse(paths.overlaps("src/a", "src/ab"))

    def test_nested_subtrees_overlap(self) -> None:
        self.assertTrue(paths.overlaps("src/**", "src/parser/**"))
        self.assertTrue(paths.overlaps("src/parser/lex.py", "src/parser/**"))
        self.assertTrue(paths.overlaps("docs", "docs/guide.md"))

    def test_identical_patterns_overlap(self) -> None:
        self.assertTrue(paths.overlaps("src/**", "src/**"))

    def test_a_leading_wildcard_is_treated_as_overlapping(self) -> None:
        # Conservative by design: a false overlap costs an edit, a false
        # disjointness costs two flows writing the same file.
        self.assertTrue(paths.overlaps("*.md", "docs/**"))

    def test_literal_prefix(self) -> None:
        self.assertEqual(paths.literal_prefix("src/parser/**"), ["src", "parser"])
        self.assertEqual(paths.literal_prefix("src/*.py"), ["src"])
        self.assertEqual(paths.literal_prefix("*.py"), [])


if __name__ == "__main__":
    unittest.main()
