# 0007 — Two contract types: task and goal

Status: accepted, 2026-07-31

## Context

Most flows operate on code-shaped work with a deterministic oracle:
tests pass or fail, scope matches or does not, hashes are identical or
not. But the same orchestration pattern — contracts, gates, lenses,
review, envelopes — is wanted for outcome-level questions: "was this
goal achieved?", where no hash can answer.

## Decision

Contracts come in two types with one shared envelope language:

- **Task contract** — deterministic oracle: scope, protected files,
  verification command. The default for all producing flows.
- **Goal contract** — goal, subgoals, evidence requirements, attainment
  rubric. Consumed by `assure` in goal mode, and later by goal-driven
  program planning (ADR 0004).

Goal contracts are explicitly second-class on certainty: their gates
check evidence obligations (deliverables exist, references resolve,
numbers trace), which is weaker than hashes. Flows driven by goal
contracts therefore escalate review earlier and hit human checkpoints
more often, and their envelopes must separate *checked as evidence*
from *judged by a model*.

## Consequences

- One orchestration system covers both "build this correctly" and "did
  we achieve this", without pretending they have equal oracles.
- Goal-mode verdicts carry mandatory non-claims about oracle strength.
- The attainment rubric is defined per goal contract, not globally —
  scoring stays out of core schemas (see `concepts/envelope.md`).
