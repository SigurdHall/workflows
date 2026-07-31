"""Every annotated fixture validates, or fails for exactly its annotated reason."""

from __future__ import annotations

import unittest
from dataclasses import replace

from tests import support


class FixtureHarnessTest(unittest.TestCase):
    """The harness must be able to fail; otherwise the corpus proves nothing."""

    def test_a_wrong_annotation_is_detected(self) -> None:
        template = next(f for f in support.iter_fixtures() if f.expect == "invalid")
        mislabelled = replace(template, expected_errors=(("/nowhere", "type"),))
        self.assertNotEqual(
            support.actual_errors(mislabelled), sorted(mislabelled.expected_errors)
        )

    def test_a_valid_fixture_cannot_annotate_errors(self) -> None:
        with self.assertRaises(ValueError):
            support.load_fixture_mapping(
                {
                    "fixture_version": support.FIXTURE_VERSION,
                    "schema": "core.defs.schema.json#/$defs/status",
                    "expect": "valid",
                    "reason": "contradictory",
                    "expected_errors": [{"path": "", "keyword": "enum"}],
                    "data": "BLOCKED",
                }
            )

    def test_an_invalid_fixture_must_annotate_errors(self) -> None:
        with self.assertRaises(ValueError):
            support.load_fixture_mapping(
                {
                    "fixture_version": support.FIXTURE_VERSION,
                    "schema": "core.defs.schema.json#/$defs/status",
                    "expect": "invalid",
                    "reason": "unannotated",
                    "data": "nope",
                }
            )

    def test_unknown_fixture_keys_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            support.load_fixture_mapping(
                {
                    "fixture_version": support.FIXTURE_VERSION,
                    "schema": "core.defs.schema.json#/$defs/status",
                    "expect": "valid",
                    "reason": "extra key",
                    "data": "BLOCKED",
                    "comment": "not part of the format",
                }
            )


class FixtureCorpusTest(unittest.TestCase):
    def test_corpus_is_not_empty(self) -> None:
        self.assertGreater(len(list(support.iter_fixtures())), 0)

    def test_corpus_covers_both_expectations(self) -> None:
        expectations = {fixture.expect for fixture in support.iter_fixtures()}
        self.assertEqual(expectations, {"valid", "invalid"})

    def test_every_fixture_matches_its_annotation(self) -> None:
        for fixture in support.iter_fixtures():
            with self.subTest(fixture=fixture.name):
                actual = support.actual_errors(fixture)
                expected = sorted(fixture.expected_errors)
                self.assertEqual(
                    actual,
                    expected,
                    f"{fixture.name} ({fixture.reason}): expected {expected}, got {actual}",
                )


if __name__ == "__main__":
    unittest.main()
