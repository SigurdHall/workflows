# Live run, 2026-08-01 — the first one that reached a verdict

The first `implement` flow run against a live model rather than a stub. It
passed, and the five attempts it took to get there are more useful than the
pass.

## Setup

Synthetic fixture: a `percent_change(baseline, actual)` that divides by the
baseline with no guard, two passing tests for non-zero baselines, and a
contract asking for a total function — a zero baseline must not raise and must
not report a finite percentage. Scope `src/calc/**`, protected `tests/**`,
verification `unittest discover`.

| Role | Model | Effort |
|---|---|---|
| worker, repair, review-1 | `gpt-5.6-luna` | max |
| review-2, review-3 | `gpt-5.6-sol` | high |

## Result

PASS. Ladder levels 0 and 1 ran; 2 and 3 were not triggered.

The worker added a two-line guard returning NaN for a zero baseline. Both
level-1 reviewers passed all three acceptance criteria, each backed by
evidence they had executed — including the negative-path criterion, whose
`negative_path_claim` was backed by an actual probe rather than an assertion.
The negative-path reviewer logged 3 evidence items, the scope-integrity
reviewer 7; both included items of kind `probe`.

## Cost

| Step | Model | Wall clock | New input | Cached input | Output |
|---|---|---|---|---|---|
| work-1 | luna/max | 114 s | 125 751 | 98 048 | 3 639 |
| review, negative-path | luna/max | 82 s | 109 814 | 82 944 | 3 722 |
| review, scope-integrity | luna/max | 138 s | 109 465 | 96 000 | 6 714 |
| **total** | | **334 s** | **345 030** | **276 992** | **14 075** |

Three model calls for a two-line change. That ratio is the thing to watch:
the orchestration is free, but a review pass costs about what the work costs,
and two lenses cost two reviews. Whether the second lens earned its place here
is exactly what the benchmark flow measures and this run does not.

## What the five attempts exposed

Each failure was a real defect, and all but the last were in this repository.

1. **Dirty base.** A manual `unittest` run before the flow left `__pycache__`
   in the worktree, so `base_identity` refused to start. The gate was right;
   the fixture needed `__pycache__/` in `.gitignore`, as any real repository
   has.
2. **`-m worker-class`.** The flow CLI had no way to bind a model, so a live
   run sent the *role name* to the provider. Fixed by deployment profiles
   (`--profile`), and a live run without one is now refused with an
   explanation instead of a provider error.
3. **`$ref` rejected.** The provider will not follow a reference out of the
   document and refuses any that is not to a top-level definition. Our output
   schemas are layered on a shared `$defs` library, so what validates here was
   not something a provider could be handed. The runner now flattens the
   schema before sending it.
4. **Unsupported keywords, then optional fields.** The provider rejects
   `uniqueItems`, `minItems`, `pattern` and the rest of the constraint
   vocabulary outright, and requires every declared property to appear in
   `required`. The runner strips those keywords and sends optional fields as
   required-and-nullable, dropping the nulls again before validating. What is
   stripped is not unenforced: this repository's own validator sees the full
   schema and buys one retry.
5. **The sandbox refused every write.** With `-s workspace-write` the worker
   still reported `writing is blocked by read-only sandbox; rejected by user
   approval settings`, and after that a plain read-only workspace. Dropping
   `--ephemeral`, keeping the user config, and `-c approval_policy=never` all
   made no difference; `-a never` is not a flag `codex exec` accepts. The run
   that passed used `--dangerously-bypass-sandbox`, which is opt-in and off by
   default.

The fourth run is worth its own line: the worker could not write, said so
honestly in its summary, and the `candidate_changed` gate caught the empty
candidate and refused to send it to a reviewer. That gate was added after a
blind review of M4 pointed out that an untouched worktree passes every other
gate for free — and here it earned its place in a real run.

## What this run does not establish

- **Nothing about model choice.** One model, one effort, one task.
- **Nothing about lens yield.** Two lenses both passed; a run where nothing is
  wrong cannot separate a lens that would have found something from one that
  would not.
- **Nothing about the ladder.** Levels 2 and 3 never fired, so the escalation
  thresholds are still untested against a live disagreement.
- **Nothing about repair.** The first candidate was clean, so the repair path
  and its rebuild-from-base guarantee ran only in tests.
- **Nothing about cost at realistic size.** A two-line change on a four-file
  fixture is the smallest possible task; the input tokens are dominated by
  fixed overhead, not by the work.
- **Whether the sandbox limitation is this host, this Codex version, or this
  path.** It was not isolated further.
