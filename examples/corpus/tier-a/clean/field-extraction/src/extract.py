"""field-extraction with neither defect planted.

Booleans are real booleans, and a body carrying no parseable record is refused
rather than returned as a valid empty result.
"""
from __future__ import annotations

SCHEMA = {"name": str, "active": bool, "age": int}
_BOOLEANS = {"true": True, "false": False}


def parse_record(line: str) -> dict[str, object]:
    pairs = (pair.strip().split("=", 1) for pair in line.split(";") if "=" in pair)
    fields = {key.strip(): value.strip() for key, value in pairs}
    spelling = fields.get("active", "").strip().lower()
    return {
        "name": fields.get("name", "").strip(),
        "active": _BOOLEANS.get(spelling, spelling),
        "age": int(fields.get("age", "0").strip()),
    }


def validate_record(record: dict[str, object]) -> bool:
    """True when every field satisfies the closed schema's type."""
    if not isinstance(record["name"], str) or not record["name"]:
        return False
    if not isinstance(record["active"], bool):
        return False
    if not isinstance(record["age"], int) or isinstance(record["age"], bool):
        return False
    return True


def parse_records(text: str) -> list[dict[str, object]]:
    candidates = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not candidates:
        raise ValueError("the body carries no records; an empty result would hide that")
    return [
        record
        for record in (parse_record(line) for line in candidates)
        if validate_record(record)
    ]
