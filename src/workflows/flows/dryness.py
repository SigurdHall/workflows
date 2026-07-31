"""The fan-out stop rule.

Fan-out stops when K consecutive *distinct* lenses return nothing new.
Distinct is the load-bearing word: a lens that returns empty twice is one
lens telling you the same thing twice, not two independent signals that the
ground is covered. Counting retries as rounds is how a fan-out convinces
itself it is done after asking one perspective repeatedly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence


def finding_key(finding: dict[str, Any]) -> tuple[str, str, str]:
    """What makes two findings the same finding.

    Not the id: two lenses name the same defect differently. Location, claim
    and severity together are the practical identity.
    """
    return (
        str(finding.get("location", "")),
        " ".join(str(finding.get("claim", "")).lower().split()),
        str(finding.get("severity", "")),
    )


@dataclass
class DrynessTracker:
    """Counts consecutive distinct lenses that added nothing new."""

    rounds_required: int = 2
    seen: set[tuple[str, str, str]] = field(default_factory=set)
    dry_lenses: list[str] = field(default_factory=list)
    consulted: list[str] = field(default_factory=list)

    @property
    def is_dry(self) -> bool:
        return len(self.dry_lenses) >= self.rounds_required

    def record(self, lens_id: str, findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Register one lens's findings; return the ones that were new.

        A lens consulted twice never contributes a second dry round: dryness
        is a statement about perspectives, not about attempts.
        """
        self.consulted.append(lens_id)
        fresh = [
            finding for finding in findings if finding_key(finding) not in self.seen
        ]
        for finding in fresh:
            self.seen.add(finding_key(finding))
        if fresh:
            self.dry_lenses.clear()
        elif lens_id not in self.dry_lenses:
            self.dry_lenses.append(lens_id)
        return fresh


def run_until_dry(
    lens_ids: Sequence[str],
    consult: Callable[[str], list[dict[str, Any]]],
    *,
    rounds_required: int = 2,
) -> DrynessTracker:
    """Consult lenses in order until K distinct ones add nothing, or all are used."""
    tracker = DrynessTracker(rounds_required=rounds_required)
    for lens_id in lens_ids:
        tracker.record(lens_id, consult(lens_id))
        if tracker.is_dry:
            break
    return tracker
