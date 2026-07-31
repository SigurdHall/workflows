# 0005 — Pluggable runner interface, Codex CLI first

Status: accepted, 2026-07-31

## Context

The motivating experiments ran on a desktop agent host whose subagent
facility could not select the desired worker model, forcing separate
task threads as a workaround. Meanwhile the review ladder (ADR 0003)
requires a cross-family model at level 4, so a single-provider binding
is structurally insufficient even if it were convenient.

## Decision

Flows call models only through a runner interface: a call carries model,
effort, composed prompt, expected output schema, working directory,
sandbox policy, and timeout; it returns structured output plus telemetry
(new input, cached input, output tokens, duration). v0 implements one
runner: Codex CLI headless execution. The interface is designed so a
second CLI-based runner (for cross-family review) is an added module,
not a refactor.

Runner *profiles* are declarative and provider-unresolved: flows name
ladder levels and worker classes; a deployment-level profile resolves
them to concrete models and efforts.

## Consequences

- v0 ships fast on one provider; level 4 of the ladder remains declared
  but unimplemented until a second runner lands — envelopes must say so
  in `non_claims` rather than silently skipping the level.
- Model and effort become per-call parameters, ending the
  thread-per-model workaround.
- Every model call is telemetered uniformly, which is what makes
  cost-per-stage and lens-yield measurable across providers later.
