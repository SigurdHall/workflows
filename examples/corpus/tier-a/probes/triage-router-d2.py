"""Class 17, trigger mismatch: a keyword fires on an unrelated sense of the word.

Present when a device complaint about holding a charge routes to billing.
The rule matches the substring, not the meaning, and the fixture phrase is the
one where those come apart.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load  # noqa: E402

PHRASE = "My phone won't hold a charge since the last update"


def defect_is_present() -> bool:
    router = load("router")
    return router.classify(PHRASE) == "billing"


answer(defect_is_present)
