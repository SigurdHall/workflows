"""The `assure` flow, candidate mode: review without producing.

Work that arrived from somewhere else — a human, another tool, an earlier
run — still gets the same treatment: level-0 gates first, then the review
ladder, then one verdict. There is no producing step and no repair, so a
FAIL here is a report, not a retry.

Goal mode (a goal contract's evidence obligations rather than a candidate)
arrives with M7.
"""

from __future__ import annotations

from typing import Any

from workflows.flows import base, ladder, review
from workflows.flows.base import FlowContext

FLOW = "assure"


def run(context: FlowContext) -> dict[str, Any]:
    """Gates, then the ladder, against a candidate this flow did not build."""
    envelopes: list[dict[str, Any]] = []
    levels_run: list[int] = [0]

    diff = base.candidate_diff(context)
    candidate = base.candidate_identity(context, diff)

    gate_envelope = base.gate_step(
        context,
        "gates-candidate",
        context.post_gates,
        require_clean=False,
        candidate=candidate,
    )
    envelopes.append(gate_envelope)

    non_claims: list[str] = [
        "This flow produced nothing and repaired nothing; it judges a "
        "candidate it did not build.",
    ]

    if gate_envelope["result"] == "FAIL":
        non_claims.append(
            "No model reviewed this candidate: it is not gate-clean, and "
            "reviewers only see gate-clean work."
        )
        non_claims.append(ladder.LEVEL_4_NON_CLAIM)
        return _verdict(
            context,
            result="FAIL",
            envelopes=envelopes,
            levels_run=levels_run,
            candidate=candidate,
            extra_non_claims=non_claims,
        )

    outcome = review.run_ladder(
        context,
        candidate=candidate,
        diff=diff,
        gate_result=gate_envelope["result"],
    )
    envelopes.extend(outcome.envelopes)
    levels_run.extend(outcome.levels_run)
    non_claims.extend(review.ladder_non_claims(outcome))
    if outcome.failed:
        non_claims.append(
            "A review step failed rather than concluding, so this candidate "
            "was never judged. A failed call is not a finding."
        )
        return _verdict(
            context,
            result="BLOCKED",
            envelopes=envelopes,
            levels_run=levels_run,
            candidate=candidate,
            extra_non_claims=non_claims,
        )
    if outcome.escalations:
        non_claims.append("Escalations recorded: " + "; ".join(outcome.escalations) + ".")

    blocking = ladder.blocking_findings(
        envelopes, context.escalation.level_2_on_severity
    )
    passed = outcome.result == "PASS" and not blocking
    return _verdict(
        context,
        result="PASS" if passed else "FAIL",
        envelopes=envelopes,
        levels_run=levels_run,
        candidate=candidate,
        extra_non_claims=non_claims,
    )


def _verdict(
    context: FlowContext,
    *,
    result: str,
    envelopes: list[dict[str, Any]],
    levels_run: list[int],
    candidate: dict[str, Any] | None,
    extra_non_claims: list[str],
) -> dict[str, Any]:
    document = base.verdict(
        context,
        flow=FLOW,
        result=result,
        envelopes=envelopes,
        ladder_levels_run=levels_run,
        candidate=candidate,
        extra_non_claims=extra_non_claims,
    )
    return base.write_verdict(context, document)
