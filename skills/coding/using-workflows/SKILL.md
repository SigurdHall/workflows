---
name: using-workflows
description: Delegate bounded coding work through this repository's orchestration — task contracts, deterministic gates, a blind review ladder, and a batch program level with one human checkpoint. Use when work should be handed to a coding agent under enforced scope and protected-file guarantees, when several bounded tasks should run in parallel under one approval, when an existing candidate needs a blind review, when two reviewers disagree, when a goal needs an evidence-based attainment check, or when reviewer and lens performance should be measured. Also triggers on: kjør en flyt, implement-flyt, fanout, assure, adjudicate, benchmark, plan.toml, program run, kontrakt for oppgaven, gates, linser, konvolutt, verdikt, kjøremappe. Use an informal handoff prompt instead when no contract or gate is wanted.
---

# Using the workflows orchestration

Models do judgment; code does protocol. Reach for a flow when the *protocol*
matters — enforced scope, byte-identical protected files, blind review,
resumable runs, one approval for a batch. Skip it for a one-file edit: the
contract would cost more than the change.

Paths below are relative to this repository's root. `docs/deviations.md`
records every departure from `docs/roadmap.md` and why; read it before
changing anything here.

## Choose the flow first

| Situation | Flow |
|---|---|
| One bounded task with a real verification command | `implement` |
| One task, weak test oracle, wide unknown defect surface | `fanout` |
| A candidate that already exists and needs judging | `assure` (candidate mode) |
| "Did we achieve this?" with no deterministic oracle | `assure` (goal contract) |
| Two envelopes that reached different conclusions | `adjudicate` |
| Measuring reviewer recall or lens yield | `benchmark` |
| More than one task | `program` over a plan |

`fanout` is breadth of *perspectives* on one task; `program` is breadth of
*tasks*. They compose: a program may run several tasks of which some fan out.

## Run it

Install once with `pip install -e .`, or put `src` on the path per command
(`PYTHONPATH=src` in bash, `$env:PYTHONPATH="src"` in PowerShell).

On Windows, check that `python` is a real interpreter before using it in a
contract: where the Microsoft Store alias is active, `python` resolves to a
stub that exits nonzero without running anything, and `py` is the interpreter.
The verification gate will catch it — but as a failed contract, not as a
helpful message.

```
python -m workflows.check <schema> <file>                 # validate any document
python -m workflows.flow implement --contract c.json --worktree <repo> --dry-run
python -m workflows.program run plan.toml                 # resolve and print
python -m workflows.program run plan.toml --approve       # the single checkpoint
python -m workflows.program resume <run-id>
python -m workflows.benchmark run <corpus.json> --matrix m.toml --work-root <dir>
```

Exit codes are check-style everywhere: 0 clean, 1 violations or a failed
verdict, 2 usage or configuration error.

## The order that works

1. Write the task contract. Validate it *before* anything else:
   `python -m workflows.check task-contract.schema.json <contract>`.
2. Dry-run the flow. Read the run directory: `prompts/` is exactly what a
   model would be sent, `gates/<step>/` is what each gate concluded,
   `manifest.json` is what a resume would skip.
3. Fix what the dry run exposes — usually the contract, not the code.
4. Run for real. Read the verdict's `non_claims` before its result.

## Preconditions that will bite you

Each of these is a failure that happened, not a hypothetical:

- **`runs/` must be gitignored** in the target repository. A run writes while
  it runs, so a run directory git can see makes every scope and identity gate
  report on the run's own bookkeeping. The flow CLI refuses to start and says
  so.
- **A plan's `write_scope` must equal its contract's `scope.allowed_paths`.**
  The plan states what the human approves; the contract states what the gate
  enforces. `resolve` rejects a mismatch rather than letting them drift.
- **Two tasks may not name the same contract file.** They would share its
  scope whatever the plan says, and tasks that share a write target are one
  task.
- **`verification.command` is argv, not a shell string**, and there is no
  fallback interpreter. A missing executable is `command_not_found` and a
  FAIL — never a skip, never green.
- **`unittest discover` exits 5 when it finds no tests.** A `tests/` directory
  without `__init__.py`, or holding plain functions instead of `TestCase`
  classes, discovers nothing and fails the verification gate.
- **A frozen base must exist.** `resolve` checks it, and a resume refuses a
  changed contract, base or plan — those are frozen at run start.
  `examples/plan.example.toml` carries a placeholder base: copy it and
  substitute a real commit rather than running it in place.

## Read a result honestly

- **A dry run never reports PASS.** No model was called, so nothing was
  judged; the verdict is INCONCLUSIVE and says why. Reading INCONCLUSIVE as
  failure misreads every dry run.
- **`non_claims` is the boundary of the result**, not decoration. Carry it
  into whatever you report to a human.
- **Ladder level 4 never runs** while this deployment has one runner family.
  Every verdict states it. Do not describe a PASS as fully reviewed.
- **A producing step reports NOT_RUN, not PASS** — a producer evaluates no
  criterion, and grading its own work is what the gates and the ladder
  replace.
- **Benchmark recall is matched by file path.** Read recall per defect class,
  not the aggregate, and treat unmatched findings as unmatched rather than
  wrong.

## When changing this repository

Per milestone: implement, `python -m unittest` green,
`python scripts/check_content_policy.py` green, commit, push — then freeze the
commit in a detached worktree and give *that* to independent blind reviewers
with one sharp lens each, requiring an executed probe behind every claim. That
routine found defects a green suite did not, including a review that could
clear its own CRITICAL finding and a gate that polluted the worktree it was
judging.

Log every roadmap departure in `docs/deviations.md`: a visible deviation
beats a silent adaptation.

This repository is public and strictly generic. No task content, no
organisation or customer names, no local absolute paths, no credentials.
`scripts/check_content_policy.py` gates file content; it does not see git
metadata, so check the commit identity separately.
