# Gate

A deterministic check in code. Costs zero tokens, runs in milliseconds,
and is always right about what it checks.

## Core gates

- **Scope gate** — `git diff --name-status` against the contract's allowed
  paths. Any file outside scope fails the gate.
- **Protected-hash gate** — blob hashes of protected files compared
  against the base commit. Byte-identical or fail.
- **Verification gate** — run the contract's verification command; the
  exit code is the primary oracle.
- **Schema gate** — every envelope validates against its schema before it
  crosses a step boundary. Free-text protocol data is forbidden.
- **Base-identity gate** — the candidate's parent commit is exactly the
  frozen base; the worktree is clean.

## Rules

- Gates run before *and* after every model stage. A reviewer must never
  be the first thing to see a candidate a gate could have rejected.
- A gate failure is terminal for the step: the result goes back to repair,
  never onward to review. Expensive reviewers only see gate-clean work.
- Gates produce envelope fragments (check id, result, evidence), so gate
  evidence and model evidence live in the same record.
- For goal contracts, gates check evidence obligations (deliverables
  exist, references resolve) — weaker than hashes, still deterministic.

## Anti-patterns

- Asking a model to verify what a hash can verify. The most expensive
  finding in the motivating experiments was a protected-file modification
  discovered by an eleven-minute LLM review; a hash gate finds it in
  milliseconds.
- Prompt-only protection ("do not modify tests") with no enforcing gate.
- Gates that log warnings instead of failing. A gate that cannot fail is
  documentation.
