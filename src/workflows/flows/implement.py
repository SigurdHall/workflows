"""The `implement` flow: one worker, gates, review ladder, targeted repair.

The building block the other flows compose. Its shape is the shared anatomy
with one producing step:

    freeze base -> level-0 gates -> worker -> level-0 gates -> review ladder
    -> (on findings) repair from the *original* base -> gates -> re-review

Repair never edits the failed candidate. It resets the worktree to the
frozen base and rebuilds, because reverting an illegal change on top of
itself leaves the change in the candidate's history — and the costliest
finding in the motivating experiments was exactly such a change surviving
every functional check.
"""

from __future__ import annotations

from typing import Any

from workflows import prompts
from workflows.flows import base, ladder, review
from workflows.flows.base import FlowContext

DEFAULT_WORK_LENS = "work/spec-fidelity"
FLOW = "implement"


def run(context: FlowContext) -> dict[str, Any]:
    """Run the flow to a verdict. Every step is resumable; nothing is replayed."""
    envelopes: list[dict[str, Any]] = []
    levels_run: list[int] = [0]
    escalations: list[str] = []
    superseded: list[str] = []

    pre = base.gate_step(context, "gates-pre", context.pre_gates, require_clean=True)
    envelopes.append(pre)
    if pre["result"] == "FAIL":
        return _verdict(
            context,
            result="BLOCKED",
            envelopes=envelopes,
            levels_run=levels_run,
            candidate=None,
            extra_non_claims=[
                "The run stopped before any model was called: the base did "
                "not satisfy its own level-0 gates, so nothing about the task "
                "was attempted.",
                ladder.LEVEL_4_NON_CLAIM,
            ],
        )

    work_lens = (context.work_lenses or (DEFAULT_WORK_LENS,))[0]
    outcome: review.LadderOutcome | None = None
    candidate: dict[str, Any] | None = None
    gates_envelope: dict[str, Any] | None = None

    for round_index in range(context.escalation.max_repair_rounds + 1):
        if round_index == 0:
            producer = _work_step(context, work_lens)
        else:
            producer = _repair_step(
                context, round_index, outcome.open_findings if outcome else []
            )
        envelopes.append(producer)
        if producer["status"] != "COMPLETED":
            return _verdict(
                context,
                result="BLOCKED",
                envelopes=envelopes,
                levels_run=levels_run,
                candidate=None,
                extra_non_claims=[
                    "The producing step failed, so no candidate was reviewed.",
                    ladder.LEVEL_4_NON_CLAIM,
                ],
            )

        diff = base.candidate_diff(context)
        candidate = base.candidate_identity(context, diff)
        gates_envelope = base.gate_step(
            context,
            f"gates-post-r{round_index}",
            context.post_gates,
            require_clean=False,
            candidate=candidate,
            attempt=round_index + 1,
        )
        envelopes.append(gates_envelope)

        # A gate failure is terminal for the step: the result goes back to
        # repair, never onward to an expensive reviewer.
        if gates_envelope["result"] == "FAIL":
            if round_index < context.escalation.max_repair_rounds:
                outcome = review.LadderOutcome(envelopes=[gates_envelope])
                superseded.extend([producer["step_id"], gates_envelope["step_id"]])
                continue
            return _verdict(
                context,
                result="FAIL",
                envelopes=envelopes,
                levels_run=levels_run,
                candidate=candidate,
                superseded=superseded,
                extra_non_claims=[
                    "No model reviewed the final candidate: it never became "
                    "gate-clean, and reviewers only see gate-clean work.",
                    ladder.LEVEL_4_NON_CLAIM,
                ],
            )

        outcome = review.run_ladder(
            context,
            candidate=candidate,
            diff=diff,
            gate_result=gates_envelope["result"],
            round_index=round_index,
        )
        envelopes.extend(outcome.envelopes)
        levels_run.extend(outcome.levels_run)
        escalations.extend(outcome.escalations)

        if outcome.failed:
            return _verdict(
                context,
                result="BLOCKED",
                envelopes=envelopes,
                levels_run=levels_run,
                candidate=candidate,
                superseded=superseded,
                extra_non_claims=[
                    "A review step failed rather than concluding, so this "
                    "candidate was never judged. A failed call is not a finding.",
                    ladder.LEVEL_4_NON_CLAIM,
                ],
            )

        blocking = ladder.blocking_findings(
            outcome.envelopes, context.escalation.level_2_on_severity
        )
        if outcome.result == "PASS" and not blocking:
            break
        if round_index >= context.escalation.max_repair_rounds:
            break
        superseded.extend(
            [producer["step_id"], gates_envelope["step_id"]]
            + [envelope["step_id"] for envelope in outcome.envelopes]
        )

    final_envelopes = [
        envelope for envelope in envelopes if envelope["step_id"] not in set(superseded)
    ]
    passed = (
        gates_envelope is not None
        and gates_envelope["result"] == "PASS"
        and outcome is not None
        and outcome.result == "PASS"
        and not ladder.blocking_findings(
            final_envelopes, context.escalation.level_2_on_severity
        )
    )
    non_claims = list(review.ladder_non_claims(outcome)) if outcome else [ladder.LEVEL_4_NON_CLAIM]
    if escalations:
        non_claims.append("Escalations recorded: " + "; ".join(escalations) + ".")
    if superseded:
        non_claims.append(
            f"{len(superseded)} step(s) from earlier repair rounds are marked "
            "RESOLVED in this verdict: their findings were answered by a "
            "later round, not withdrawn."
        )
    if ladder.must_stop(final_envelopes, context.escalation):
        non_claims.append(
            "A finding at or above the plan's stop threshold is open: this "
            "verdict is a report to a human, not an approval."
        )
    return _verdict(
        context,
        result="PASS" if passed else "FAIL",
        envelopes=envelopes,
        levels_run=levels_run,
        candidate=candidate,
        superseded=superseded,
        extra_non_claims=non_claims,
    )


def _work_step(context: FlowContext, lens_id: str) -> dict[str, Any]:
    lens = context.lens(lens_id)
    prompt = prompts.work(
        contract=context.contract,
        lens=lens,
        output_schema=context.schemas().get(base.WORK_RESULT_SCHEMA),
        focus_hint=context.focus_hint,
    )
    return base.model_step(
        context,
        "work-1",
        kind="work",
        role="worker",
        prompt=prompt,
        output_schema_ref=base.WORK_RESULT_SCHEMA,
        lens_id=lens_id,
        envelope_from=lambda output: base.work_envelope(
            context, "work-1", output, lens_id=lens_id, candidate=None
        ),
    )


def _repair_step(
    context: FlowContext, round_index: int, findings: list[dict[str, Any]]
) -> dict[str, Any]:
    """Targeted repair: relevant lenses only, rebuilt from the original base."""
    step_id = f"repair-r{round_index}"
    if not base.already_produced(context, step_id):
        # Only reset when this repair has not run. Resetting a worktree whose
        # repair is already on disk would discard the work and then ask a
        # model to redo it.
        base.reset_to_base(context)

    available = list(context.work_lenses or (DEFAULT_WORK_LENS,))
    chosen = ladder.lenses_for_findings(findings, available)
    lens_id = chosen[0]
    lens = context.lens(lens_id)
    prompt = prompts.repair(
        contract=context.contract,
        lens=lens,
        output_schema=context.schemas().get(base.WORK_RESULT_SCHEMA),
        findings=findings,
        focus_hint=context.focus_hint,
    )
    return base.model_step(
        context,
        step_id,
        kind="repair",
        role="repair",
        prompt=prompt,
        output_schema_ref=base.WORK_RESULT_SCHEMA,
        lens_id=lens_id,
        envelope_from=lambda output: base.work_envelope(
            context, step_id, output, lens_id=lens_id, candidate=None, kind="repair"
        ),
        attempt=round_index + 1,
    )


def _verdict(
    context: FlowContext,
    *,
    result: str,
    envelopes: list[dict[str, Any]],
    levels_run: list[int],
    candidate: dict[str, Any] | None,
    extra_non_claims: list[str],
    superseded: list[str] | None = None,
) -> dict[str, Any]:
    document = base.verdict(
        context,
        flow=FLOW,
        result=result,
        envelopes=envelopes,
        ladder_levels_run=levels_run,
        candidate=candidate,
        superseded_steps=superseded or (),
        extra_non_claims=extra_non_claims,
    )
    return base.write_verdict(context, document)
