"""Deterministic prompt composition.

The driver composes every prompt from parts, in a fixed order, with stable
JSON serialization. Same contract plus same lens plus same focus hint gives
a byte-identical prompt — no timestamps, no absolute paths, no dictionary
iteration order leaking through. That property is what makes prompts
diffable and cacheable, and lens yield measurable.

Reviewer blindness is enforced by the shape of this module, not by an
instruction inside a prompt: :func:`review` has no parameter through which
worker or synthesizer dialogue could reach a reviewer. A reviewer sees the
contract, the candidate, its lens, and the output schema. That is all there
is to pass it.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from workflows.lenses import Lens

PROMPT_VERSION = "workflows.prompt.v1"

_OUTPUT_INSTRUCTION = (
    "Return exactly one JSON object that validates against the schema below. "
    "No prose, no markdown fence, no commentary before or after it. Every "
    "claim you make must point at evidence you actually produced; a claim "
    "with no logged probe is an assertion, not a finding."
)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def _section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.rstrip()}\n"


def _header(role: str) -> str:
    return f"# {role}\n\nprompt_version: {PROMPT_VERSION}\nrole: {role}\n"


def _assemble(parts: Sequence[str]) -> str:
    return "\n".join(part.rstrip() + "\n" for part in parts if part)


def _lens_section(lens: Lens) -> str:
    return _section(f"Lens: {lens.reference}", lens.text)


def _focus_section(focus_hint: str | None) -> str:
    if not focus_hint:
        return ""
    return _section(
        "Focus",
        focus_hint.strip()
        + "\n\n(Chosen at planning time and recorded in the plan. It narrows "
        "attention; it does not replace the lens or the contract.)",
    )


def _output_section(output_schema: dict[str, Any]) -> str:
    return _section("Required output", _OUTPUT_INSTRUCTION + "\n\n" + _json(output_schema))


def work(
    *,
    contract: dict[str, Any],
    lens: Lens,
    output_schema: dict[str, Any],
    focus_hint: str | None = None,
) -> str:
    """A producer prompt: contract, work lens, output schema."""
    return _assemble(
        [
            _header("work"),
            _section("Contract", _json(contract)),
            _lens_section(lens),
            _focus_section(focus_hint),
            _output_section(output_schema),
        ]
    )


def review(
    *,
    contract: dict[str, Any],
    lens: Lens,
    output_schema: dict[str, Any],
    candidate: str,
    focus_hint: str | None = None,
) -> str:
    """A blind review prompt.

    There is deliberately no parameter for how the candidate came to be. A
    reviewer in a fresh context finds more than a reviewer reading the
    producer's reasoning, and the way to guarantee a fresh context is to
    have nothing to pass.
    """
    return _assemble(
        [
            _header("review"),
            _section("Contract", _json(contract)),
            _section("Candidate", candidate),
            _lens_section(lens),
            _focus_section(focus_hint),
            _output_section(output_schema),
        ]
    )


def synthesis(
    *,
    contract: dict[str, Any],
    output_schema: dict[str, Any],
    candidates: Sequence[tuple[str, str]],
    focus_hint: str | None = None,
) -> str:
    """A synthesis prompt: several lens candidates, one integrated result.

    The synthesizer is the one role that legitimately sees other producers'
    work — that is what it is for. It sees their *candidates*, labelled by
    lens, not their reasoning: a diff is a fact, and an explanation of a diff
    is a story about one.
    """
    body = "\n\n".join(
        f"### Candidate from {lens_id}\n\n```diff\n{diff.strip()}\n```"
        for lens_id, diff in candidates
    )
    return _assemble(
        [
            _header("synthesis"),
            _section("Contract", _json(contract)),
            _section(
                "Candidates to integrate",
                body
                + "\n\nProduce one integrated candidate that satisfies the "
                "contract. Where two candidates conflict, choose and say why "
                "in a decision; do not merge both.",
            ),
            _focus_section(focus_hint),
            _output_section(output_schema),
        ]
    )


def adjudication(
    *,
    contract: dict[str, Any],
    lens: Lens,
    output_schema: dict[str, Any],
    candidate: str,
    disputed: Sequence[dict[str, Any]],
) -> str:
    """An adjudication prompt: the disputed claims, and nothing about who made them.

    The claims arrive stripped of their authorship. Knowing which reviewer
    said what invites deciding by reputation, and the point of adjudication
    is that each claim is settled by a probe.
    """
    return _assemble(
        [
            _header("adjudication"),
            _section("Contract", _json(contract)),
            _section("Candidate", candidate),
            _section(
                "Disputed claims",
                _json(list(disputed))
                + "\n\nSettle each claim with a probe you run. A claim no probe "
                "can settle is UNRESOLVED; that is an answer, not a failure.",
            ),
            _lens_section(lens),
            _output_section(output_schema),
        ]
    )


def attainment(
    *,
    contract: dict[str, Any],
    lens: Lens,
    output_schema: dict[str, Any],
    checked: Sequence[dict[str, Any]],
    focus_hint: str | None = None,
) -> str:
    """A goal-attainment prompt.

    What a gate already checked is passed in as *checked*, so the reviewer
    knows not to spend its judgment there — and so it cannot present a
    deterministic result as its own finding.
    """
    return _assemble(
        [
            _header("attainment"),
            _section("Goal contract", _json(contract)),
            _section(
                "Already checked deterministically",
                _json(list(checked))
                + "\n\nThese were settled by a gate. Do not re-assert them as "
                "judgments: an obligation met is not a goal achieved.",
            ),
            _lens_section(lens),
            _focus_section(focus_hint),
            _output_section(output_schema),
        ]
    )


def repair(
    *,
    contract: dict[str, Any],
    lens: Lens,
    output_schema: dict[str, Any],
    findings: Sequence[dict[str, Any]],
    focus_hint: str | None = None,
) -> str:
    """A targeted repair prompt: the findings this lens is responsible for.

    Repair rebuilds from the original base, so the failed candidate is not
    passed in: reverting an illegal change on top of itself leaves the
    change in the history of the candidate, and the point is that it should
    never have been there.
    """
    return _assemble(
        [
            _header("repair"),
            _section("Contract", _json(contract)),
            _section(
                "Findings to resolve",
                _json(list(findings))
                + "\n\nBuild from the original base. Do not start from the "
                "candidate these findings were raised against.",
            ),
            _lens_section(lens),
            _focus_section(focus_hint),
            _output_section(output_schema),
        ]
    )


def duel(
    *,
    rubric: str,
    output_schema: dict[str, Any],
    one: str,
    two: str,
) -> str:
    """A blind pairwise duel prompt.

    There is deliberately no parameter for where the candidates came from:
    not the lineage, not the author, not which of them is the incumbent. A
    judge that cannot be told is a judge that cannot be biased, and the way
    to guarantee that is a prompt with no field for the knowledge.
    """
    return _assemble(
        [
            _header("judge"),
            _section("Rubric", rubric),
            _section("Candidate one", one),
            _section("Candidate two", two),
            _section(
                "How to judge",
                "Apply the rubric exactly as written. Check its disqualifiers "
                "before ranking anything. Then walk the ranked criteria in "
                "order: the first criterion that separates the candidates "
                "decides, and later criteria stop mattering. Prefer neither "
                "when nothing separates them - 'none' is a verdict, not a "
                "failure. Every preference must point at concrete places in "
                "both candidates; a preference that points at nothing will "
                "be rejected.",
            ),
            _output_section(output_schema),
        ]
    )


def induction(
    *,
    rubric: str,
    output_schema: dict[str, Any],
    chosen: str,
    over: str,
) -> str:
    """The rule a human override implies.

    The owner ranked one candidate above another against the standing
    rubric's outcome. A pick teaches the system one bit and evaporates; the
    point of this prompt is to turn it into a law the owner can ratify.
    """
    return _assemble(
        [
            _header("judge"),
            _section("Rubric", rubric),
            _section("The owner's choice", chosen),
            _section("Ranked above", over),
            _section(
                "What to induce",
                "The owner overrode a tournament: they ranked the first of "
                "these candidates above the second, against the standing "
                "rubric's outcome. Induce the single explicit rule that, "
                "added to the rubric, would have produced the owner's "
                "ranking. Phrase it so the owner can ratify it by reading it "
                "alone, and name the existing criteria it would fight with - "
                "an amendment that hides its conflicts cannot be ratified "
                "honestly.",
            ),
            _output_section(output_schema),
        ]
    )
