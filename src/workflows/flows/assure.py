"""The `assure` flow, candidate mode: review without producing.

Work that arrived from somewhere else — a human, another tool, an earlier
run — still gets the same treatment: level-0 gates first, then the review
ladder, then one verdict. There is no producing step and no repair, so a
FAIL here is a report, not a retry.

Goal mode (a goal contract's evidence obligations rather than a candidate)
arrives with M7.
"""

from __future__ import annotations

from typing import Any, Sequence

from workflows import prompts
from workflows.flows import base, ladder, review
from workflows.flows.base import FlowContext
from workflows.schema import ValidationError

FLOW = "assure"
GOAL_LENS = "review/goal-attainment"
ATTAINMENT_RESULT_SCHEMA = "attainment-result.schema.json"
EVIDENCE_GATES = ("evidence_obligations",)


def run(context: FlowContext) -> dict[str, Any]:
    """Candidate mode, or goal mode when the contract is a goal contract."""
    if context.contract.get("contract_type") == "goal":
        return run_goal_mode(context)
    return run_candidate_mode(context)


def run_candidate_mode(context: FlowContext) -> dict[str, Any]:
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


def run_goal_mode(context: FlowContext) -> dict[str, Any]:
    """A goal contract: evidence-obligation gates, then an attainment review.

    Goal contracts are second-class on certainty and this flow never pretends
    otherwise. The gate settles what a deterministic check can settle —
    deliverables exist, references resolve — and the model judges the rest.
    The verdict names which obligations fell in which half, because "the
    obligations were met" and "the goal was achieved" are different claims.
    """
    envelopes: list[dict[str, Any]] = []
    gate_envelope = base.gate_step(
        context, "gates-evidence", EVIDENCE_GATES, require_clean=False
    )
    envelopes.append(gate_envelope)

    checked = [
        outcome
        for outcome in gate_envelope["criterion_results"]
        if outcome["criterion_id"].startswith("evidence_obligations/")
    ]
    deterministic = [
        outcome["criterion_id"].split("/", 1)[1]
        for outcome in checked
        if outcome["result"] in ("PASS", "FAIL")
    ]
    left_to_judgment = [
        outcome["criterion_id"].split("/", 1)[1]
        for outcome in checked
        if outcome["result"] == "NOT_RUN"
    ]

    non_claims = [
        "A goal contract has no deterministic oracle. "
        f"{len(deterministic)} obligation(s) were settled by a gate; "
        f"{len(left_to_judgment)} were left to a model's judgment"
        + (": " + ", ".join(left_to_judgment) if left_to_judgment else "")
        + ".",
        "An obligation met is not a goal achieved: this flow checks that "
        "deliverables exist and references resolve, and judges the rest.",
        ladder.LEVEL_4_NON_CLAIM,
    ]

    if gate_envelope["result"] == "FAIL":
        non_claims.insert(
            0,
            "No model judged attainment: the evidence obligations are unmet, "
            "so there was nothing traceable to judge against.",
        )
        return _verdict(
            context,
            result="FAIL",
            envelopes=envelopes,
            levels_run=[0],
            candidate=None,
            extra_non_claims=non_claims,
        )

    step_id = "attainment"
    lens = context.lens(GOAL_LENS)
    prompt = prompts.attainment(
        contract=context.contract,
        lens=lens,
        output_schema=context.schemas().get(ATTAINMENT_RESULT_SCHEMA),
        checked=checked,
        focus_hint=context.focus_hint,
    )
    attainment_envelope = base.model_step(
        context,
        step_id,
        kind="review",
        role="review-1",
        prompt=prompt,
        output_schema_ref=ATTAINMENT_RESULT_SCHEMA,
        lens_id=GOAL_LENS,
        ladder_level=1,
        extra_validator=_attainment_rules(context),
        envelope_from=lambda output: _attainment_envelope(context, step_id, output),
    )
    envelopes.append(attainment_envelope)

    if attainment_envelope["status"] != "COMPLETED":
        non_claims.insert(
            0,
            "The attainment review failed rather than concluding, so nothing "
            "was judged about this goal.",
        )
        return _verdict(
            context,
            result="BLOCKED",
            envelopes=envelopes,
            levels_run=[0, 1],
            candidate=None,
            extra_non_claims=non_claims,
        )

    level = attainment_envelope.get("notes")
    if level:
        non_claims.append(f"Attainment graded against this contract's own rubric: {level}.")
    blocking = ladder.blocking_findings(envelopes, context.escalation.level_2_on_severity)
    result = "PASS" if attainment_envelope["result"] == "PASS" and not blocking else "FAIL"
    return _verdict(
        context,
        result=result,
        envelopes=envelopes,
        levels_run=[0, 1],
        candidate=None,
        extra_non_claims=non_claims,
    )


def _attainment_rules(context: FlowContext) -> Any:
    """Rules the schema cannot state about a goal judgment."""
    contract = context.contract
    levels = {
        level["id"] for level in contract.get("attainment_rubric", {}).get("levels", [])
    }
    subgoals = {subgoal["id"] for subgoal in contract.get("subgoals", [])}

    def validate(output: dict[str, Any]) -> list[ValidationError]:
        errors: list[ValidationError] = []
        if output.get("attainment_level") not in levels:
            errors.append(
                ValidationError(
                    "/attainment_level",
                    "semantic:grade_outside_the_rubric",
                    "the grade must be one of this contract's own rubric level "
                    f"ids: {', '.join(sorted(levels))}",
                )
            )
        judged = {entry["subgoal_id"] for entry in output.get("judged", [])}
        missing = sorted(subgoals - judged)
        if missing:
            errors.append(
                ValidationError(
                    "/judged",
                    "semantic:subgoal_not_judged",
                    "every subgoal must be judged, including the ones with no "
                    "supporting evidence; missing: " + ", ".join(missing),
                )
            )
        unknown = sorted(judged - subgoals)
        if unknown:
            errors.append(
                ValidationError(
                    "/judged",
                    "semantic:unknown_subgoal",
                    "these are not subgoals of this contract: " + ", ".join(unknown),
                )
            )
        declared = {item["id"] for item in output.get("evidence", [])}
        for index, entry in enumerate(output.get("judged", [])):
            refs = entry.get("evidence_refs", [])
            for ref in refs:
                if ref not in declared:
                    errors.append(
                        ValidationError(
                            f"/judged/{index}/evidence_refs",
                            "semantic:unknown_evidence_ref",
                            f"{ref!r} is not declared in this document's evidence",
                        )
                    )
            if entry.get("met") == "PASS" and not refs:
                errors.append(
                    ValidationError(
                        f"/judged/{index}/evidence_refs",
                        "semantic:pass_requires_evidence",
                        "a subgoal judged met with nothing pointing at it is "
                        "vacuous success",
                    )
                )
        return errors

    return validate


def _attainment_envelope(
    context: FlowContext, step_id: str, output: dict[str, Any]
) -> dict[str, Any]:
    judged = output.get("judged", [])
    results = {entry["met"] for entry in judged}
    if "FAIL" in results:
        result = "FAIL"
    elif "INCONCLUSIVE" in results or "NOT_RUN" in results:
        result = "INCONCLUSIVE"
    else:
        result = "PASS"
    envelope: dict[str, Any] = {
        "schema_version": "workflows.envelope.v1",
        "envelope_id": f"{context.run_id}/{step_id}",
        "run_id": context.run_id,
        "step_id": step_id,
        "step_kind": "review",
        "status": "COMPLETED",
        "terminal": True,
        "result": result,
        "dry_run": context.dry_run,
        "produced_at": context.now(),
        "contract_ref": context.contract_ref,
        "ladder_level": 1,
        "lens_id": GOAL_LENS,
        "evidence": list(output.get("evidence", [])),
        "criterion_results": [
            {
                "criterion_id": entry["subgoal_id"],
                "result": entry["met"],
                "evidence_refs": list(entry.get("evidence_refs", [])),
                "negative_path_claim": False,
                "note": entry["assessment"][:2000],
            }
            for entry in judged
        ],
        "findings": list(output.get("findings", [])),
        "non_claims": list(output.get("non_claims", []))
        + [
            "Judged, not checked: nothing here was settled by a hash or a "
            "command, and a goal contract's gates are weaker than a task "
            "contract's by design.",
        ],
        "side_effects": [{"kind": "none", "target": "none"}],
        "notes": output.get("attainment_level", ""),
    }
    return envelope


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
