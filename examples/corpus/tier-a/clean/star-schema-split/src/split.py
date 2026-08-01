"""star-schema-split with neither defect planted.

A blank customer key is normalised to an explicit member rather than accepted
as its own identity or dropped, and every customer the fact refers to reaches
the dimension. The fact still carries one row per order, which is what the
task's own tests require.
"""
from __future__ import annotations

import csv
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "extract.csv"
UNKNOWN_CUSTOMER = "unknown"
UNKNOWN_REGION = "unknown"


def read_extract(path: Path = DATA_PATH) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def customer_key(row: dict[str, str]) -> str:
    """One place decides identity, so the fact and the dimension agree."""
    return row["customer_id"].strip() or UNKNOWN_CUSTOMER


def build_dimension(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """One row per distinct customer the fact can refer to."""
    seen: dict[str, dict[str, str]] = {}
    for row in rows:
        key = customer_key(row)
        if key not in seen:
            seen[key] = {
                "customer_id": key,
                "customer_name": row["customer_name"],
                "region": row["region"] or UNKNOWN_REGION,
            }
    return list(seen.values())


def build_fact(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """One row per order, keyed the same way the dimension is."""
    return [
        {
            "order_id": row["order_id"],
            "customer_id": customer_key(row),
            "amount": row["amount"],
        }
        for row in rows
    ]
