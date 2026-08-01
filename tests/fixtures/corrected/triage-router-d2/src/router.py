"""triage-router with class 17 corrected and class 4 left planted.

'charge' no longer fires on the device sense of the word. A custom rule can
still invent a category outside the closed set, so that probe must still
report its defect present.
"""
from __future__ import annotations

CATEGORIES = ("billing", "bug", "feature-request")

RULES = [
    ("charge", "billing"),
    ("refund", "billing"),
    ("crash", "bug"),
    ("error", "bug"),
    ("add support for", "feature-request"),
]

# Phrasings where 'charge' means a battery, not money.
DEVICE_SENSE = ("hold a charge", "holding a charge", "won't charge", "will not charge")


def classify(text: str, rules: list[tuple[str, str]] = RULES) -> str:
    lowered = text.lower()
    device_context = any(phrase in lowered for phrase in DEVICE_SENSE)
    for keyword, category in rules:
        if device_context and keyword == "charge":
            continue
        if keyword in lowered:
            return category
    return "uncategorized"


def classify_batch(items: list[str], rules: list[tuple[str, str]] = RULES) -> list[str]:
    return [classify(item, rules) for item in items]


def with_custom_rule(keyword: str, category: str) -> list[tuple[str, str]]:
    return [(keyword, category)] + RULES
