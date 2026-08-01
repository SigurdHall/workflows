"""Class 2, order-dependent canonicalization: a digest that changes with row order.

Present when digesting the same rows in a different order gives a different
value. A snapshot digest is meant to identify content; if it identifies
content-plus-ordering, every reordering reads as a change.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load  # noqa: E402

ROWS = [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}, {"id": 3, "value": "c"}]


def defect_is_present() -> bool:
    snapshot = load("snapshot")
    forwards = snapshot.digest([dict(row) for row in ROWS])
    backwards = snapshot.digest([dict(row) for row in reversed(ROWS)])
    return forwards != backwards


answer(defect_is_present)
