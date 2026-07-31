# Deviations from the roadmap

Visible deviation beats silent adaptation. Every departure from
[roadmap.md](roadmap.md) or [test-charter.md](test-charter.md) is recorded
here with its reason, in milestone order.

## M0

**D-M0-1 — The acceptance criterion "CI green on an empty test suite" was
over-delivered, not met literally.** The suite ships with 66 tests.
Reason: the second half of the same criterion ("core defs validate example
fixtures") cannot be satisfied by an empty suite, so "empty" is read as
"the scaffold must be green before there is anything to test". The
scaffold was verified green independently: a fresh clone runs
`python -m unittest discover` with no install step, and CI is green on
3.12 and 3.13.

**D-M0-2 — `core.defs.schema.json` defines more `$defs` than the roadmap
bullet enumerates.** Added beyond the list: `identifier` (non-blank
machine identity — closes the blank-identity defect class at the type
level), `timestamp`, `finding_status`, `evidence_kind`,
`evidence_ref_list`, `criterion_outcome`, `side_effect`,
`side_effect_kind`, `contract_ref`, `relative_path`, `path_pattern`,
`git_commit`, `step_kind`, `step_state`, `flow_name`, `verdict_result`,
`ladder_level`, `token_usage`, `telemetry`.
Reason: the enumerated shapes (`finding`, `evidence_ref`, `candidate`)
cannot be expressed without them, and defining them once in the core is
what keeps the M1 schemas from each inventing their own identity and path
rules.

**D-M0-3 — `terminal` is an envelope field, not a core `$def`.**
`concepts/envelope.md` lists `status` "plus `terminal`" among the core
fields. It is a plain boolean with no shared shape to factor out, so it is
declared as a required property of `envelope.schema.json` (M1) rather than
as a core definition. No behaviour is lost; only the location differs.

**D-M0-4 — The two CI workflows were consolidated into one
`.github/workflows/ci.yml`.** The roadmap asks for "CI workflow running
tests + content policy on push"; the previous `content-policy.yml` was
folded into `ci.yml` as a separate job, and the test job runs a 3.12/3.13
matrix so version drift is caught rather than discovered later.

**D-M0-5 — The schema validator checks schema soundness recursively and
unconditionally, which the roadmap did not ask for.** An independent
review found that keyword *shapes* were only checked when an instance
happened to have the matching JSON type, so a schema with an empty `enum`
or a non-boolean `uniqueItems` enforced nothing and raised nothing.
`check_schema` now runs over the whole schema tree — including branches no
instance reaches — at every validation entry point and at schema
registration. Recorded because it enlarges M0's scope; see ADR 0008.

## M1

**D-M1-1 — `src/workflows/paths.py` lands in M1, ahead of the M2 gates
that need it.** Scope and protected-path matching already has three M1
consumers: the task-contract rule that a protected path may not also be
writable, the plan rule that write scopes must be disjoint, and the CLI
that reports both. Writing it once here beats writing it twice.

**D-M1-2 — `examples/plan.example.toml` was added, which the roadmap does
not list.** The plan schema is the only M1 schema whose authoring format
is TOML rather than JSON, so the example doubles as the test that the CLI
parses TOML at all.

**D-M1-3 — Semantic rules are a module (`src/workflows/semantics.py`), not
only the one check the charter names.** The charter requires the
"PASS while carrying an open CRITICAL/HIGH finding" check to live with the
validator. The same category — obligations no schema keyword can express —
covers evidence reference integrity, the negative-path probe rule, vacuous
PASS, disjoint write scopes, and step-lifecycle consistency, so they are
implemented together and reported through the same entry point.

**D-M1-4 — `SchemaRegistry.add` compares schema *content*, not object
identity, when deciding that a key is taken.** Registering the same document
twice — which happens when the CLI is handed a path to a schema that is
already in the registry — used to raise. Re-registering byte-identical
content is now allowed; only genuinely conflicting content under one key
raises. Found by an independent review, which noted that the change of an
M0 behaviour was folded into the M1 commit without being logged.

**D-M1-5 — The schema files moved from `contracts/` to
`src/workflows/contracts/`.** The roadmap names `contracts/core.defs.schema.json`,
and the top-level directory keeps the catalog page, but the files
themselves had to move: a built wheel packaged only the Python modules, so
an installed copy resolved an empty schema registry and validated nothing.
An independent review demonstrated this by building a wheel and running the
CLI from an unrelated directory. The CI job that claimed to prove
cross-repository installability was installing editably from this checkout,
which resolves the schemas back to the source tree and therefore proved
nothing; it now builds a wheel, installs it into a separate virtual
environment, and validates a document from a directory with no checkout in
it — including a case that must exit nonzero.

## M2

**D-M2-1 — Python lives in `src/workflows/`; the top-level `gates/`,
`flows/`, `runners/` and `program/` directories are documentation.** The
README's original layout listed those directories next to `scripts/` as if
they held code, while the M0 roadmap bullet mandates the package skeleton
under `src/`. One importable package is what lets a consuming repository
install this and run the same gates; the top-level directories keep the
definitions and the catalogs. The README layout now says so, and
`flows/README.md` was corrected.

**D-M2-2 — A `gate-result.schema.json` was added, which the roadmap does
not name.** The acceptance criterion says gate results must "validate
against the envelope fragment schema", and no such schema existed. It adds
a `reason_code` enum, which is what makes the charter's requirement
checkable that a missing verification command "fails closed with a distinct
reason" rather than being reported as skipped or green.

**D-M2-3 — `src/workflows/runs.py` lands in M2, ahead of the M4 resume
machinery.** The gate runner has to write results to the run directory, so
the run directory has to exist. It implements the append-only artifact
discipline and the atomically-rewritten manifest now; step scheduling and
resume arrive with the flows.

**D-M2-4 — The `evidence_obligations` gate reports `INCONCLUSIVE` for
`number_traceable` and `manual_judgment` obligations.** Neither can be
settled by a deterministic check, and reporting them as PASS or silently
skipping them would let a goal be declared attained on the strength of
gates alone. They come back `requires_judgment`, named individually in the
result's non-claims. Whether `number_traceable` deserves a real
deterministic implementation is deferred to M7, where `assure` goal mode
consumes it.

## M3

**D-M3-1 — Prompt composition and lens loading landed in M3, ahead of the
M4 bullet that names the lens starter set.** The roadmap's M3 acceptance
criterion is "composition determinism", which cannot be tested without a
composer and something to compose. The lens *files* still arrive in M4;
what M3 adds is the loader, the format check, and the composer.

**D-M3-2 — Reviewer blindness is enforced by a function signature.** The
charter tests it as a string assertion on the composed prompt. The prompt
module goes further: `prompts.review` has no parameter through which worker
or synthesizer dialogue could be passed, and a test asserts the signature
itself. A string assertion catches a leak after someone adds the parameter;
this catches the parameter.

**D-M3-3 — Token usage for one call is the final usage figure, never a
sum.** The charter forbids adding cumulative and per-turn figures together
but does not say which to keep. The runner keeps the last and records how
many usage events it saw, so an undercount is visible in the record rather
than silent. Whether a multi-turn Codex call reports per-turn or cumulative
figures is an open question, stated as such in `runners/README.md`.

**D-M3-4 — The launcher is resolved with `shutil.which`.** Not in the
roadmap, but the first live smoke test failed with `WinError 2` because an
npm-installed CLI on Windows is a `.cmd` shim and `CreateProcess` does not
apply PATHEXT to a bare name.
