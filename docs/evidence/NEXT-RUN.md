# Ready to run: the first benchmark matrix

Everything below is set up and verified. This is the next session's starting
point, not a plan to be re-derived.

## What is already true

- A live `implement` flow reaches a PASS verdict end to end
  (`live-run-2026-08-01-percent-change.md`).
- `gpt-5.6-luna` at effort `max` and `gpt-5.6-sol` at `high` both drive the
  runner; the effort override demonstrably changes reasoning-output tokens.
- The corpus loads and materializes: 6 tasks, 12 planted defects, classes
  1, 2, 4, 6, 7, 8, 10, 11, 14, 17, 18, 20, both domain families.
- The matrix runner works on a dry run and scores every cell.

## Run it

```
# 1. a profile with your real model ids (copy, do not edit in place)
cp examples/profile.example.toml <work>/profile.toml

# 2. a matrix — start with two cells, not the four in the example
cp examples/benchmark-matrix.example.toml <work>/matrix.toml

# 3. dry run first: proves the corpus materializes and every cell resolves
python -m workflows.benchmark run examples/corpus/tier-a/corpus.json \
    --matrix <work>/matrix.toml --work-root <work>/bench-dry --dry-run

# 4. the real thing
python -m workflows.benchmark run examples/corpus/tier-a/corpus.json \
    --matrix <work>/matrix.toml --work-root <work>/bench-1
```

`--work-root` must be outside this repository. The corpus contracts use
`python` in their verification command; on a host where `python` is the
Windows Store alias, that fails closed as it should — either fix the PATH or
regenerate the contracts with `py`.

The matrix runner does not yet take `--profile` or the sandbox bypass on the
command line; both are constructor arguments today. Wiring them through is the
first small change the real run will demand.

## What to record afterwards

Write `benchmark-<date>-tier-a.md` beside the JSON report, and answer:

1. **Per-class recall.** Which of the twelve planted classes escaped every
   reviewer? Those are the classes the lens set does not cover, and the
   evidence-driven trigger for authoring a new lens (ADR 0002).
2. **Lens yield.** Which lens ids produced matched findings, and which
   produced none across every cell? A lens that never yields is a candidate
   for merging or retirement — telemetry decides, not intuition.
3. **Fan-out width against cost.** The cell with `worker_count = 3` versus
   `worker_count = 1`: how much more did it cost, and did it detect more?
   This repository asserts 3–5 workers; that number has never been measured.
4. **Unmatched findings.** Read a sample. An unmatched finding may be a real
   defect the corpus author did not plant — in which case the corpus is what
   needs fixing.

## Budget warning

Twelve defects across six tasks, times the number of cells. The first live
`implement` run cost roughly 345k new input and 14k output tokens for a
two-line change with two review lenses. Scale that before starting: a
four-cell matrix over six tasks is a different order of spend, and the
matrix has no budget stop of its own — only the program level does, per cell.

Start with two cells and two tasks (`--matrix` with two entries; trim the
corpus by copying it and deleting tasks) before running the full grid.
