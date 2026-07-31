<!-- lens: work/minimal-change v1 -->

# Minimal change

Build the smallest diff that satisfies the contract. Every line that
changes must trace to a specific acceptance criterion; every line
that doesn't is a line this lens should have left alone.

## Targets

- Refactors bundled into a feature or fix without the contract asking
  for them.
- Renamed symbols, moved files, or reformatted blocks that widen the
  diff without changing behavior any criterion depends on.
- Shared code paths rewritten when a smaller, local change would have
  satisfied the same criteria.
- Protected or out-of-scope files touched because an unrelated fix
  was tempting while already there.

## Method

1. Read the contract's `scope` and `protected` lists first. Scope is
   the full set of paths this change may touch; protected paths stay
   byte-identical regardless of how good an unrelated fix looks.
2. Before writing anything, read the code around each likely change
   site and note its existing naming, formatting, and structure. That
   is the idiom this change must match, not improve on.
3. Identify the smallest set of lines or functions whose change is
   necessary for the acceptance criteria to hold. If a spec-fidelity
   decomposition already exists, use it as the checklist; if not,
   build the equivalent list before editing.
4. For each candidate edit, ask whether a criterion requires this
   specific line to change. If the answer is no, leave the line as it
   is, even if it looks improvable.
5. When a real improvement is spotted outside the required lines,
   record it as a deferred follow-up instead of folding it into this
   diff.
6. Prefer an additive change (a new branch, a new function) over
   rewriting a shared path, unless the contract specifically requires
   replacing the shared logic.
7. After implementing, diff the candidate against the base and check
   every changed line against the criterion or protected-file
   necessity that required it. Anything unaccounted for gets removed
   or gets an explicit justification.
8. Record diff size (files touched, lines added and removed) as
   evidence. A diff larger than its justification list is a finding
   against this lens's own work, not a detail to omit.

## Does not cover

- Whether the built behavior actually matches the contract — that is
  `work/spec-fidelity`; this lens only bounds how much code moves to
  get there.
- Handling of malformed or edge-case input — that is
  `work/defensive-input`; do not skip a required validation branch
  just because it would add lines.
- Naming and shape decisions for a genuinely new interface — that is
  `work/api-design`. Minimal-change governs how existing code is
  touched, not how a new surface is designed.

## Output obligations

- A diff-size summary (files touched, lines added and removed).
- A per-file, and where useful per-line, justification tracing each
  change back to a criterion or a protected-file constraint.
- A list of noticed-but-deferred improvements, kept out of this diff
  and recorded as follow-up notes, not as `findings` against the
  contract.
- Confirmation that no file outside `scope` was touched and that
  every file in `protected` is unchanged, byte for byte.
