<!-- lens: review/closed-contract v1 -->

# Closed contract

Attack perspective: assume the candidate's schema or contract claims to
be closed, and try to get something past it that should not fit. Then
check the claim itself — a schema that reads closed in prose and a
validator that does not enforce it are two different facts, and only
one of them is checked by reading.

## Targets

- Undeclared or extra fields accepted where the schema claims a closed
  shape (class 4: open contract).
- A contract documented as closed ("extra fields rejected", "closed
  schema") whose actual validating code path does not enforce it.
- Schema-versus-behavior drift: a field typed, required, or
  enum-constrained on paper that the executable path enforces
  partially, differently, or not at all.
- Blank identity accepted: whitespace-only or empty strings passing an
  identifier field (class 6).
- Structurally-present but semantically empty payloads that satisfy a
  presence check without carrying real content (class 7, the
  contract-shape half — see "Does not cover" for the boundary half).

## Method

1. Read the schema or type definition first — the canonical closed-shape
   declaration — then find the function that actually validates against
   it. A contract has one written definition but sometimes several
   candidate enforcement points; identify which one really runs.
2. Build probes from one baseline valid payload:
   - baseline plus one undeclared field,
   - baseline with a field renamed to a plausible synonym or wrong case,
   - baseline with an enum-typed field set outside its declared values,
   - baseline with a version field set to an unexpected value,
   - a required identifier field set to an empty or whitespace-only
     string.
3. Execute each probe against the live validator, not a manual reading
   of the schema text. Record accepted or rejected, and the exact
   rejection reason when there is one.
4. Compare the contract's written closedness claim against the probe
   results. A mismatch in either direction is a finding: fields the
   prose says are rejected but the code accepts, or fields the code
   rejects that the prose never declared invalid.

## Does not cover

- Extreme or edge scalar values inside an already-accepted field
  (empty, zero, maximum, unicode) — `review/boundary-values` owns
  behavior at the edges of an accepted shape; this lens only asks
  whether the shape itself is closed.
- Identity, digest, and ordering stability — `review/determinism`.
- Relations between separately computed outputs — `review/metamorphic`.
- Whether a rejected payload can re-enter through a different
  transition later — `review/negative-path`.
- Whether the candidate altered its own tests or validators —
  `review/scope-integrity`.

## Output obligations

- Every accepted/rejected claim references the executed probe (payload
  and observed result) in `evidence_refs`.
- A claim that a contract "is closed" requires at least one executed
  undeclared-field probe against the live validator; the schema text
  alone is not evidence, since the failure mode this lens targets is
  exactly a schema that reads closed while its validator is not.
- Any mismatch between the contract's prose and the probed behavior is
  reported as a finding, not silently reconciled in the write-up.
- A `non_claims` entry for any declared field this lens did not probe.
