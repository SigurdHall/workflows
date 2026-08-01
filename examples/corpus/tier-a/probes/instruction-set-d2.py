"""Class 18, instruction conflict: two rules that cannot both hold.

Present when the file both exempts small refunds from manager sign-off and
requires sign-off for all refunds, with no reconciling language. This is a
**heuristic**, not a decision: it recognises this particular contradiction by
its shape, and would not notice a differently worded one. The manifest records
the caveat beside the defect.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load, task_directory  # noqa: E402

RECONCILERS = ("except", "unless", "other than", "subject to", "notwithstanding", "aside from")


def exempts_small_refunds(rule: str) -> bool:
    lowered = rule.lower()
    return "sign-off" in lowered and (
        "without manager sign-off" in lowered or "no manager sign-off" in lowered
    )


def requires_all_refunds(rule: str) -> bool:
    lowered = rule.lower()
    return "sign-off" in lowered and ("all refunds" in lowered or "every refund" in lowered)


def defect_is_present() -> bool:
    checker = load("checker")
    rules = checker.load_rules(task_directory() / "src" / "instructions.md")
    exempting = [rule for rule in rules if exempts_small_refunds(rule)]
    requiring = [rule for rule in rules if requires_all_refunds(rule)]
    if not exempting or not requiring:
        return False
    return not any(
        marker in rule.lower()
        for rule in exempting + requiring
        for marker in RECONCILERS
    )


answer(defect_is_present)
