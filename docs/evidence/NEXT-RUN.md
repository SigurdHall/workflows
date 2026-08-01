# Ready to run: the first benchmark matrix

Everything below is set up and verified. This is the next session's starting
point, not a plan to be re-derived.

## What is already true

- A live `implement` flow reaches a PASS verdict end to end
  (`live-run-2026-08-01-percent-change.md`).
- A live `implement` flow runs end to end **over a corpus task through the
  benchmark CLI**, worker and reviewers included
  (`live-probe-2026-08-01-benchmark-cell.md`).
- `gpt-5.6-luna` at effort `max` and `gpt-5.6-sol` at `high` both drive the
  runner; the effort override demonstrably changes reasoning-output tokens.
- The corpus loads and materializes: 6 tasks, 12 planted defects, classes
  1, 2, 4, 6, 7, 8, 10, 11, 14, 17, 18, 20, both domain families.
- The matrix CLI takes `--profile`, `--task`, `--budget-tokens`,
  `--budget-seconds` and `--dangerously-bypass-sandbox`. The wiring the
  previous version of this file listed as missing is done.
- A live matrix refuses cells whose model is a role placeholder, before it
  materializes anything.

## Read this before spending anything

**A cell's per-class recall is not reviewer recall.** Over an `implement`
flow, a planted defect the worker *fixed* and a planted defect every reviewer
*missed* both score zero, and the number cannot tell them apart. A live probe
demonstrated the first case: the worker removed both planted defects in one
pass, correctly, and the cell scored 0/2.

So a matrix run today answers question 3 below (cost against fan-out width)
and gives an honest reading of *nothing else*. Questions 1 and 2 need the
scorer to know whether the defect was still present in the candidate it
scored. See the probe record for the shape of that fix — an executable probe
per planted defect — and treat it as the decision to make before, not after,
paying for a grid.

## Run it

```
# 1. a profile with your real model ids (copy, do not edit in place)
cp examples/profile.example.toml <work>/profile.toml

# 2. a matrix — start with two cells, not the four in the example, and
#    substitute real model ids for the role placeholders it ships with
cp examples/benchmark-matrix.example.toml <work>/matrix.toml

# 3. dry run first: proves the corpus materializes and every cell resolves
python -m workflows.benchmark run examples/corpus/tier-a/corpus.json \
    --matrix <work>/matrix.toml --work-root <work>/bench-dry --dry-run

# 4. the real thing, two tasks and a budget that can stop it
python -m workflows.benchmark run examples/corpus/tier-a/corpus.json \
    --matrix <work>/matrix.toml --work-root <work>/bench-1 \
    --profile <work>/profile.toml \
    --task measure-variance --task triage-router \
    --budget-tokens 1500000 --budget-seconds 3600
```

`--work-root` must be outside this repository. The corpus contracts use
`python` in their verification command; on a host where `python` is the
Windows Store alias, that fails closed as it should — put the real
interpreter's directory first on `PATH`, or regenerate the contracts with
`py`.

Budgets are **per cell, not per matrix**, and are checked between tasks
rather than mid-call. A two-cell matrix can spend twice `--budget-tokens`,
and a single runaway task is not interrupted by them.

## What to record afterwards

Write `benchmark-<date>-tier-a.md` beside the JSON report, and answer:

1. **Per-class recall.** Which of the planted classes escaped every
   reviewer? Read it only for defects that were still present — see the
   caveat above.
2. **Lens yield.** Which lens ids produced matched findings, and which
   produced none across every cell? A lens that never yields is a candidate
   for merging or retirement — telemetry decides, not intuition.
3. **Fan-out width against cost.** The cell with `worker_count = 3` versus
   `worker_count = 1`: how much more did it cost, and did it detect more?
   This repository asserts 3–5 workers; that number has never been measured.
   This is the question a matrix can answer honestly today.
4. **Unmatched findings.** Read a sample. An unmatched finding may be a real
   defect the corpus author did not plant — in which case the corpus is what
   needs fixing.

## Budget warning

One live cell over one corpus task cost roughly 85k–110k new input tokens and
took two to three minutes, for a task with two review lenses and no repair
round. Scale from that, not from the `percent-change` run: multiply by tasks,
then by cells. Start with two cells and two tasks before running the full
grid.
