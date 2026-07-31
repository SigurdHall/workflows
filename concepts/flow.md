# Flow

A named composition of gates, model calls, and checkpoints operating on
one contract. A flow is a script with a run directory — never a chat
thread.

## The five flows

- `implement` — one worker → gates → review ladder → targeted repair.
  The building block the others compose.
- `fanout` — N lens workers in parallel → one synthesizer builds one
  integrated candidate → gates → review ladder → targeted repair with
  2–3 relevant workers, resynthesis from the original base.
- `assure` — no production step: gates + review lenses against an
  existing candidate (candidate mode) or against a goal contract's
  evidence requirements (goal mode).
- `adjudicate` — takes two conflicting envelopes, produces one resolution
  with explicit evidence requirements: every disputed claim must be
  probed, not re-asserted.
- `benchmark` — runs a matrix (model × effort × worker count) against a
  task corpus with planted defects and a hidden answer key. The only flow
  that can turn this repository's defaults into measurements.

## Shared anatomy

Every flow, regardless of shape:

1. Freezes the base (commit, worktree) and validates the contract.
2. Runs level-0 gates before any model call.
3. Calls models only through the runner interface, only with composed
   prompts, only expecting schema-valid envelopes back.
4. Runs level-0 gates after every producing stage.
5. Escalates review on signal (see the ladder in the README).
6. Writes everything to the run directory as it happens — a flow killed
   at any point is resumable from its manifest.
7. Ends by emitting one envelope with verdict, findings, evidence, and
   non-claims.

## Rules

- Flows never talk to each other directly; a program coordinates them.
  Envelopes are the only interface.
- Repair is targeted: findings go to the 2–3 workers whose lenses are
  relevant, never broadcast to all. Resynthesis always starts from the
  original base, not from the failed candidate.
- Every flow supports `--dry-run`: worktrees, prompts, and manifest are
  materialized, no model is called.

## Anti-patterns

- A flow that "just this once" messages another flow mid-run.
- Broadcast repair — sending two precise findings to ten workers buys
  redundancy, not coverage.
- Treating a synthesized candidate as reviewable before its gates ran.
