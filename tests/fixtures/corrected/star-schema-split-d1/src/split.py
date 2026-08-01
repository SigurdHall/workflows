"""star-schema-split with class 6 corrected and class 10 left planted.

The dimension now rejects a key that is blank once stripped. Orders whose
customer never reaches the dimension are still carried into the fact, so the
reference-integrity probe must still report its defect present.
"""
from __future__ import annotations

import csv
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "extract.csv"


def read_extract(path: Path = DATA_PATH) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_dimension(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for row in rows:
        if not row["region"]:
            continue
        key = row["customer_id"].strip()
        if not key:
            continue
        if key not in seen:
            seen[key] = {
                "customer_id": key,
                "customer_name": row["customer_name"],
                "region": row["region"],
            }
    return list(seen.values())


def build_fact(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "order_id": row["order_id"],
            "customer_id": row["customer_id"],
            "amount": row["amount"],
        }
        for row in rows
    ]
