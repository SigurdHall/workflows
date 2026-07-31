<!-- lens: review/adjudication v1 -->

# Adjudication

Attack perspective: two envelopes reached different conclusions about
the same candidate, and neither conclusion is authority by itself.
Treat the disagreement as the object under test — not which reviewer
argued better, but which disputed claim has actually been probed.
This is the level-3 lens: it runs only when a conflict reaches it,
never as a routine second opinion.

## Targets

- Claims one envelope asserts and the other denies about the same
  candidate.
- Claims both envelopes agree on but that neither backed with an
  executed probe — agreement between two reviewers is not evidence.
- Severity disagreements: the same finding rated differently by the
  two envelopes.
- A disputed claim that no available probe can settle, which must be
  reported UNRESOLVED rather than decided by preference.

## Method

1. Read both envelopes in full before touching the candidate. Do not
   read one first and treat it as the baseline the other must beat.
2. Enumerate every disputed claim as its own item, stripped of which
   envelope made it — authorship invites deciding by reputation, and
   that is exactly what this lens exists to prevent.
3. For each disputed claim, construct the smallest probe that would
   distinguish UPHELD from REJECTED, before considering which side it
   favors.
4. Run the probe against the actual candidate, never against either
   envelope's description of it, and record the outcome.
5. For claims where both envelopes agree but neither cites a probe,
   run one anyway before accepting the claim — unanimous but unprobed
   is still unprobed.
6. If no probe can be constructed that would distinguish the two
   positions, resolve the claim UNRESOLVED and record why no probe
   applies, rather than picking a side.
7. Record, per claim: the two original positions, the probe run (or
   why none could settle it), and the resolution reached.

## Does not cover

- Whether a claim's payload is well-formed against a closed schema —
  `review/closed-contract`.
- Determinism, ordering, or digest stability of the candidate itself —
  `review/determinism`.
- Boundary or edge-value correctness of the candidate — `review/
  boundary-values`.
- Relations between separately computed outputs — `review/metamorphic`.
- Whether either original review respected declared scope or left
  protected paths untouched — `review/scope-integrity`.
- Whether a declared-invalid transition is actually rejected —
  `review/negative-path`, unless that rejection is itself the disputed
  claim, in which case the probe is still run here, not assumed from
  either envelope's say-so.
- Whether an outcome-level goal, as opposed to a candidate, was
  attained — `review/goal-attainment`.

## Output obligations

- Every resolution cites the probe that settled it in `evidence_refs`;
  a rationale that only compares how persuasively the two envelopes
  were argued is not a resolution.
- "The other reviewer was more thorough" or "the second review is
  more recent" is never cited as deciding evidence.
- UNRESOLVED is a permitted verdict, and required whenever no
  constructed probe distinguishes the two positions — reporting a
  decision anyway, to close the ladder, is the exact failure mode
  this lens exists to catch.
- A `non_claims` entry for any disputed claim this lens did not probe.
