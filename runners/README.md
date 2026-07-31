# Runners

A runner is the only way a flow reaches a model. A call carries model,
effort, composed prompt, expected output schema, working directory, sandbox
policy and timeout; a result carries structured output plus telemetry
(ADR 0005). Flows name ladder levels and worker classes; a deployment
profile resolves them to concrete models, so a second runner is a module,
not a refactor.

Interface: `src/workflows/runners/__init__.py`.
Codex implementation: `src/workflows/runners/codex.py`.

## Two disciplines that live in the interface, not in a runner

**Bounded retry.** Output that fails its schema buys exactly one more
attempt, carrying the validation errors verbatim. Then the call is FAILED
and emits an envelope saying so. Never a silent pass; never an unbounded
loop. A model that answers with the wrong shape twice has told you
something — a driver that keeps asking has not.

**Honest telemetry.** New input, cached input and output tokens are recorded
separately and never summed into one number. Within one call exactly one
usage figure is recorded — the final one — and the number of usage events
is recorded beside it, so an undercount would be visible rather than
silent. The motivating experiments logged ~29.6M "registered" tokens for a
run whose real work was an order of magnitude smaller; that number came
from adding cumulative and per-turn figures together.

## The Codex invocation contract

Verified against the installed CLI on 2026-07-31 (`codex-cli 0.145.0`) with
`codex exec --help`, and exercised end to end by the smoke test below.

```
<composed prompt on stdin> | codex exec \
  --json \
  --skip-git-repo-check \
  --ephemeral \
  --ignore-user-config \
  -C <cwd> \
  -s <read-only|workspace-write|danger-full-access> \
  --output-schema <schema.json> \
  -m <model> \
  -c model_reasoning_effort=<effort> \
  -
```

| Call field | Flag |
|---|---|
| prompt | stdin, with a trailing `-` argument |
| output_schema | `--output-schema <file>` |
| model | `-m` |
| effort | `-c model_reasoning_effort=<effort>` |
| cwd | `-C` |
| sandbox | `-s` |
| timeout | not a CLI flag; enforced by the runner around the subprocess |

Five details are load-bearing, and each is here because of something
observed rather than assumed:

1. **The prompt goes on stdin.** Passed as an argv string, a prompt
   containing JSON braces and quotes was mangled by the shell before Codex
   ever saw it (`error: unexpected argument 'answer\:\pong\}...'`). A test
   asserts the prompt never appears in argv.
2. **stdout and stderr are captured separately.** Merged, a single stderr
   diagnostic lands inside the JSONL event stream. Unparseable stdout lines
   are skipped rather than treated as failures.
3. **The launcher is resolved through PATHEXT.** On Windows an
   npm-installed CLI is a `.cmd` shim and `CreateProcess` does not apply
   PATHEXT to a bare name; the first live smoke test of this runner failed
   with `WinError 2` for exactly that reason.
4. **`--ignore-user-config` is on by default.** The composed prompt should
   be the only input: a machine's personal configuration is not part of a
   run's record, and an unrelated MCP server failing to authenticate is not
   this run's problem. It also removed several thousand input tokens per
   call.
5. **An error item is not a failed call.** `item.completed` with
   `item.type == "error"` is emitted for non-fatal warnings while the
   process exits zero.

Event stream shape, as observed:

```
{"type":"thread.started","thread_id":"..."}
{"type":"turn.started"}
{"type":"item.completed","item":{"type":"error","message":"..."}}
{"type":"item.completed","item":{"type":"agent_message","text":"{...}"}}
{"type":"turn.completed","usage":{"input_tokens":...,"cached_input_tokens":...,
  "cache_write_input_tokens":...,"output_tokens":...,"reasoning_output_tokens":...}}
```

## Live smoke test

2026-07-31, `codex-cli 0.145.0`, model `gpt-5.6-sol`, effort `low`. A
throwaway connectivity prompt in a temporary scratch directory, sandbox
`read-only`, never against a real repository. Run through `CodexRunner` and
`invoke_validated`, not through a hand-typed command line:

```
status: COMPLETED   reason: clean   attempts: 1
output: {"answer": "pong", "confident": true}
telemetry: {"runner": "codex", "model": "gpt-5.6-sol", "effort": "low",
            "dry": false, "duration_ms": 4943,
            "tokens": {"new_input": 17867, "cached_input": 0,
                       "cache_write_input": 0, "output": 20,
                       "reasoning_output": 0},
            "attempt": 1, "usage_events": 1}
```

What this establishes: the argv contract works, structured output arrives
and validates, telemetry parses with its fields separate. What it does
**not** establish, and no test in this repository does yet: that the effort
override changes model behaviour (the CLI accepted
`-c model_reasoning_effort=low` and exited zero; the effect was not
measured), that a multi-turn call reports usage per turn rather than
cumulatively, or that a schema-violating response from a real model is
recovered by the retry — that path is covered by tests against a fake
runner only.

## Dry runs

`DryRunner` composes and records the call, returns a stub built from the
output schema, and marks its telemetry `dry`. It starts no process at all —
a test asserts this by making `subprocess.run` raise for the duration of
the call. A dry-run envelope carries `dry_run: true`, so nothing downstream
can mistake it for evidence.

## Level 4 is declared, not implemented

The review ladder's level 4 needs a cross-family runner. v0 ships one
runner, so level 4 never runs, and envelopes must say so in `non_claims`
rather than skipping it silently.
