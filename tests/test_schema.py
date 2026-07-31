"""Unit tests for the minimal schema validator.

Failure paths are the product: a validator that silently ignores a keyword,
conflates ``true`` with ``1``, or degrades a schema error into a pass would
turn every downstream gate into documentation.
"""

from __future__ import annotations

import unittest

from tests import support
from workflows import schema as s


def errors(instance, schema, **kwargs):
    return sorted((e.path, e.keyword) for e in s.validate(instance, schema, **kwargs))


class UnsupportedKeywordTest(unittest.TestCase):
    def test_unknown_keyword_raises_instead_of_being_ignored(self) -> None:
        for keyword in ("oneOf", "anyOf", "allOf", "not", "if", "format", "patternProperties"):
            with self.subTest(keyword=keyword):
                with self.assertRaises(s.SchemaError) as ctx:
                    s.validate("anything", {"type": "string", keyword: []})
                self.assertIn(keyword, str(ctx.exception))

    def test_unknown_keyword_nested_in_properties_raises(self) -> None:
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string", "oneOf": []}},
        }
        with self.assertRaises(s.SchemaError):
            s.validate({"a": "x"}, schema)

    def test_annotation_keywords_are_accepted(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "annotated.schema.json",
            "title": "t",
            "description": "d",
            "$comment": "c",
            "examples": ["x"],
            "default": "x",
            "deprecated": False,
            "type": "string",
        }
        self.assertEqual(errors("x", schema), [])

    def test_unsupported_type_name_raises(self) -> None:
        with self.assertRaises(s.SchemaError):
            s.validate(1, {"type": "int"})

    def test_non_object_schema_raises(self) -> None:
        with self.assertRaises(s.SchemaError):
            s.validate(1, True)  # type: ignore[arg-type]


class SchemaSoundnessTest(unittest.TestCase):
    """A malformed schema must raise for every instance, not only for one shape.

    Regression tests for a review finding: keyword *shapes* used to be checked
    inside the same ``isinstance`` guards as the instance checks, so a broken
    schema validated cleanly whenever the instance happened to have a
    different JSON type. The validator would then have been an instance of the
    very defect class it exists to catch.
    """

    MALFORMED = [
        {"required": "a"},
        {"required": ["a", "a"]},
        {"pattern": "["},
        {"pattern": 7},
        {"minLength": "two"},
        {"maxLength": -1},
        {"minItems": 1.5},
        {"properties": "bad"},
        {"additionalProperties": 5},
        {"minimum": "zero"},
        {"items": 5},
        {"enum": []},
        {"enum": "PASS"},
        {"type": "int"},
        {"type": []},
        {"$ref": ""},
        {"uniqueItems": 1},
        {"uniqueItems": "true"},
        {"uniqueItems": {"not": "a boolean"}},
        {"minLength": 5, "maxLength": 2},
        {"minItems": 5, "maxItems": 2},
        {"minimum": 5, "maximum": 2},
    ]

    INSTANCES = [None, True, 0, 1.5, "x", [1, 1], {"a": 1}]

    def test_malformed_schemas_raise_for_every_instance_type(self) -> None:
        for schema in self.MALFORMED:
            for instance in self.INSTANCES:
                with self.subTest(schema=schema, instance=instance):
                    with self.assertRaises(s.SchemaError):
                        s.validate(instance, dict(schema))

    def test_unvisited_branches_are_checked(self) -> None:
        # No instance ever reaches these sub-schemas; they must still be sound.
        for schema in (
            {"type": "object", "properties": {"absent": {"oneOf": []}}},
            {"type": "object", "properties": {"absent": {"enum": []}}},
            {"type": "object", "additionalProperties": {"uniqueItems": "yes"}},
            {"type": "array", "items": {"minimum": "zero"}},
            {"$defs": {"unused": {"type": "nope"}}, "type": "string"},
        ):
            with self.subTest(schema=schema):
                with self.assertRaises(s.SchemaError):
                    s.validate({} if schema.get("type") == "object" else [], schema)

    def test_unique_items_is_enforced_only_by_the_boolean_true(self) -> None:
        self.assertEqual(errors([1, 1], {"type": "array", "uniqueItems": True}),
                         [("", "uniqueItems")])
        self.assertEqual(errors([1, 1], {"type": "array", "uniqueItems": False}), [])

    def test_check_schema_accepts_the_repository_contracts(self) -> None:
        registry = support.registry()
        for key in registry.keys():
            with self.subTest(schema=key):
                s.check_schema(registry.get(key), origin=key)

    def test_check_schema_names_the_offending_node(self) -> None:
        with self.assertRaises(s.SchemaError) as ctx:
            s.check_schema(
                {"$defs": {"broken": {"enum": []}}}, origin="example.schema.json"
            )
        self.assertIn("example.schema.json/$defs/broken", str(ctx.exception))


class RegistryIsolationTest(unittest.TestCase):
    """A shared, mutable, process-wide registry would let one caller weaken
    every later validation. Each default_registry() call parses its own copy.
    """

    def test_mutating_a_resolved_schema_does_not_leak(self) -> None:
        first = s.default_registry()
        self.assertIsNot(first, s.default_registry())
        document = first.get("core.defs.schema.json")
        document["$defs"]["digest"]["pattern"] = "^.*$"
        fresh = s.default_registry().get("core.defs.schema.json")
        self.assertEqual(fresh["$defs"]["digest"]["pattern"], "^sha256:[0-9a-f]{64}$")

    def test_registration_rejects_an_unsound_document(self) -> None:
        registry = s.SchemaRegistry()
        with self.assertRaises(s.SchemaError):
            registry.add({"$id": "broken.schema.json", "$defs": {"x": {"enum": []}}})


class TypeTest(unittest.TestCase):
    def test_boolean_is_not_an_integer(self) -> None:
        self.assertEqual(errors(True, {"type": "integer"}), [("", "type")])
        self.assertEqual(errors(True, {"type": "number"}), [("", "type")])

    def test_integer_is_not_a_boolean(self) -> None:
        self.assertEqual(errors(1, {"type": "boolean"}), [("", "type")])

    def test_integer_satisfies_number(self) -> None:
        self.assertEqual(errors(3, {"type": "number"}), [])

    def test_float_does_not_satisfy_integer(self) -> None:
        self.assertEqual(errors(3.5, {"type": "integer"}), [("", "type")])

    def test_union_type_accepts_either(self) -> None:
        schema = {"type": ["string", "null"]}
        self.assertEqual(errors("x", schema), [])
        self.assertEqual(errors(None, schema), [])
        self.assertEqual(errors(3, schema), [("", "type")])

    def test_type_failure_suppresses_downstream_keywords(self) -> None:
        # One cause, one error: a wrong type must not also report pattern.
        schema = {"type": "string", "pattern": "^x$"}
        self.assertEqual(errors(7, schema), [("", "type")])


class ConstAndEnumTest(unittest.TestCase):
    def test_true_does_not_equal_one(self) -> None:
        self.assertEqual(errors(1, {"const": True}), [("", "const")])
        self.assertEqual(errors(True, {"const": 1}), [("", "const")])

    def test_zero_equals_zero_point_zero(self) -> None:
        self.assertEqual(errors(0.0, {"const": 0}), [])
        self.assertEqual(errors(0, {"const": 0.0}), [])

    def test_string_does_not_equal_number(self) -> None:
        self.assertEqual(errors("1", {"const": 1}), [("", "const")])

    def test_enum_membership_is_type_strict(self) -> None:
        self.assertEqual(errors(1, {"enum": [True, "1"]}), [("", "enum")])
        self.assertEqual(errors(True, {"enum": [True, "1"]}), [])

    def test_nested_const_compares_structurally(self) -> None:
        schema = {"const": {"a": [1, {"b": None}]}}
        self.assertEqual(errors({"a": [1, {"b": None}]}, schema), [])
        self.assertEqual(errors({"a": [1, {"b": False}]}, schema), [("", "const")])

    def test_empty_enum_is_a_schema_error(self) -> None:
        with self.assertRaises(s.SchemaError):
            s.validate("x", {"enum": []})


class StringAndNumberTest(unittest.TestCase):
    def test_pattern_and_length(self) -> None:
        schema = {"type": "string", "pattern": "^[a-z]+$", "minLength": 2, "maxLength": 4}
        self.assertEqual(errors("abc", schema), [])
        self.assertEqual(errors("a", schema), [("", "minLength")])
        self.assertEqual(errors("abcde", schema), [("", "maxLength")])
        self.assertEqual(errors("ABC", schema), [("", "pattern")])

    def test_pattern_is_a_search_not_a_full_match(self) -> None:
        # JSON Schema semantics, pinned deliberately: an unanchored pattern
        # matches anywhere in the string. Contract authors must write ^...$.
        self.assertEqual(errors("xxabcxx", {"type": "string", "pattern": "abc"}), [])
        self.assertEqual(
            errors("xxabcxx", {"type": "string", "pattern": "^abc$"}),
            [("", "pattern")],
        )

    def test_invalid_pattern_raises(self) -> None:
        with self.assertRaises(s.SchemaError):
            s.validate("x", {"pattern": "["})

    def test_bounds_ignore_booleans(self) -> None:
        schema = {"minimum": 0, "maximum": 10}
        self.assertEqual(errors(True, schema), [])  # only the type keyword judges booleans
        self.assertEqual(errors(-1, schema), [("", "minimum")])
        self.assertEqual(errors(11, schema), [("", "maximum")])


class ArrayTest(unittest.TestCase):
    def test_items_report_indexed_paths(self) -> None:
        schema = {"type": "array", "items": {"type": "string"}}
        self.assertEqual(errors(["a", 2, "c"], schema), [("/1", "type")])

    def test_item_bounds(self) -> None:
        schema = {"type": "array", "minItems": 1, "maxItems": 2}
        self.assertEqual(errors([], schema), [("", "minItems")])
        self.assertEqual(errors([1, 2, 3], schema), [("", "maxItems")])

    def test_unique_items_is_type_strict(self) -> None:
        schema = {"type": "array", "uniqueItems": True}
        self.assertEqual(errors([1, True], schema), [])
        self.assertEqual(errors([1, 1.0], schema), [("", "uniqueItems")])
        self.assertEqual(errors([{"a": 1}, {"a": 1}], schema), [("", "uniqueItems")])

    def test_unique_items_reports_once(self) -> None:
        schema = {"type": "array", "uniqueItems": True}
        self.assertEqual(errors(["a", "a", "a"], schema), [("", "uniqueItems")])


class ObjectTest(unittest.TestCase):
    def test_closed_contract_rejects_unknown_properties(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"a": {"type": "string"}},
        }
        self.assertEqual(errors({"a": "x", "b": 1}, schema), [("/b", "additionalProperties")])

    def test_required_paths_point_at_the_missing_property(self) -> None:
        schema = {"type": "object", "required": ["a", "b"], "properties": {}}
        self.assertEqual(errors({}, schema), [("/a", "required"), ("/b", "required")])

    def test_additional_properties_schema_is_applied(self) -> None:
        schema = {"type": "object", "additionalProperties": {"type": "integer"}}
        self.assertEqual(errors({"x": 1}, schema), [])
        self.assertEqual(errors({"x": "1"}, schema), [("/x", "type")])

    def test_pointer_tokens_are_escaped(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        }
        self.assertEqual(errors({"a/b": 1}, schema), [("/a~1b", "additionalProperties")])

    def test_required_must_be_a_list_of_strings(self) -> None:
        with self.assertRaises(s.SchemaError):
            s.validate({}, {"type": "object", "required": "a"})


class RefTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = support.registry()

    def test_internal_ref_resolves(self) -> None:
        schema = {
            "$defs": {"name": {"type": "string"}},
            "type": "object",
            "properties": {"n": {"$ref": "#/$defs/name"}},
        }
        self.assertEqual(errors({"n": 1}, schema), [("/n", "type")])

    def test_external_ref_resolves_through_the_registry(self) -> None:
        schema = {"$ref": "core.defs.schema.json#/$defs/digest"}
        self.assertEqual(errors("sha256:" + "a" * 64, schema, registry=self.registry), [])
        self.assertEqual(errors("nope", schema, registry=self.registry), [("", "pattern")])

    def test_ref_siblings_are_also_enforced(self) -> None:
        schema = {
            "$ref": "core.defs.schema.json#/$defs/evidence_ref_list",
            "minItems": 1,
        }
        self.assertEqual(errors([], schema, registry=self.registry), [("", "minItems")])

    def test_unresolvable_ref_raises(self) -> None:
        with self.assertRaises(s.SchemaError):
            s.validate("x", {"$ref": "#/$defs/missing"})

    def test_unknown_document_raises(self) -> None:
        with self.assertRaises(s.SchemaError):
            s.validate("x", {"$ref": "nope.schema.json#/$defs/a"}, registry=self.registry)

    def test_external_ref_without_registry_raises(self) -> None:
        with self.assertRaises(s.SchemaError):
            s.validate("x", {"$ref": "core.defs.schema.json#/$defs/digest"}, registry=None)

    def test_cyclic_ref_raises_instead_of_hanging(self) -> None:
        schema = {"$defs": {"loop": {"$ref": "#/$defs/loop"}}, "$ref": "#/$defs/loop"}
        with self.assertRaises(s.SchemaError):
            s.validate("x", schema)

    def test_resolve_schema_returns_the_owning_document(self) -> None:
        resolved, document = s.resolve_schema(
            "core.defs.schema.json#/$defs/finding", self.registry
        )
        self.assertEqual(resolved["type"], "object")
        self.assertIn("evidence_ref", document["$defs"])


class RegistryTest(unittest.TestCase):
    def test_directory_registry_indexes_by_name_and_id(self) -> None:
        registry = support.registry()
        self.assertIn("core.defs.schema.json", registry.keys())
        self.assertIs(
            registry.get("core.defs.schema.json"),
            registry.get(registry.get("core.defs.schema.json")["$id"]),
        )

    def test_conflicting_schemas_under_one_key_raise(self) -> None:
        registry = s.SchemaRegistry()
        registry.add({"$id": "a.schema.json", "type": "string"})
        with self.assertRaises(s.SchemaError):
            registry.add({"$id": "a.schema.json", "type": "integer"})

    def test_registering_the_same_document_twice_is_allowed(self) -> None:
        registry = s.SchemaRegistry()
        registry.add({"$id": "a.schema.json", "type": "string"})
        registry.add({"$id": "a.schema.json", "type": "string"})
        self.assertEqual(registry.keys(), ["a.schema.json"])

    def test_schema_without_identity_raises(self) -> None:
        with self.assertRaises(s.SchemaError):
            s.SchemaRegistry().add({"type": "string"})

    def test_unknown_schema_message_lists_known_keys(self) -> None:
        with self.assertRaises(s.SchemaError) as ctx:
            support.registry().get("missing.schema.json")
        self.assertIn("core.defs.schema.json", str(ctx.exception))


class ValidateRefTest(unittest.TestCase):
    def test_validate_ref_uses_the_repository_contracts(self) -> None:
        self.assertEqual(s.validate_ref("BLOCKED", "core.defs.schema.json#/$defs/status"), [])
        self.assertEqual(
            [e.keyword for e in s.validate_ref("nope", "core.defs.schema.json#/$defs/status")],
            ["enum"],
        )

    def test_error_string_shows_root_as_slash(self) -> None:
        error = s.ValidationError("", "enum", "must be one of []")
        self.assertTrue(str(error).startswith("/: enum:"))


if __name__ == "__main__":
    unittest.main()
