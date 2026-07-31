"""The `adjudicate` flow: two conflicting envelopes in, one resolution out.

Adjudication is not a vote on which reviewer argued better. Every disputed
claim is enumerated by code — not by a model summarising the disagreement —
and each one must be settled by a probe the adjudicator ran. A claim no
probe can settle comes back UNRESOLVED, which is an answer.

The claims reach the adjudicator stripped of authorship. Knowing which
reviewer said what invites deciding by reputation, and reputation is exactly
what the motivating experiments showed to be uncorrelated with being right:
the larger model scored more generously, found nothing unique, and asserted
an unprobed property on the one candidate where it was false.
"""

from __future__ import annotations

from typing import Any, Sequence

from workflows import prompts
from workflows.flows import base, ladder
from workflows.flows.base import FlowContext, FlowError
from workflows.schema import ValidationError

FLOW = "adjudicate"
ADJUDICATION_LENS = "review/adjudication"
ADJUDICATION_RESULT_SCHEMA = "adjudication-result.schema.json"


def claim_key(finding: dict[str, Any]) -> tuple[str, str]:
    """What makes two findings the same claim — severity deliberately excluded.

    Two reviewers naming the same defect at different severities are having a
    calibration disagreement, not raising two findings. Keying on severity
    would turn one dispute into two, and neither would be the real one.
    """
    return (
        str(finding.get("location", "")),
        " ".join(str(finding.get("claim", "")).lower().split()),
    )


def disputed_claims(
    left: dict[str, Any], right: dict[str, Any]
) -> list[dict[str, Any]]:
    """Everything the two envelopes do not agree on, enumerated in code.

    Three kinds of disagreement: a finding only one of them raised, a
    finding both raised at different severities, and a criterion they
    graded differently. The overall result is included when it differs,
    because two envelopes that disagree about the verdict while agreeing on
    every finding are disagreeing about something worth naming.
    """
    claims: list[dict[str, Any]] = []
    left_findings = {claim_key(f): f for f in left.get("findings", [])}
    right_findings = {claim_key(f): f for f in right.get("findings", [])}

    for index, (key, finding) in enumerate(sorted(left_findings.items())):
        if key not in right_findings:
            claims.append(
                {
                    "claim_id": f"claim-finding-a-{index}",
                    "kind": "finding_only_in_one_envelope",
                    "claim": finding.get("claim"),
                    "location": finding.get("location"),
                    "severity": finding.get("severity"),
                    "positions": ["raised", "not raised"],
                }
            )
    for index, (key, finding) in enumerate(sorted(right_findings.items())):
        if key not in left_findings:
            claims.append(
                {
                    "claim_id": f"claim-finding-b-{index}",
                    "kind": "finding_only_in_one_envelope",
                    "claim": finding.get("claim"),
                    "location": finding.get("location"),
                    "severity": finding.get("severity"),
                    "positions": ["not raised", "raised"],
                }
            )

    for index, key in enumerate(sorted(set(left_findings) & set(right_findings))):
        first, second = left_findings[key], right_findings[key]
        if first.get("severity") != second.get("severity"):
            claims.append(
                {
                    "claim_id": f"claim-severity-{index}",
                    "kind": "severity_disagreement",
                    "claim": first.get("claim"),
                    "location": first.get("location"),
                    "positions": [first.get("severity"), second.get("severity")],
                }
            )

    left_criteria = {c["criterion_id"]: c for c in left.get("criterion_results", [])}
    right_criteria = {c["criterion_id"]: c for c in right.get("criterion_results", [])}
    for index, criterion_id in enumerate(sorted(set(left_criteria) & set(right_criteria))):
        first, second = left_criteria[criterion_id], right_criteria[criterion_id]
        if first.get("result") != second.get("result"):
            claims.append(
                {
                    "claim_id": f"claim-criterion-{index}",
                    "kind": "criterion_disagreement",
                    "claim": f"criterion {criterion_id}",
                    "positions": [first.get("result"), second.get("result")],
                }
            )

    if left.get("result") != right.get("result"):
        claims.append(
            {
                "claim_id": "claim-result",
                "kind": "result_disagreement",
                "claim": "the overall result of the review",
                "positions": [left.get("result"), right.get("result")],
            }
        )
    return claims


def _probe_rule(
    claims: Sequence[dict[str, Any]],
) -> Any:
    expected = {claim["claim_id"] for claim in claims}

    def validate(output: dict[str, Any]) -> list[ValidationError]:
        errors: list[ValidationError] = []
        kinds = {item["id"]: item.get("kind") for item in output.get("evidence", [])}
        seen: set[str] = set()
        for index, resolution in enumerate(output.get("resolutions", [])):
            seen.add(resolution.get("claim_id", ""))
            refs = resolution.get("evidence_refs", [])
            unknown = [ref for ref in refs if ref not in kinds]
            for ref in unknown:
                errors.append(
                    ValidationError(
                        f"/resolutions/{index}/evidence_refs",
                        "semantic:unknown_evidence_ref",
                        f"{ref!r} is not declared in this document's evidence",
                    )
                )
            if resolution.get("resolution") == "UNRESOLVED":
                continue
            if not any(kinds.get(ref) == "probe" for ref in refs):
                errors.append(
                    ValidationError(
                        f"/resolutions/{index}",
                        "semantic:resolution_requires_probe",
                        "a disputed claim is settled by a probe, not by "
                        "re-asserting one side; report UNRESOLVED when no "
                        "probe can settle it",
                    )
                )
        missing = sorted(expected - seen)
        if missing:
            errors.append(
                ValidationError(
                    "/resolutions",
                    "semantic:unresolved_claims_missing",
                    "every disputed claim must be answered; missing: "
                    + ", ".join(missing),
                )
            )
        return errors

    return validate


def run(
    context: FlowContext,
    *,
    left: dict[str, Any],
    right: dict[str, Any],
    candidate_diff: str = "",
) -> dict[str, Any]:
    """Adjudicate two envelopes into one resolution."""
    claims = disputed_claims(left, right)
    if not claims:
        raise FlowError(
            "these two envelopes agree on every finding, criterion and result; "
            "there is nothing to adjudicate"
        )

    context.run.write_artifact(
        "disputed-claims.json",
        {
            "run_id": context.run_id,
            "envelopes": [left.get("envelope_id"), right.get("envelope_id")],
            "claims": claims,
        },
    )

    lens = context.lens(ADJUDICATION_LENS)
    prompt = prompts.adjudication(
        contract=context.contract,
        lens=lens,
        output_schema=context.schemas().get(ADJUDICATION_RESULT_SCHEMA),
        candidate=candidate_diff,
        disputed=claims,
    )
    step_id = "adjudication"
    envelope = base.model_step(
        context,
        step_id,
        kind="adjudication",
        role="adjudication",
        prompt=prompt,
        output_schema_ref=ADJUDICATION_RESULT_SCHEMA,
        lens_id=ADJUDICATION_LENS,
        ladder_level=3,
        extra_validator=_probe_rule(claims),
        envelope_from=lambda output: _envelope(context, step_id, output, claims),
    )

    envelopes = [left, right, envelope]
    unresolved = [
        resolution
        for resolution in envelope.get("criterion_results", [])
        if resolution.get("result") == "INCONCLUSIVE"
    ]
    non_claims = [
        "Adjudication settles disputed claims by probe; it does not re-review "
        "the candidate, and a claim neither envelope raised was not considered.",
        ladder.LEVEL_4_NON_CLAIM,
    ]
    if unresolved:
        non_claims.append(
            f"{len(unresolved)} claim(s) were left UNRESOLVED: no probe could "
            "settle them, so the disagreement stands and a human decides."
        )
    if envelope["status"] != "COMPLETED":
        non_claims.append(
            "The adjudication step failed rather than concluding, so the "
            "disagreement is untouched."
        )

    document = base.verdict(
        context,
        flow=FLOW,
        result="INCONCLUSIVE" if unresolved or envelope["status"] != "COMPLETED" else envelope["result"],
        envelopes=envelopes,
        ladder_levels_run=[0, 3],
        candidate=left.get("candidate") or right.get("candidate"),
        extra_non_claims=non_claims,
    )
    return base.write_verdict(context, document)


def _envelope(
    context: FlowContext,
    step_id: str,
    output: dict[str, Any],
    claims: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """One resolution envelope: each claim becomes a criterion outcome."""
    result_for = {"UPHELD": "PASS", "REJECTED": "FAIL", "UNRESOLVED": "INCONCLUSIVE"}
    criterion_results = [
        {
            "criterion_id": resolution["claim_id"],
            "result": result_for[resolution["resolution"]],
            "evidence_refs": list(resolution.get("evidence_refs", [])),
            "negative_path_claim": False,
            "note": resolution["rationale"][:2000],
        }
        for resolution in output.get("resolutions", [])
    ]
    upheld = [
        resolution
        for resolution in output.get("resolutions", [])
        if resolution["resolution"] == "UPHELD"
    ]
    findings = [
        {
            "id": f"adjudicated-{resolution['claim_id']}",
            "severity": resolution.get("severity", "MEDIUM"),
            "status": "OPEN",
            "claim": resolution["rationale"][:2000],
            "evidence_refs": list(resolution.get("evidence_refs", [])),
            "required_action": "Resolve the upheld claim, or record why it is accepted.",
            "negative_path_claim": False,
            "criterion_id": resolution["claim_id"],
        }
        for resolution in upheld
    ]
    unresolved = [
        resolution["claim_id"]
        for resolution in output.get("resolutions", [])
        if resolution["resolution"] == "UNRESOLVED"
    ]
    non_claims = list(output.get("non_claims", []))
    if unresolved:
        non_claims.append(
            "Left undecided: " + ", ".join(unresolved) + ". No probe settled them."
        )
    envelope: dict[str, Any] = {
        "schema_version": "workflows.envelope.v1",
        "envelope_id": f"{context.run_id}/{step_id}",
        "run_id": context.run_id,
        "step_id": step_id,
        "step_kind": "adjudication",
        "status": "COMPLETED",
        "terminal": True,
        "result": "FAIL" if findings else ("INCONCLUSIVE" if unresolved else "PASS"),
        "dry_run": context.dry_run,
        "produced_at": context.now(),
        "contract_ref": context.contract_ref,
        "ladder_level": 3,
        "lens_id": ADJUDICATION_LENS,
        "evidence": list(output.get("evidence", [])),
        "criterion_results": criterion_results,
        "findings": findings,
        "non_claims": non_claims,
        "side_effects": [{"kind": "none", "target": "none"}],
    }
    return envelope
