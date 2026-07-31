"""Route triage items to one of a closed set of categories."""
from __future__ import annotations

CATEGORIES = ("billing", "bug", "feature-request")

# (keyword, category) - first match wins.
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
    """Add a one-off routing rule ahead of the defaults."""
    return [(keyword, category)] + RULES
