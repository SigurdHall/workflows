"""field-extraction with class 7 corrected and class 1 left planted.

A body carrying no parseable record is refused rather than returned as a valid
empty result. 'active' is still its string spelling, so that probe must still
report its defect present.
"""
from __future__ import annotations

SCHEMA = {"name": str, "active": bool, "age": int}


def parse_record(line: str) -> dict[str, object]:
    pairs = (pair.strip().split("=", 1) for pair in line.split(";") if "=" in pair)
    fields = {key.strip(): value.strip() for key, value in pairs}
    return {
        "name": fields.get("name", "").strip(),
        "active": fields.get("active", "").strip(),
        "age": int(fields.get("age", "0").strip()),
    }


def validate_record(record: dict[str, object]) -> bool:
    if not isinstance(record["name"], str) or not record["name"]:
        return False
    if record["active"] not in (True, False, "true", "false"):
        return False
    if not isinstance(record["age"], int):
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
