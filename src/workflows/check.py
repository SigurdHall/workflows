"""Validate documents against this repository's schemas.

    python -m workflows.check <schema> <file> [<file> ...]

``<schema>`` is a schema document name (``envelope.schema.json``), a
reference into one (``core.defs.schema.json#/$defs/finding``), or a path to
a schema file. ``<file>`` is JSON, or TOML when it ends in ``.toml`` —
plans are authored as TOML and validated as the parsed structure.

Exit codes are check-style, so this runs unchanged in a consuming
repository's CI:

* 0 — every document is valid
* 1 — at least one document has violations
* 2 — usage or configuration error (unknown schema, unreadable file,
  unparseable document, unsound schema)

Schema violations and semantic violations are both reported. Semantic rules
run only on documents that pass schema validation; the cause is reported
once, not twice.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from workflows import semantics
from workflows.schema import (
    SchemaError,
    SchemaRegistry,
    ValidationError,
    contracts_dir,
    default_registry,
)

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_USAGE = 2


def load_document(path: Path) -> Any:
    # utf-8-sig, not utf-8: a byte order mark is what Windows editors and a
    # plain PowerShell redirection produce, and a document is not malformed
    # for carrying one.
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".toml":
        return tomllib.loads(text)
    return json.loads(text)


def build_registry(schema_dir: Path | None) -> SchemaRegistry:
    if schema_dir is None:
        return default_registry()
    return SchemaRegistry.from_directory(schema_dir)


def resolve_reference(reference: str, registry: SchemaRegistry) -> str:
    """Accept a schema name, a name with a fragment, or a file path."""
    document, separator, fragment = reference.partition("#")
    if document not in registry.keys():
        candidate = Path(document)
        if candidate.is_file():
            registry.add(
                json.loads(candidate.read_text(encoding="utf-8")), key=candidate.name
            )
            document = candidate.name
        # Otherwise leave it alone: the registry raises a message that lists
        # the schemas it does know.
    return document + separator + fragment


def report(path: Path, errors: list[ValidationError], as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "file": str(path),
                    "errors": [
                        {"path": e.path, "keyword": e.keyword, "message": e.message}
                        for e in errors
                    ],
                },
                indent=2,
            )
        )
        return
    for error in errors:
        print(f"{path}:{error.path or '/'}: {error.keyword}: {error.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.check",
        description="Validate documents against the workflows schemas.",
    )
    parser.add_argument("schema", help="schema name, name#/$defs/name, or path")
    parser.add_argument("files", nargs="+", type=Path, help="documents to validate")
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=None,
        help=f"directory of schema documents (default: {contracts_dir()})",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--quiet", action="store_true", help="report nothing, only exit")
    args = parser.parse_args(argv)

    try:
        registry = build_registry(args.schema_dir)
        reference = resolve_reference(args.schema, registry)
    except (SchemaError, OSError, json.JSONDecodeError) as exc:
        print(f"schema error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    failed = False
    for path in args.files:
        try:
            document = load_document(path)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"cannot read {path}: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            print(f"cannot parse {path}: {exc}", file=sys.stderr)
            return EXIT_USAGE

        try:
            errors = semantics.check_document(document, reference, registry=registry)
        except SchemaError as exc:
            print(f"schema error: {exc}", file=sys.stderr)
            return EXIT_USAGE

        if errors:
            failed = True
            if not args.quiet:
                report(path, errors, args.json)
        elif not args.quiet and not args.json:
            print(f"{path}: ok")

    return EXIT_VIOLATIONS if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
