"""measure-variance with neither defect planted.

The defect-free base an `assure` cell diffs against: the candidate it reviews
is the seed, so the diff a reviewer sees is the one that *introduces* classes
11 and 14. Kept minimal on purpose — a base that also differs in style would
make the review about style.
"""
from __future__ import annotations

import csv
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "budget_actuals.csv"


def read_rows(path: Path = DATA_PATH) -> list[dict[str, float | str | None]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            budget_text = record["budget"].strip()
            rows.append(
                {
                    "department": record["department"],
                    "budget": float(budget_text) if budget_text else None,
                    "actual": float(record["actual"]),
                }
            )
    return rows


def variance(budget: float, actual: float) -> float:
    return actual - budget


def percent_variance(budget: float | None, actual: float) -> float | None:
    if budget is None or budget == 0:
        return None
    return (actual - budget) / budget * 100.0


def portfolio_percent_variance(
    rows: list[dict[str, float | str | None]]
) -> float | None:
    """Recomputed from summed totals across departments with a known budget."""
    usable = [row for row in rows if row["budget"] is not None and row["budget"] != 0]
    if not usable:
        return None
    return percent_variance(
        sum(row["budget"] for row in usable), sum(row["actual"] for row in usable)
    )
