<!-- lens: review/goal-attainment v1 -->

# Goal attainment

Attack perspective: assume the deliverables were declared sufficient
because the evidence-obligation gate came back green, and look for
the gap between "obligations met" and "goal achieved." A goal
contract's oracle is explicitly weaker than a task contract's (ADR
0007); this lens carries that weaker certainty honestly, subgoal by
subgoal.

## Targets

- A subgoal not actually met by the deliverables that exist, even
  though every named deliverable is present.
- Claims inside a deliverable that are unsourced, untraceable, or cite
  a reference that does not resolve to anything concrete.
- A deliverable that exists and passes its presence check but does
  not do what the subgoal needed it to do.
- The gap between obligations met (what a gate checked) and the goal
  achieved (what this lens judges).
- An attainment level asserted without naming, for every subgoal, the
  deliverable and location that supports it.

## Method

1. Read the goal and every subgoal first, before opening any
   deliverable — know what "achieved" means before hunting evidence.
2. Read the deliverables the evidence-obligation gate already
   confirmed exist and resolve; treat that as settled, not as a
   finding to re-assert.
3. Map each subgoal to the deliverable and location meant to support
   it. An unmapped subgoal is itself a finding, not a gap to fill in
   silently.
4. At each mapped location, judge whether the content supports the
   subgoal's statement — not whether an artifact merely exists.
5. Trace every number, claim, or figure presented as fact to its
   stated source. Untraceable claims are findings; traceable ones are
   evidence.
6. Grade the whole against the contract's own `attainment_rubric`,
   choosing one declared level id. Never invent a level, a
   percentage, or a score between two levels.
7. Record, per subgoal: met or not, the deliverable and location
   relied on, and whether that reliance was traced or assumed.

## Does not cover

- Whether a named deliverable exists, or a reference resolves — a gate
  checks that deterministically; re-asserting it here counts the same
  weak evidence twice.
- Whether a claim's payload is well-formed against a closed schema —
  `review/closed-contract`.
- Whether the candidate stayed inside a task contract's declared
  scope or left protected paths untouched — `review/scope-integrity`.
- Determinism or digest stability of any artifact — `review/determinism`.
- Boundary or edge-value handling inside a deliverable's own logic —
  `review/boundary-values`.
- Relations between separately produced outputs — `review/metamorphic`.
- Whether a declared-invalid state or transition is rejected —
  `review/negative-path`.
- Resolving a disagreement between two prior attainment judgments —
  `review/adjudication`.

## Output obligations

- Every attainment claim names the specific deliverable and location
  that supports it, in `evidence_refs`; naming no location makes it a
  non-claim, not a finding.
- Anything this lens could not trace to a source is stated as a
  non-claim, never assumed true because a gate found the artifact.
- The reported grade is one of the contract's own `attainment_rubric`
  level ids, verbatim — never an invented scale, a percentage, or an
  average of per-subgoal judgments.
- A `non_claims` entry for any subgoal this lens could not map, and
  for any evidence obligation left to the gate, not re-judged here.
