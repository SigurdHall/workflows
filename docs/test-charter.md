# Test charter

The required floor of test cases per milestone. The implementer writes
these plus their own; the charter exists so the implementer is not the
sole author of their own oracle. Every case below is mandatory before a
milestone counts as done; most are derived from failures actually
observed in the motivating experiments — they are regression tests
against reality, not hypotheticals.

Principle: **failure paths are the product.** A gate or validator whose
happy path works but whose failure path is untested is untested.

## M1 — Contract and envelope fixtures

Each schema needs valid fixtures *and* these invalid ones, each failing
for exactly the annotated reason:

- Envelope without `non_claims` (or with an empty list).
- Digest missing the `sha256:` prefix, and digest with wrong hex length —
  both occurred as real hand-written envelope errors.
- An unknown extra field (must be rejected: closed contracts).
- `status` / severity / result values outside the enums.
- Missing `schema_version`, and a `schema_version` that is not the const.
- A verdict claiming PASS while carrying an open CRITICAL/HIGH finding —
  rejected by a semantic check (schema alone cannot express this; the
  check lives with the validator and must be tested here).

## M2 — Gates

Every gate is tested on failure first. Mandatory cases:

- **scope**: one modified file outside allowed paths; one *added* file
  outside scope; a rename crossing the scope boundary.
- **protected_hash**: a single-byte change to a protected file; a
  whitespace-only change; a deleted protected file. All three fail —
  a protected-test modification survived synthesis and all functional
  checks in the motivating experiment and was the costliest finding.
- **base_identity**: wrong parent commit; dirty worktree; unknown base.
- **verification_command**: nonzero exit fails; a *missing interpreter or
  command* (the Windows Store alias class of failure) fails closed with
  a distinct reason — it must never be reported as skipped or green, and
  any fallback interpreter must be explicit configuration, never silent.
- **schema gate**: the real envelope failures from M1's invalid fixtures,
  fed through the gate runner end to end.

## M3 — Runner

- Composition determinism: same contract + lens + focus hint composed
  twice → byte-identical prompt (this property is what makes lens yield
  measurable; test it, do not assume it).
- Output failing the output schema → exactly one bounded retry carrying
  the validation error → FAILED envelope. Never a silent pass, never an
  unbounded retry loop.
- Timeout produces a FAILED envelope with telemetry, not a hang.
- Telemetry double-count regression: cumulative vs per-call token
  figures must not be summed together (a real aggregation trap in the
  source telemetry this repo's design was measured with).
- Dry-run makes zero network/process calls to the provider (assert via
  injected fake).

## M4/M5 — Flows

- Repair provenance: after a failed candidate that (in the fixture)
  touched a protected file, the repaired candidate is rebuilt from the
  *original* base — the illegal change must be absent, not reverted on
  top. Verify by hash against the base, not by reading the diff.
- Reviewer blindness: the composed review prompt contains the candidate
  and contract but no worker/synthesizer dialogue (string-level assert
  on the composed prompt).
- Negative-path probe rule: a review envelope asserting a negative-path
  property ("invalid transitions are rejected") without a matching
  probe in `evidence_refs` is rejected. This encodes the observed
  reviewer failure mode of asserting unprobed safety properties.
- Fan-out dryness is measured across *distinct* lens ids: a run where
  the same lens returns empty twice does not count as two dry rounds.
- Kill/resume: killing after worker k of n and resuming re-runs nothing
  before k (assert via call-recording fake runner).

## M6 — Program

- Two tasks with overlapping write scopes → rejected at plan resolve,
  before the checkpoint.
- Resume after kill re-runs no completed flow.
- Token/wall-clock budget breach → clean stop with a BLOCKED envelope
  and consolidated report, not a crash.
- The single checkpoint fires exactly once per program (not per task).

## M8 — Benchmark corpus: the planted-defect taxonomy

The corpus must plant defects from this validated taxonomy — every class
below escaped green public tests and at least one blind max-effort
review in the motivating experiments:

1. Type conflation — boolean/integer equality treated as equivalence.
2. Order-dependent canonicalization — digest/identity changes under pure
   reordering of the same set.
3. Vacuous success — empty expected/candidate inputs pass trivially.
4. Open contract — unknown fields accepted where the contract is closed.
5. Lifecycle escape — progression allowed after a blocked/failed state.
6. Blank identity — whitespace-only or empty identifiers accepted.
7. Degenerate input — header-only/empty-body files accepted.
8. Stale state — an older async result overwriting a newer one.
9. Numeric canonicalization — equal values (0 vs 0.0) hashing or
   comparing as different without a finding.
10. Reference integrity — dangling cross-references not validated.

Requirements: each planted defect has a hidden answer-key entry
(class, location, severity, triggering probe); the scorer reports
reviewer recall/precision *per class* and lens yield per lens id; scorer
unit tests run against a hand-computed key. Corpus tasks are synthetic
and generic — never derived from real project content.

## Meta-rule: who reviews the repo's own work

This repository must eat its own principles: milestone commits get an
independent review pass (a second model or a human), and once `assure`
is usable it reviews this repo's own subsequent milestones. Green unit
tests are a gate, not a verdict — that distinction is the founding
observation of the whole design.
