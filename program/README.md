# Program

One plan, many contracts, one human checkpoint. The implementation is
[`src/workflows/program.py`](../src/workflows/program.py); this page is the
catalog.

```
python -m workflows.program run plan.toml             # resolve and print
python -m workflows.program run plan.toml --approve   # execute
python -m workflows.program resume <run-id>
```

Exit codes: 0 every task passed, or the plan resolved and awaits approval;
1 the program finished with a failure or a stop; 2 usage or configuration
error.

## The checkpoint

`run` without `--approve` resolves the plan, prints it, and stops. The
printed plan is the artifact a human approves: frozen bases, every task with
its flow, contract digest, write scope, lens set and focus hint, plus the
budgets and escalation thresholds.

Everything that can fail before a human is asked anything, fails there:
overlapping write scopes, a contract file that does not exist, a contract
that does not validate, a flow this version cannot run. Nothing is created
on disk, so a rejected plan leaves nothing behind.

After approval the program stops only on signal. Per-task approval would
defeat the level — the human becomes the bottleneck N times per batch.

## Isolation and parallelism

Every task gets its own worktree at its repository's frozen base, and the
plan's write scopes are disjoint by construction. Tasks run
`concurrency.max_parallel_tasks` at a time.

Task parallelism (this level) and lens fan-out (inside one `fanout` flow)
are orthogonal and compose freely: a program of nine tasks may run seven
`implement` flows and two `fanout` flows, each of which fans out internally.

## Budgets

Budgets are enforced from telemetry, not estimated. A token budget counts
**new input plus output**. Cached input is recorded and reported separately
and never folded in: an aggregate that mixes cached and new input overstates
cost several-fold, and a budget built on it would stop runs that cost
little.

A breach stops the program cleanly. Tasks that never started are reported as
BLOCKED rather than dropped, and the report says explicitly that nothing is
claimed about them.

## The run directory

```
runs/<program-run-id>/
  manifest.json        kind: program, one step per task
  plan.json            the plan as approved
  plan-source.json     where it came from, so a resume reads the original
  reports/1.json       one report per execution; a resume writes the next
  worktrees/<task>/    one per task, at the frozen base
  tasks/<task>/        each task's own flow run directory
```

Every execution writes its own numbered report. A resume that completed more
tasks has something new to say, and run artifacts are append-only, so it says
it in the next file rather than over the last one.

## Resume

`program resume <run-id>` re-reads the *original* plan file — not the copy in
the run — because contract paths are relative to it, and refuses to continue
if that file has changed since the run started. A plan is frozen at run
start; changing it mid-run is a new run. A task whose flow already reached a
verdict is not re-run, and the report says so per task.
