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
| Does per-class recall measure reviewer recall? | It does now. It did not: over an `implement` cell it conflated "the worker fixed it" with "every reviewer missed it". Demonstrated in the probe record, then fixed with presence probes — re-scoring that same run reads `removed 2` where it once read `recall 0/2` |
| Do the presence probes discriminate? | Yes, offline: each of the 12 reports its defect present in the seed, absent when its own defect is fixed, and present when only the *other* defect of its task is fixed. The two `measure-variance` probes were also checked against a real worker candidate |
| Does a flow refuse to conclude when a reviewer dies? | Yes, observed live: BLOCKED, not PASS, on one surviving reviewer that passed every criterion |
| Does the review ladder catch a violation of a named acceptance criterion? | **Not reliably.** Six reviewers across two producing flows marked AC-3 PASS with the defect it names live in the candidate. The review prompt carries the diff, not the code the criterion is about — `benchmark-2026-08-01-tier-a.md` |
| Is fan-out of 3 worth it over 1? | **First measurement says no** — same defects removed, same one missed, 2.4× the input tokens. Two tasks, one model: a signal, not a verdict |
| Is a fast worker-class model the best level-1 reviewer? | **Unmeasured.** The claim comes from the motivating experiments, not from this repository |
| Is fan-out of 3–5 workers worth it over 1? | **Unmeasured.** The benchmark matrix exists to answer it |
| Which lenses actually yield findings? | **Unmeasured.** Needs benchmark runs with lens attribution |
| Do the ladder thresholds fire at the right time? | **Unmeasured** |

Every row marked unmeasured is a default this repository currently asserts.
That is the honest state, and the reason the benchmark flow was built.
