# Live probes, 2026-08-01 — what one benchmark cell actually measures

Three runs of a single benchmark cell over a single corpus task, before
spending anything on a matrix. Each cost about 100k tokens and each exposed
something no dry run could: two defects in this repository and one in the
corpus, plus a measurement flaw in the benchmark's headline number.

## Setup

| | |
|---|---|
| Corpus | `examples/corpus/tier-a/corpus.json`, task `measure-variance` only |
| Planted | class 11 (aggregation misuse), class 14 (blank/zero conflation) |
| Cell | `gpt-5.6-luna`, effort `max`, `worker_count = 1` → `implement` |
| Ladder | level 1, two review lenses (`scope-integrity`, `closed-contract`) |
| Sandbox | `--dangerously-bypass-sandbox` (see the run record for why) |

## The three probes

| | Outcome | New input | Output | Wall clock |
|---|---|---|---|---|
| 1 | BLOCKED — gates failed on build artifacts | 84 102 | 5 741 | 118 s |
| 2 | FAIL — worker produced nothing, correctly | 109 736 | 8 528 | 169 s |
| 3 | BLOCKED — worker fixed both defects, one reviewer died | 335 430 | 14 252 | 450 s |

Recall in every probe: **0/2**. Probe 3 explains why that number is not what
it looks like.

### Probe 1 — build artifacts defeated a gate

The worker ran the project's own tests, leaving `__pycache__` inside the
contract's protected paths. The corpus seeds are Python and carry no ignore
file, so those `.pyc` files were untracked additions. Two consequences:

- `scope` and `protected_hash` **failed** — reporting as the worker's work
  files the worker never authored.
- `candidate_changed` **passed** — on the artifacts. That gate exists to catch
  a worker that changed nothing, which is exactly what had happened.

The second is the serious one. Vacuous success is defect class 3 in this
repository's own taxonomy, and the gate guarding it was defeated by build
output. `materialize()` now writes a `.gitignore` into the generated
repository; `git ls-files --others --exclude-standard` does the rest.

### Probe 2 — the same run, read correctly

With the ignore file in place and nothing else changed, the same cell failed
with `candidate_changed: the worktree is byte-identical to the frozen base`,
and no reviewer ran — reviewers only see gate-clean work. The verdict now
named the real problem instead of two invented ones.

The real problem was in the corpus. The worker's own non-claims:

> No source changes were made because the acceptance criteria are not
> simultaneously satisfiable within the allowed scope and protected tests.

Verified by reading the files rather than trusting the model: the seed's
protected test asserted `portfolio_percent_variance(rows) == 20.0/3`, the
mean-of-ratios value the planted defect produces. AC-1 requires the
verification command to exit zero; AC-2 requires the ratio of sums. No
candidate inside `measure-variance/src/**` can satisfy both. The worker was
right to produce nothing and said so precisely.

The test now asserts only that the portfolio figure is a number. The corpus
property is preserved — the defect still survives a green happy-path run —
without the contract being impossible. The other eleven planted defects were
checked against the manifest's own `survives` entries: they describe tests
that are *incomplete*, not tests that encode the defect.

### Probe 3 — and now the measurement itself is wrong

With a satisfiable contract the worker did the work, in one pass, correctly:

- `read_rows` maps a blank budget to `None` rather than `0.0` — class 14,
  gone, exactly as AC-3 asks.
- `portfolio_percent_variance` sums budgets and actuals and takes one ratio
  instead of averaging per-department percentages — class 11, gone, exactly
  as AC-2 asks.

Both planted defects are absent from the candidate the reviewers see. No
reviewer can flag what is not there, so the cell scores **recall 0/2** — for
a run in which the system did precisely the right thing.

| Step | Wall clock | New input | Cached input | Output |
|---|---|---|---|---|
| work-1 | 146 s | 155 148 | 124 416 | 7 168 |
| review, scope-integrity | 152 s | 0 | 0 | 0 |
| review, closed-contract | 151 s | 180 282 | 151 808 | 7 084 |
| **total** | **450 s** | **335 430** | **276 224** | **14 252** |

The zero row is an interruption of the operator's own making: the
scope-integrity reviewer was killed mid-call on a mistaken belief that it had
hung, and its retry failed too. Two things follow, and both are worth
recording.

**The flow handled it correctly.** The verdict is BLOCKED, not FAIL and not
PASS, with the non-claim *"A review step failed rather than concluding, so
this candidate was never judged. A failed call is not a finding."* The
reviewer that did conclude passed all three acceptance criteria; the flow
still refused to conclude from one reviewer. That path had never been
exercised against a live model before, and it held.

**The cost figures understate.** A killed call emits no usage events, so its
provider-side spend is absent from the 335 430. Probe 3's numbers are a floor,
not a per-cell estimate.

## The flaw this exposes

The scorer counts a planted defect as detected when a reviewer's finding
points at its file. Over an `implement` flow that conflates two opposite
outcomes:

- the worker fixed the defect → nothing to find → 0
- the worker left the defect and every reviewer missed it → 0

Only the second is a reviewer failure, and the number cannot tell them apart.
Per-class recall from an `implement` cell is therefore not reviewer recall,
which is what `docs/roadmap.md` asks the benchmark for.

The report now carries this in its own non-claims, which is honesty, not a
fix. A fix needs ground truth on whether the defect is still present in the
scored candidate. The cheapest form is an executable probe per planted
defect — a small test that fails if and only if the defect is there — turning
the corpus's prose `triggering_probe` field into something the scorer can
run. Then a cell reports three numbers instead of one: defects removed by the
worker, defects surviving and caught, defects surviving and missed. Only the
last two belong in recall.

That is a corpus and scorer change, not a wiring change, and it is the
decision this probe hands back rather than making on its own.

## What these probes do not establish

- **Nothing about model choice, lens yield, ladder thresholds or fan-out
  width.** One cell, one task, one model. The matrix still has not run.
- **Nothing about the other five corpus tasks.** Only `measure-variance` was
  materialized. The contract-satisfiability check on the other five was a
  reading of the manifest, not a run.
- **Nothing about repair.** `max_repair_rounds` is 0 in a generated benchmark
  plan, so that path is still untested against a live model.
- **That the worker's fix is correct beyond the criteria it was judged on.**
  One reviewer at level 1 concluded on it; the second died. Levels 2 and 3 did
  not run, and level 4 cannot.
- **A clean per-cell cost.** Probe 3 lost a reviewer and its retry, so its
  totals are a floor. Probes 1 and 2 stopped at the gates and never reached
  the ladder. No probe here measured a complete, uninterrupted cell.
