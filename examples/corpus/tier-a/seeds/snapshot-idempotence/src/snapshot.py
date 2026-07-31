"""Append daily snapshots to a per-entity snapshot store."""
from __future__ import annotations

import hashlib
import json


def digest(rows: list[dict[str, object]]) -> str:
    """A content digest for one snapshot's rows."""
    return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()


def apply_snapshot(
    store: dict[str, dict[str, object]],
    entity: str,
    as_of: str,
    rows: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Record a snapshot for ``entity``, keyed by the date it is as of."""
    store[entity] = {
        "as_of": as_of,
        "rows": rows,
        "digest": digest(rows),
    }
    return store
