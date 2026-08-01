"""Class 8, stale state: a late-arriving older snapshot overwrites a newer one.

Present when applying a snapshot as of an earlier date replaces one already
stored for a later date. Arrival order is not chronological order, and a store
that assumes it is loses the newer state silently.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import answer, load  # noqa: E402


def defect_is_present() -> bool:
    snapshot = load("snapshot")
    store: dict = {}
    snapshot.apply_snapshot(store, "acme", "2026-07-02", [{"id": 1, "value": "new"}])
    try:
        snapshot.apply_snapshot(store, "acme", "2026-07-01", [{"id": 1, "value": "old"}])
    except Exception:
        # Refusing the out-of-order write is one legitimate fix.
        return False
    return store.get("acme", {}).get("as_of") != "2026-07-02"


answer(defect_is_present)
