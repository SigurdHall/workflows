"""field-extraction with class 1 corrected and class 7 left planted.

'active' is now a real bool. A body with no records still comes back as a
plain empty list, so that probe must still report its defect present.
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
    if not isinstance(record["name"], str) or not record["name"]:
        return False
    if not isinstance(record["active"], bool):
        return False
    if not isinstance(record["age"], int):
        return False
    return True


def parse_records(text: str) -> list[dict[str, object]]:
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        record = parse_record(line)
        if validate_record(record):
            records.append(record)
    return records
