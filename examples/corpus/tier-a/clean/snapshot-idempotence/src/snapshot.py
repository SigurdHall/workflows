"""snapshot-idempotence with neither defect planted.

The digest is canonical over the set of rows, and a snapshot as of an earlier
date never replaces a newer one.
"""
from __future__ import annotations

import hashlib
import json


def digest(rows: list[dict[str, object]]) -> str:
    """A content digest that does not depend on the order rows arrived in."""
    canonical = sorted(json.dumps(row, sort_keys=True) for row in rows)
    return hashlib.sha256(json.dumps(canonical).encode("utf-8")).hexdigest()


def apply_snapshot(
    store: dict[str, dict[str, object]],
    entity: str,
    as_of: str,
    rows: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Record a snapshot, keeping the newest as_of the store has seen."""
    existing = store.get(entity)
    if existing is not None and str(existing.get("as_of", "")) >= as_of:
        return store
    store[entity] = {"as_of": as_of, "rows": rows, "digest": digest(rows)}
    return store
