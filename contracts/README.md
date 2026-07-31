# Contracts

JSON Schemas for everything that crosses a boundary: contracts, envelopes,
verdicts, plans, and run manifests. Draft 2020-12, closed
(`additionalProperties: false`), `schema_version` as a `const` per
document, digests as `sha256:` plus 64 lowercase hex characters.

- `core.defs.schema.json` — shared `$defs` referenced by every other
  schema as `core.defs.schema.json#/$defs/<name>`. It defines identity,
  digests, timestamps, the status/result/severity enums, the finding and
  evidence shapes, non-claims, side effects, and candidate identity. It
  deliberately contains no scores and no rubrics
  (`concepts/envelope.md`).

Schemas are validated by `src/workflows/schema.py`, which implements the
subset recorded in
[ADR 0008](../docs/decisions/0008-minimal-internal-schema-validator.md)
and raises on any keyword outside it. `tests/test_schema_conventions.py`
enforces the draft, identity, closed-object, keyword-subset and
`$ref`-resolvability conventions across every document here. The
`schema_version`-as-`const` convention applies to instance documents;
`core.defs.schema.json` is a `$defs` library with no instance form, so it
carries the shared `schema_version` *pattern* instead and the `const`
check applies from the M1 schemas onwards.

Fixtures live in `tests/fixtures/` and are self-describing: each file
names the schema it targets, whether it is expected to be valid or
invalid, why, and — for invalid fixtures — the exact `(path, keyword)`
violations it must produce.
