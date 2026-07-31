import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from split import build_dimension, build_fact, read_extract


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.rows = read_extract()

    def test_dimension_has_one_row_per_distinct_customer(self):
        dimension = build_dimension(self.rows)
        ids = [row["customer_id"] for row in dimension]
        self.assertEqual(len(ids), len(set(ids)))

    def test_fact_has_one_row_per_order(self):
        fact = build_fact(self.rows)
        self.assertEqual(len(fact), 5)

    def test_every_known_customer_appears_in_the_fact_table(self):
        dimension_ids = {row["customer_id"] for row in build_dimension(self.rows)}
        fact_ids = {row["customer_id"] for row in build_fact(self.rows)}
        self.assertTrue(dimension_ids <= fact_ids)


if __name__ == "__main__":
    unittest.main()
