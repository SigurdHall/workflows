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
