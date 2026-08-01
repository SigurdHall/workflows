"""Class 11, aggregation misuse: a mean of ratios where a ratio of sums belongs.

Present when `portfolio_percent_variance` averages each department's own
percentage. Two departments with very different budgets make the two methods
disagree by a wide margin, so no rounding tolerance has to be guessed at.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load  # noqa: E402

ROWS = [
    {"department": "large", "budget": 1000.0, "actual": 1200.0},
    {"department": "small", "budget": 100.0, "actual": 50.0},
]
MEAN_OF_RATIOS = (20.0 + -50.0) / 2  # -15.0
RATIO_OF_SUMS = (1250.0 - 1100.0) / 1100.0 * 100.0  # 13.63...


def defect_is_present() -> bool:
    variance = load("variance")
    value = variance.portfolio_percent_variance([dict(row) for row in ROWS])
    if value is None:
        # Refusing to answer is not the planted defect; it is a different one.
        return False
    return abs(float(value) - MEAN_OF_RATIOS) < abs(float(value) - RATIO_OF_SUMS)


answer(defect_is_present)
