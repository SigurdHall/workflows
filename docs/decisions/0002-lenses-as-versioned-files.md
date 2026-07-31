# 0002 — Lenses are versioned files, composed deterministically

Status: accepted, 2026-07-31

## Context

In the motivating fan-out experiment, ten worker perspectives were
defined ad hoc inside one delegation prompt. They overlapped heavily
(three lenses converged on determinism/digest territory, three more on
adversarial-input territory) and yielded only three distinct findings.
Because the lenses had no stable identity, per-lens yield could not be
measured, and the run could not be reproduced.

Two alternatives were considered: fully static lens files, and an LLM
"input generator" that rewrites general lenses per task.

## Decision

A lens is a versioned markdown file with fixed sections (targets, method,
does-not-cover, output obligations), injected verbatim. The driver
composes prompts deterministically: contract + lens + output schema +
an optional one-to-two-sentence focus hint chosen at planning time and
recorded in the plan. No model rewrites lens content at run time.

## Consequences

- Same lens + same contract → byte-identical prompt: reproducible,
  diffable, cacheable.
- Lens yield (finding → lens) becomes measurable, so lens sets and
  worker counts can be tuned on evidence (ADR-relevant telemetry lives
  in the run, see `concepts/run.md`).
- Task specificity is bounded to the contract and the focus hint. If a
  task class is chronically under-served, the fix is authoring a new
  lens file — a reviewed, versioned change — not a runtime rewrite.
- Rejected: LLM input generator — it reintroduces nondeterminism and
  cost into the glue (ADR 0001) and makes you measure the interpreter
  instead of the lens.
