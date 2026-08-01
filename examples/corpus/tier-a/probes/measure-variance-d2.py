"""Class 14, blank/zero conflation: a missing budget read as a budget of zero.

Present when a blank budget column becomes the float 0.0 in the parsed row.
Any other treatment — None, an omitted row, a raised error — means the blank
is no longer being silently folded in as a real zero.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load  # noqa: E402

CSV = "department,budget,actual\nretail,1000,1200\nsupport,,150\n"


def defect_is_present() -> bool:
    variance = load("variance")
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "budget_actuals.csv"
        path.write_text(CSV, encoding="utf-8")
        rows = variance.read_rows(path)
    blank = [row for row in rows if row.get("department") == "support"]
    if not blank:
        return False
    budget = blank[0].get("budget")
    return isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget == 0


answer(defect_is_present)
