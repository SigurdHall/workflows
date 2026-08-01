"""triage-router with neither defect planted.

A custom rule cannot invent a category outside the closed set, and the
'charge' keyword does not fire on the battery sense of the word.
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

# Phrasings where 'charge' is a battery, not money.
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
    """Add a one-off routing rule ahead of the defaults, inside the contract."""
    if category not in CATEGORIES:
        raise ValueError(
            f"{category!r} is not one of the routing categories: {', '.join(CATEGORIES)}"
        )
    return [(keyword, category)] + RULES
