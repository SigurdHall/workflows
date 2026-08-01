"""Class 10, reference integrity: fact rows pointing at absent dimension members.

Present when the fact table carries a customer id the dimension does not
contain. The fixture has a customer with no region on file, which the seed
drops from the dimension while keeping its orders in the fact.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load  # noqa: E402

ROWS = [
    {"order_id": "1", "customer_id": "c1", "customer_name": "Acme", "region": "north", "amount": "100"},
    {"order_id": "2", "customer_id": "c9", "customer_name": "Ghost", "region": "", "amount": "75"},
]


def defect_is_present() -> bool:
    split = load("split")
    dimension = {
        str(member.get("customer_id", "")).strip()
        for member in split.build_dimension([dict(row) for row in ROWS])
    }
    fact = {
        str(row.get("customer_id", "")).strip()
        for row in split.build_fact([dict(row) for row in ROWS])
    }
    return bool(fact - dimension)


answer(defect_is_present)
