import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from snapshot import apply_snapshot, digest


class SnapshotTests(unittest.TestCase):
    def test_apply_snapshot_records_rows_and_digest(self):
        store = {}
        rows = [{"sku": "a1", "qty": 3}, {"sku": "b2", "qty": 5}]
        apply_snapshot(store, "site-1", "2026-07-01", rows)
        self.assertEqual(store["site-1"]["as_of"], "2026-07-01")
        self.assertEqual(store["site-1"]["digest"], digest(rows))

    def test_a_later_snapshot_replaces_an_earlier_one(self):
        store = {}
        apply_snapshot(store, "site-1", "2026-07-01", [{"sku": "a1", "qty": 3}])
        apply_snapshot(store, "site-1", "2026-07-02", [{"sku": "a1", "qty": 4}])
        self.assertEqual(store["site-1"]["as_of"], "2026-07-02")

    def test_digest_is_stable_for_the_same_rows_object(self):
        rows = [{"sku": "a1", "qty": 3}, {"sku": "b2", "qty": 5}]
        self.assertEqual(digest(rows), digest(rows))


if __name__ == "__main__":
    unittest.main()
