# Benchmark task domains

Task archetypes for the `benchmark` corpus (see `test-charter.md`, M8).
The corpus should mirror real consulting work — BI/analytics engineering
and agent engineering alike — not just abstract coding katas, and it
must span the full oracle spectrum, because the review ladder and the
two contract types (ADR 0007) are only validated by tasks of every
oracle strength. All fixtures are synthetic and generic.

Domains are grouped by oracle tier.

## Tier A — deterministic oracle (task contracts)

Full gate coverage: tests, scope, hashes decide.

| Archetype | Deliverable | Typical planted defects |
|---|---|---|
| Measure logic | DAX measures: variance, percent variance, as-of / period-to-date time intelligence, safe division, explicit blank-vs-zero policy | 11, 13, 14, plus classes 1, 9 |
| Semantic model construction | Star schema from a flat extract: fact/dimension split, keys, cardinality, relationship directions | 12, plus classes 6, 10 |
| Calculated tables and calendars | Calendar/date tables, calculation groups, period logic | 13, 15, plus classes 2, 7 |
| Report definition as code | Report-page JSON (PBIR-style): visual configs, measure bindings, bookmarks, themes | 16, plus classes 4, 8, 10 |
| Data transformation | Source-to-model mapping (CSV → dimensions/facts), incremental snapshot idempotence | plus classes 3, 6, 7, 8 |
| Diagnosis | A model/report fixture with one planted root cause; the prompt describes only the customer-visible symptom ("the YTD card shows wrong numbers in January"); the deliverable is cause + minimal fix | any class above — the answer key *is* the planted cause |
| Information triage | Classify and route a batch of synthetic items (messages, findings, feed entries) against a closed category contract, with a hidden answer key | 17, plus classes 3, 6 |
| Structured extraction | Pull typed fields from messy text into a closed schema, rejecting what does not fit | plus classes 4, 6, 7 |

The diagnosis archetype is the deterministic form of "solving customer
issues": recall and precision are measurable exactly like reviewer
recall, because the true cause is known and hidden. Triage and
extraction are the deterministic core of information-sorting agent
work for the same reason.

## Tier B — hybrid oracle (task contract + judged rubric)

The structural part is gated deterministically; the quality part is
judged. Envelopes must separate the two (checked vs judged).

| Archetype | Deterministic part | Judged part |
|---|---|---|
| Dashboard components (React/TS) | Model/logic tests, type checks, a11y attribute presence, contract closure | Layout sanity, interaction quality |
| Data-story structure ("BI copy") | Every claim binds to an existing measure/field; structure schema-valid; numbers reproducible from the fixture | Narrative arc, audience fit, emphasis choices |
| Incremental improvement | Full regression suite stays green; scope and protected files intact | Whether the "improvement" actually improved anything |
| Skill/instruction authoring | Frontmatter schema-valid; referenced paths exist; trigger description scored against a *hidden phrasing set* (routing recall/precision on requests that should and should not trigger it) | Procedural clarity, right altitude of detail |
| Prompt rewriting | Constraint checklist; output-format compliance measured on fixture inputs | Clarity, economy, robustness of wording |

Incremental improvement is the benchmark form of
incremental-creativity work: the deterministic half asserts nothing
broke; the judged half rates the delta. The hidden phrasing set does
the same for skill authoring: whether a description routes correctly
is an empirical question, not a matter of taste.

## Tier C — weak oracle (goal contracts)

Judged with evidence obligations; exercised by `assure` in goal mode.

- Requirements-to-spec: turn a deliberately vague customer request into
  a report specification (audience, pages, measures, open questions).
- Customer-issue response: given a diagnosis, produce the client-facing
  explanation with options, trade-offs, and a recommendation.
- Agent-workflow design: turn a loose automation goal into a workflow
  plan (roles, gates, escalation points, what stays human).

## Domain defect-class extensions

Extending the base taxonomy (classes 1–10 in `test-charter.md`):

11. **Aggregation misuse** — a non-additive measure aggregated
    additively (sum of ratios where ratio of sums is required; averages
    of averages).
12. **Filter-context leak** — a measure silently ignoring or overriding
    the filter context it is documented to respect.
13. **Time-boundary error** — as-of / period boundaries off by one;
    year-start, leap-day, and week-53 edges mishandled.
14. **Blank/zero conflation** — missing data treated as zero (or the
    reverse), silently changing rates, averages, and rankings.
15. **Nondeterministic ties** — ranking/top-N unstable under equal
    values; result order changes between runs.
16. **Unit/scale drift** — thousands vs units, percent vs fraction, or
    currency scale mixed silently across measures or visuals.
17. **Trigger mismatch** — a skill/router description that over- or
    under-matches its hidden phrasing set: fires on requests it should
    not own, or misses phrasings it should.
18. **Instruction conflict** — a new instruction silently contradicting
    an existing rule in the same instruction corpus.
19. **Context bloat** — instructions that duplicate context already
    available to the agent, or mandate unbounded enumeration where
    filtered access exists.
20. **Unverifiable imperative** — an instruction with no observable
    success criterion, unfalsifiable by construction.

Classes 11–16 are the BI analogues and 17–20 the agent-engineering
analogues of the base classes, and they earn their place the same way:
each is a defect that plausibly survives green happy-path tests and
demands either a targeted probe or a domain-aware review lens.

## Measuring judged quality

Judged rubrics are the weak point of Tier B/C, so the scorer needs
anchors that do not depend on trusting one judge's absolute score:

- **Known-worse variants.** For each creative fixture, the corpus also
  contains one or more deliberately degraded variants (buried lede,
  claim/number mismatch, wrong audience register). A judge — model or
  ladder level — is measured on *detection*: does it rank the intact
  artifact above every degraded one? This turns quality judgment into a
  recall task with a hidden answer key.
- **Pairwise, not absolute.** Judged comparisons are pairwise A/B with
  randomized order, never absolute scores — absolute scoring rewards
  leniency (an observed reviewer failure mode).
- **Rubric per contract.** The attainment rubric lives in the goal
  contract (ADR 0007), and judged envelopes carry mandatory non-claims
  about oracle strength.

## Relation to lenses

Domain fixtures exercise the *generic* review lenses — aggregation
misuse falls to a semantics/canonicalization lens, filter-context leaks
to a closed-contract lens, tie instability to a determinism lens. If a
domain class chronically escapes every existing lens in benchmark runs,
that is the evidence-driven trigger for authoring a new lens file
(ADR 0002), not for making lenses task-specific.
