# 0009 — evolve: search under judgment

Status: accepted, 2026-08-01

## Context

Every flow in v0 is verification under gates: a contract states what must be
true, and the machinery checks whether a candidate made it true. That shape
requires an oracle. Creative and underspecified deliverables — report design,
data narrative, product surfaces — have none, and the operator's stated need
is incremental improvement *without their input* in exactly those domains.

The first benchmark matrix (2026-08-01) settled two things this design leans
on. Fan-out as redundancy bought nothing on convergent tasks: three workers
removed the same defects as one at 2.4× the cost, because N attempts at one
answer converge. And the binding constraint in practice is the operator's
judgment-minutes, not tokens — generation is cheap, comparison is scarce.

## Decision

A sixth flow, `evolve`: iterative search under an explicit, human-ratified
rubric, with the human at the boundary and never inside the loop.

- **Two tracks, not one.** Climbing lineages improve incrementally under a
  strict retention rule; fresh starts generate whole candidates blind to the
  incumbent; at least one reframe per round challenges the deliverable's form
  itself. Critique alone is closed — it can only point inward at the form
  that already exists.
- **Lineages, not one polished artifact.** Each lens continues its own line;
  lines compete rarely, in tournaments, so an approach that is worst for
  three rounds can still win when it is fully thought through.
- **Blind pairwise tournament.** Judges see a rubric and two candidates —
  no lineage, no authorship, no incumbency. The rubric is a precedence list:
  disqualifiers first, then the first criterion that separates decides.
  Unanimity decides; a split panel is a tie, and a tie keeps the incumbent.
  Preference without pointed evidence is rejected as taste.
- **Retention is the ratchet.** A challenger must beat the incumbent, not
  merely be argued for. Accepted gains become preserved criteria that later
  rounds must still satisfy — this is what makes the loop converge instead
  of circle. Merging happens only through grafts that win their own blind
  duel against the ungrafted winner.
- **The human ratifies meaning, and overrides become law.** One touchpoint
  before (ratify the rubric: what does better mean), one after (pick from
  champion plus best-per-lineage). When the owner overrides the machine's
  ranking, the system induces the rule that would have produced the owner's
  ranking and proposes it as a rubric amendment. A pick teaches one bit and
  evaporates; a ratified rule applies to every later comparison.
- **The judgment corpus is the product.** Rubric, lens library and
  tournament records accumulate across runs and transfer across projects.
  The deliverable is a by-product. This inverts the other flows, and it is
  deliberate: it is the only mechanism here that substitutes for domain
  expertise the operator does not have.
- **Stop on stability**: two rounds without a new champion, so easy tasks
  stay cheap and hard ones stay thorough without anyone deciding depth in
  advance.

## Consequences

- Ships in stages. M9.1 is the tournament and the rule inducer, dry-run
  tested; the loop (lineages, grafts, director, archive) is M9.2; the first
  live run on a real deliverable with a ratified rubric is M9.3.
- A new role, `judge`, joins the deployment profile. Judges run read-only:
  they compare, they never touch a worktree.
- Rubric *instances* live with the products they govern, never in this
  repository — a rubric names the product, and this repository is public.
  This repository carries the schemas and the machinery.
- Non-claims are structural: evolve finds the best of what was generated,
  not an optimum; and a rubric authored and judged by one model family caps
  the search at that family's prior. The human ratification step exists to
  break that cap, and no result should be read as if it did more.
