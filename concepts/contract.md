# Contract

What must be done, stated precisely enough that a gate can check it and a
model cannot misread it.

## Two types

**Task contract** — for work with a deterministic oracle (code, config,
documents with checkable structure):

- `goal`: one paragraph of intent — the *why* that survives edge cases.
- `scope`: paths the worker may change. Everything else is read-only.
- `protected`: paths that must remain byte-identical (tests, evaluators,
  specs). Enforced by hash gates, never by trust.
- `acceptance`: criteria a reviewer maps evidence to.
- `verification`: the exact command whose exit code is the primary oracle.

**Goal contract** — for outcome-level work without a deterministic oracle:

- `goal` and `subgoals`: the intended outcome, decomposed.
- `evidence_requirements`: what must exist and be traceable for the goal
  to count as achieved (deliverables present, claims sourced, numbers
  reproducible).
- `attainment_rubric`: how a reviewer grades goal attainment.

## Rules

- One contract per task. A program is a plan of many contracts.
- A contract is frozen at run start; changing it mid-run is a new run.
- Goal contracts have weaker oracles than task contracts. This must never
  be papered over: flows driven by goal contracts escalate review earlier
  and hit human checkpoints more often, and their envelopes must say what
  was *checked as evidence* versus what was *judged*.

## Anti-patterns

- Vague scope ("improve the parser") — gates cannot check intent.
- Protected files listed nowhere, protected by prompt text only. A prompt
  instruction is not a gate.
- Acceptance criteria that restate the goal instead of decomposing it.
