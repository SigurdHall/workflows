# Roadmap

**Status: M0–M8 complete as of v0.1.0.** Every acceptance criterion below
passes, CI is green, and a three-task program (two `implement`, one
`fanout`) dry-runs end to end and resumes without repeating a completed
flow. What that does and does not establish is stated in the README's
Status section; every departure from this roadmap is in
[deviations.md](deviations.md).

Implementation milestones for v0. Each milestone lists acceptance
criteria; a milestone is done when all criteria pass locally
(`python -m unittest` + `python scripts/check_content_policy.py`) and in
CI, **and** the mandatory test cases for that milestone in
[test-charter.md](test-charter.md) are implemented and green. The
charter is the floor, not the ceiling — the implementer adds their own
cases on top. Conventions: Python 3.12+, stdlib only, English, schemas
per the README's conventions section.

## M0 — Foundations

- Package skeleton (`src/workflows/`), unittest scaffold, CI workflow
  running tests + content policy on push.
- Schema core: `contracts/core.defs.schema.json` with the shared `$defs`
  (schema_version pattern, sha256 digest pattern, status enums, result
  enums, severity enum, finding shape, evidence ref, non-claims,
  candidate identity `{id, digest, immutable}`).
- ADR 0008 written: schema validation approach — minimal internal
  validator for the subset this repo uses (`type`, `required`,
  `properties`, `additionalProperties: false`, `enum`, `const`,
  `pattern`, arrays, min/max) is preferred to keep stdlib-only; if that
  subset proves insufficient, a single `jsonschema` dependency is the
  fallback and the ADR records it.

Acceptance: CI green on an empty test suite + policy check; core defs
validate example fixtures.

## M1 — Contracts and envelopes

- Schemas: `task-contract`, `goal-contract`, `envelope` (step result),
  `verdict`, `run-manifest`, `plan`.
- Validator CLI: `python -m workflows.check <schema> <file>` (check-style
  exit codes, usable from other repos' CI unchanged).
- Fixture examples per schema (valid + invalid) under `tests/fixtures/`.

Acceptance: round-trip tests — every fixture validates or fails exactly
as annotated.

## M2 — Gates

- Gate framework: a gate is a pure function `(contract, run_ctx) ->
  GateResult` (envelope fragment); a gate runner executes a named gate
  list and writes results to the run directory.
- Core gates: `base_identity`, `scope`, `protected_hash`,
  `verification_command`, `schema` (envelope validation),
  `evidence_obligations` (goal contracts).
- All git interaction via subprocess against a worktree path; no
  third-party git library.

Acceptance: unit tests per gate including failure paths (out-of-scope
file, modified protected file, dirty worktree, nonzero verification
exit); gate results validate against the envelope fragment schema.

## M3 — Runner

- Runner interface per ADR 0005: call = {model, effort, prompt,
  output_schema, cwd, sandbox, timeout}; result = {output, telemetry}.
- Codex CLI implementation (headless exec). Verify current flags against
  installed CLI docs at implementation time — do not assume; record the
  exact invocation contract in `runners/README.md`.
- Structured output: instruct + validate against `output_schema`; on
  validation failure, one bounded retry with the validation error, then
  FAILED envelope.
- `--dry-run` support at the runner level: compose and record the
  prompt, return a stub, mark telemetry as dry.
- Telemetry per call: new input, cached input, output tokens, duration,
  lens id — appended to `telemetry.jsonl`.

Acceptance: dry-run tests (no network) for composition, validation-retry
logic (mocked), telemetry records; one manual live smoke test documented
in the runner README.

## M4 — Flows: implement, assure (candidate mode), repair

- `implement`: freeze base → gates → worker call → gates → level-1
  review (blind, fresh prompt from review lenses) → on findings,
  targeted repair from original base → re-review → final envelope.
- `assure` candidate mode: gates + review lenses against an existing
  candidate; no producing step.
- Repair as a shared sub-step (used by implement and later fanout):
  findings routed to relevant lenses only; resynthesis from original
  base.
- Starter lens set: 4 work lenses, 6 review lenses, written per
  `concepts/lens.md` with explicit does-not-cover boundaries.
- Escalation triggers implemented as data (thresholds in flow config),
  levels 2–3 wired, level 4 declared-but-unimplemented per ADR 0005
  (non-claim in envelopes).

Acceptance: full dry-run of both flows produces a complete, resumable
run directory with schema-valid envelopes; kill/resume test passes.

## M5 — Flow: fanout

- N parallel worker calls (lens set from plan), one synthesizer call,
  gates, review ladder, targeted repair, resynthesis.
- Stop rule: fan-out width is a plan parameter in v0; the dryness stop
  rule (K consecutive distinct lenses with nothing new) implemented for
  the iterative variant, measured across distinct lenses.
- Parallelism via per-worker worktrees or read-only snapshots; workers
  never share a write target.

Acceptance: dry-run with 5 lenses produces 5 distinct composed prompts
(byte-stable across two runs), one synthesis input manifest, resumable
mid-fan-out.

## M6 — Program

- `plan` schema (from M1) + `program run plan.toml`: resolve, print,
  single approval checkpoint, parallel flow execution with disjoint
  write scopes enforced, signal stops, consolidated report,
  `program resume <run-id>`.
- Budgets (tokens, wall clock) enforced from telemetry.

Acceptance: dry-run of a 3-task plan (2 implement + 1 fanout) end to
end; scope-overlap plan is rejected at resolve time; resume test.

## M7 — Flows: adjudicate + assure (goal mode)

- `adjudicate`: two envelopes in, disputed claims enumerated, each must
  be probed (runner calls with adjudication lens), one resolution
  envelope out.
- `assure` goal mode: goal contract in, evidence-obligation gates +
  attainment review, verdict separating checked-vs-judged, mandatory
  oracle-strength non-claims.

Acceptance: fixture-driven dry-runs for both; goal-mode envelope
fixtures show the checked/judged separation.

## M8 — Flow: benchmark

- Planted-defect corpus tooling: defect manifest format (hidden answer
  key), corpus builder, scorer (reviewer recall/precision, lens yield).
- Corpus content per `test-charter.md` and `benchmark-domains.md`:
  Tier A archetypes from both domain families (BI/analytics and
  agent-engineering), defect classes 1–20.
- Matrix runner over {model, effort, worker count} reusing program
  infrastructure.
- Report: per-cell cost (new input/output tokens, wall clock) vs
  detection — the artifact that turns the repo's defaults (3–5 workers,
  ladder thresholds) into measurements.

Acceptance: dry-run matrix on a toy corpus; scorer unit tests against a
hand-computed answer key.

## Post-v0 (recorded, not scheduled)

- Second runner (cross-family) → activates ladder level 4.
- Goal-driven plan generation (ADR 0004, same checkpoint).
- Pre-push hook installer for the local content policy.
- Content-policy coverage of git metadata (author/committer identity, tag
  and branch names), which the file-content scan cannot see — see the
  known gap in ADR 0006.
- Lens library growth driven by benchmark lens-yield data.

Deviations from this roadmap are logged in [deviations.md](deviations.md).

## Post-v0 — M9: evolve

Search under judgment for deliverables with no oracle. Design in
ADR 0009; the flow ships in stages because a selection step that cannot be
trusted makes everything above it noise with confidence.

- **M9.1 — Tournament and rule inducer.** Blind pairwise duels against a
  ratified rubric; side-swapped panels; unanimity decides and a split panel
  keeps the incumbent; king-of-the-hill ranking; a human override is turned
  into a proposed rubric amendment, never applied. Acceptance: a dry run
  produces a schema-valid report with no model call; stubbed panels prove
  blindness, side-swap correction, and that 2-1 is a tie.
- **M9.2 — The loop.** Lens lineages plus fresh starts plus a reframe per
  round; keep-or-discard per lineage; grafts that must win their own blind
  duel; a director turning critique into the next round's lens set; archive
  of best-per-lineage; stop after two rounds without a new champion.
- **M9.3 — First live run on a real deliverable**, with a ratified rubric
  owned outside this repository. The judgment corpus it leaves behind —
  rubric amendments, lens library, tournament records — is the measured
  product; the deliverable is the by-product.
