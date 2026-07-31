"""Pull typed fields out of semicolon-delimited text lines."""
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
    """True when every field satisfies the closed schema's type."""
    if not isinstance(record["name"], str) or not record["name"]:
        return False
    if record["active"] not in (True, False, "true", "false"):
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
