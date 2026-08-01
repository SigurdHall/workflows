# Evidence

Where measurements live. Everything else in this repository is a design
argument; this directory is what turns the arguments into numbers, or
contradicts them.

Two kinds of record go here:

- **Run records** (`live-run-<date>-<name>.md`) — what a real run did, what it
  cost, and what it exposed. One file per run worth remembering, not per run.
- **Benchmark reports** (`benchmark-<date>-<corpus>.json` plus a companion
  `.md`) — the output of `python -m workflows.benchmark run`, with the matrix
  that produced it and a short reading of what it says.

Run directories themselves are not committed: `runs/` is gitignored, they can
be large, and they belong to the machine that produced them. What belongs here
is the distilled record — numbers, what was learned, and what remains
unmeasured.

## Rules for a record

- **State the model, effort and date.** A cost figure with no model attached
  measures nothing, and providers change under a fixed name.
- **Keep new input, cached input and output separate.** An aggregate that
  mixes cached and new input overstates cost several-fold.
- **Say what the run did not establish.** A single run is an anecdote. Two
  runs of one task on one model are two anecdotes.
- **Stay generic.** This repository is public: no task content from real
  projects, no organisation names, no local paths. Fixtures used for a run
  record must be synthetic, as the corpus ones are.

## What is measured so far

| Question | Status |
|---|---|
| Does a flow work end to end against a live model? | Yes — `live-run-2026-08-01-percent-change.md` |
| Does a benchmark cell run a live flow over a corpus task? | Yes — `live-probe-2026-08-01-benchmark-cell.md` |
| What does one small `implement` run cost? | Two data points, in those records |
| Does per-class recall measure reviewer recall? | **No** — over an `implement` cell it conflates "the worker fixed it" with "every reviewer missed it". Demonstrated in the probe record |
| Does a flow refuse to conclude when a reviewer dies? | Yes, observed live: BLOCKED, not PASS, on one surviving reviewer that passed every criterion |
| Is a fast worker-class model the best level-1 reviewer? | **Unmeasured.** The claim comes from the motivating experiments, not from this repository |
| Is fan-out of 3–5 workers worth it over 1? | **Unmeasured.** The benchmark matrix exists to answer it |
| Which lenses actually yield findings? | **Unmeasured.** Needs benchmark runs with lens attribution |
| Do the ladder thresholds fire at the right time? | **Unmeasured** |

Every row marked unmeasured is a default this repository currently asserts.
That is the honest state, and the reason the benchmark flow was built.
