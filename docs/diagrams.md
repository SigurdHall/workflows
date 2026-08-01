# Flow diagrams

One diagram per flow. A diagram is a rendered *view of this file*,
regenerated on demand — never a checked-in image, because a picture that can
drift from the code is documentation that lies with confidence. This file is
the source: the grammar says how to draw, the canonical contents say what
each flow's diagram must contain. Any renderer that honors both produces a
correct diagram.

## The grammar

- **A box is a step**: a title plus a subtitle of at most five words. What
  does not fit in five words belongs in prose, not in the box.
- **Color names the actor, and only the actor.** Four families:
  - *amber* — a human acts here
  - *gray* — deterministic code (gates, resolution, scoring, enumeration)
  - *teal* — a model producing (workers, synthesis, repair, lineages)
  - *blue* — a model judging (reviewers, judges, adjudicators, directors)
  Every diagram carries a one-line legend of the families it actually uses.
- **A dashed container is an autonomous region**: no human inside it. Label
  it with what repeats ("round n — no human").
- **A solid arrow is sequence within one run. A dashed arrow is inheritance
  across runs** (a corpus, an archive, a rubric carried forward).
- **A loop arrow is a bounded retry** — repair rounds, escalation. The bound
  goes in the subtitle, because an unbounded loop drawn without its bound is
  a promise the code does not make.
- Sentence case everywhere, including titles.

## Rendering notes

In-conversation renderers with a class-based palette: color families map to
`c-amber`, `c-gray`, `c-teal`, `c-blue`; boxes take a light fill with a
strong stroke (`fill-50` + `stroke-600`); text uses the title/subtitle
classes (`th`/`ts`), minimum 11px, weights 400 and 500 only. Standalone SVG:
pick equivalent hues and verify both light and dark backgrounds. Layout is
the renderer's choice; content is not.

## Canonical contents, per flow

Each list names the required boxes as `actor: title — subtitle`, then the
required edges. A diagram may add layout, never steps.

### implement

- gray: contract — goal, scope, protected, verification
- gray: pre-gates — base identity, command runs
- teal: worker — one worktree, frozen base
- gray: post-gates — scope, protected, changed, tests
- blue: review ladder — blind, escalates on signal
- teal: repair — targeted, bounded rounds
- gray: verdict — with non-claims

Edges: contract → pre-gates → worker → post-gates → ladder → verdict;
loop ladder → repair → post-gates (bounded).

### fanout

- gray: contract — weak oracle, wide surface
- teal: lens workers ×N — own worktrees, blind to each other
- teal: synthesis — sees candidates, not reasoning
- gray: post-gates — scope, protected, changed, tests
- blue: review ladder — blind, escalates on signal
- gray: verdict — width is asserted, it says so

Edges: contract → workers (parallel) → synthesis → post-gates → ladder →
verdict; repair loop as in implement.

### assure

- gray: a candidate exists — produced elsewhere, judged here
- fork by contract type:
  - candidate mode — gray: gates (not required clean) → blue: review ladder
    → gray: verdict — FAIL is a report, not a retry
  - goal mode — gray: evidence-obligation gate — settles what code can →
    blue: judged against the contract's rubric → gray: verdict — obligation
    met is not goal achieved

### adjudicate

- gray: two conflicting envelopes — authorship stripped first
- gray: claims enumerated by code — never summarized by a model
- blue: adjudicator — every claim needs an executed probe
- gray: outcomes — settled, or UNRESOLVED as an answer

Edges: envelopes → enumeration → adjudicator → outcomes.

### benchmark

- gray: corpus — seeds, hidden key, presence probes
- gray: materialize — one frozen commit, ignore file
- gray: cells — flow × model × effort × width
- teal: each cell runs a live flow — through the program level
- gray: presence probes — present, removed, indeterminate
- gray: score — recall is caught over present

Edges: corpus → materialize → cells → live flow → probes → score.

### program

- gray: plan — N tasks, budgets, escalation
- gray: resolve — write scope must equal contract scope
- amber: approve — the single checkpoint
- dashed container "execution — stops only on signal":
  - teal: task × flow — own worktree each, parallel
  - gray: signals — budget, severity, stop
- gray: consolidated report — one, with non-claims

Edges: plan → resolve → approve → tasks → report; signals sit beside tasks.

### evolve

- amber: ratify the rubric — what better means
- dashed container "round n — no human":
  - teal: spread — lens lineages, fresh starts, a reframe
  - teal: produce — parallel lineages, own worktrees
  - blue: tournament — blind, pairwise, first separating criterion
  - blue: direct — critique becomes next round's lenses
- gray: finalists — champion plus best per lineage
- amber: the owner picks — an override induces a rule
- gray: judgment corpus — rubric, lenses, tournament logs

Edges: ratify → round; round cycles spread → produce → tournament → direct →
spread; exit "two rounds without a new champion" → finalists → pick →
corpus; dashed edge corpus → next run's round.
