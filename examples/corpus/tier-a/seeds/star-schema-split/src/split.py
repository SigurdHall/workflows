"""Split a flat sales extract into fact and dimension tables."""
from __future__ import annotations

import csv
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "extract.csv"


def read_extract(path: Path = DATA_PATH) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_dimension(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """One row per distinct customer that has a region on file."""
    seen: dict[str, dict[str, str]] = {}
    for row in rows:
        if not row["region"]:
            continue  # no region yet, not ready for the dimension
        key = row["customer_id"]
        if key not in seen:
            seen[key] = {
                "customer_id": key,
                "customer_name": row["customer_name"],
                "region": row["region"],
            }
    return list(seen.values())


def build_fact(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """One row per order, carrying the customer key forward unchanged."""
    return [
        {
            "order_id": row["order_id"],
            "customer_id": row["customer_id"],
            "amount": row["amount"],
        }
        for row in rows
    ]
