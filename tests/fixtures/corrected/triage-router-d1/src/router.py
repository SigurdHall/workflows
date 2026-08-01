"""triage-router with class 4 corrected and class 17 left planted.

A custom rule can no longer invent a category outside the closed set. The
'charge' keyword still fires on any sense of the word, so that probe must
still report its defect present.
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


def classify(text: str, rules: list[tuple[str, str]] = RULES) -> str:
    lowered = text.lower()
    for keyword, category in rules:
        if keyword in lowered:
            return category
    return "uncategorized"


def classify_batch(items: list[str], rules: list[tuple[str, str]] = RULES) -> list[str]:
    return [classify(item, rules) for item in items]


def with_custom_rule(keyword: str, category: str) -> list[tuple[str, str]]:
    if category not in CATEGORIES:
        raise ValueError(
            f"{category!r} is not one of the routing categories: {', '.join(CATEGORIES)}"
        )
    return [(keyword, category)] + RULES
