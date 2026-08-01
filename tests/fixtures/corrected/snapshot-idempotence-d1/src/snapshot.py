"""snapshot-idempotence with class 8 corrected and class 2 left planted.

A snapshot as of an earlier date no longer replaces a newer one. The digest is
still order-dependent, so that probe must still report its defect present.
"""
from __future__ import annotations

import hashlib
import json


def digest(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()


def apply_snapshot(
    store: dict[str, dict[str, object]],
    entity: str,
    as_of: str,
    rows: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    existing = store.get(entity)
    if existing is not None and str(existing.get("as_of", "")) >= as_of:
        return store
    store[entity] = {"as_of": as_of, "rows": rows, "digest": digest(rows)}
    return store
