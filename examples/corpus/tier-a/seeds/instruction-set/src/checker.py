"""Structural checks for the refund-handling instruction file."""
from __future__ import annotations

import re
from pathlib import Path

INSTRUCTIONS_PATH = Path(__file__).resolve().parent / "instructions.md"
RULE_PATTERN = re.compile(r"^\d+\.\s+(.+)$", re.MULTILINE)


def load_rules(path: Path = INSTRUCTIONS_PATH) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [match.group(1).strip() for match in RULE_PATTERN.finditer(text)]


def has_minimum_rule_count(rules: list[str], minimum: int = 3) -> bool:
    return len(rules) >= minimum


def mentions_order_number(rules: list[str]) -> bool:
    return any("order number" in rule.lower() for rule in rules)


def every_rule_is_nonempty(rules: list[str]) -> bool:
    return all(rule.strip() for rule in rules)
