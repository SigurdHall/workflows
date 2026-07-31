<!-- lens: work/spec-fidelity v1 -->

# Spec fidelity

Build exactly what the contract specifies. The goal is not "working
code" in the abstract; it is a candidate whose behavior is traceable,
criterion by criterion, back to the contract's acceptance list.

## Targets

- Acceptance criteria implemented partially, or swapped for a nearby
  criterion that happened to be easier to write.
- Ambiguity in the contract resolved silently, by picking whichever
  reading was easiest to code, instead of being surfaced as a
  decision.
- Behavior added that no criterion asked for, on the assumption it is
  obviously implied.
- Criteria that are internally contradictory or unverifiable as
  written, passed over instead of flagged.

## Method

1. Read the contract's `goal` and `acceptance` list before reading
   any existing code. The goal is the intent that must survive edge
   cases; the acceptance list is what a reviewer checks line by line.
2. Decompose each acceptance criterion into the smallest independently
   checkable sub-claims it implies. A criterion like "rejects invalid
   input" is not one claim; it is one claim per input class the
   contract or domain makes relevant.
3. For every sub-claim, locate the code path that will make it true.
   If none exists yet, that is the unit of work; if one already
   exists, verify it actually covers the sub-claim rather than
   assuming it does.
4. Where the contract underspecifies a case, do not pick silently.
   Write down the candidate readings, choose one, and record the
   decision and its reason before implementing against it.
5. Implement only what a sub-claim or a recorded decision requires.
   Anything else belongs in a follow-up note, not in this change.
6. After implementing, re-check each sub-claim against the built
   behavior and record PASS, FAIL, or NOT_RUN per criterion — not a
   single aggregate judgment for the whole contract.
7. If a criterion cannot be satisfied as written (it contradicts
   another criterion, or nothing could verify it), stop and report
   that instead of quietly reinterpreting it into something buildable.

## Does not cover

- How small the resulting diff is, or whether existing structure and
  idiom are preserved — that is `work/minimal-change`.
- How the implementation behaves on malformed, empty, or hostile
  input — that is `work/defensive-input`; this lens only asks whether
  the *specified* behavior was built, not whether unspecified inputs
  are handled safely.
- The shape of any new interface (naming, error surface, what is easy
  to misuse) — that is `work/api-design`.

## Output obligations

- A criterion-to-sub-claim decomposition, with a result recorded per
  sub-claim, not only per top-level criterion.
- A decision log entry for every ambiguity encountered: the readings
  considered, the one chosen, and why.
- `evidence_refs` pointing at the code or check that makes each
  sub-claim true.
- A `non_claims` entry for any criterion whose verification is
  outside what this step could check (for example, deferred to
  integration).
- Any criterion flagged as contradictory or unverifiable, reported as
  a finding rather than silently resolved.
