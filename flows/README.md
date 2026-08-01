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

**Recall is caught over present, never caught over planted.** A cell runs a
producing step, and a worker that fixes a planted defect leaves nothing for a
reviewer to catch. Counting that as a miss would measure the worker and call
it review. So every planted defect carries a **presence probe** — a script in
the corpus, never in a seed tree, run against the candidate after the flow:

```
<interpreter> <probe_path> <task directory inside the candidate>
# prints exactly one of DEFECT_PRESENT / DEFECT_ABSENT, exits zero
```

A probe that crashes, times out, says nothing, or says both has not decided.
That is INDETERMINATE, and it is reported beside the other counts rather than
folded into either. Every cell therefore accounts for each planted defect
exactly once as `present + removed + indeterminate`, and each present one as
`caught + missed`. `missed` is the number this flow exists to drive down.

A probe answers whether the defect is there, not whether the candidate is
good: a candidate that removed the planted defect and introduced a worse one
probes ABSENT, and the report says so in its non-claims.

A cell names its `flow`. `implement` and `fanout` measure a whole
configuration — what a worker leaves and what review catches. An `assure`
cell measures reviewer recall with no worker in the way, which is the
cleanest thing this corpus can measure: each task declares a defect-free
`clean_path` that the cell commits as its base, with the seed placed on top
as the candidate, so the diff a reviewer judges is the one that *introduces*
the planted defects.

`adjudicate` cannot be a cell. It is reached from a conflict inside a flow,
so a matrix that scheduled it would be inventing a conflict rather than
measuring one.

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
