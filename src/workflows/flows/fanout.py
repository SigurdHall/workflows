"""The `fanout` flow: N lens workers, one synthesizer, then the usual anatomy.

Fan-out is breadth of *perspectives* on one task, which is orthogonal to a
program's breadth of *tasks*. Each worker gets its own worktree from the
frozen base, so workers never share a write target and a worker cannot see
what another worker did. The synthesizer sees their candidates — labelled by
lens — and builds one integrated candidate in the main worktree.

Everything after synthesis is the shared anatomy: gates, review ladder,
targeted repair, resynthesis from the original base.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from workflows import gitcmd, prompts
from workflows.flows import base, ladder, review
from workflows.flows.base import FlowContext, FlowError

FLOW = "fanout"
MIN_LENSES = 2


def run(context: FlowContext) -> dict[str, Any]:
    lens_ids = list(context.work_lenses)
    if len(lens_ids) < MIN_LENSES:
        raise FlowError(
            "fan-out is breadth of perspectives: give it at least two work "
            f"lenses, not {len(lens_ids)}"
        )

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
                "not satisfy its own level-0 gates.",
                ladder.LEVEL_4_NON_CLAIM,
            ],
        )

    worker_envelopes, candidates = _fan_out(context, lens_ids)
    envelopes.extend(worker_envelopes)
    usable = [pair for pair in candidates if pair[1] is not None]
    if not usable:
        return _verdict(
            context,
            result="BLOCKED",
            envelopes=envelopes,
            levels_run=levels_run,
            candidate=None,
            extra_non_claims=[
                "Every worker failed, so there was nothing to synthesize.",
                ladder.LEVEL_4_NON_CLAIM,
            ],
        )

    manifest = _synthesis_manifest(context, usable, worker_envelopes)
    outcome: review.LadderOutcome | None = None
    candidate: dict[str, Any] | None = None
    gates_envelope: dict[str, Any] | None = None

    for round_index in range(context.escalation.max_repair_rounds + 1):
        if round_index == 0:
            producer = _synthesis_step(context, usable, round_index)
        else:
            if not base.already_produced(context, f"resynthesis-r{round_index}"):
                base.reset_to_base(context)
            producer = _resynthesis_step(
                context, usable, round_index, outcome.open_findings if outcome else []
            )
        envelopes.append(producer)
        if producer["status"] != "COMPLETED":
            return _verdict(
                context,
                result="BLOCKED",
                envelopes=envelopes,
                levels_run=levels_run,
                candidate=None,
                superseded=superseded,
                extra_non_claims=[
                    "The synthesis step failed, so no candidate was reviewed.",
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
                    "candidate was never judged.",
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

    final = [e for e in envelopes if e["step_id"] not in set(superseded)]
    passed = (
        gates_envelope is not None
        and gates_envelope["result"] == "PASS"
        and outcome is not None
        and outcome.result == "PASS"
        and not ladder.blocking_findings(final, context.escalation.level_2_on_severity)
    )
    non_claims = list(review.ladder_non_claims(outcome)) if outcome else [ladder.LEVEL_4_NON_CLAIM]
    non_claims.append(
        f"Fan-out width was a plan parameter ({len(lens_ids)} lenses), not a "
        "measurement: no dryness stop rule decided that the ground was covered."
    )
    failed_workers = [e for e in worker_envelopes if e["status"] != "COMPLETED"]
    if failed_workers:
        non_claims.append(
            f"{len(failed_workers)} of {len(lens_ids)} worker(s) failed and "
            "contributed nothing to the synthesis: "
            + ", ".join(sorted(e.get("lens_id", e["step_id"]) for e in failed_workers))
            + "."
        )
    if escalations:
        non_claims.append("Escalations recorded: " + "; ".join(escalations) + ".")
    non_claims.append(f"Synthesis input manifest: {manifest}.")
    return _verdict(
        context,
        result="PASS" if passed else "FAIL",
        envelopes=envelopes,
        levels_run=levels_run,
        candidate=candidate,
        superseded=superseded,
        extra_non_claims=non_claims,
    )


# --------------------------------------------------------------------------
# Fan-out
# --------------------------------------------------------------------------


def _worker_root(context: FlowContext) -> Path:
    root = context.worker_worktrees or (context.run.root / "worktrees")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _fan_out(
    context: FlowContext, lens_ids: list[str]
) -> tuple[list[dict[str, Any]], list[tuple[str, str | None]]]:
    """One worktree and one call per lens. Workers never share a write target."""
    root = _worker_root(context)
    worktrees: dict[str, Path] = {}
    for lens_id in lens_ids:
        path = root / lens_id.replace("/", "-")
        step_id = _worker_step_id(lens_id)
        if not path.exists() and not context.run.is_completed(step_id):
            # Serialized on purpose: parallel worktree creation is how you
            # meet packed-refs.lock.
            gitcmd.add_worktree(context.worktree, path, context.base)
        worktrees[lens_id] = path

    def one(lens_id: str) -> dict[str, Any]:
        return _worker_step(context, lens_id, worktrees[lens_id])

    width = max(1, min(context.max_parallel_workers, len(lens_ids)))
    if width == 1:
        envelopes = [one(lens_id) for lens_id in lens_ids]
    else:
        with ThreadPoolExecutor(max_workers=width) as pool:
            envelopes = list(pool.map(one, lens_ids))

    candidates: list[tuple[str, str | None]] = []
    for lens_id, envelope in zip(lens_ids, envelopes):
        if envelope["status"] != "COMPLETED":
            candidates.append((lens_id, None))
            continue
        worker_context = replace(context, worktree=worktrees[lens_id])
        candidates.append((lens_id, base.candidate_diff(worker_context)))
    return envelopes, candidates


def _worker_step_id(lens_id: str) -> str:
    return f"work-{lens_id.split('/')[-1]}"


def _worker_step(context: FlowContext, lens_id: str, worktree: Path) -> dict[str, Any]:
    lens = context.lens(lens_id)
    step_id = _worker_step_id(lens_id)
    prompt = prompts.work(
        contract=context.contract,
        lens=lens,
        output_schema=context.schemas().get(base.WORK_RESULT_SCHEMA),
        focus_hint=context.focus_hint,
    )
    worker_context = replace(context, worktree=worktree)
    return base.model_step(
        worker_context,
        step_id,
        kind="work",
        role="worker",
        prompt=prompt,
        output_schema_ref=base.WORK_RESULT_SCHEMA,
        lens_id=lens_id,
        envelope_from=lambda output: base.work_envelope(
            worker_context, step_id, output, lens_id=lens_id, candidate=None
        ),
    )


def _synthesis_manifest(
    context: FlowContext,
    candidates: list[tuple[str, str | None]],
    worker_envelopes: list[dict[str, Any]],
) -> str:
    """What the synthesizer was given, recorded before it is given it."""
    by_step = {envelope["step_id"]: envelope for envelope in worker_envelopes}
    document = {
        "run_id": context.run_id,
        "width": len(candidates),
        "inputs": [
            {
                "lens_id": lens_id,
                "step_id": _worker_step_id(lens_id),
                "envelope_id": by_step[_worker_step_id(lens_id)]["envelope_id"],
                "digest": "sha256:"
                + hashlib.sha256((diff or "").encode("utf-8")).hexdigest(),
                "empty": not (diff or "").strip(),
            }
            for lens_id, diff in candidates
        ],
    }
    relative = "synthesis-inputs.json"
    context.run.write_artifact(relative, document)
    return relative


def _synthesis_step(
    context: FlowContext, candidates: list[tuple[str, str]], round_index: int
) -> dict[str, Any]:
    step_id = "synthesis"
    prompt = prompts.synthesis(
        contract=context.contract,
        output_schema=context.schemas().get(base.WORK_RESULT_SCHEMA),
        candidates=[(lens_id, diff or "") for lens_id, diff in candidates],
        focus_hint=context.focus_hint,
    )
    return base.model_step(
        context,
        step_id,
        kind="synthesis",
        role="synthesis",
        prompt=prompt,
        output_schema_ref=base.WORK_RESULT_SCHEMA,
        envelope_from=lambda output: base.work_envelope(
            context, step_id, output, lens_id=None, candidate=None, kind="synthesis"
        ),
        attempt=round_index + 1,
    )


def _resynthesis_step(
    context: FlowContext,
    candidates: list[tuple[str, str]],
    round_index: int,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resynthesis from the original base, with findings routed to relevant lenses."""
    step_id = f"resynthesis-r{round_index}"
    available = [lens_id for lens_id, _ in candidates]
    relevant = ladder.lenses_for_findings(findings, available)
    chosen = [pair for pair in candidates if pair[0] in relevant] or candidates
    prompt = prompts.repair(
        contract=context.contract,
        lens=context.lens(relevant[0]),
        output_schema=context.schemas().get(base.WORK_RESULT_SCHEMA),
        findings=findings,
        focus_hint=context.focus_hint,
    ) + "\n" + prompts.synthesis(
        contract=context.contract,
        output_schema=context.schemas().get(base.WORK_RESULT_SCHEMA),
        candidates=[(lens_id, diff or "") for lens_id, diff in chosen],
    )
    return base.model_step(
        context,
        step_id,
        kind="synthesis",
        role="synthesis",
        prompt=prompt,
        output_schema_ref=base.WORK_RESULT_SCHEMA,
        envelope_from=lambda output: base.work_envelope(
            context, step_id, output, lens_id=None, candidate=None, kind="synthesis"
        ),
        attempt=round_index + 1,
    )


def cleanup_worktrees(context: FlowContext) -> None:
    """Remove worker worktrees. Never called automatically: a killed run's
    worktrees are what a resumed run reuses."""
    root = context.worker_worktrees or (context.run.root / "worktrees")
    if not root.exists():
        return
    for path in sorted(root.iterdir()):
        if path.is_dir():
            gitcmd.remove_worktree(context.worktree, path)


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
