"""star-schema-split with class 10 corrected and class 6 left planted.

Every customer the fact refers to now reaches the dimension, with an explicit
placeholder where the region is unknown. Blank keys are still accepted, so the
blank-identity probe must still report its defect present.
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
        key = row["customer_id"]
        if key not in seen:
            seen[key] = {
                "customer_id": key,
                "customer_name": row["customer_name"],
                "region": row["region"] or "unknown",
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
