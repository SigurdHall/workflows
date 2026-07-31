# Deviations from the roadmap

Visible deviation beats silent adaptation. Every departure from
[roadmap.md](roadmap.md) or [test-charter.md](test-charter.md) is recorded
here with its reason, in milestone order.

## M0

**D-M0-1 — The acceptance criterion "CI green on an empty test suite" was
over-delivered, not met literally.** The suite ships with 66 tests.
Reason: the second half of the same criterion ("core defs validate example
fixtures") cannot be satisfied by an empty suite, so "empty" is read as
"the scaffold must be green before there is anything to test". The
scaffold was verified green independently: a fresh clone runs
`python -m unittest discover` with no install step, and CI is green on
3.12 and 3.13.

**D-M0-2 — `core.defs.schema.json` defines more `$defs` than the roadmap
bullet enumerates.** Added beyond the list: `identifier` (non-blank
machine identity — closes the blank-identity defect class at the type
level), `timestamp`, `finding_status`, `evidence_kind`,
`evidence_ref_list`, `criterion_outcome`, `side_effect`,
`side_effect_kind`, `contract_ref`, `relative_path`, `path_pattern`,
`git_commit`, `step_kind`, `step_state`, `flow_name`, `verdict_result`,
`ladder_level`, `token_usage`, `telemetry`.
Reason: the enumerated shapes (`finding`, `evidence_ref`, `candidate`)
cannot be expressed without them, and defining them once in the core is
what keeps the M1 schemas from each inventing their own identity and path
rules.

**D-M0-3 — `terminal` is an envelope field, not a core `$def`.**
`concepts/envelope.md` lists `status` "plus `terminal`" among the core
fields. It is a plain boolean with no shared shape to factor out, so it is
declared as a required property of `envelope.schema.json` (M1) rather than
as a core definition. No behaviour is lost; only the location differs.

**D-M0-4 — The two CI workflows were consolidated into one
`.github/workflows/ci.yml`.** The roadmap asks for "CI workflow running
tests + content policy on push"; the previous `content-policy.yml` was
folded into `ci.yml` as a separate job, and the test job runs a 3.12/3.13
matrix so version drift is caught rather than discovered later.

**D-M0-5 — The schema validator checks schema soundness recursively and
unconditionally, which the roadmap did not ask for.** An independent
review found that keyword *shapes* were only checked when an instance
happened to have the matching JSON type, so a schema with an empty `enum`
or a non-boolean `uniqueItems` enforced nothing and raised nothing.
`check_schema` now runs over the whole schema tree — including branches no
instance reaches — at every validation entry point and at schema
registration. Recorded because it enlarges M0's scope; see ADR 0008.

## M1

**D-M1-1 — `src/workflows/paths.py` lands in M1, ahead of the M2 gates
that need it.** Scope and protected-path matching already has three M1
consumers: the task-contract rule that a protected path may not also be
writable, the plan rule that write scopes must be disjoint, and the CLI
that reports both. Writing it once here beats writing it twice.

**D-M1-2 — `examples/plan.example.toml` was added, which the roadmap does
not list.** The plan schema is the only M1 schema whose authoring format
is TOML rather than JSON, so the example doubles as the test that the CLI
parses TOML at all.

**D-M1-3 — Semantic rules are a module (`src/workflows/semantics.py`), not
only the one check the charter names.** The charter requires the
"PASS while carrying an open CRITICAL/HIGH finding" check to live with the
validator. The same category — obligations no schema keyword can express —
covers evidence reference integrity, the negative-path probe rule, vacuous
PASS, disjoint write scopes, and step-lifecycle consistency, so they are
implemented together and reported through the same entry point.

**D-M1-4 — `SchemaRegistry.add` compares schema *content*, not object
identity, when deciding that a key is taken.** Registering the same document
twice — which happens when the CLI is handed a path to a schema that is
already in the registry — used to raise. Re-registering byte-identical
content is now allowed; only genuinely conflicting content under one key
raises. Found by an independent review, which noted that the change of an
M0 behaviour was folded into the M1 commit without being logged.

**D-M1-5 — The schema files moved from `contracts/` to
`src/workflows/contracts/`.** The roadmap names `contracts/core.defs.schema.json`,
and the top-level directory keeps the catalog page, but the files
themselves had to move: a built wheel packaged only the Python modules, so
an installed copy resolved an empty schema registry and validated nothing.
An independent review demonstrated this by building a wheel and running the
CLI from an unrelated directory. The CI job that claimed to prove
cross-repository installability was installing editably from this checkout,
which resolves the schemas back to the source tree and therefore proved
nothing; it now builds a wheel, installs it into a separate virtual
environment, and validates a document from a directory with no checkout in
it — including a case that must exit nonzero.

## M2

**D-M2-1 — Python lives in `src/workflows/`; the top-level `gates/`,
`flows/`, `runners/` and `program/` directories are documentation.** The
README's original layout listed those directories next to `scripts/` as if
they held code, while the M0 roadmap bullet mandates the package skeleton
under `src/`. One importable package is what lets a consuming repository
install this and run the same gates; the top-level directories keep the
definitions and the catalogs. The README layout now says so, and
`flows/README.md` was corrected.

**D-M2-2 — A `gate-result.schema.json` was added, which the roadmap does
not name.** The acceptance criterion says gate results must "validate
against the envelope fragment schema", and no such schema existed. It adds
a `reason_code` enum, which is what makes the charter's requirement
checkable that a missing verification command "fails closed with a distinct
reason" rather than being reported as skipped or green.

**D-M2-3 — `src/workflows/runs.py` lands in M2, ahead of the M4 resume
machinery.** The gate runner has to write results to the run directory, so
the run directory has to exist. It implements the append-only artifact
discipline and the atomically-rewritten manifest now; step scheduling and
resume arrive with the flows.

**D-M2-4 — The `evidence_obligations` gate reports `INCONCLUSIVE` for
`number_traceable` and `manual_judgment` obligations.** Neither can be
settled by a deterministic check, and reporting them as PASS or silently
skipping them would let a goal be declared attained on the strength of
gates alone. They come back `requires_judgment`, named individually in the
result's non-claims. Whether `number_traceable` deserves a real
deterministic implementation is deferred to M7, where `assure` goal mode
consumes it. Superseded in M7 by D-M7-1: the gate reports NOT_RUN per
obligation and PASS overall, because there is no check to run rather than a
check that could not conclude.

## M3

**D-M3-1 — Prompt composition and lens loading landed in M3, ahead of the
M4 bullet that names the lens starter set.** The roadmap's M3 acceptance
criterion is "composition determinism", which cannot be tested without a
composer and something to compose. The lens *files* still arrive in M4;
what M3 adds is the loader, the format check, and the composer.

**D-M3-2 — Reviewer blindness is enforced by a function signature.** The
charter tests it as a string assertion on the composed prompt. The prompt
module goes further: `prompts.review` has no parameter through which worker
or synthesizer dialogue could be passed, and a test asserts the signature
itself. A string assertion catches a leak after someone adds the parameter;
this catches the parameter.

**D-M3-3 — Token usage for one call is the final usage figure, never a
sum.** The charter forbids adding cumulative and per-turn figures together
but does not say which to keep. The runner keeps the last and records how
many usage events it saw, so an undercount is visible in the record rather
than silent. Whether a multi-turn Codex call reports per-turn or cumulative
figures is an open question, stated as such in `runners/README.md`.

**D-M3-4 — The launcher is resolved with `shutil.which`.** Not in the
roadmap, but the first live smoke test failed with `WinError 2` because an
npm-installed CLI on Windows is a `.cmd` shim and `CreateProcess` does not
apply PATHEXT to a bare name.

## M4

**D-M4-1 — The lens files live in `src/workflows/lenses/`, not `lenses/`.**
Same reason as the schemas (D-M1-5): a prompt composed without its lens is
a different prompt, so the data ships inside the package. The top-level
`lenses/` directory keeps the catalog page.

**D-M4-2 — Two schemas the roadmap does not name: `work-result` and
`review-result`.** A model returns a *result*; the driver builds the
envelope. Without a schema for what a model may return there is nothing for
the runner's structured-output contract to validate against, and envelopes
would be hand-authored by models — which ADR 0001 forbids.

**D-M4-3 — A dry run may never report PASS.** The roadmap asks only that
`--dry-run` call no model. Since the dry runner returns a schema-shaped
stub, a flow would otherwise conclude PASS from stubs. Any dry-run verdict
that would have passed is reported INCONCLUSIVE with a non-claim saying
nothing was judged.

**D-M4-4 — A review step that *fails* ends the flow BLOCKED rather than
triggering a repair round.** A failed call produced no judgment, so there
is nothing to repair and nothing to escalate. Repair rounds are for
findings, not for transport failures.

**D-M4-5 — Verdict ids are namespaced by the step that produced them, and
superseded rounds are marked RESOLVED rather than dropped.** Two rounds of
review legitimately both produce a finding called `F-1` pointing at their
own `probe-1`; folding them together unnamespaced made one round's claim
resolve to the other round's evidence. Findings from a round a later repair
answered stay in the record as RESOLVED — what a repair fixed is part of
what happened.

**D-M4-6 — The flow CLI refuses to start when its run directory is visible
to git inside the worktree.** Found by the first end-to-end dry run: the
run wrote its own files into the worktree it was judging, and the
base-identity gate correctly reported the worktree dirty. The gate was
right; the configuration was wrong, and the flow now says so before any
model is called.

**D-M4-7 — Gate results are written per step, not per gate.** The same gate
runs several times in a flow — before the work, after it, and again after
each repair — and run artifacts are append-only, so a single
`gates/<gate>.json` path made the second run of a gate fail outright. Found
by the first flow test, not by reasoning.

## M5

**D-M5-1 — Fan-out defaults to sequential workers.** The roadmap says "N
parallel worker calls"; the isolation requirement it states — per-worker
worktrees, never a shared write target — is what makes the result correct,
and concurrency only changes wall-clock. `max_parallel_workers` defaults to
1 so a run is reproducible by default, and a plan raises it. Worktree
creation stays serialized at any width: parallel creation is how you meet
`packed-refs.lock`.

**D-M5-2 — The dryness stop rule is implemented and tested but not wired
into the fan-out flow.** The roadmap scopes v0's width to a plan parameter
and asks for the dryness rule "for the iterative variant", which v0 does
not ship. `flows/dryness.py` implements and tests it — including the
charter's case that one lens returning empty twice is not two dry rounds —
and every fan-out verdict carries a non-claim saying the width was chosen,
not measured, so a plan parameter cannot read as a coverage claim.

**D-M5-3 — Duplicate lens ids in a fan-out lens set collapse to one
worker.** A worker's step id derives from its lens, and step ids are the
resume key. Listing a lens twice therefore produces one worker, not two —
which matches the design intent (the same perspective twice is not
breadth), but is worth stating because a plan author might expect two.

**D-M5-5 — Six rules added after an independent review of M4, none of them
in the roadmap.** All six were counter-examples the review executed against
the frozen M4 commit, not hypotheticals:

1. A step whose envelope reached disk before its manifest record was
   re-invoked on resume — and for a repair step, the worktree was reset
   first, destroying work that was already done. The artifact now wins over
   the index.
2. Resuming a run with a different contract or base was silently accepted,
   so gates ran against one contract while every envelope was stamped with
   another. Both are compared against the manifest and refused.
3. A review could raise a CRITICAL finding, mark it `ACCEPTED_RISK` itself,
   and return PASS — the model under judgment clearing its own worst
   finding. A review result may now only emit findings as OPEN.
4. A PASS with an empty `criterion_results` validated cleanly: a judgment
   about nothing. `pass_without_criteria` rejects it.
5. An untouched worktree passed every gate for free. The
   `candidate_changed` gate closes it.
6. A level-1 review returning INCONCLUSIVE did not escalate, so the one
   answer that says nothing was the one that stopped the ladder.

Two smaller consequences: a producing step's envelope now reports
`NOT_RUN` rather than `PASS`, because a producer evaluates no criterion;
and re-running a finished run returns its recorded verdict instead of
writing a second one.

**D-M5-4 — Worker worktrees are never removed automatically.** A killed
run's worktrees are exactly what a resumed run reuses, so cleanup is an
explicit call (`fanout.cleanup_worktrees`) rather than a `finally` block
that would make every kill unresumable.

## M6

**D-M6-1 — The checkpoint is a flag, not a prompt.** The roadmap says
"single approval checkpoint". An interactive prompt cannot run in CI and
cannot be scripted, so `program run plan.toml` resolves and prints, and the
same command with `--approve` executes. The approval is a deliberate human
act either way, and it happens exactly once per program.

**D-M6-2 — A token budget counts new input plus output; cached input is
reported but not charged.** The roadmap says budgets are "enforced from
telemetry" without saying what counts. Charging cached input would stop runs
that cost little, and the repository's own design note is that an aggregate
mixing cached and new input overstates cost several-fold.

**D-M6-3 — Every execution writes a numbered report
(`reports/1.json`, `reports/2.json`, …).** The roadmap says "consolidated
report", singular. Run artifacts are append-only, and a resume that
completed more tasks has something new to say; overwriting the first report
would erase what the program knew when it stopped.

**D-M6-4 — A resume re-reads the original plan file rather than the copy in
the run.** Contract paths are relative to the plan file, so the copy cannot
resolve them. The digest of the original is compared against the one
recorded at run start, so a plan edited after approval is refused rather
than silently executed.

**D-M6-5 — `examples/contracts/` was added.** The example plan referenced
contract files that did not exist, so it validated against the schema but
could not resolve. Three generic contracts make the example plan runnable
end to end, which is what the v0 acceptance criterion asks for.

## M7

**D-M7-1 — The `evidence_obligations` gate now reports PASS with NOT_RUN
sub-checks, where it previously reported INCONCLUSIVE.** A goal contract's
`manual_judgment` obligation has no check to run, so the gate did not fail
to conclude — there was nothing to conclude. Reporting the whole gate
INCONCLUSIVE overstated its scope and made every goal verdict unpassable
while hiding what the gate did settle. The gate now passes on the half it
checks and names the half it left to judgment, and the verdict carries the
oracle-strength non-claims.

**D-M7-2 — Two schemas the roadmap does not name: `adjudication-result`
and `attainment-result`.** Same reason as M4's work/review results: a model
returns a result and the driver builds the envelope, so each model role
needs a schema for what it may return.

**D-M7-3 — Adjudication matches findings on location and claim, ignoring
severity.** Two reviewers naming the same defect at different severities
are having a calibration disagreement, not raising two findings; keying on
severity turned one dispute into two, neither of which was the real one.

**D-M7-4 — Verdicts now aggregate criterion results from every envelope,
not only from review envelopes.** Goal mode needs the gate's per-obligation
outcomes and the model's per-subgoal judgments side by side, which is what
"separating checked from judged" means in practice. Task flows gain gate
outcomes in their verdicts, which is an improvement rather than a cost.
