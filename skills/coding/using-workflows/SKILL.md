---
name: using-workflows
description: Delegate bounded coding work through this repository's orchestration — task contracts, deterministic gates, a blind review ladder, and a batch program level with one human checkpoint. Use when work should be handed to a coding agent under enforced scope and protected-file guarantees, when several bounded tasks should run in parallel under one approval, when an existing candidate needs a blind review, when two reviewers disagree, when a goal needs an evidence-based attainment check, or when reviewer and lens performance should be measured. Also triggers on: kjør en flyt, implement-flyt, fanout, assure, adjudicate, benchmark, plan.toml, program run, kontrakt for oppgaven, gates, linser, konvolutt, verdikt, kjøremappe. Use an informal handoff prompt instead when no contract or gate is wanted.
---

# Using the workflows orchestration

Models do judgment; code does protocol. Reach for a flow when the *protocol*
matters — enforced scope, byte-identical protected files, blind review,
resumable runs, one approval for a batch.

## Decide whether to use a flow at all

This is the decision that matters most, and it is usually "no". Measured on
2026-08-01, one task through one flow costs **700k–1.7M new input tokens and
7–20 minutes**, whatever the size of the change. The first live run spent
345k tokens on a two-line guard.

Do not use a flow when:

- the change is small and a test would catch a mistake — the contract costs
  more than the change, every time;
- you can review the result yourself in less time than the flow takes;
- there is no verification command worth running, and no goal rubric either —
  the gates are then the only real check, and you can run those yourself.

Use one when at least one of these is true:

- **the protected files matter more than the change** — a byte-identical hash
  gate is worth more than any amount of care;
- **the scope must be provable**, not merely intended;
- **several bounded tasks should run under one approval**, with one report;
- **the work must be auditable afterwards** — every prompt, gate result and
  verdict on disk, resumable;
- **an existing candidate needs a blind judgement** from something that never
  saw how it was made.

Cost scales with reviewers, not with the diff. Two review lenses are two full
calls; escalating to level 2 is a third.

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

**A live run needs a profile.** Flows name roles — `worker`, `review-1`,
`review-2` — and a deployment profile binds each to a concrete model and
effort. The built-in bindings are role *names*, not models, so a live run
without `--profile` is refused rather than sent to a provider that would
reject `-m worker-class`. Copy `examples/profile.example.toml` and put your
own model ids in it.

On Windows, check that `python` is a real interpreter before using it in a
contract: where the Microsoft Store alias is active, `python` resolves to a
stub that exits nonzero without running anything, and `py` is the interpreter.
The verification gate will catch it — but as a failed contract, not as a
helpful message.

```
python -m workflows.check <schema> <file>                 # validate any document
python -m workflows.flow implement --contract c.json --worktree <repo> --dry-run
python -m workflows.flow implement --contract c.json --worktree <repo> \
    --profile profile.toml --review-lens review/negative-path
python -m workflows.program run plan.toml                 # resolve and print
python -m workflows.program run plan.toml --approve --profile profile.toml
python -m workflows.program resume <run-id>
python -m workflows.benchmark run <corpus.json> --matrix m.toml --work-root <dir>
```

Exit codes are check-style everywhere: 0 clean, 1 violations or a failed
verdict, 2 usage or configuration error.

## Measuring, not asserting

A benchmark cell is one flow over one corpus, run through the program level
and scored against a hidden answer key. The matrix file declares cells:

```toml
[[cell]]
flow = "assure"          # implement | fanout | assure. Omit and width decides.
model = "gpt-5.6-luna"   # a real model id: a live matrix refuses role names
effort = "max"
worker_count = 1         # fanout needs >1; assure produces nothing, leave at 1
```

```
python -m workflows.benchmark run <corpus.json> --matrix m.toml \
    --work-root <outside the repo> --profile profile.toml \
    --task <id> --task <id> --budget-tokens 1500000
python -m workflows.benchmark score <corpus.json> <program-run-root> --task <id>
```

**Read `caught`, `missed`, `removed` and `indeterminate` — not one recall
number.** A cell runs a producing step, so a worker that fixes a planted
defect leaves nothing for a reviewer to catch. Recall is `caught / present`;
`removed` and `indeterminate` are reported beside it and belong to neither
side. A cell with nothing present reports no recall rather than zero.

Which cell answers which question:

| Cell | What it measures |
|---|---|
| `assure` | Reviewer recall and lens yield, with no worker in the way. The cleanest measurement here |
| `implement` | The whole configuration end to end: what a worker leaves and what review catches |
| `fanout` | The same, against the cost of extra worker breadth |

`adjudicate` cannot be a cell. It is reached from a conflict *inside* a flow,
and a matrix that scheduled it would be inventing a conflict rather than
measuring one; `load_matrix` refuses it and says so.

Budgets are **per cell, not per matrix**, and are checked between tasks rather
than mid-call. Start with two cells and two tasks: one live `assure` cell over
one task cost ~550k new input tokens and ~15 minutes when the ladder escalated
to level 2.

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
- **The target repository needs `__pycache__/` ignored**, or any command you
  run before the flow leaves the worktree dirty and `base_identity` refuses to
  start. The gate is right; the repository is missing a line. This bites twice:
  a *worker* that runs the project's own tests leaves the same artifacts, and
  then `scope` and `protected_hash` fail work it never did — while
  `candidate_changed` passes on those artifacts, so a worker that changed
  nothing clears the gate that exists to catch exactly that. An unignored build
  artifact does not just add noise; it defeats a gate.
- **A contract whose protected tests pin the wrong answer cannot be
  satisfied.** If a test the contract protects asserts the behaviour an
  acceptance criterion says is wrong, no candidate inside the allowed scope can
  pass both. A good worker will produce nothing and say why in its non-claims;
  read those before assuming it failed. The fix is to the contract or the test,
  not to the worker.
- **The provider's sandbox may refuse writes a worker needs.** On at least one
  Windows host `workspace-write` still reports a read-only workspace, and the
  worker then produces an empty candidate — which the `candidate_changed` gate
  catches rather than passing on. `--dangerously-bypass-sandbox` is the opt-in
  escape; leave it off wherever the sandbox works. What bounds the risk when
  it is on is the worktree and the gates, not the provider.

## Read a result honestly

- **A PASS means the diff was reviewed, not that the contract holds.** Measured
  on 2026-08-01: six reviewers across two producing flows marked an acceptance
  criterion PASS while the defect that criterion names was live in the
  candidate. The review prompt carries the contract and the worker's *diff* —
  not the code the criteria are about — so a criterion about untouched code is
  answered from nothing. Until that is fixed, treat a producing flow's PASS as
  "nothing wrong in the change", and use `assure` against a known-good base
  when you need the stronger claim. See
  `docs/evidence/benchmark-2026-08-01-tier-a.md`.
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
