<!-- lens: review/boundary-values v1 -->

# Boundary values

Attack perspective: assume the candidate handles the middle of the
input space correctly, and go straight for the edges — empty, zero,
one, maximum, off-by-one, unicode, very large, and malformed-but-
plausible input.

## Targets

- Vacuous success: an empty expected or candidate input passes
  verification trivially, because there was nothing to disagree with
  (class 3).
- Degenerate input accepted: header-only or empty-body payloads that
  satisfy structural checks without carrying content (class 7, the
  boundary half — see "Does not cover" for the contract-shape half).
- Off-by-one handling at declared limits: the exact maximum length,
  count, or index mishandled at the boundary or one past it.
- Encoding edges: multi-byte and combining unicode, right-to-left text,
  very long strings, very large or very small numeric magnitudes.
- Malformed-but-structurally-plausible input: stray whitespace, mixed
  line endings, a truncated final record.

## Method

1. Read the input validation or parsing entry point first — the code
   that touches raw input before any downstream logic runs.
2. Build a boundary matrix per parameter or field: zero-element
   collection, single-element collection, declared maximum, maximum
   plus one, a negative value where unsigned is expected, a unicode
   string, a very long string.
3. Run every boundary probe through the real validation-and-processing
   path, not a stub or a mental simulation. Record accepted or
   rejected, and any output produced.
4. Test zero-element and single-element collections as two separate
   probes. Do not conflate "empty" with "singleton" — that conflation
   is exactly how a vacuous success hides.
5. For any declared maximum, test at the maximum and at maximum-plus-
   one in the same pass, to catch off-by-one errors in one comparison.
6. Run one malformed-but-plausible probe — stray whitespace, a wrong
   line ending, a truncated trailing record — and record whether it is
   rejected or silently accepted.
7. Record, per probe: parameter, boundary case, input, actual result,
   and pass/fail against the contract's stated bound.

## Does not cover

- Whether undeclared fields or extra structure are accepted —
  `review/closed-contract`.
- Numeric-value equality or canonicalization for hashing or comparison
  purposes — `review/determinism`.
- Whether a rejection at a boundary can be bypassed by a different
  transition later — `review/negative-path`.
- Cross-input relations, such as an output that should scale with an
  input — `review/metamorphic`.

## Output obligations

- Every accept/reject claim at a boundary cites the exact probe value
  used and the observed result in `evidence_refs`.
- A claim that "empty input is rejected" requires a logged probe that
  actually ran an empty input; inferring rejection from a length check
  read in source is not sufficient.
- Zero-element and single-element results are reported separately, even
  when they agree, so the distinction is visible in the record.
- A `non_claims` entry for any parameter this lens did not probe at its
  boundary.
