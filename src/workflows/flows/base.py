"""Shared flow anatomy.

Every flow, regardless of shape: freeze the base and validate the contract,
run level-0 gates before any model call, call models only through the runner
with composed prompts, run gates again after every producing stage, escalate
review on signal, write everything to the run directory as it happens, and
end by emitting one envelope.

The step machinery is what makes that resumable. A step consults the
manifest before acting: a step already recorded COMPLETED returns its
written envelope and does not run again. That is the whole of resume — there
is no replay path, because nothing re-derives what was recorded.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from workflows import gates, gitcmd, lenses, prompts, runners
from workflows.flows.ladder import Escalation
from workflows.runs import RunDirectory, utc_now
from workflows.schema import SchemaRegistry, ValidationError, default_registry
from workflows.semantics import check_document, semantic_errors

ENVELOPE_SCHEMA = "envelope.schema.json"
VERDICT_SCHEMA = "verdict.schema.json"
WORK_RESULT_SCHEMA = "work-result.schema.json"
REVIEW_RESULT_SCHEMA = "review-result.schema.json"

DEFAULT_BINDINGS = {
    "worker": ("worker-class", "medium"),
    "synthesis": ("worker-class", "high"),
    "repair": ("worker-class", "medium"),
    "review-1": ("worker-class", "medium"),
    "review-2": ("worker-class", "high"),
    "review-3": ("strongest-same-family", "high"),
    "review-4": ("cross-family", "high"),
    "adjudication": ("strongest-same-family", "high"),
}


class FlowError(RuntimeError):
    """The flow was configured wrongly — an author error, not a model error."""


@dataclass(frozen=True)
class Profile:
    """Provider-unresolved role bindings.

    A flow names roles; a deployment binds them. Keeping the binding out of
    the flow is what lets a second runner family serve ladder level 4 as an
    added module rather than a refactor.
    """

    bindings: dict[str, tuple[str, str]] = field(default_factory=lambda: dict(DEFAULT_BINDINGS))
    sandbox_for_role: dict[str, str] = field(default_factory=dict)

    def resolve(self, role: str) -> tuple[str, str]:
        try:
            return self.bindings[role]
        except KeyError:
            raise FlowError(f"no model bound to role {role!r}") from None

    def sandbox(self, role: str) -> str:
        if role in self.sandbox_for_role:
            return self.sandbox_for_role[role]
        return "workspace-write" if role in ("worker", "repair", "synthesis") else "read-only"


@dataclass
class FlowContext:
    """Everything a flow needs, resolved once at the start of a run."""

    contract: dict[str, Any]
    contract_ref: dict[str, Any]
    worktree: Path
    base: str
    run: RunDirectory
    runner: Any
    run_id: str
    profile: Profile = field(default_factory=Profile)
    escalation: Escalation = field(default_factory=Escalation)
    registry: SchemaRegistry | None = None
    dry_run: bool = False
    work_lenses: tuple[str, ...] = ()
    review_lenses: tuple[str, ...] = ()
    focus_hint: str | None = None
    lens_directory: Path | None = None
    clock: Callable[[], str] = utc_now
    allow_reset: bool = True
    max_parallel_workers: int = 1
    worker_worktrees: Path | None = None
    pre_gates: tuple[str, ...] = ("base_identity", "verification_command")
    post_gates: tuple[str, ...] = (
        "base_identity",
        "candidate_changed",
        "scope",
        "protected_hash",
        "verification_command",
    )

    def schemas(self) -> SchemaRegistry:
        if self.registry is None:
            self.registry = default_registry()
        return self.registry

    def now(self) -> str:
        return self.clock()

    def lens(self, identifier: str) -> lenses.Lens:
        return lenses.load(identifier, self.lens_directory)

    def gate_context(self, **overrides: Any) -> gates.GateContext:
        settings: dict[str, Any] = {
            "worktree": self.worktree,
            "base": self.base,
            "dry_run": self.dry_run,
            "registry": self.schemas(),
            "clock": self.clock,
        }
        settings.update(overrides)
        return gates.GateContext(**settings)


# --------------------------------------------------------------------------
# Candidate identity
# --------------------------------------------------------------------------


def candidate_diff(context: FlowContext) -> str:
    """What a reviewer sees: the candidate, and nothing about its author."""
    tracked = gitcmd.run(
        context.worktree, "diff", "--find-renames", context.base
    ).stdout
    untracked = []
    for path in gitcmd.untracked_files(context.worktree):
        target = context.worktree / path
        try:
            body = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            body = "<unreadable>"
        untracked.append(f"--- /dev/null\n+++ b/{path}\n" + body)
    return tracked + ("\n".join(untracked) if untracked else "")


def candidate_identity(context: FlowContext, diff: str) -> dict[str, Any]:
    digest = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    return {
        "id": f"{context.run_id}/candidate",
        "digest": f"sha256:{digest}",
        "immutable": True,
    }


def reset_to_base(context: FlowContext) -> None:
    """Discard the candidate and start again from the frozen base.

    Repair resynthesises from the original base rather than editing the
    failed candidate. Reverting an illegal change on top of itself leaves it
    in the candidate's history, and the point is that it should never have
    been there.
    """
    if not context.allow_reset:
        raise FlowError(
            "this flow may not reset its worktree; give it a worktree it owns"
        )
    gitcmd.run(context.worktree, "reset", "--hard", context.base)
    gitcmd.run(context.worktree, "clean", "-fdq")


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------


def envelope_path(step_id: str) -> str:
    return f"envelopes/{step_id}.json"


def adopt_written_envelope(
    context: FlowContext, step_id: str, kind: str, *, attempt: int = 1
) -> dict[str, Any] | None:
    """Recover a step whose envelope reached disk before its manifest record.

    A process killed in the window between writing the envelope and recording
    COMPLETED leaves a run whose manifest says RUNNING and whose result is
    already on disk. Trusting the manifest alone there re-invokes a model that
    already answered — and, for a repair step, resets the worktree first,
    destroying work that was done. The artifact is the evidence; the manifest
    is the index. When they disagree, the artifact wins.
    """
    relative = envelope_path(step_id)
    if not (context.run.root / relative).is_file():
        return None
    envelope = context.run.read_artifact(relative)
    now = context.now()
    context.run.record_step(
        {
            "step_id": step_id,
            "kind": kind,
            "state": "COMPLETED" if envelope.get("status") == "COMPLETED" else "FAILED",
            "attempt": attempt,
            "finished_at": now,
            "envelope_path": relative,
            "note": "adopted an envelope written before the run was interrupted",
        },
        now=now,
    )
    return envelope


def already_produced(context: FlowContext, step_id: str) -> bool:
    """True when this step's result exists, however the manifest reads."""
    recorded = context.run.step(step_id)
    if recorded is not None and recorded.get("state") == "COMPLETED":
        return True
    return (context.run.root / envelope_path(step_id)).is_file()


def step(
    context: FlowContext,
    step_id: str,
    kind: str,
    produce: Callable[[], dict[str, Any]],
    *,
    lens_id: str | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    """Run one step, or return what it already produced.

    This is the resume mechanism in full: the manifest is consulted first,
    and a COMPLETED step is read back rather than repeated.
    """
    recorded = context.run.step(step_id)
    if recorded is not None and recorded.get("state") == "COMPLETED":
        return context.run.read_artifact(recorded["envelope_path"])

    adopted = adopt_written_envelope(context, step_id, kind, attempt=attempt)
    if adopted is not None:
        return adopted

    started = context.now()
    context.run.record_step(
        {
            "step_id": step_id,
            "kind": kind,
            "state": "RUNNING",
            "attempt": attempt,
            "started_at": started,
            **({"lens_id": lens_id} if lens_id else {}),
        },
        now=started,
    )

    envelope = produce()
    relative = envelope_path(step_id)
    context.run.write_artifact(relative, envelope)
    finished = context.now()
    context.run.record_step(
        {
            "step_id": step_id,
            "state": "COMPLETED" if envelope.get("status") == "COMPLETED" else "FAILED",
            "finished_at": finished,
            "envelope_path": relative,
        },
        now=finished,
    )
    return envelope


def gate_step(
    context: FlowContext,
    step_id: str,
    gate_names: Sequence[str],
    *,
    require_clean: bool = True,
    documents: Sequence[gates.DocumentRef] = (),
    candidate: dict[str, Any] | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    def produce() -> dict[str, Any]:
        gate_context = context.gate_context(
            require_clean=require_clean, documents=tuple(documents)
        )
        results = gates.run_gates(gate_names, context.contract, gate_context)
        gates.write_gate_results(results, context.run, step_id=step_id, attempt=attempt)
        return gates.gate_envelope(
            results,
            run_id=context.run_id,
            step_id=step_id,
            contract_ref=context.contract_ref,
            dry_run=context.dry_run,
            produced_at=context.now(),
            candidate=candidate,
            side_effects=[
                {"kind": "file_write", "target": f"runs/{context.run_id}/gates"}
            ],
        )

    return step(context, step_id, "gate", produce, attempt=attempt)


def model_step(
    context: FlowContext,
    step_id: str,
    *,
    kind: str,
    role: str,
    prompt: str,
    output_schema_ref: str,
    envelope_from: Callable[[dict[str, Any]], dict[str, Any]],
    lens_id: str | None = None,
    ladder_level: int | None = None,
    extra_validator: Callable[[dict[str, Any]], Sequence[ValidationError]] | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    """One model call, recorded prompt, bounded retry, envelope either way."""
    registry = context.schemas()
    output_schema = registry.get(output_schema_ref)
    model, effort = context.profile.resolve(role)

    def produce() -> dict[str, Any]:
        context.run.write_artifact(f"prompts/{step_id}.json", {"prompt": prompt})
        call = runners.RunnerCall(
            prompt=prompt,
            output_schema=output_schema,
            model=model,
            effort=effort,
            cwd=context.worktree,
            sandbox=context.profile.sandbox(role),
            lens_id=lens_id,
            step_id=step_id,
        )
        result = runners.invoke_validated(
            context.runner, call, registry=registry, extra_validator=extra_validator
        )
        for record in result.attempts:
            context.run.append_telemetry(
                record.telemetry.to_record(step_id=step_id, role=role)
            )
        if not result.completed:
            return runners.failed_envelope(
                result,
                run_id=context.run_id,
                step_id=step_id,
                step_kind=kind,
                contract_ref=context.contract_ref,
                produced_at=context.now(),
                dry_run=context.dry_run,
                lens_id=lens_id,
                ladder_level=ladder_level,
            )
        envelope = envelope_from(result.output or {})
        envelope["telemetry"] = result.telemetry.to_document()
        return envelope

    return step(context, step_id, kind, produce, lens_id=lens_id, attempt=attempt)


# --------------------------------------------------------------------------
# Envelope construction
# --------------------------------------------------------------------------


def work_envelope(
    context: FlowContext,
    step_id: str,
    result: dict[str, Any],
    *,
    lens_id: str | None,
    candidate: dict[str, Any] | None,
    kind: str = "work",
) -> dict[str, Any]:
    evidence = [
        {
            "id": f"{step_id}/summary",
            "kind": "log",
            "ref": f"envelopes/{step_id}.json",
            "excerpt": result.get("summary", "")[:4000],
        }
    ]
    envelope: dict[str, Any] = {
        "schema_version": "workflows.envelope.v1",
        "envelope_id": f"{context.run_id}/{step_id}",
        "run_id": context.run_id,
        "step_id": step_id,
        "step_kind": kind,
        "status": "COMPLETED",
        "terminal": True,
        # A producer evaluates no criterion. Reporting PASS here would be a
        # producer grading its own work, which is what the gates and the
        # ladder exist to replace.
        "result": "NOT_RUN",
        "dry_run": context.dry_run,
        "produced_at": context.now(),
        "contract_ref": context.contract_ref,
        "evidence": evidence,
        "criterion_results": [],
        "findings": [],
        "non_claims": list(result.get("non_claims", []))
        + [
            "A producer's own account of its work is not a review; nothing "
            "here was independently checked.",
        ],
        "side_effects": [
            {"kind": "file_write", "target": path}
            for path in result.get("changed_paths", [])
        ]
        or [{"kind": "none", "target": "none"}],
    }
    if lens_id:
        envelope["lens_id"] = lens_id
    if candidate is not None:
        envelope["candidate"] = candidate
    return _dedupe_non_claims(envelope)


def review_envelope(
    context: FlowContext,
    step_id: str,
    result: dict[str, Any],
    *,
    lens_id: str | None,
    ladder_level: int,
    candidate: dict[str, Any] | None,
    kind: str = "review",
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": "workflows.envelope.v1",
        "envelope_id": f"{context.run_id}/{step_id}",
        "run_id": context.run_id,
        "step_id": step_id,
        "step_kind": kind,
        "status": "COMPLETED",
        "terminal": True,
        "result": result.get("result", "INCONCLUSIVE"),
        "dry_run": context.dry_run,
        "produced_at": context.now(),
        "contract_ref": context.contract_ref,
        "ladder_level": ladder_level,
        "evidence": list(result.get("evidence", [])),
        "criterion_results": list(result.get("criterion_results", [])),
        "findings": list(result.get("findings", [])),
        "non_claims": list(result.get("non_claims", [])),
        "side_effects": [{"kind": "none", "target": "none"}],
    }
    if lens_id:
        envelope["lens_id"] = lens_id
        for finding in envelope["findings"]:
            finding.setdefault("lens_id", lens_id)
    if candidate is not None:
        envelope["candidate"] = candidate
    return _dedupe_non_claims(envelope)


def _dedupe_non_claims(envelope: dict[str, Any]) -> dict[str, Any]:
    seen: list[str] = []
    for claim in envelope.get("non_claims", []):
        if claim not in seen:
            seen.append(claim)
    envelope["non_claims"] = seen or ["This envelope makes no bounded claim."]
    return envelope


def review_result_validator(
    context: FlowContext, *, ladder_level: int, lens_id: str | None
) -> Callable[[dict[str, Any]], Sequence[ValidationError]]:
    """Hold a review result to the envelope's semantic rules before accepting it.

    A reviewer that asserts an unprobed negative-path property, points at
    evidence it never logged, or passes a candidate while carrying an open
    blocking finding gets the errors back and exactly one more attempt.
    """

    def validate(output: dict[str, Any]) -> Sequence[ValidationError]:
        envelope = review_envelope(
            context,
            "validation-probe",
            output,
            lens_id=lens_id,
            ladder_level=ladder_level,
            candidate=None,
        )
        errors = list(semantic_errors(envelope, ENVELOPE_SCHEMA))
        # A reviewer reports what it found; it does not decide what to do
        # about it. Without this, a review can raise a CRITICAL finding,
        # mark it ACCEPTED_RISK itself, and return PASS — the model under
        # judgment clearing its own worst finding, which is the whole
        # premise of an independent ladder undone in one field.
        for index, finding in enumerate(output.get("findings", [])):
            if finding.get("status") != "OPEN":
                errors.append(
                    ValidationError(
                        f"/findings/{index}/status",
                        "semantic:review_may_not_dispose_of_its_own_finding",
                        "a review reports findings as OPEN; accepting or "
                        "withdrawing one is a later decision by a different "
                        "step or a human",
                    )
                )
        return errors

    return validate


def _namespaced(step_id: str, identifier: str) -> str:
    return f"{step_id}/{identifier}"


def verdict(
    context: FlowContext,
    *,
    flow: str,
    result: str,
    envelopes: Sequence[dict[str, Any]],
    ladder_levels_run: Sequence[int],
    candidate: dict[str, Any] | None,
    superseded_steps: Sequence[str] = (),
    extra_non_claims: Sequence[str] = (),
) -> dict[str, Any]:
    """One consolidated judgment, with what it does not claim spelled out.

    Ids are namespaced by the step that produced them. Two rounds of review
    legitimately both produce a finding called ``F-1`` pointing at their own
    ``probe-1``; folding them together unnamespaced would make one round's
    claim resolve to the other round's evidence.

    ``superseded_steps`` names steps whose findings a later round resolved.
    They stay in the record, marked RESOLVED, rather than disappearing —
    what a repair fixed is part of what happened.
    """
    superseded = set(superseded_steps)
    evidence: list[dict[str, Any]] = []
    criterion_results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    claimed: set[str] = set()

    for envelope in envelopes:
        step_id = envelope.get("step_id", "step")
        for item in envelope.get("evidence", []):
            evidence.append({**item, "id": _namespaced(step_id, item["id"])})
        for finding in envelope.get("findings", []):
            copied = {
                **finding,
                "id": _namespaced(step_id, finding["id"]),
                "evidence_refs": [
                    _namespaced(step_id, ref) for ref in finding.get("evidence_refs", [])
                ],
            }
            if step_id in superseded and copied.get("status") == "OPEN":
                copied["status"] = "RESOLVED"
            findings.append(copied)
        if envelope.get("step_kind") != "review":
            continue
        for outcome in envelope.get("criterion_results", []):
            if outcome["criterion_id"] in claimed or step_id in superseded:
                continue
            claimed.add(outcome["criterion_id"])
            criterion_results.append(
                {
                    **outcome,
                    "evidence_refs": [
                        _namespaced(step_id, ref) for ref in outcome.get("evidence_refs", [])
                    ],
                }
            )

    extra_non_claims = list(extra_non_claims)
    if context.dry_run and result in ("PASS", "FAIL"):
        # A dry run calls no model, so it concludes nothing — in either
        # direction. The one real signal a dry run carries is a gate finding,
        # because gates do run; without one, the verdict is INCONCLUSIVE.
        real = [
            finding
            for envelope in envelopes
            for finding in envelope.get("findings", [])
            if finding.get("status") == "OPEN"
        ]
        if not real:
            result = "INCONCLUSIVE"
        extra_non_claims.insert(
            0,
            "Dry run: prompts, gates and the manifest were materialized and no "
            "model was called. Nothing here is evidence about the candidate.",
        )

    document = {
        "schema_version": "workflows.verdict.v1",
        "verdict_id": f"{context.run_id}/verdict",
        "run_id": context.run_id,
        "flow": flow,
        "result": result,
        "dry_run": context.dry_run,
        "decided_at": context.now(),
        "contract_ref": context.contract_ref,
        "ladder_levels_run": sorted(set(ladder_levels_run)),
        "envelope_refs": [envelope["envelope_id"] for envelope in envelopes],
        "evidence": evidence,
        "criterion_results": criterion_results,
        "findings": findings,
        "non_claims": list(extra_non_claims),
    }
    if candidate is not None:
        document["candidate"] = candidate
    return _dedupe_non_claims(document)


def write_verdict(context: FlowContext, document: dict[str, Any]) -> dict[str, Any]:
    """Record the verdict, or return the one this run already reached.

    A verdict is terminal. Re-running a finished run replays nothing and must
    not re-decide it: the recorded verdict is the run's decision, and a second
    one differing only by its timestamp would be a rewritten audit trail.
    """
    relative = "verdict.json"
    if (context.run.root / relative).is_file():
        return context.run.read_artifact(relative)
    context.run.write_artifact(relative, document)
    return document


def validate_document(
    context: FlowContext, document: dict[str, Any], schema_ref: str
) -> list[ValidationError]:
    return check_document(document, schema_ref, registry=context.schemas())


__all__ = [
    "ENVELOPE_SCHEMA",
    "REVIEW_RESULT_SCHEMA",
    "VERDICT_SCHEMA",
    "WORK_RESULT_SCHEMA",
    "FlowContext",
    "FlowError",
    "Profile",
    "candidate_diff",
    "candidate_identity",
    "gate_step",
    "model_step",
    "reset_to_base",
    "review_envelope",
    "review_result_validator",
    "step",
    "validate_document",
    "verdict",
    "work_envelope",
]
