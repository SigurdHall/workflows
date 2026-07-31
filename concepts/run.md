# Run

A run is a directory on disk. It is the audit trail, the resume point,
and the telemetry source for one execution of a flow or program.

## Contents

```
runs/<run-id>/
  manifest.json      what ran: plan/contract refs, base commits, step
                     states, timestamps
  envelopes/         every envelope every step produced
  prompts/           the exact composed prompt per model call
  telemetry.jsonl    per-call records: model, effort, tokens (new input,
                     cached input, output), duration, lens id
  gates/             gate results with evidence
```

## Rules

- **Append-only.** Steps write as they complete; nothing is rewritten.
  A run killed at any point is resumable from its manifest, and completed
  steps are never repeated.
- **Idempotent steps.** Every step checks the manifest before acting.
  Worktree creation, gate runs, and model calls all tolerate re-entry.
- **Telemetry is a product, not a byproduct.** Three numbers per model
  call minimum — new input, cached input, output — plus duration and lens
  attribution. Aggregate token counts that mix cached and new input
  overstate cost several-fold; record them separately, and include *all*
  calls (including any platform-side review/guardian overhead) so totals
  mean "everything this run consumed".
- **Lens yield lives here.** finding → lens id → run id is the join that
  lets defaults (how many workers, which lenses) become measurements.
- Run directories are local artifacts and never committed; `runs/` is
  gitignored. They must contain no secrets — prompts are composed from
  contracts and lenses, which are clean by the content policy.

## Anti-patterns

- State that exists only in a chat transcript or a model's context.
- A "resume" that replays completed model calls because nothing recorded
  their completion.
- Reporting one big token number. The motivating experiments logged
  ~29.6M "registered" tokens for a fan-out whose real work was ~1.6M new
  input + 0.6M output; the undifferentiated number misleads by 10×.
