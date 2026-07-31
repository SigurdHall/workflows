# Contracts

JSON Schemas for everything that crosses a boundary: contracts, envelopes,
verdicts, plans, and run manifests. Draft 2020-12, closed
(`additionalProperties: false`), `schema_version` as a `const` per
document, digests as `sha256:` plus 64 lowercase hex characters.

**The schema files live in [`src/workflows/contracts/`](../src/workflows/contracts/)**,
inside the package. They are data the validator needs, not documentation:
a built wheel that shipped only the Python modules would install a
validator with an empty registry — a gate that cannot check anything. This
page is the catalog; `WORKFLOWS_CONTRACTS_DIR` points the validator
somewhere else when a consuming repository has its own.

- `core.defs.schema.json` — shared `$defs` referenced by every other
  schema as `core.defs.schema.json#/$defs/<name>`. It defines identity,
  digests, timestamps, the status/result/severity enums, the finding and
  evidence shapes, non-claims, side effects, candidate identity, paths,
  telemetry and token usage. It deliberately contains no scores and no
  rubrics (`concepts/envelope.md`).
- `task-contract.schema.json` / `goal-contract.schema.json` — the two
  contract types (ADR 0007).
- `envelope.schema.json` — the result of any step, and the only thing
  that crosses a step boundary.
- `verdict.schema.json` — a flow's consolidated judgment about one
  candidate.
- `run-manifest.schema.json` — what ran, what state each step is in, and
  what a resume may skip.
- `plan.schema.json` — one plan, many contracts; authored as TOML and
  validated as the parsed structure.

## Validating

```
python -m workflows.check <schema> <file> [<file> ...]
```

`<schema>` is a document name (`envelope.schema.json`), a reference into
one (`core.defs.schema.json#/$defs/finding`), or a path to a schema file.
`<file>` is JSON, or TOML when it ends in `.toml`. Exit codes are
check-style — 0 clean, 1 violations, 2 usage or configuration error — so
the command runs unchanged in a consuming repository's CI.

## Rules a schema cannot express

Some obligations are not shapes: a claim must point at evidence that
exists, a PASS may not carry an open HIGH finding, a negative-path claim
needs an executed probe, and two tasks in one plan may not write the same
file. Those live in `src/workflows/semantics.py`, run from the same entry
point as schema validation, and are reported with a `semantic:` keyword so
a fixture annotates them exactly like a schema violation. Semantic rules
run only on documents that already pass their schema, so one cause is
reported once.

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
