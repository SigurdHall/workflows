"""Shared test helpers: the annotated-fixture harness.

A fixture file is self-describing, so one generic test can assert that every
fixture in the repository validates — or fails for exactly the annotated
reason. "Exactly" is set equality over ``(path, keyword)`` pairs: a fixture
that starts failing for an additional reason is a regression signal, not a
detail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from workflows import schema as schema_mod
from workflows import semantics

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
CONTRACTS_DIR = REPO_ROOT / "contracts"

FIXTURE_VERSION = "workflows.fixture.v1"
_REQUIRED_KEYS = {"fixture_version", "schema", "expect", "reason", "data"}
_ALLOWED_KEYS = _REQUIRED_KEYS | {"expected_errors"}


@dataclass(frozen=True)
class Fixture:
    path: Path
    schema_ref: str
    expect: str
    reason: str
    expected_errors: tuple[tuple[str, str], ...]
    data: Any

    @property
    def name(self) -> str:
        return str(self.path.relative_to(FIXTURE_ROOT)).replace("\\", "/")


def load_fixture(path: Path) -> Fixture:
    return load_fixture_mapping(json.loads(path.read_text(encoding="utf-8")), path)


def load_fixture_mapping(raw: Any, path: Path = Path("<memory>")) -> Fixture:
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: fixture must be a JSON object")
    missing = _REQUIRED_KEYS - set(raw)
    if missing:
        raise ValueError(f"{path}: fixture missing key(s) {sorted(missing)}")
    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise ValueError(f"{path}: unknown fixture key(s) {sorted(unknown)}")
    if raw["fixture_version"] != FIXTURE_VERSION:
        raise ValueError(f"{path}: unsupported fixture_version {raw['fixture_version']!r}")
    if raw["expect"] not in ("valid", "invalid"):
        raise ValueError(f"{path}: expect must be 'valid' or 'invalid'")
    if not str(raw["reason"]).strip():
        raise ValueError(f"{path}: reason must be a non-empty explanation")

    annotated = raw.get("expected_errors", [])
    if raw["expect"] == "valid":
        if annotated:
            raise ValueError(f"{path}: a valid fixture cannot annotate expected errors")
    elif not annotated:
        raise ValueError(f"{path}: an invalid fixture must annotate its expected errors")

    errors: list[tuple[str, str]] = []
    for entry in annotated:
        if set(entry) != {"path", "keyword"}:
            raise ValueError(f"{path}: expected_errors entries need exactly path and keyword")
        errors.append((entry["path"], entry["keyword"]))

    return Fixture(
        path=path,
        schema_ref=raw["schema"],
        expect=raw["expect"],
        reason=raw["reason"],
        expected_errors=tuple(errors),
        data=raw["data"],
    )


def iter_fixtures(root: Path = FIXTURE_ROOT) -> Iterator[Fixture]:
    for path in sorted(root.rglob("*.json")):
        yield load_fixture(path)


def registry() -> schema_mod.SchemaRegistry:
    return schema_mod.SchemaRegistry.from_directory(CONTRACTS_DIR)


def actual_errors(fixture: Fixture) -> list[tuple[str, str]]:
    """Schema violations, or — when the schema is clean — semantic ones.

    Fixtures annotate both the same way; semantic keywords carry a
    ``semantic:`` prefix.
    """
    errors = semantics.check_document(
        fixture.data, fixture.schema_ref, registry=registry()
    )
    return sorted((error.path, error.keyword) for error in errors)
