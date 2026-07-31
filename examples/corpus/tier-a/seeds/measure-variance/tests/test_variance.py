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

    def test_portfolio_percent_variance_matches_hand_computed_average(self):
        rows = read_rows()
        # Hand-computed as the mean of each department's own percent
        # variance: retail 20.0, logistics -10.0, wholesale 10.0.
        self.assertAlmostEqual(portfolio_percent_variance(rows), 20.0 / 3)


if __name__ == "__main__":
    unittest.main()
