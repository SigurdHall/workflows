# Gates

Deterministic checks. Zero tokens, milliseconds, and always right about
what they check. Gates run before *and* after every model stage, and a gate
failure is terminal for the step: the result goes back to repair, never
onward to review. Expensive reviewers only ever see gate-clean work.

The implementation is `src/workflows/gates.py`; this page is the catalog.

| Gate | Checks | Fails with |
|---|---|---|
| `base_identity` | HEAD is the frozen base or a commit directly on it; optionally that the worktree is clean | `unknown_base`, `base_mismatch`, `dirty_worktree` |
| `candidate_changed` | The candidate differs from the base at all | `empty_candidate` |
| `scope` | No path outside the contract's `allowed_paths` changed — including untracked additions and both ends of a rename | `out_of_scope_change` |
| `protected_hash` | Protected files are byte-identical to the base | `protected_modified`, `protected_deleted`, `protected_missing_at_base` |
| `verification_command` | The contract's command exits as the contract says | `nonzero_exit`, `command_not_found`, `timeout` |
| `schema` | Every presented document validates, schema and semantic rules alike | `schema_invalid` |
| `evidence_obligations` | Goal contracts: deliverables exist, references resolve, commands succeed | `missing_artifact`, `empty_artifact`, `unresolved_reference`, `requires_judgment` |

Every gate returns a result *and* a machine-readable reason code, validated
against `contracts/gate-result.schema.json`. Nothing is warned about: a gate
that cannot fail is documentation.

## Three rules the implementation takes literally

**Untracked files are changes.** `git diff` never mentions them, so a scope
gate built on the diff alone would let a worker create any file anywhere.
The scope gate reads the diff *and* `git ls-files --others`.

**A rename is judged at both ends.** Moving a file out of scope changes a
path the contract never allowed, so both the old and the new path must be
in scope.

**An empty candidate is a failure, not a pass.** Every other gate passes an
untouched worktree for free: nothing is out of scope, no protected file
moved, and the base's own verification still exits zero. `candidate_changed`
is the gate that stops a flow from reporting success for work that never
happened. In a dry run it reports NOT_RUN with a non-claim, because a dry
run was never going to produce a candidate.

**No silent fallback for a missing command.** A verification command whose
executable does not exist fails with `command_not_found` — never "skipped",
never green, and never quietly retried through a different interpreter. If
a specific interpreter is needed, the contract names it. This is the
Windows Store `python` alias class of failure, and it is the one that turns
an untested candidate into a green one.

## Goal contracts get weaker gates, and say so

`evidence_obligations` checks that deliverables exist and that references
resolve. That is weaker than a hash, and the gate does not pretend
otherwise: obligations no deterministic check can settle come back
`INCONCLUSIVE` with `requires_judgment`, named individually in the result's
non-claims, so a goal can never be declared attained on gates alone.
