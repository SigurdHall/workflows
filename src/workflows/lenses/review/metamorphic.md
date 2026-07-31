<!-- lens: review/metamorphic v1 -->

# Metamorphic

Attack perspective: pick a relation that must hold between a base
input/output pair and a deliberately related second pair, and check
whether it holds. This is the lens for when no single input has a known
correct answer to check against — the relation is the oracle.

## Targets

- Round-trip relations: encode then decode, serialize then parse, write
  then read, returning content equivalent to the original.
- Idempotence: applying an operation a second time to its own output
  does not change the result, wherever the contract implies a stable
  fixed point (for example, re-running an unchanged check).
- Split/combine relations: processing two parts separately and merging
  the results agrees with processing the combined whole in one pass.
- Monotonic or non-dropping relations: processing a superset of items
  does not silently drop or contradict results already established for
  a subset.
- Irrelevant-change invariance that is not pure reordering: a no-op
  change to an unrelated part of state, or a rename of a non-semantic
  field, does not change the target output.

## Method

1. Read the operation under test first, then identify or construct its
   natural counterpart: an inverse, a split, a superset, or a repeat.
2. Choose one metamorphic relation appropriate to the operation —
   round-trip, idempotence, split/combine, or monotonicity — and name it
   explicitly before probing. Do not probe first and rationalize a
   relation afterward.
3. Construct the paired probe: base input `x`, and the derived input(s)
   the relation requires — `decode(encode(x))`, `f(f(x))`,
   `f(a) + f(b)` against `f(a-combined-with-b)`, or `x` against a
   superset `x'`.
4. Run both sides through the same code path and compare according to
   the relation, not for exact output equality unless the relation
   demands it.
5. Record the relation chosen, both invocations, both outputs, and
   whether the relation held. No ground truth for `x` alone is required
   for this probe to be valid — that independence is the point of this
   lens.

## Does not cover

- Byte-identical stability of one input under pure reordering or
  numeric restatement — `review/determinism` covers that one specific
  relation; this lens covers relations other than reorder-equality.
- Whether extra or malformed fields are accepted at all —
  `review/closed-contract`.
- Single-input boundary or edge-value handling — `review/boundary-
  values`.
- Rejection and lifecycle correctness — `review/negative-path`.
- Whether the candidate weakened the check that would catch a broken
  relation — `review/scope-integrity`.

## Output obligations

- Every relation claim ("round-trip held", "idempotence failed") cites
  both concrete invocations and both outputs in `evidence_refs`.
- Stating that a relation "holds by construction" without running both
  sides is an assertion, not a finding, and must not be reported as one.
- The relation chosen is named explicitly in the record, not left
  implicit in the probe description.
- A `non_claims` entry for any relation considered but not probed.
