"""measure-variance with class 14 corrected and class 11 left planted.

A blank budget is now None rather than 0.0. The portfolio percentage is still
a mean of per-department ratios, so that probe must still report its defect
present.
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


def portfolio_percent_variance(rows: list[dict[str, float | str | None]]) -> float:
    """Mean percent variance across departments with a known budget."""
    values = [
        value
        for value in (percent_variance(row["budget"], row["actual"]) for row in rows)
        if value is not None
    ]
    return sum(values) / len(values)
