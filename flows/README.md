# Flows

Implementations of the five flows live here, one directory per flow:

- `implement/` — one worker, gates, review ladder, targeted repair.
- `fanout/` — N lens workers, one synthesizer, gates, review, repair.
- `assure/` — review-only: candidate mode and goal mode.
- `adjudicate/` — resolve two conflicting envelopes with evidence.
- `benchmark/` — matrix runs against a planted-defect corpus.

See `concepts/flow.md` for the shared anatomy every flow must follow, and
`docs/roadmap.md` for implementation order and acceptance criteria.

Flows are plain Python (3.12+, stdlib only), implemented in
`src/workflows/flows/` and invoked as modules. They read contracts and
lenses, call models only through the runner interface, run checks only
through the gates, and write only to their run directory and their task
worktree.
