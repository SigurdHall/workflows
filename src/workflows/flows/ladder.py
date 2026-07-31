"""The review ladder, as data.

Review escalates on signal — never as a pipeline every candidate traverses.
A PASS at any level produces an envelope and stops the ladder. The
thresholds are configuration, not code: a plan states them, a flow reads
them, and nothing here decides what "serious enough" means.

Levels are functions, not "smarter models": recall, calibration,
adjudication, independence. Which model serves a level is a deployment
question, answered by a runner profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

SEVERITY_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

LEVEL_ROLES = {
    1: "review-1",
    2: "review-2",
    3: "review-3",
    4: "review-4",
}

LEVEL_4_NON_CLAIM = (
    "Ladder level 4 (cross-family review plus a human) did not run: this "
    "deployment has one runner family, so a blind spot shared by that family "
    "would not have been caught here."
)


def severity_at_least(severity: str, threshold: str) -> bool:
    try:
        return SEVERITY_ORDER.index(severity) >= SEVERITY_ORDER.index(threshold)
    except ValueError:
        return False


@dataclass(frozen=True)
class Escalation:
    """Thresholds a plan sets and a flow obeys."""

    level_2_on_severity: str = "HIGH"
    level_3_on_conflict: bool = True
    stop_on_severity: str = "CRITICAL"
    max_repair_rounds: int = 2
    dryness_rounds: int = 2

    @classmethod
    def from_plan(cls, block: dict[str, Any] | None) -> Escalation:
        if not block:
            return cls()
        return cls(
            level_2_on_severity=block.get("level_2_on_severity", cls.level_2_on_severity),
            level_3_on_conflict=block.get("level_3_on_conflict", cls.level_3_on_conflict),
            stop_on_severity=block.get("stop_on_severity", cls.stop_on_severity),
            max_repair_rounds=block.get("max_repair_rounds", cls.max_repair_rounds),
            dryness_rounds=block.get("dryness_rounds", cls.dryness_rounds),
        )


def open_findings(envelopes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        finding
        for envelope in envelopes
        for finding in envelope.get("findings", [])
        if finding.get("status") == "OPEN"
    ]


def blocking_findings(
    envelopes: Sequence[dict[str, Any]], threshold: str
) -> list[dict[str, Any]]:
    return [
        finding
        for finding in open_findings(envelopes)
        if severity_at_least(finding.get("severity", "LOW"), threshold)
    ]


def escalate_to_level_2(
    review_envelopes: Sequence[dict[str, Any]],
    gate_result: str,
    escalation: Escalation,
) -> str | None:
    """Reason to run level 2, or None to stop the ladder.

    Two signals, both from ADR 0003: a finding at or above the threshold, and
    disagreement between the gates and the reviewer. Disagreement matters in
    both directions — a reviewer passing what a gate failed is as
    interesting as the reverse.
    """
    findings = blocking_findings(review_envelopes, escalation.level_2_on_severity)
    if findings:
        return (
            f"level-1 review raised {len(findings)} open finding(s) at or above "
            f"{escalation.level_2_on_severity}"
        )
    review_result = combined_result(review_envelopes)
    if review_result == "INCONCLUSIVE":
        # A reviewer that could not conclude is exactly what a second opinion
        # is for. Treating it as "no signal" would silently accept the one
        # answer that says nothing.
        return "level-1 review could not conclude"
    if gate_result == "PASS" and review_result == "FAIL":
        return "the gates passed the candidate the reviewer failed"
    if gate_result == "FAIL" and review_result == "PASS":
        return "the reviewer passed a candidate the gates failed"
    return None


def escalate_to_level_3(
    level_1: Sequence[dict[str, Any]],
    level_2: Sequence[dict[str, Any]],
    escalation: Escalation,
) -> str | None:
    """Adjudication is for an unresolved conflict, not for a second opinion."""
    if not escalation.level_3_on_conflict or not level_2:
        return None
    first, second = combined_result(level_1), combined_result(level_2)
    if first != second and {first, second} <= {"PASS", "FAIL"}:
        return f"level 1 concluded {first} and level 2 concluded {second}"
    return None


def combined_result(envelopes: Sequence[dict[str, Any]]) -> str:
    """One result from several envelopes: any FAIL fails."""
    results = [envelope.get("result") for envelope in envelopes]
    if not results:
        return "NOT_RUN"
    if "FAIL" in results:
        return "FAIL"
    if "INCONCLUSIVE" in results:
        return "INCONCLUSIVE"
    if all(result == "NOT_RUN" for result in results):
        return "NOT_RUN"
    return "PASS"


def must_stop(envelopes: Sequence[dict[str, Any]], escalation: Escalation) -> bool:
    """A finding severe enough that the program stops for a human."""
    return bool(blocking_findings(envelopes, escalation.stop_on_severity))


def lenses_for_findings(
    findings: Sequence[dict[str, Any]], available: Sequence[str], limit: int = 3
) -> list[str]:
    """Route findings to the lenses responsible for them.

    Repair is targeted: sending two precise findings to ten workers buys
    redundancy, not coverage. Findings that name a lens go back to it;
    findings that name none fall back to the first available lens so that
    nothing is dropped silently.
    """
    chosen: list[str] = []
    for finding in findings:
        lens_id = finding.get("lens_id")
        if lens_id and lens_id in available and lens_id not in chosen:
            chosen.append(lens_id)
    if not chosen and available:
        chosen.append(available[0])
    return chosen[:limit]
