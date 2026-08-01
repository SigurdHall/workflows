# Benchmark, 2026-08-01 — Tier A, three flows

The first matrix this repository has run against a live model. It replaces
four assertions with measurements, contradicts one of them, and leaves the
rest standing — which is worth saying first, because most of what this
repository asserts is still asserted.

## What was run

| | |
|---|---|
| Corpus | `examples/corpus/tier-a/corpus.json`, `tier-a-v0`, 12 planted defects |
| Model | `gpt-5.6-luna`, effort `max`, every role |
| Runner | Codex CLI, `--dangerously-bypass-sandbox` (see the run record for why) |
| Ladder | level 1 two lenses (`scope-integrity`, `closed-contract`), level 2 on HIGH |
| Repair | none — generated benchmark plans set `max_repair_rounds: 0` |

**Run A** — three flows over `measure-variance` (bi-analytics) and
`triage-router` (agent-engineering). **Run B** — `assure` over the remaining
four tasks, finishing per-class recall across all twelve planted defects.

## Run A: three flows, two tasks, four planted defects

| Cell | Recall | Present | Removed | New input | Output | Wall clock |
|---|---|---|---|---|---|---|
| `assure` w1 | **4/4** | 4 | 0 | 1 646 354 | 101 452 | 33 min |
| `implement` w1 | **0/1** | 1 | 3 | 1 439 554 | 59 287 | 20 min |
| `fanout` w3 | **0/1** | 1 | 3 | 3 399 049 | 149 514 | 35 min |

Read the three columns together or not at all. `implement` and `fanout` score
0/1 not because reviewers failed three times, but because the workers removed
three of the four defects before any reviewer saw them. Under the old
matched-over-planted arithmetic all three cells would have read 0/4, 0/4 and
0/4, and the table would have said nothing.

### Fan-out of three bought nothing over one

Same two tasks, same model, same lens set. Fan-out removed the same three
defects, missed the same one, and cost **2.4× the new input** of a single
worker. On `measure-variance` both flows removed both defects; on
`triage-router` both removed class 4 and both left class 17.

This repository asserts three to five workers. This is the first measurement
against that default, and it is a contradiction — over **two tasks**, which is
a signal, not a verdict. What it does establish is that the assertion was
never free: the cost side is now measured, and it is roughly double.

### The headline finding: a false PASS on a criterion that named the defect

`triage-router`'s contract carries **AC-3: "A keyword rule does not match
phrasing that belongs to a different category."** That is class 17, verbatim.

Both producing cells marked **AC-3 PASS** while the defect was live in the
candidate they passed. Six model calls across the two flows — two level-1
reviewers each, plus fan-out's synthesis and its escalations — and every one
agreed. The presence probe disagrees, and the probe is discrimination-tested:
it reports ABSENT against a corrected variant and PRESENT here.

The same defect, the same lens set and the same model was caught in the
`assure` cell by all three reviewers.

The cause is in the review prompt (`src/workflows/prompts.py`). A review
prompt is assembled from the contract, **the diff**, the lens and the output
schema. The reviewer is handed the acceptance criteria and the worker's diff —
not the code those criteria are about. It runs in the worktree and *could*
read the file, but nothing directs it there. In an `assure` cell the diff
introduces the defect, so the answer is on screen; in a producing flow class
17 sat in code the worker never touched, outside the diff, and no reviewer
went looking.

**The ladder verifies the diff while the verdict claims it verified the
contract.** That is a defect in this repository, not a property of review, and
it is the most consequential thing this matrix found: a bounded, mechanically
detectable violation of a named criterion produced PASS twice.

It is not fixed in this run's code. Recorded here rather than patched in
silence, because the numbers above were produced by the code as it stands.

### Cost per call, by flow

| Flow | Calls per task | New input per task |
|---|---|---|
| `assure` | 3–4 (level 2 escalated on both tasks) | ~820k |
| `implement` | 3 | ~720k |
| `fanout` w3 | 6–8 (3 workers, synthesis, up to level 3) | ~1.7M |

## Run B: `assure` over the other four tasks

| Cell | Recall | Present | New input | Output | Wall clock |
|---|---|---|---|---|---|
| `assure` w1, four tasks | **8/8** | 8 | 2 802 382 | 179 427 | 60 min |

Combined with run A, `assure` scored **12/12 across all twelve planted
defects** — every class in the corpus, both domain families, both tiers of
difficulty the corpus has.

The claims are specific, not path-matching luck. Spot-checked across tasks,
reviewers named the mechanism: *"apply_snapshot overwrites the stored newer
snapshot when an older as_of date is applied"*, *"digest produces different
values for the same set of rows when the input row order is reversed"*,
*"build_dimension emits a dimension member with customer_id ' '"*. Those are
the planted defects, described as their authors described them.

Both heuristic probes (`instruction-set`, classes 18 and 20) reported PRESENT
and the reviewers caught both. That is one data point for prose defects, from
probes that are heuristics by construction — read it with the `probe_caveat`
in the manifest beside it.

### Lens yield, and an accidental before-and-after

| Run | Lens | Findings | Matched |
|---|---|---|---|
| B (after the fix) | `review/scope-integrity` | 12 | 12 |
| B (after the fix) | `review/closed-contract` | 10 | 10 |
| A (before the fix) | `review/scope-integrity` | 6 | 6 |
| A (before the fix) | `review/scope-integrity-v1` | 2 | 2 |
| A (before the fix) | `review/closed-contract` | 2 | 2 |
| A (before the fix) | `review/closed-contract-v1` | 2 | 2 |
| A (before the fix) | `review-closed-contract-v1` | 1 | 1 |

Run A and run B are separate processes; the lens-attribution fix landed
between them. Run A shows one lens reported as three, run B shows two lenses
reported as two. The corruption and its repair are both visible in live data,
which is a better test than the unit test that now guards it.

**Both lenses yield.** Neither is a candidate for retirement on this evidence:
`scope-integrity` produced more findings, `closed-contract` produced findings
on every task it ran. No lens produced zero.

### "Zero unmatched" is an artifact, not a fact

Both runs report `unmatched_findings: 0`, and that number should not be
believed. Matching is by file path, and on `field-extraction` the reviewers
raised two findings that describe defects the corpus does not plant:

- an undeclared field is accepted and silently discarded;
- `age=True` passes the int check, because `isinstance(True, int)` is true in
  Python.

Both point at `field-extraction/src/extract.py`, which is where the planted
defects live, so path matching absorbed them into the matched count. The
second is a real bug worth fixing in the corpus seed. The report's own
non-claim about path matching is not a formality — here is what it costs.

## Totals

| | New input | Output | Wall clock |
|---|---|---|---|
| Whole matrix, 4 cells, 10 task-runs | **9 287 339** | 489 680 | ~2h 30m |

Roughly 9.3 million new input tokens to measure twelve planted defects across
six synthetic tasks. That is the honest price of one calibration pass, and it
should be read before planning the next one.

## What the run exposed in the repository itself

Two defects, both found by reading the benchmark's own output rather than by a
test, both fixed:

- **A retry recorded no reason.** Two of three review calls on one task ran a
  second attempt, doubling that step's cost, and the run directory recorded
  only `attempt: 2`. An attempt number with no reason cannot separate a
  fixable prompt or schema problem from model variance. Telemetry now carries
  `retry_reason` (D-M8-12).
- **Lens attribution came from the model.** A level-2 reviewer running
  `review/scope-integrity` wrote `review/scope-integrity-v1` into its
  findings, and `setdefault` kept it. The yield table showed one lens as two,
  each with half the findings — corrupting exactly the telemetry ADR 0002 says
  lens sets must be tuned on. Code now writes it (D-M8-13).

The lens-yield figures below the fix are therefore the first trustworthy ones.

## What this does not establish

- **Two tasks for the flow comparison.** The fan-out result is a signal from
  n=2, on one model at one effort. It does not license removing fan-out.
- **One model, one effort.** Nothing here compares models or efforts. Every
  role in every cell was `gpt-5.6-luna` at `max`, so a cell scores a
  configuration, not a reviewer.
- **No repair round ran.** Benchmark plans set `max_repair_rounds: 0`, so the
  repair path is still untested against a live model.
- **Level 4 never ran and cannot** until a second runner family exists. Every
  verdict says so.
- **Detection is matched by file path.** A finding that names the right file
  for the wrong reason counts as a hit. Per-class figures, not the aggregate,
  are what carry meaning.
- **Two probes are heuristics.** The `instruction-set` defects live in prose,
  which has no executable oracle; both carry a `probe_caveat` in the manifest.
