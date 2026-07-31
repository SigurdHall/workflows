# 0004 — Program level with a single human checkpoint

Status: accepted, 2026-07-31

## Context

Running nine parallel tasks through conversational coordination required
a human to track nine threads, and the one serious near-miss of the
motivating experiments — tasks initially created against a real project
instead of the isolated benchmark — was caught by the human, not by any
gate. At the same time, per-task approvals defeat the point of
parallelism: the human becomes the bottleneck N times per batch.

## Decision

Task parallelism is a first-class level, `program`: one plan file
declaring frozen bases, tasks with contracts and flows, budgets, and
escalation thresholds. Exactly one human checkpoint — plan approval
before execution, where the resolved plan (scopes, flows, budgets) is
printed. After approval the program stops only on signal: escalation
above threshold, or an irreversible step. Every flow and program
supports `--dry-run` (materialize everything, call no model).

Plans are hand-written in v0. Goal-driven plan generation (a planning
model decomposes a goal contract into task contracts) reuses the same
format and the same single checkpoint in a later version.

## Consequences

- The human administers one artifact and one decision per batch.
- The scope near-miss class is closed twice over: scope is declared in
  the plan the human approves, and enforced by gates per task.
- Lens fan-out (breadth of perspectives, inside one flow) and task
  parallelism (breadth of tasks, this level) stay orthogonal and
  composable; neither is a variant of the other.
- Tasks in one program must have disjoint write scopes; overlapping
  scope means it is one task.
