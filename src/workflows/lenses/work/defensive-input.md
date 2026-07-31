<!-- lens: work/defensive-input v1 -->

# Defensive input

Build for the input that was not in the happy-path example. This
lens treats malformed, empty, degenerate, and hostile input as
first-class cases to design for, not exceptions patched after a bug
report.

## Targets

Cases drawn from the project's defect taxonomy, applied at design
time instead of discovered at review time:

- Blank identity — whitespace-only or empty identifiers accepted as
  valid.
- Degenerate input — header-only, empty-body, or zero-length payloads
  accepted as if they were complete.
- Vacuous success — an empty or trivial input passes verification
  without exercising any real logic.
- Type conflation — boolean, integer, and string forms of the same
  value treated as interchangeable where they are not.
- Numeric and order canonicalization — values that are equal but
  differently represented (0 vs 0.0, a reordered set) producing
  different results or different identities.

## Method

1. Read the contract's acceptance criteria and note every input the
   implementation will receive: its declared type, its implied
   invariants (non-empty, unique, ordered), and where it crosses a
   trust boundary.
2. Before writing the happy path, enumerate the degenerate and
   hostile variant of each input: empty, whitespace-only, wrong type,
   duplicate, boundary-length, differently-encoded-but-equal.
3. For every enumerated case, decide explicitly whether it is
   rejected, normalized, or accepted, and write that decision down
   before implementing it — not after something downstream breaks.
4. Implement validation at the boundary. A malformed identifier
   should fail before it reaches business logic, not three calls
   deep.
5. Write a failing-path check for each enumerated case alongside the
   happy-path implementation. A validation branch with no case that
   exercises it is unverified, not implemented.
6. Check specifically for vacuous success: run the empty or
   degenerate case through and confirm it fails or is explicitly
   rejected, rather than trivially reporting success because there
   was nothing to disagree with.
7. Check numeric and order canonicalization directly: assert that
   equal-but-differently-represented inputs produce the same result,
   and that reordering alone does not change an identity or digest.

## Does not cover

- Whether the happy-path behavior matches what the contract asked
  for — that is `work/spec-fidelity`.
- How large the resulting diff is — that is `work/minimal-change`;
  do not trim a required validation branch to save lines.
- The external shape of error surfaces (what type a caller catches,
  what a schema rejects) — that is `work/api-design`. This lens
  decides what happens internally when input is bad; api-design
  decides how that is exposed to a caller.

## Output obligations

- The enumerated list of degenerate and hostile cases considered,
  with the decision (reject, normalize, or accept) recorded for
  each.
- A failing-path check or probe for each case, referenced in
  `evidence_refs` — an enumerated case with no check is an
  assertion, not a finding.
- A `non_claims` entry naming any input class deliberately left
  unhandled, and why.
- Any case that could not be defended against, reported as a finding
  rather than shipped silently.
