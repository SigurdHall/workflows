"""Class 6, blank identity: whitespace accepted as a dimension key.

Present when `build_dimension` emits a member whose customer_id is empty once
stripped. A key that is blank in substance is not a key, whatever it looks
like in a CSV cell.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load  # noqa: E402

ROWS = [
    {"order_id": "1", "customer_id": "c1", "customer_name": "Acme", "region": "north", "amount": "100"},
    {"order_id": "2", "customer_id": " ", "customer_name": "Unnamed", "region": "west", "amount": "50"},
]


def defect_is_present() -> bool:
    split = load("split")
    members = split.build_dimension([dict(row) for row in ROWS])
    return any(not str(member.get("customer_id", "")).strip() for member in members)


answer(defect_is_present)
