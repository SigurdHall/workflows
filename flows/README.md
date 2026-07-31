# Flows

Implementations of the five flows live here, one directory per flow:

- `implement/` — one worker, gates, review ladder, targeted repair.
- `fanout/` — N lens workers, one synthesizer, gates, review, repair.
- `assure/` — review-only: candidate mode and goal mode.
- `adjudicate/` — resolve two conflicting envelopes with evidence.
- `benchmark/` — matrix runs against a planted-defect corpus.

Implemented so far: `implement` and `assure` (candidate mode). The rest
arrive with their milestones.

```
python -m workflows.flow implement --contract c.json --worktree . --dry-run
python -m workflows.flow assure    --contract c.json --worktree . --dry-run
```

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
