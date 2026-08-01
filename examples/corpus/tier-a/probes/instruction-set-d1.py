"""Class 20, unverifiable imperative: a rule with no observable pass/fail signal.

Present when the rule list still holds a subjective quality demand carrying no
criterion anyone could check. This is a **heuristic**, not a decision: prose
has no executable oracle. It looks for a quality word with no co-located
observable — a number, a duration, a required element, or a checker function
that evaluates it — and the manifest records the caveat beside the defect.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load, task_directory  # noqa: E402

QUALITY_WORDS = (
    "empathetic", "empathy", "appropriately", "appropriate tone",
    "professional", "reasonable", "as needed", "where appropriate",
    "friendly", "polite",
)
OBSERVABLE_MARKERS = (
    "must include", "must contain", "at least", "no more than", "within",
    "list of", "template", "checklist", "verbatim", "exactly",
)


def rule_is_unverifiable(rule: str) -> bool:
    lowered = rule.lower()
    if not any(word in lowered for word in QUALITY_WORDS):
        return False
    if any(marker in lowered for marker in OBSERVABLE_MARKERS):
        return False
    return not any(character.isdigit() for character in lowered)


def defect_is_present() -> bool:
    checker = load("checker")
    rules = checker.load_rules(task_directory() / "src" / "instructions.md")
    unverifiable = [rule for rule in rules if rule_is_unverifiable(rule)]
    if not unverifiable:
        return False
    # A checker function that names the quality would make it observable.
    names = " ".join(dir(checker)).lower()
    return not any(
        word.split()[0] in names for rule in unverifiable
        for word in QUALITY_WORDS if word in rule.lower()
    )


answer(defect_is_present)
