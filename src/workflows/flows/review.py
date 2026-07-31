"""The review ladder as a runnable sub-step, shared by every flow.

Level 0 has already run when this starts — a reviewer must never be the
first thing to see a candidate a gate could have rejected. From there the
ladder climbs only on signal, and a PASS at any level stops it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from workflows import prompts
from workflows.flows import base, ladder
from workflows.flows.base import FlowContext

DEFAULT_REVIEW_LENSES = ("review/closed-contract",)


@dataclass
class LadderOutcome:
    envelopes: list[dict[str, Any]] = field(default_factory=list)
    levels_run: list[int] = field(default_factory=lambda: [0])
    escalations: list[str] = field(default_factory=list)
    failed: bool = False

    @property
    def result(self) -> str:
        return ladder.combined_result(
            [e for e in self.envelopes if e.get("step_kind") == "review"]
        )

    @property
    def findings(self) -> list[dict[str, Any]]:
        return [
            finding
            for envelope in self.envelopes
            for finding in envelope.get("findings", [])
        ]

    @property
    def open_findings(self) -> list[dict[str, Any]]:
        return ladder.open_findings(self.envelopes)


def _review_call(
    context: FlowContext,
    *,
    step_id: str,
    lens_id: str,
    level: int,
    candidate: dict[str, Any],
    diff: str,
    attempt: int,
) -> dict[str, Any]:
    lens = context.lens(lens_id)
    prompt = prompts.review(
        contract=context.contract,
        lens=lens,
        output_schema=context.schemas().get(base.REVIEW_RESULT_SCHEMA),
        candidate=diff,
        focus_hint=context.focus_hint,
    )
    return base.model_step(
        context,
        step_id,
        kind="review",
        role=ladder.LEVEL_ROLES[level],
        prompt=prompt,
        output_schema_ref=base.REVIEW_RESULT_SCHEMA,
        lens_id=lens_id,
        ladder_level=level,
        extra_validator=base.review_result_validator(
            context, ladder_level=level, lens_id=lens_id
        ),
        envelope_from=lambda output: base.review_envelope(
            context,
            step_id,
            output,
            lens_id=lens_id,
            ladder_level=level,
            candidate=candidate,
        ),
        attempt=attempt,
    )


def run_ladder(
    context: FlowContext,
    *,
    candidate: dict[str, Any],
    diff: str,
    gate_result: str,
    round_index: int = 0,
) -> LadderOutcome:
    """Level 1 always; levels 2 and 3 on signal; level 4 declared, not run."""
    outcome = LadderOutcome()
    review_lenses = context.review_lenses or DEFAULT_REVIEW_LENSES
    suffix = f"r{round_index}"

    level_1: list[dict[str, Any]] = []
    for lens_id in review_lenses:
        envelope = _review_call(
            context,
            step_id=f"review-l1-{lens_id.split('/')[-1]}-{suffix}",
            lens_id=lens_id,
            level=1,
            candidate=candidate,
            diff=diff,
            attempt=round_index + 1,
        )
        level_1.append(envelope)
    outcome.envelopes.extend(level_1)
    outcome.levels_run.append(1)

    if any(envelope.get("status") != "COMPLETED" for envelope in level_1):
        # A step that failed produced no judgment. Escalating on it would be
        # escalating on nothing.
        outcome.failed = True
        return outcome

    reason = ladder.escalate_to_level_2(level_1, gate_result, context.escalation)
    if reason is None:
        return outcome
    outcome.escalations.append(f"level 2: {reason}")

    level_2 = [
        _review_call(
            context,
            step_id=f"review-l2-{suffix}",
            lens_id=review_lenses[0],
            level=2,
            candidate=candidate,
            diff=diff,
            attempt=round_index + 1,
        )
    ]
    outcome.envelopes.extend(level_2)
    outcome.levels_run.append(2)

    conflict = ladder.escalate_to_level_3(level_1, level_2, context.escalation)
    if conflict is None:
        return outcome
    outcome.escalations.append(f"level 3: {conflict}")

    level_3 = [
        _review_call(
            context,
            step_id=f"review-l3-{suffix}",
            lens_id=review_lenses[0],
            level=3,
            candidate=candidate,
            diff=diff,
            attempt=round_index + 1,
        )
    ]
    outcome.envelopes.extend(level_3)
    outcome.levels_run.append(3)
    return outcome


def ladder_non_claims(outcome: LadderOutcome) -> list[str]:
    """What a ladder that stopped early does not claim."""
    claims = [ladder.LEVEL_4_NON_CLAIM]
    unreached = [level for level in (2, 3) if level not in outcome.levels_run]
    if unreached:
        claims.append(
            "Ladder level(s) "
            + ", ".join(str(level) for level in unreached)
            + " did not run: no signal called for them, so severity was not "
            "independently calibrated."
        )
    return claims
