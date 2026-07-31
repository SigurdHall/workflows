# Program

One plan, many contracts. The program level exists so a human administers
*one thing*: one plan file in, one checkpoint, one consolidated report
out.

## Shape

A plan file (TOML) declares:

- the frozen base per repository,
- the list of tasks, each with its contract and its chosen flow
  (`implement` or `fanout`, with lens set for the latter),
- concurrency limits and budgets (tokens, wall clock),
- the escalation thresholds that stop the program for a human.

## Execution

1. `program run plan.toml` prints the resolved plan — tasks, flows,
   scopes, budgets — and stops at the single human checkpoint.
2. On approval, every task gets its own worktree and flow. Tasks run in
   parallel; flows never share write targets.
3. The program collects envelopes as flows finish, and stops only on
   signal: an escalation above threshold, or an irreversible step.
4. The result is one consolidated report: per-task verdicts, open
   findings, telemetry, and every escalation in one place.

## Two kinds of parallelism

Task parallelism (this level) and lens fan-out (inside one `fanout` flow)
are orthogonal and compose freely: a program of nine tasks may run seven
`implement` and two `fanout` flows. Do not model task parallelism as a
fan-out variant — breadth over tasks and breadth over perspectives answer
different questions.

## Rules

- One human approval per program, before execution. Everything after is
  signal-driven. Per-task approval defeats the purpose of the level.
- A program is resumable: killed at any point, `program resume <run-id>`
  continues from the manifests without repeating completed flows.
- Programs may be driven by a goal contract in a later version: a
  planning model decomposes the goal into task contracts, and the human
  approves the decomposition at the same single checkpoint. The plan
  format is identical; only the author differs.

## Anti-patterns

- Coordinating parallel tasks through a conversational thread — the
  motivating experiments spent millions of replayed context tokens and
  real failure modes (free-text protocol envelopes, waiting-loop threads)
  on coordination a loop does for free.
- Programs whose tasks share write scope. If two tasks touch the same
  files, they are one task.
