import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extract import parse_record, parse_records, validate_record


class ExtractTests(unittest.TestCase):
    def test_parses_a_well_formed_line(self):
        record = parse_record("name=Jane Doe; active=true; age=34")
        self.assertEqual(record["name"], "Jane Doe")
        self.assertEqual(record["age"], 34)

    def test_validate_record_accepts_a_well_formed_record(self):
        record = parse_record("name=Jane Doe; active=true; age=34")
        self.assertTrue(validate_record(record))

    def test_parse_records_returns_one_record_per_line(self):
        text = "name=Jane Doe; active=true; age=34\nname=Sam Lee; active=false; age=41\n"
        records = parse_records(text)
        self.assertEqual(len(records), 2)

    def test_parse_records_skips_comment_lines(self):
        text = "# export header\nname=Jane Doe; active=true; age=34\n"
        records = parse_records(text)
        self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
