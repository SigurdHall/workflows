"""Class 4, open contract: a custom rule may invent a category.

Present when `with_custom_rule` accepts a category outside CATEGORIES and the
router then returns it. The closed set is the contract; a helper that widens
it silently makes every downstream consumer's exhaustive match wrong.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load  # noqa: E402


def defect_is_present() -> bool:
    router = load("router")
    try:
        rules = router.with_custom_rule("urgent", "escalation")
        verdict = router.classify("this is urgent", rules)
    except Exception:
        # Rejecting the out-of-contract category is the expected fix.
        return False
    return verdict not in router.CATEGORIES and verdict != "uncategorized"


answer(defect_is_present)
