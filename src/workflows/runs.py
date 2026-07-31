"""The run directory: audit trail, resume point, telemetry source.

Everything a run produces lands here as it happens, so a run killed at any
point can be resumed from its manifest without repeating completed steps.

Two write disciplines, deliberately different:

* Artifacts (envelopes, prompts, gate results, telemetry) are **append-only**.
  Writing the same path twice with identical content is a no-op, which is
  what makes step re-entry safe; writing it with *different* content is an
  error, because a run that rewrites its own record is not an audit trail.
* The manifest is the single mutable index. It is rewritten atomically —
  written to a temporary file and replaced — so a kill mid-write cannot
  leave a run unresumable.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
TELEMETRY_NAME = "telemetry.jsonl"
MANIFEST_SCHEMA = "run-manifest.schema.json"


class RunError(RuntimeError):
    """The run directory is in a state the caller may not silently repair."""


def utc_now() -> str:
    """RFC 3339 UTC, second precision — the timestamp shape the schemas take."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dumps(document: Any) -> str:
    return json.dumps(document, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


REPLACE_ATTEMPTS = 10
REPLACE_BACKOFF_SECONDS = 0.05


def _replace_with_retry(temporary: Path, target: Path) -> None:
    """Atomic rename, retried against transient file locks.

    On Windows an indexer, a virus scanner or an open editor can hold a
    handle on the target for a few milliseconds and turn the rename into
    ``PermissionError``. Losing a run's manifest to that would make the run
    unresumable, so the rename retries briefly and then gives up loudly.
    """
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_BACKOFF_SECONDS * (attempt + 1))


class RunDirectory:
    """One run's directory on disk."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        # Fan-out runs several workers at once against one run directory. The
        # manifest is read-modify-write, so it is the one thing that must not
        # be touched concurrently.
        self._lock = threading.RLock()

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def telemetry_path(self) -> Path:
        return self.root / TELEMETRY_NAME

    @property
    def envelopes(self) -> Path:
        return self.root / "envelopes"

    @property
    def prompts(self) -> Path:
        return self.root / "prompts"

    @property
    def gates(self) -> Path:
        return self.root / "gates"

    def create(self, manifest: dict[str, Any]) -> RunDirectory:
        """Create the directory layout and write the initial manifest."""
        for directory in (self.root, self.envelopes, self.prompts, self.gates):
            directory.mkdir(parents=True, exist_ok=True)
        if self.manifest_path.exists():
            raise RunError(f"run already exists: {self.root}")
        self.write_manifest(manifest)
        return self

    @property
    def exists(self) -> bool:
        return self.manifest_path.is_file()

    # -- artifacts (append-only) -------------------------------------------

    def write_artifact(self, relative: str | Path, document: Any) -> Path:
        path = self.root / relative
        payload = _dumps(document)
        with self._lock:
            if path.exists():
                existing = path.read_text(encoding="utf-8")
                if existing == payload:
                    return path  # idempotent re-entry
                raise RunError(
                    f"refusing to rewrite an existing run artifact: {path}. "
                    "Run artifacts are append-only; a changed step writes a new "
                    "attempt, it does not overwrite the record of the old one."
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
        return path

    def read_artifact(self, relative: str | Path) -> Any:
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def append_telemetry(self, record: dict[str, Any]) -> None:
        with self._lock:
            self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
            with self.telemetry_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def telemetry(self) -> list[dict[str, Any]]:
        if not self.telemetry_path.is_file():
            return []
        lines = self.telemetry_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    # -- manifest (the single mutable index) -------------------------------

    def read_manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.manifest_path.with_suffix(".json.tmp")
            temporary.write_text(_dumps(manifest), encoding="utf-8")
            _replace_with_retry(temporary, self.manifest_path)

    def step(self, step_id: str) -> dict[str, Any] | None:
        for record in self.read_manifest().get("steps", []):
            if record.get("step_id") == step_id:
                return record
        return None

    def is_completed(self, step_id: str) -> bool:
        """What resume asks before doing anything: has this step already run?"""
        record = self.step(step_id)
        return record is not None and record.get("state") == "COMPLETED"

    def record_step(self, step: dict[str, Any], *, now: str | None = None) -> None:
        """Insert or replace one step record and stamp the manifest."""
        with self._lock:
            manifest = self.read_manifest()
            steps = manifest.setdefault("steps", [])
            for index, existing in enumerate(steps):
                if existing.get("step_id") == step.get("step_id"):
                    steps[index] = {**existing, **step}
                    break
            else:
                steps.append(step)
            manifest["updated_at"] = now or utc_now()
            self.write_manifest(manifest)
