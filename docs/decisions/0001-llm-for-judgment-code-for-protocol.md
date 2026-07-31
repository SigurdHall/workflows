# 0001 — LLM for judgment, code for protocol

Status: accepted, 2026-07-31

## Context

A controlled multi-agent experiment (July 2026, synthetic benchmark)
coordinated producers, a router, and reviewers entirely through LLM
threads. The coordination layer — not the model work — was the dominant
cost and failure source: a waiting "router" thread consumed ~7M
registered tokens to act as a queue; hand-written free-text envelopes
failed schema twice, costing a correction round; and a protected-file
modification was caught by an eleven-minute LLM review when a blob-hash
comparison would have caught it in milliseconds for zero tokens.

## Decision

Models are called only for judgment work: implementing, reviewing,
synthesizing, adjudicating. Everything between two model calls — prompt
composition, schema validation, scope and hash checks, routing, retries,
record keeping — is deterministic code. If a step *can* be a
deterministic check, it *must* be one.

## Consequences

- Gates run before and after every model stage; reviewers only ever see
  gate-clean candidates.
- Envelopes are generated and validated by the driver, never free-typed
  by a model.
- Orchestration cost drops to near zero and becomes reproducible.
- The trade-off: scripted orchestration executes a wrong design to
  completion. Mitigated by ADR 0004 (single plan checkpoint + dry-run),
  not by putting a model back in the glue.
