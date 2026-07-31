# workflows

Deterministic orchestration for LLM coding agents: models do the judgment,
code does the protocol.

This repository defines reusable agent workflows as **versioned files and
scripts** — not as chat threads. It exists because orchestrating agents
through conversational coordination is expensive, unreproducible, and
fragile in exactly the places code is free, reproducible, and strict:
routing, validation, scope checking, hashing, retrying, and record keeping.

## Two principles

1. **LLM for judgment, code for protocol.** Implementing, reviewing,
   synthesizing, and adjudicating are model work. Everything between two
   model calls — composing prompts, validating output, checking scope,
   hashing protected files, running tests, routing results — is a script.
   If a step can be a deterministic check, it must be one.
2. **Independence beats scale, and scale beats model variety.** A blind
   reviewer in a fresh context finds more than a smarter model reviewing
   its own work. Diverse perspectives on one problem find more than
   identical retries. Both effects were observed in controlled experiments
   (see `docs/decisions/`).

## The seven concepts

Everything in this repository is one of these seven things. If something
does not fit, it probably does not belong here.

| Concept | What it is | Lives in |
|---|---|---|
| **Contract** | What must be done: goal, allowed scope, protected files, acceptance criteria, verification command. Two types: task contract (deterministic oracle) and goal contract (evidence rubric). | `contracts/` |
| **Gate** | A deterministic check in code: diff scope, protected-file hash, schema validation, running the verification command. Costs zero tokens. Runs before and after all model work. | `gates/` |
| **Lens** | A perspective a model works from — one versioned file per lens, injected verbatim into the prompt. Work lenses for producers, review lenses for reviewers. | `lenses/` |
| **Flow** | A named composition of gates, model calls, and checkpoints operating on one contract. A script, not a thread. | `flows/` |
| **Program** | One plan, many contracts: runs N tasks in parallel, each with its own flow, worktree, and review ladder. One human checkpoint, one consolidated report. | `program/` |
| **Run** | A directory on disk with a run manifest: which plan, which commits, which steps completed, every envelope, all telemetry. Makes everything resumable and auditable. | `runs/` (gitignored) |
| **Envelope** | The machine-readable result of any step: verdict, findings, evidence, non-claims. The only thing that crosses a step boundary. | `contracts/` (schemas) |

## Flow catalog

| Level | Name | What it does | When |
|---|---|---|---|
| Program | `program` | One plan file, N tasks in parallel, one checkpoint, one report | More than one task |
| Flow | `implement` | One worker → gates → review ladder → targeted repair | Standard bounded task |
| Flow | `fanout` | N lens workers → one synthesis → gates → review → repair | Weak test oracle, large unknown defect surface |
| Flow | `assure` | Review of an existing candidate, or of goal attainment (two modes) | Work produced outside a flow; goal checks |
| Flow | `adjudicate` | Two conflicting verdicts → adjudication with evidence requirements | Reviewers disagree |
| Flow | `benchmark` | Model × effort × worker-count matrix against a task corpus with planted defects | Calibrating every default in this repo |

Note the two orthogonal kinds of parallelism: `fanout` is breadth of
*perspectives* on one task; `program` is breadth of *tasks*. They compose
freely — a program can run nine tasks of which two use `fanout` internally.

## The review ladder

Review escalates on signal, never as a pipeline every candidate flows
through. A PASS at any level produces an envelope and stops the ladder.

| Level | Reviewer | Function | Trigger |
|---|---|---|---|
| 0 | Deterministic gates | Scope, hashes, schema, tests | Always, before any model review |
| 1 | Fast worker-class model, blind, fresh context | Defect recall | Always |
| 2 | Second model, same family | Severity calibration, second opinion | HIGH finding, or gate/reviewer disagreement |
| 3 | Strongest same-family model | Adjudication between conflicting levels | Unresolved conflict |
| 4 | Cross-family model + human | Final gate; blind spots the whole model family shares | Irreversible step (merge, release, publish) |

Concrete model bindings live in runner profiles, not in flow definitions —
flows name ladder levels, deployments resolve models.

## Human checkpoints

Every program pauses exactly once for plan approval before execution, then
only stops on signal: an escalation above threshold, or an irreversible
step. Every flow supports `--dry-run`, which materializes worktrees,
prompts, and the run manifest without a single model call.

## Repository layout

```
concepts/          one page per concept (the seven above)
contracts/         the schema catalog (the files live in src/workflows/contracts/)
lenses/work/       producer perspectives (one versioned file per lens)
lenses/review/     reviewer attack perspectives
src/workflows/     the implementation: schemas, gates, runners, flows, program
tests/             unittest suite and the annotated fixture corpus
examples/          generic example artifacts (a plan, a contract)
gates/             what each gate checks and how it fails
runners/           the runner interface and its invocation contract
flows/             the five flows
program/           the batch orchestrator
scripts/           repo tooling
docs/decisions/    architecture decision records
docs/roadmap.md    implementation milestones
docs/deviations.md every departure from the roadmap, with its reason
runs/              run artifacts (gitignored)
```

Python lives in `src/workflows/` — one importable package, so a consuming
repository installs it and runs the same gates and validators this
repository runs. The `gates/`, `runners/`, `flows/` and `program/`
directories carry the definitions and the documentation for those layers;
`lenses/` carries the lens files themselves, which are data injected
verbatim into prompts.

## Running one

```
python -m workflows.program run plan.toml            # resolve, print, stop
python -m workflows.program run plan.toml --approve  # the single checkpoint
python -m workflows.flow implement --contract c.json --worktree . --dry-run
```

`--dry-run` materializes worktrees, composed prompts, gate results and the
run manifest, and calls no model. A dry run never reports PASS: nothing was
judged, so the verdict is INCONCLUSIVE and says why.

## Using the validator

Every document that crosses a boundary is schema-validated, and consuming
repositories are expected to run the same validator in their own CI:

```
pip install -e .
python -m workflows.check plan.schema.json plan.toml
python -m workflows.check envelope.schema.json runs/<id>/envelopes/*.json
```

Exit codes are check-style: 0 clean, 1 violations, 2 usage or configuration
error. Without an install, prefix with `PYTHONPATH=src`. See
[contracts/README.md](contracts/README.md) for the schemas and for the
semantic rules no schema keyword can express.

## Status

v0: concept layer complete (this README, `concepts/`, `docs/decisions/`).
Implementation proceeds per [docs/roadmap.md](docs/roadmap.md).

## Content policy

This repository is public and generic by design. It must never contain
task content, private data, internal organization or customer names,
local absolute paths, or credentials. `scripts/check_content_policy.py`
enforces the generic rules in CI; a gitignored local policy file may add
private terms for pre-push checks. Genericity is a feature: it is what
makes these workflows reusable.

## Conventions

- JSON Schema draft 2020-12, `additionalProperties: false`,
  `schema_version` as a `const`, digests as `sha256:` + 64 hex chars.
- TOML for definitions and profiles, JSON for wire data, Markdown for
  documentation and lenses.
- Python 3.12+, standard library only, `python -m unittest` for tests.
- Runner profiles are declarative and provider-unresolved; deployments
  bind models.

## License

MIT — see [LICENSE](LICENSE).
