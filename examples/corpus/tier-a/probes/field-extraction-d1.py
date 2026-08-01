"""Class 1, type conflation: a boolean field left as its string spelling.

Present when `active` comes back as text rather than a bool. The schema
declares bool; validation that accepts the spellings "true" and "false"
alongside real booleans hides the fact that nothing ever converted them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load  # noqa: E402

LINE = "name=Ada; active=true; age=36"


def defect_is_present() -> bool:
    extract = load("extract")
    record = extract.parse_record(LINE)
    return not isinstance(record.get("active"), bool)


answer(defect_is_present)
