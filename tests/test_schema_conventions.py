"""Repository conventions every schema document must satisfy.

These run over the whole ``contracts/`` directory, including branches no
fixture happens to exercise, so an unsupported keyword or an accidentally
open object cannot reach a consumer.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Iterator

from tests import support
from workflows import schema as s

DRAFT = "https://json-schema.org/draft/2020-12/schema"


def schema_documents() -> list[tuple[str, dict[str, Any]]]:
    paths = sorted(support.CONTRACTS_DIR.glob("*.schema.json"))
    return [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in paths]


def walk(node: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield every sub-schema node, located by a readable path."""
    if not isinstance(node, dict):
        return
    yield path or "<root>", node
    for name, child in (node.get("$defs") or {}).items():
        yield from walk(child, f"{path}/$defs/{name}")
    for name, child in (node.get("properties") or {}).items():
        yield from walk(child, f"{path}/properties/{name}")
    if isinstance(node.get("items"), dict):
        yield from walk(node["items"], f"{path}/items")
    if isinstance(node.get("additionalProperties"), dict):
        yield from walk(node["additionalProperties"], f"{path}/additionalProperties")


class SchemaConventionsTest(unittest.TestCase):
    def test_there_is_at_least_one_schema(self) -> None:
        self.assertTrue(schema_documents())

    def test_documents_declare_draft_and_identity(self) -> None:
        for name, document in schema_documents():
            with self.subTest(schema=name):
                self.assertEqual(document.get("$schema"), DRAFT)
                self.assertEqual(document.get("$id"), name)

    def test_only_supported_keywords_are_used(self) -> None:
        allowed = s.SUPPORTED_KEYWORDS | s.ANNOTATION_KEYWORDS
        for name, document in schema_documents():
            for where, node in walk(document):
                with self.subTest(schema=name, node=where):
                    self.assertEqual(set(node) - allowed, set())

    def test_object_schemas_are_closed(self) -> None:
        for name, document in schema_documents():
            for where, node in walk(document):
                if node.get("type") != "object" and "properties" not in node:
                    continue
                with self.subTest(schema=name, node=where):
                    self.assertIs(
                        node.get("additionalProperties"),
                        False,
                        "object schemas must be closed contracts",
                    )

    def test_required_properties_are_declared(self) -> None:
        for name, document in schema_documents():
            for where, node in walk(document):
                declared = set(node.get("properties") or {})
                for required in node.get("required", []):
                    with self.subTest(schema=name, node=where, property=required):
                        self.assertIn(required, declared)

    def test_every_ref_resolves(self) -> None:
        registry = support.registry()
        for name, document in schema_documents():
            for where, node in walk(document):
                ref = node.get("$ref")
                if ref is None:
                    continue
                with self.subTest(schema=name, node=where, ref=ref):
                    s._resolve_ref(ref, document, registry)

    def test_instance_documents_pin_their_schema_version(self) -> None:
        """Every document that describes an instance declares a const version.

        ``core.defs.schema.json`` is exempt: it is a ``$defs`` library with no
        instance form, and carries the shared version *pattern* instead.
        """
        pattern = support.registry().get("core.defs.schema.json")["$defs"]["schema_version"]
        checked = 0
        for name, document in schema_documents():
            if "type" not in document:
                continue
            with self.subTest(schema=name):
                version = (document.get("properties") or {}).get("schema_version")
                self.assertIsNotNone(version, "instance documents need a schema_version")
                self.assertIn("const", version, "schema_version must be a const")
                self.assertIn("schema_version", document.get("required", []))
                self.assertEqual(s.validate(version["const"], pattern), [])
                checked += 1
        self.assertGreater(checked, 0)

    def test_every_schema_version_const_is_unique(self) -> None:
        versions = [
            (document.get("properties") or {}).get("schema_version", {}).get("const")
            for _, document in schema_documents()
            if "type" in document
        ]
        self.assertEqual(len(versions), len(set(versions)))

    def test_digest_definitions_use_the_prefixed_sha256_shape(self) -> None:
        digest = support.registry().get("core.defs.schema.json")["$defs"]["digest"]
        self.assertEqual(digest["pattern"], "^sha256:[0-9a-f]{64}$")

    def test_schema_version_definition_requires_an_explicit_version(self) -> None:
        pattern = support.registry().get("core.defs.schema.json")["$defs"]["schema_version"]
        for accepted in ("workflows.envelope.v1", "workflows.task-contract.v2"):
            self.assertEqual(s.validate(accepted, pattern), [])
        for rejected in ("workflows.envelope", "envelope.v1", "workflows.Envelope.v1", ""):
            self.assertTrue(s.validate(rejected, pattern), f"{rejected!r} should be rejected")


if __name__ == "__main__":
    unittest.main()
