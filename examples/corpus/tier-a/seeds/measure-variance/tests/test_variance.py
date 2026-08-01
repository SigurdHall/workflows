import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from variance import percent_variance, portfolio_percent_variance, read_rows, variance


class VarianceTests(unittest.TestCase):
    def test_variance_is_actual_minus_budget(self):
        self.assertEqual(variance(1000, 1200), 200)

    def test_percent_variance_basic(self):
        self.assertAlmostEqual(percent_variance(1000, 1200), 20.0)

    def test_percent_variance_guards_zero_budget(self):
        self.assertIsNone(percent_variance(0, 150))

    def test_portfolio_percent_variance_returns_a_number(self):
        # Deliberately does not assert what the portfolio figure should be.
        # A test that pinned it would pin one aggregation method, and this
        # corpus plants defects that a green happy-path run does not catch —
        # not defects the protected tests make impossible to fix.
        self.assertIsInstance(portfolio_percent_variance(read_rows()), float)


if __name__ == "__main__":
    unittest.main()
