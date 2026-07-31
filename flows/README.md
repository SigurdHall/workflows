# Flows

The implementation is [`src/workflows/flows/`](../src/workflows/flows/), one
module per flow; this page is the catalog.

| Flow | What it does | Status |
|---|---|---|
| `implement` | One worker, gates, review ladder, targeted repair | implemented |
| `fanout` | N lens workers, one synthesizer, gates, review, repair | implemented |
| `assure` | Review-only: candidate mode, and goal mode | implemented |
| `adjudicate` | Resolve two conflicting envelopes with evidence | implemented |
| `benchmark` | Matrix runs against a planted-defect corpus | implemented |

```
python -m workflows.flow implement --contract c.json --worktree . --dry-run
python -m workflows.flow assure    --contract c.json --worktree . --dry-run
python -m workflows.flow fanout    --contract c.json --worktree . --dry-run \
    --work-lens work/spec-fidelity --work-lens work/defensive-input
```

`assure` switches to goal mode when the contract is a goal contract: the
evidence-obligation gate settles what a deterministic check can settle, a
model judges the rest against the contract's own rubric, and the verdict
names which obligations fell in which half. An obligation met is not a goal
achieved, and a goal-mode verdict says so.

`adjudicate` takes two conflicting envelopes. The disputed claims are
enumerated by code, not summarised by a model, and each must be settled by a
probe the adjudicator ran; a claim no probe can settle comes back
UNRESOLVED, which is an answer. The claims reach the adjudicator stripped of
authorship, so nothing can be decided by which reviewer wrote it.

`benchmark` is the only flow that turns this repository's defaults into
measurements. It materializes a corpus with planted defects and a hidden
answer key, runs a matrix of {model, effort, worker count} cells through the
program level, and reports cost against detection:

```
python -m workflows.benchmark run <corpus.json> --matrix matrix.toml \
    --work-root <outside this repository> --dry-run
python -m workflows.benchmark score <corpus.json> <program-run-root>
```

Recall is reported per defect class, because one aggregate number hides
exactly the classes that escape. Findings that match no planted defect are
counted as *unmatched*, never as false positives: the corpus plants a known
set of defects, not every defect in the fixture, and calling an unmatched
finding wrong would train the system to reward reviewers that find only what
is expected.

Fan-out gives each worker its own worktree from the frozen base, so workers
never share a write target and none of them can see what another did. The
synthesizer sees their candidates labelled by lens — a diff is a fact, an
explanation of a diff is a story about one — and builds one integrated
candidate. Width is a plan parameter in v0, and every fan-out verdict says
so: a chosen width is not a measurement that the ground is covered.

Exit codes: 0 the verdict passed (or a dry run completed), 1 it did not,
2 usage or configuration error.

`--dry-run` materializes worktree state, composed prompts, gate results and
the run manifest, and calls no model. A dry run never reports PASS: nothing
was judged, so the verdict is INCONCLUSIVE and says why.

The run directory must not be visible to git inside the worktree it judges.
A run writes while it runs, so a visible `runs/` turns every scope and
identity gate into a report about the run's own bookkeeping; the CLI
refuses to start rather than produce that.

See `concepts/flow.md` for the shared anatomy every flow must follow, and
`docs/roadmap.md` for implementation order and acceptance criteria.

Flows are plain Python (3.12+, stdlib only), implemented in
`src/workflows/flows/` and invoked as modules. They read contracts and
lenses, call models only through the runner interface, run checks only
through the gates, and write only to their run directory and their task
worktree.
