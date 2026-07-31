# Lens

A perspective a model works from. One versioned markdown file per lens,
injected verbatim into the prompt. Lenses exist so that parallel agents
are *complementary*, not ten copies of the same attempt.

## File structure

Every lens file has the same sections:

- **Name and version** — stable identity, so telemetry can attribute
  findings to lenses across runs.
- **Targets** — the defect or design classes this lens hunts.
- **Method** — how to work: what to read first, what to probe, what
  evidence to produce.
- **Does not cover** — the neighboring territory deliberately left to
  other lenses. This section is what prevents overlap.
- **Output obligations** — what the envelope must contain for this lens's
  claims to count.

## Two families

- `lenses/work/` — producer perspectives for implementation fan-out
  (e.g. spec-fidelity, minimal-change, API-design, defensive-input).
- `lenses/review/` — attack perspectives for reviewers (e.g. determinism,
  boundary-values, closed-contract, metamorphic, red-team).

The families share the file format and are never mixed in one call.

## Composition

The final prompt is composed deterministically by the driver:

```
contract + lens file + output schema + optional focus hint
```

The focus hint is one or two task-specific sentences chosen at planning
time and recorded in the plan. No model rewrites a lens at run time: the
same lens plus the same contract must produce a byte-identical prompt.
That is what makes lens yield measurable — which lens found which finding
— and prompts cacheable and diffable.

## Rules

- Lens sets are chosen per task at planning time; the choice is recorded
  in the plan and the run manifest.
- Fan-out stops when K consecutive *distinct* lenses return nothing new —
  dryness is measured across lenses, not across retries of one lens.
- A lens that never yields findings across many runs is a candidate for
  merging or retirement; telemetry decides, not intuition. In the
  motivating experiment, ten ad hoc lenses yielded three distinct
  findings because several converged on the same territory.

## Anti-patterns

- Lenses defined ad hoc inside a delegation prompt — unmeasurable and
  unrepeatable.
- An LLM "interpreter" that rewrites general lenses per task — you end up
  measuring the interpreter, and reproducibility dies in the glue.
- Overlapping lenses without "does not cover" boundaries.
