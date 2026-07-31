# 0008 — Minimal internal schema validator

Status: accepted, 2026-07-31

## Context

Every boundary in this system is schema-validated (ADR 0001,
`concepts/gate.md`): envelopes, contracts, plans, run manifests, and the
structured output of every model call. That makes the validator a load-
bearing gate, and it makes its availability a deployment concern —
consuming repositories are expected to run `python -m workflows.check`
in CI unchanged.

The repository convention is stdlib-only Python. The obvious alternative
is the `jsonschema` package: complete, well tested, and a dependency
whose absence turns every gate into a skipped step in an environment that
did not install it.

The schemas here use a small, deliberately boring subset of JSON Schema
draft 2020-12. Closed contracts and explicit enums do the work;
combinators do not appear.

## Decision

Ship a minimal internal validator (`src/workflows/schema.py`) covering
exactly the subset the repository uses:

`$ref` (JSON Pointer fragments, same-document and cross-document via a
registry), `$defs`, `type` (including `integer` vs `number` vs `boolean`),
`enum`, `const`, `required`, `properties`, `additionalProperties`,
`pattern`, `minLength`, `maxLength`, `minimum`, `maximum`, `items`,
`minItems`, `maxItems`, `uniqueItems`. Annotation keywords (`$schema`,
`$id`, `$comment`, `title`, `description`, `examples`, `default`,
`deprecated`) are accepted and constrain nothing.

Two properties make it a gate rather than a decoration:

1. **Unsupported keywords raise, they are never ignored.** A schema using
   `oneOf`, `if`/`then`, `format`, or `patternProperties` is a
   `SchemaError` — loudly, at validation time, and in a repository-wide
   convention test that walks every schema node including branches no
   fixture exercises. A validator that silently skips a constraint would
   report a pass it never checked.
2. **Comparison is JSON-typed.** `true` is never equal to `1` and never
   equal to `"true"`; `0` and `0.0` are equal, per JSON Schema numeric
   semantics. Type conflation is defect class 1 in the benchmark taxonomy;
   the validator must not be an instance of it.

Combinators are out of the subset on purpose. Where a union looks
necessary, the repository uses separate schemas plus a discriminating
field, or a semantic check next to the validator (as with the
"PASS while carrying an open HIGH finding" rule, which no schema
keyword can express).

**Fallback, recorded now so it is not re-litigated later:** if the subset
proves insufficient — a genuine need for combinators or recursion that
separate schemas cannot express — the replacement is a single
`jsonschema` dependency, not a growing home-grown implementation. That
change requires an amendment to this ADR stating which construct forced
it, and it must keep the two properties above (strict unknown-keyword
behaviour is not `jsonschema`'s default posture, so it would move into
the repository's own conventions test).

## Consequences

- Zero runtime dependencies; the gate runs anywhere Python 3.12 runs,
  including in consuming repositories that install nothing.
- The subset is enforced in both directions: the validator rejects
  unsupported keywords at run time, and the conventions test rejects them
  at authoring time.
- Validator behaviour is itself under test — type conflation, numeric
  equality, closed contracts, pointer escaping, cyclic `$ref` — because a
  validator nobody tested is an untested gate for everything downstream.
- Semantic rules that schemas cannot express live next to the validator
  and are tested with the same fixture corpus, so they cannot be quietly
  skipped by callers that only run schema validation.
