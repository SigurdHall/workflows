import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router import classify, classify_batch, with_custom_rule


class RouterTests(unittest.TestCase):
    def test_classifies_billing_language(self):
        self.assertEqual(classify("Please refund my last charge"), "billing")

    def test_classifies_bug_language(self):
        self.assertEqual(classify("The app crashed on launch"), "bug")

    def test_unmatched_text_is_uncategorized(self):
        self.assertEqual(classify("What time is the demo tomorrow?"), "uncategorized")

    def test_batch_preserves_order(self):
        items = ["add support for dark mode", "I was overcharged twice"]
        self.assertEqual(classify_batch(items), ["feature-request", "billing"])

    def test_custom_rule_is_tried_first(self):
        rules = with_custom_rule("vip", "billing")
        self.assertEqual(classify("vip customer needs a callback", rules), "billing")


if __name__ == "__main__":
    unittest.main()
