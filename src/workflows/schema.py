"""Minimal JSON Schema validator for the subset this repository uses.

The rationale, the exact supported subset, and the escape hatch are recorded
in ``docs/decisions/0008-minimal-internal-schema-validator.md``. Two rules
drive the implementation:

* Unsupported schema keywords raise :class:`SchemaError` instead of being
  ignored. A validator that silently skips a constraint is documentation,
  not a gate.
* Instance comparison is JSON-typed: ``true`` never equals ``1`` and never
  equals ``"true"``. Numeric values compare by value, so ``0`` equals
  ``0.0`` (JSON Schema semantics).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

MAX_DEPTH = 64
"""Guard against cyclic ``$ref`` graphs; this repository has none."""

ANNOTATION_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "$defs",
        "title",
        "description",
        "examples",
        "default",
        "deprecated",
    }
)
"""Keywords carried for humans and tooling; they constrain nothing."""

SUPPORTED_KEYWORDS = frozenset(
    {
        "$ref",
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "additionalProperties",
        "pattern",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
)
"""Every keyword this validator enforces. Anything else is an error."""

TYPE_NAMES = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)


class SchemaError(Exception):
    """The schema is malformed or uses a keyword outside the supported subset."""


@dataclass(frozen=True)
class ValidationError:
    """One instance violation, located by JSON Pointer."""

    path: str
    keyword: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '/'}: {self.keyword}: {self.message}"


class SchemaRegistry:
    """Schema documents addressable by file name and by ``$id``."""

    def __init__(self) -> None:
        self._schemas: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_directory(cls, directory: Path | str) -> SchemaRegistry:
        registry = cls()
        for path in sorted(Path(directory).glob("*.schema.json")):
            registry.add(json.loads(path.read_text(encoding="utf-8")), key=path.name)
        return registry

    def add(self, schema: dict[str, Any], key: str | None = None) -> None:
        if not isinstance(schema, dict):
            raise SchemaError("a schema document must be an object")
        keys = {k for k in (key, schema.get("$id")) if isinstance(k, str) and k}
        if not keys:
            raise SchemaError("a schema document needs an $id or an explicit key")
        check_schema(schema, origin=sorted(keys)[0])
        for name in keys:
            existing = self._schemas.get(name)
            if existing is not None and existing is not schema:
                raise SchemaError(f"duplicate schema key: {name}")
            self._schemas[name] = schema

    def get(self, key: str) -> dict[str, Any]:
        try:
            return self._schemas[key]
        except KeyError:
            known = ", ".join(self.keys()) or "<empty>"
            raise SchemaError(f"unknown schema {key!r}; known: {known}") from None

    def keys(self) -> list[str]:
        return sorted(self._schemas)


def contracts_dir() -> Path:
    """Directory holding this repository's schema documents.

    ``WORKFLOWS_CONTRACTS_DIR`` overrides it so consuming repositories can
    point the validator at their own copy.
    """
    override = os.environ.get("WORKFLOWS_CONTRACTS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "contracts"


@lru_cache(maxsize=None)
def _document_sources(directory: str) -> tuple[tuple[str, str], ...]:
    """Cache the raw text of each schema document, not the parsed objects."""
    return tuple(
        (path.name, path.read_text(encoding="utf-8"))
        for path in sorted(Path(directory).glob("*.schema.json"))
    )


def default_registry() -> SchemaRegistry:
    """A fresh registry over :func:`contracts_dir`.

    Only the file text is cached. Every call parses its own schema objects,
    so a caller that mutates a resolved schema cannot corrupt validation for
    the rest of the process. Callers in hot paths build one registry and pass
    it explicitly.
    """
    registry = SchemaRegistry()
    for name, text in _document_sources(str(contracts_dir())):
        registry.add(json.loads(text), key=name)
    return registry


def resolve_schema(
    ref: str, registry: SchemaRegistry | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve ``file.schema.json#/$defs/name`` to ``(schema, document)``.

    The document is returned so that same-document ``#/...`` references
    inside the resolved sub-schema keep resolving correctly.
    """
    registry = registry if registry is not None else default_registry()
    base, _, _fragment = ref.partition("#")
    if not base:
        raise SchemaError(f"schema reference needs a document: {ref!r}")
    document = registry.get(base)
    return _resolve_ref(ref, document, registry)


def _resolve_ref(
    ref: Any, document: dict[str, Any], registry: SchemaRegistry | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(ref, str) or not ref:
        raise SchemaError(f"$ref must be a non-empty string, got {ref!r}")
    base, _, fragment = ref.partition("#")
    if base:
        if registry is None:
            raise SchemaError(f"no registry available to resolve external $ref {ref!r}")
        document = registry.get(base)
    target: Any = document
    if fragment:
        if not fragment.startswith("/"):
            raise SchemaError(f"only JSON Pointer fragments are supported: {ref!r}")
        for raw in fragment.split("/")[1:]:
            token = raw.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or token not in target:
                raise SchemaError(f"unresolvable $ref: {ref!r}")
            target = target[token]
    if not isinstance(target, dict):
        raise SchemaError(f"$ref does not point at a schema object: {ref!r}")
    return target, document


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _type_matches(value: Any, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "null":
        return value is None
    raise SchemaError(f"unsupported type name: {name!r}")


def json_equal(left: Any, right: Any) -> bool:
    """JSON equality: type-strict for booleans, value-based for numbers."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            json_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            json_equal(left[k], right[k]) for k in left
        )
    return False


def _pointer(path: str, token: str | int) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def _compiled(pattern: Any, where: str = "<inline>") -> re.Pattern[str]:
    if not isinstance(pattern, str):
        raise SchemaError(f"pattern must be a string at {where}, got {pattern!r}")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise SchemaError(f"invalid pattern {pattern!r} at {where}: {exc}") from exc


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check_schema(
    schema: Any, *, origin: str = "<inline>", path: str = "", _depth: int = 0
) -> None:
    """Verify that a schema is well formed, independently of any instance.

    Every supported keyword's *value* is checked here, recursively, including
    branches no instance ever reaches. Without this, keyword shapes would only
    be checked when an instance happened to have the matching JSON type — so a
    schema with an empty ``enum`` or a non-boolean ``uniqueItems`` could sit in
    ``contracts/`` for months and quietly enforce nothing.

    Raises :class:`SchemaError`; returns None when the schema is sound.
    """
    where = f"{origin}{path or ''}" if path else origin
    if _depth > MAX_DEPTH:
        raise SchemaError(f"maximum schema nesting exceeded at {where}")
    if not isinstance(schema, dict):
        raise SchemaError(f"schema at {where} must be an object, got {_type_name(schema)}")

    unknown = set(schema) - SUPPORTED_KEYWORDS - ANNOTATION_KEYWORDS
    if unknown:
        raise SchemaError(f"unsupported schema keyword(s) at {where}: {sorted(unknown)}")

    if "$ref" in schema and not (
        isinstance(schema["$ref"], str) and schema["$ref"]
    ):
        raise SchemaError(f"$ref must be a non-empty string at {where}")

    if "type" in schema:
        declared = schema["type"]
        names = [declared] if isinstance(declared, str) else declared
        if not isinstance(names, list) or not names:
            raise SchemaError(f"type must be a string or a non-empty list at {where}")
        for name in names:
            if not isinstance(name, str) or name not in TYPE_NAMES:
                raise SchemaError(f"unsupported type {name!r} at {where}")

    if "enum" in schema:
        if not isinstance(schema["enum"], list) or not schema["enum"]:
            raise SchemaError(f"enum must be a non-empty list at {where}")

    if "required" in schema:
        required = schema["required"]
        if not isinstance(required, list) or not all(
            isinstance(name, str) for name in required
        ):
            raise SchemaError(f"required must be a list of strings at {where}")
        if len(set(required)) != len(required):
            raise SchemaError(f"required contains duplicates at {where}")

    if "properties" in schema and not isinstance(schema["properties"], dict):
        raise SchemaError(f"properties must be an object at {where}")

    if "additionalProperties" in schema and not isinstance(
        schema["additionalProperties"], (bool, dict)
    ):
        raise SchemaError(
            f"additionalProperties must be a boolean or a schema at {where}"
        )

    if "pattern" in schema:
        _compiled(schema["pattern"], where)

    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise SchemaError(f"uniqueItems must be a boolean at {where}")

    if "items" in schema and not isinstance(schema["items"], dict):
        raise SchemaError(f"items must be a schema at {where}")

    for keyword in ("minLength", "maxLength", "minItems", "maxItems"):
        if keyword in schema and not _is_count(schema[keyword]):
            raise SchemaError(
                f"{keyword} must be a non-negative integer at {where}"
            )
    for keyword in ("minimum", "maximum"):
        if keyword in schema and not _is_number(schema[keyword]):
            raise SchemaError(f"{keyword} must be a number at {where}")

    for low, high in (
        ("minLength", "maxLength"),
        ("minItems", "maxItems"),
        ("minimum", "maximum"),
    ):
        if low in schema and high in schema and schema[low] > schema[high]:
            raise SchemaError(
                f"{low} exceeds {high} at {where}: the schema is unsatisfiable"
            )

    for name, child in (schema.get("$defs") or {}).items():
        check_schema(child, origin=origin, path=f"{path}/$defs/{name}", _depth=_depth + 1)
    for name, child in (schema.get("properties") or {}).items():
        check_schema(
            child, origin=origin, path=f"{path}/properties/{name}", _depth=_depth + 1
        )
    if "items" in schema:
        check_schema(
            schema["items"], origin=origin, path=f"{path}/items", _depth=_depth + 1
        )
    if isinstance(schema.get("additionalProperties"), dict):
        check_schema(
            schema["additionalProperties"],
            origin=origin,
            path=f"{path}/additionalProperties",
            _depth=_depth + 1,
        )


def iter_errors(
    instance: Any,
    schema: dict[str, Any],
    *,
    registry: SchemaRegistry | None = None,
    document: dict[str, Any] | None = None,
    path: str = "",
    depth: int = 0,
) -> Iterator[ValidationError]:
    """Yield every violation of ``schema`` by ``instance``.

    Raises :class:`SchemaError` for problems in the schema itself — those are
    author errors, not data errors, and must never degrade into a pass.
    """
    if depth > MAX_DEPTH:
        raise SchemaError(f"maximum schema depth exceeded at {path or '/'}")
    if depth == 0:
        # Check the whole schema tree before looking at the instance, so that
        # keyword shapes are verified even in branches this instance never
        # reaches. Schemas resolved through a registry were checked when they
        # were registered.
        check_schema(schema)
    if not isinstance(schema, dict):
        raise SchemaError(f"schema at {path or '/'} must be an object")
    if document is None:
        document = schema

    if "$ref" in schema:
        target, target_document = _resolve_ref(schema["$ref"], document, registry)
        yield from iter_errors(
            instance,
            target,
            registry=registry,
            document=target_document,
            path=path,
            depth=depth + 1,
        )

    if "type" in schema:
        declared = schema["type"]
        names = [declared] if isinstance(declared, str) else declared
        if not any(_type_matches(instance, name) for name in names):
            yield ValidationError(
                path,
                "type",
                f"expected {' or '.join(names)}, got {_type_name(instance)}",
            )
            # One cause, one error: keywords below judge a value of the wrong
            # type and would only add noise. Schema soundness was already
            # established by check_schema, so nothing is skipped unchecked.
            return

    if "const" in schema and not json_equal(instance, schema["const"]):
        yield ValidationError(
            path, "const", f"must equal {json.dumps(schema['const'])}"
        )

    if "enum" in schema and not any(
        json_equal(instance, option) for option in schema["enum"]
    ):
        yield ValidationError(
            path, "enum", f"must be one of {json.dumps(schema['enum'])}"
        )

    if isinstance(instance, str):
        # JSON Schema semantics: pattern is a search, not a full match. Anchor
        # patterns with ^ and $ when a whole-string constraint is meant.
        if "pattern" in schema and _compiled(schema["pattern"]).search(instance) is None:
            yield ValidationError(
                path, "pattern", f"does not match {schema['pattern']!r}"
            )
        if "minLength" in schema and len(instance) < schema["minLength"]:
            yield ValidationError(
                path, "minLength", f"shorter than {schema['minLength']} characters"
            )
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            yield ValidationError(
                path, "maxLength", f"longer than {schema['maxLength']} characters"
            )

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            yield ValidationError(path, "minimum", f"less than {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            yield ValidationError(path, "maximum", f"greater than {schema['maximum']}")

    if isinstance(instance, list):
        if "items" in schema:
            for index, item in enumerate(instance):
                yield from iter_errors(
                    item,
                    schema["items"],
                    registry=registry,
                    document=document,
                    path=_pointer(path, index),
                    depth=depth + 1,
                )
        if "minItems" in schema and len(instance) < schema["minItems"]:
            yield ValidationError(
                path, "minItems", f"fewer than {schema['minItems']} items"
            )
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            yield ValidationError(
                path, "maxItems", f"more than {schema['maxItems']} items"
            )
        if schema.get("uniqueItems") is True:
            for i in range(len(instance)):
                if any(json_equal(instance[i], instance[j]) for j in range(i)):
                    yield ValidationError(
                        path, "uniqueItems", f"item {i} duplicates an earlier item"
                    )
                    break

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in instance:
                yield ValidationError(
                    _pointer(path, name), "required", "missing required property"
                )
        additional = schema.get("additionalProperties")
        for key, value in instance.items():
            if key in properties:
                yield from iter_errors(
                    value,
                    properties[key],
                    registry=registry,
                    document=document,
                    path=_pointer(path, key),
                    depth=depth + 1,
                )
            elif additional is False:
                yield ValidationError(
                    _pointer(path, key),
                    "additionalProperties",
                    "property is not allowed by this closed contract",
                )
            elif isinstance(additional, dict):
                yield from iter_errors(
                    value,
                    additional,
                    registry=registry,
                    document=document,
                    path=_pointer(path, key),
                    depth=depth + 1,
                )


def validate(
    instance: Any,
    schema: dict[str, Any],
    *,
    registry: SchemaRegistry | None = None,
    document: dict[str, Any] | None = None,
) -> list[ValidationError]:
    """Return every violation; an empty list means valid."""
    return list(
        iter_errors(instance, schema, registry=registry, document=document)
    )


def validate_ref(
    instance: Any, ref: str, *, registry: SchemaRegistry | None = None
) -> list[ValidationError]:
    """Validate against ``file.schema.json#/$defs/name``."""
    registry = registry if registry is not None else default_registry()
    schema, document = resolve_schema(ref, registry)
    return validate(instance, schema, registry=registry, document=document)


def is_valid(
    instance: Any, schema: dict[str, Any], *, registry: SchemaRegistry | None = None
) -> bool:
    for _ in iter_errors(instance, schema, registry=registry):
        return False
    return True
