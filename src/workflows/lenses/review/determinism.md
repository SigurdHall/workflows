<!-- lens: review/determinism v1 -->

# Determinism

Attack perspective: assume identity, digests, and ordering are stable
by construction, and try to break that assumption with paired probes —
the same logical content presented two different ways, run through the
same code and compared.

## Targets

- Order-dependent canonicalization: reordering members of the same set
  or list changes a digest, identity, or comparison result that is
  supposed to be order-independent (class 2).
- Numeric canonicalization gaps: values that are semantically equal
  (`0` vs `0.0`, `1` vs `1.00`, `-0` vs `0`) hash or compare unequal, or
  genuinely different values collapse to equal without a finding
  (class 9).
- Non-reproducible output on byte-identical input: repeated runs of the
  same computation produce different digests or identities.
- Digest format drift: an output that does not match the contract's
  declared digest format, for example a missing `sha256:` prefix or the
  wrong hex length.

## Method

1. Read the digest, identity, or canonicalization function itself
   first, not a caller. The target is the function that is supposed to
   produce a stable value, not the code that happens to invoke it.
2. Construct a reorder probe: a baseline input, and a second input with
   the same logical members in a different order (reordered mapping
   keys, reordered list of independent items, reordered set members).
   Run both through the function and compare outputs.
3. Construct a numeric-form probe: a baseline input, and a second input
   using an alternate literal form of an equal value. Run both and
   compare.
4. Run the function twice on byte-identical input to rule out incidental
   nondeterminism — wall clock, random identifiers, or unstable
   iteration order leaking into a supposedly canonical output.
5. If the contract declares a digest format, check the actual output
   string against that format, not just against another computed
   digest.
6. Record, per probe: the two inputs, the function invoked, both
   outputs, equal or not-equal, and what the contract requires.

## Does not cover

- Whether extra or undeclared fields are accepted — `review/closed-
  contract`.
- Whether an empty, maximal, or malformed value is handled at all —
  `review/boundary-values`.
- Relations between separately computed, non-reordered outputs such as
  round-trip or idempotence — `review/metamorphic`; this lens covers
  only stability of one computation under reordering or numeric
  restatement of the same value, not relations between different
  computations.
- Lifecycle or transition legality — `review/negative-path`.

## Output obligations

- Every equal/not-equal claim cites the two concrete probe inputs and
  both observed outputs in `evidence_refs`.
- A claim that reordering "does not affect" the result requires an
  executed reorder probe with both outputs recorded — not a reading of
  the code that looks order-independent.
- A claim that two numerically-equal representations hash or compare
  equal requires the executed numeric-form probe, not an inference from
  the type system.
- A `non_claims` entry for any identity or digest path this lens did
  not exercise.
