"""measure-variance with class 11 corrected and class 14 left planted.

The portfolio percentage is now a ratio of sums. A blank budget is still read
as 0.0, so that probe must still report its defect present.
"""
from __future__ import annotations

import csv
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "budget_actuals.csv"


def read_rows(path: Path = DATA_PATH) -> list[dict[str, float | str]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            budget_text = record["budget"].strip()
            rows.append(
                {
                    "department": record["department"],
                    "budget": float(budget_text) if budget_text else 0.0,
                    "actual": float(record["actual"]),
                }
            )
    return rows


def variance(budget: float, actual: float) -> float:
    return actual - budget


def percent_variance(budget: float, actual: float) -> float | None:
    if budget == 0:
        return None
    return (actual - budget) / budget * 100.0


def portfolio_percent_variance(rows: list[dict[str, float | str]]) -> float | None:
    """Recomputed from summed totals, not averaged from per-row percentages."""
    usable = [row for row in rows if row["budget"]]
    return percent_variance(
        sum(row["budget"] for row in usable), sum(row["actual"] for row in usable)
    )
