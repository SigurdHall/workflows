# 0003 — Signal-driven review ladder with functional levels

Status: accepted, 2026-07-31

## Context

Blind-review experiments (July 2026) produced three relevant findings.
(1) A fast worker-class model reviewing blind in a fresh context had the
best defect recall, beating a larger same-family model that scored more
generously — the larger model found nothing unique and affirmatively
asserted an unprobed negative-path property on the one candidate where
it was false. (2) The larger model was, however, better calibrated on
severity. (3) Both reviewers together still missed six of nine known
weaknesses — a single blind review is necessary but not sufficient.
Separately, context independence mattered more than model variety: a
blind same-model reviewer caught its own model family's coordinator
breaking scope.

## Decision

Review is a ladder of functional levels, escalated on signal — never a
pipeline every candidate traverses:

- Level 0: deterministic gates (always, before any model).
- Level 1: fast worker-class model, blind, fresh context — recall
  (always).
- Level 2: second same-family model — severity calibration, second
  opinion (on HIGH finding or gate/reviewer disagreement).
- Level 3: strongest same-family model — adjudication (on unresolved
  conflict).
- Level 4: cross-family model + human — shared-blind-spot check and
  final gate (before irreversible steps only).

A PASS at any level emits an envelope and stops the ladder. Negative-path
claims require a logged probe, at every level.

## Consequences

- Most runs cost one blind review. The full ladder is reserved for
  signals, keeping the expensive levels rare.
- Levels are functions, not "smarter models": recall, calibration,
  adjudication, independence. Model bindings live in runner profiles.
- Reviewers are measured on reproducible findings, false
  positives/negatives, and severity calibration — never on average
  scores, which reward leniency.
