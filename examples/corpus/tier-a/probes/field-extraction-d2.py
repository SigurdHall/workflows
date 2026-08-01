"""Class 7, degenerate input: a body with no records accepted as a valid empty result.

Present when `parse_records` returns a plain empty list for input that
contains no key=value pairs at all. An empty result and an unparseable body
are different facts, and returning `[]` for both makes the caller unable to
tell them apart.

Caveat: an implementation that still returns `[]` here and reports emptiness
by some other channel would probe PRESENT. The manifest records this beside
the defect; the scorer treats the verdict as the probe's, not as truth.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load  # noqa: E402

TEXT = "# only a comment header\n\n"


def defect_is_present() -> bool:
    extract = load("extract")
    try:
        result = extract.parse_records(TEXT)
    except Exception:
        # Refusing the degenerate body outright is one legitimate fix.
        return False
    return isinstance(result, list) and result == []


answer(defect_is_present)
