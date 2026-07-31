<!-- lens: review/negative-path v1 -->

# Negative path

Attack perspective: treat every rejection the candidate claims to
perform as unproven until it has been tried and watched fail. This is
the lens the "does not cover" sections of the other five point to for
rejection behavior, and the one where an unprobed claim is the failure
mode the whole repository was built around.

## Targets

- Lifecycle escape: a blocked, failed, or rejected state allowed to
  proceed anyway (class 5).
- Stale state: an older asynchronous or out-of-order result overwriting
  a result that arrived, or was applied, more recently (class 8).
- Reference integrity: a cross-reference to an identifier that was
  never created, or was created and then removed, used without
  validation (class 10).
- General rejection-path correctness: for every state, transition, or
  reference the contract declares invalid, confirm the executable path
  actually rejects it — not that documentation says it should.

## Method

1. Read the state machine, transition table, or validating function
   first, and enumerate every declared-invalid transition, state, or
   reference before touching the candidate's code.
2. For each declared-invalid transition, construct the exact call
   sequence that attempts it — for example, blocked to completed, or
   resume after stopped — and execute it against the real code path.
   Do not simulate it by reading the code and predicting the outcome.
3. For stale-state cases: construct two results for the same identity
   carrying different recency markers, apply the newer one first, then
   submit the older one, and record the system's final state.
4. For reference-integrity cases: construct a reference to an id that
   was never created, or was created then deleted, and run it through
   whatever consumes that reference; record whether it is caught or
   silently dereferenced.
5. Never accept "the code has a check for this" as a finding on its
   own. Execute the invalid case and record the actual outcome —
   exception raised, error status returned, non-zero exit.
6. Record, per probe: the invalid transition, reference, or stale write
   attempted, the code path exercised, and the actual outcome.

## Does not cover

- Whether a rejected value is itself a boundary or degenerate case
  (empty, maximum, off-by-one) — `review/boundary-values`; this lens
  assumes the value is otherwise well-formed and asks only whether an
  invalid transition, reference, or staleness is caught.
- Whether extra fields are accepted in an otherwise-valid payload —
  `review/closed-contract`.
- Whether the validator or test guarding a transition was itself
  weakened by the candidate — `review/scope-integrity`.
- Digest or order stability of accepted states — `review/determinism`.
- Relations between related valid inputs and outputs —
  `review/metamorphic`.

## Output obligations

- A claim that an invalid transition, stale write, or dangling
  reference "is rejected" requires a logged probe in `evidence_refs`
  that actually attempted it and observed the rejection.
- Asserting an unprobed rejection property is the exact reviewer
  failure mode this repository was built to catch: in the motivating
  experiment, a reviewer asserted exactly this kind of property,
  unprobed, on the one candidate where it was false.
- No negative-path PASS is reported without an executed probe backing
  every individual claim within it — a partial probe set yields a
  partial verdict, not a rounded-up one.
- A `non_claims` entry for any declared-invalid transition or reference
  this lens did not attempt.
