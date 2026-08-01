"""snapshot-idempotence with class 2 corrected and class 8 left planted.

The digest is canonical: same rows in any order, same value. Arrival order
still overwrites a newer snapshot, so that probe must still report its defect
present.
"""
from __future__ import annotations

import hashlib
import json


def digest(rows: list[dict[str, object]]) -> str:
    canonical = sorted(json.dumps(row, sort_keys=True) for row in rows)
    return hashlib.sha256(json.dumps(canonical).encode("utf-8")).hexdigest()


def apply_snapshot(
    store: dict[str, dict[str, object]],
    entity: str,
    as_of: str,
    rows: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    store[entity] = {"as_of": as_of, "rows": rows, "digest": digest(rows)}
    return store
