# Lenses

A lens is a perspective a model works from: one versioned markdown file,
injected into the prompt verbatim. Lenses exist so that parallel agents are
*complementary* rather than ten copies of the same attempt.

**The lens files live in [`src/workflows/lenses/`](../src/workflows/lenses/)**,
inside the package, for the same reason the schemas do — a prompt composed
without its lens is a different prompt, so the data ships with the code.
`WORKFLOWS_LENSES_DIR` points the loader elsewhere.

## The starter set

Work lenses — producer perspectives:

| Lens | Territory |
|---|---|
| `work/spec-fidelity` | Build exactly what the contract says; resolve every ambiguity as a written decision rather than a silent pick |
| `work/minimal-change` | The smallest diff that satisfies the contract; every changed line traces to a criterion |
| `work/defensive-input` | Survive malformed, empty, degenerate and hostile input before the happy path |
| `work/api-design` | The callable surface: naming, closed contracts, error surfaces, easy to use correctly |

Review lenses — attack perspectives:

| Lens | Territory |
|---|---|
| `review/closed-contract` | Undeclared fields accepted; contracts open where they claim to be closed |
| `review/determinism` | Identity and digests under reordering; numeric canonicalization |
| `review/boundary-values` | Empty, one, maximum, off-by-one, unicode, malformed-but-plausible |
| `review/metamorphic` | Relations that must hold between related inputs and outputs when no single answer is known |
| `review/scope-integrity` | Did the candidate change only what it was allowed to, and is its own oracle still intact |
| `review/negative-path` | Rejection paths: invalid transitions, lifecycle escapes, stale state, dangling references |

## Format

Every lens file starts with a machine-readable header and carries four
sections. Both are enforced on load, and a malformed lens raises rather than
loading:

```markdown
<!-- lens: review/closed-contract v1 -->

## Targets
## Method
## Does not cover
## Output obligations
```

`Does not cover` is the section that does the work. It names the sibling
lenses by id and says what territory is deliberately left to them. In the
motivating experiment, ten ad hoc lenses defined inside one delegation
prompt yielded three distinct findings because several converged on the
same ground; a stated boundary is the fix, and a test asserts every lens
names at least one neighbour.

## Rules

- Lens sets are chosen per task at planning time and recorded in the plan,
  so a finding can be attributed to a lens across runs.
- Nothing rewrites a lens at run time. Same lens plus same contract gives a
  byte-identical prompt — that is what makes lens yield measurable and
  prompts diffable.
- A lens that never yields findings across many runs is a candidate for
  merging or retirement. Telemetry decides that, not intuition, which is
  what the benchmark flow is for.
- Adding a lens is a reviewed, versioned change. Bump the version in the
  header when the content changes materially, so telemetry can tell two
  versions apart.
