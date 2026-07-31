import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from checker import (
    every_rule_is_nonempty,
    has_minimum_rule_count,
    load_rules,
    mentions_order_number,
)


class CheckerTests(unittest.TestCase):
    def test_loads_all_numbered_rules(self):
        self.assertEqual(len(load_rules()), 6)

    def test_has_minimum_rule_count(self):
        self.assertTrue(has_minimum_rule_count(load_rules()))

    def test_mentions_order_number(self):
        self.assertTrue(mentions_order_number(load_rules()))

    def test_every_rule_is_nonempty(self):
        self.assertTrue(every_rule_is_nonempty(load_rules()))


if __name__ == "__main__":
    unittest.main()
