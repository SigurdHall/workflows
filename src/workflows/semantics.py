"""Checks a schema keyword cannot express.

JSON Schema can say what shape a document has. It cannot say that a claim
must point at evidence that exists, that a PASS may not carry an open HIGH
finding, or that two tasks in one plan may not write the same file. Those
rules are the difference between a document that parses and a document that
means something, so they live here — next to the validator, run by the same
entry point, and covered by the same annotated fixture corpus.

Semantic errors are reported as :class:`~workflows.schema.ValidationError`
with a ``semantic:<rule>`` keyword, so a fixture annotates them exactly like
a schema violation.

Semantic checks assume a schema-valid document. :func:`check_document` runs
schema validation first and returns without running them if it fails — a
gate failure is terminal for the step, and a rule reading fields that are
not there would report noise instead of the cause.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterator

from workflows import paths
from workflows.schema import (
    SchemaRegistry,
    ValidationError,
    default_registry,
    resolve_schema,
    validate,
)

RULE_PREFIX = "semantic:"

BLOCKING_SEVERITIES = frozenset({"CRITICAL", "HIGH"})
PASSING_RESULTS = frozenset({"PASS"})


def _error(path: str, rule: str, message: str) -> ValidationError:
    return ValidationError(path, RULE_PREFIX + rule, message)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _duplicates(
    entries: list[dict[str, Any]], key: str, base: str, rule: str
) -> Iterator[ValidationError]:
    seen: set[Any] = set()
    for index, entry in enumerate(entries):
        value = entry.get(key)
        if value in seen:
            yield _error(
                f"{base}/{index}/{key}", rule, f"{value!r} is already used above"
            )
        seen.add(value)


# --------------------------------------------------------------------------
# Shared: evidence discipline (envelopes and verdicts)
# --------------------------------------------------------------------------


def _evidence_checks(document: dict[str, Any]) -> Iterator[ValidationError]:
    evidence = document.get("evidence", [])
    yield from _duplicates(evidence, "id", "/evidence", "duplicate_evidence_id")
    kinds = {entry.get("id"): entry.get("kind") for entry in evidence}

    for field in ("findings", "criterion_results"):
        for index, entry in enumerate(document.get(field, [])):
            refs = entry.get("evidence_refs", [])
            for position, ref in enumerate(refs):
                if ref not in kinds:
                    yield _error(
                        f"/{field}/{index}/evidence_refs/{position}",
                        "unknown_evidence_ref",
                        f"{ref!r} is not declared in this document's evidence",
                    )
            if entry.get("negative_path_claim") and not any(
                kinds.get(ref) == "probe" for ref in refs
            ):
                yield _error(
                    f"/{field}/{index}",
                    "negative_path_requires_probe",
                    "a claim that something invalid is rejected needs an "
                    "executed probe among its evidence, not an assertion",
                )

    yield from _duplicates(document.get("findings", []), "id", "/findings", "duplicate_finding_id")
    yield from _duplicates(
        document.get("criterion_results", []),
        "criterion_id",
        "/criterion_results",
        "duplicate_criterion_id",
    )

    for index, outcome in enumerate(document.get("criterion_results", [])):
        if outcome.get("result") in PASSING_RESULTS and not outcome.get("evidence_refs"):
            yield _error(
                f"/criterion_results/{index}/evidence_refs",
                "pass_requires_evidence",
                "a PASS with no evidence is vacuous success",
            )


def _open_blocking_findings(document: dict[str, Any]) -> list[int]:
    return [
        index
        for index, finding in enumerate(document.get("findings", []))
        if finding.get("status") == "OPEN"
        and finding.get("severity") in BLOCKING_SEVERITIES
    ]


def _pass_integrity(document: dict[str, Any]) -> Iterator[ValidationError]:
    if document.get("result") not in PASSING_RESULTS:
        return
    blocking = _open_blocking_findings(document)
    if blocking:
        yield _error(
            "/result",
            "pass_with_open_blocking_finding",
            "PASS while findings "
            + ", ".join(str(index) for index in blocking)
            + " are OPEN at CRITICAL or HIGH severity",
        )
    # A PASS is a claim about the criteria, not only about the findings: a
    # document can report every criterion FAIL, carry no finding at all, and
    # still say PASS unless this is checked. NOT_RUN stays allowed — a gate
    # with nothing to check is legitimate — but it must be named in
    # non_claims, which is what the gate runner does.
    outcomes = document.get("criterion_results", [])
    if not outcomes:
        yield _error(
            "/criterion_results",
            "pass_without_criteria",
            "PASS while no criterion was evaluated: a judgment about nothing "
            "is the vacuous-success shape",
        )
    unmet = [
        (index, outcome.get("result"))
        for index, outcome in enumerate(outcomes)
        if outcome.get("result") in ("FAIL", "INCONCLUSIVE")
    ]
    if unmet:
        yield _error(
            "/result",
            "pass_with_unmet_criterion",
            "PASS while criteria "
            + ", ".join(f"{index} ({result})" for index, result in unmet)
            + " did not pass",
        )


def _dry_run_consistency(document: dict[str, Any]) -> Iterator[ValidationError]:
    telemetry = document.get("telemetry")
    if telemetry is None:
        return
    if telemetry.get("dry") != document.get("dry_run"):
        yield _error(
            "/telemetry/dry",
            "dry_run_inconsistent",
            "telemetry disagrees with the envelope about whether a model was called",
        )


# --------------------------------------------------------------------------
# Per document type
# --------------------------------------------------------------------------


def _envelope(document: dict[str, Any]) -> Iterator[ValidationError]:
    yield from _evidence_checks(document)
    yield from _pass_integrity(document)
    yield from _dry_run_consistency(document)
    if document.get("status") == "COMPLETED" and document.get("terminal") is False:
        yield _error(
            "/terminal",
            "completed_is_terminal",
            "a COMPLETED step is not attempted again; terminal must be true",
        )


def _verdict(document: dict[str, Any]) -> Iterator[ValidationError]:
    yield from _evidence_checks(document)
    yield from _pass_integrity(document)
    if 0 not in document.get("ladder_levels_run", []):
        yield _error(
            "/ladder_levels_run",
            "gates_always_run",
            "level 0 gates run before any model review; a verdict without "
            "them rests on nothing deterministic",
        )


def _task_contract(document: dict[str, Any]) -> Iterator[ValidationError]:
    yield from _duplicates(document.get("acceptance", []), "id", "/acceptance", "duplicate_criterion_id")
    allowed = document.get("scope", {}).get("allowed_paths", [])
    for index, protected in enumerate(document.get("protected", [])):
        # Both sides are patterns. Asking whether the protected *string*
        # matches an allowed pattern misses the common case where the
        # protected side carries the wildcard: protected "*.md" against
        # allowed "README.md" is a contradiction that reads as clean.
        if any(paths.overlaps(pattern, protected) for pattern in allowed):
            yield _error(
                f"/protected/{index}",
                "protected_inside_scope",
                f"{protected!r} is both writable and protected; a hash gate "
                "would reject every candidate that uses its own scope",
            )


def _goal_contract(document: dict[str, Any]) -> Iterator[ValidationError]:
    yield from _duplicates(document.get("subgoals", []), "id", "/subgoals", "duplicate_subgoal_id")
    yield from _duplicates(
        document.get("evidence_requirements", []),
        "id",
        "/evidence_requirements",
        "duplicate_requirement_id",
    )
    yield from _duplicates(
        document.get("attainment_rubric", {}).get("levels", []),
        "id",
        "/attainment_rubric/levels",
        "duplicate_rubric_level_id",
    )
    for index, requirement in enumerate(document.get("evidence_requirements", [])):
        if requirement.get("check") != "manual_judgment" and not requirement.get("target"):
            yield _error(
                f"/evidence_requirements/{index}/target",
                "check_requires_target",
                f"the {requirement.get('check')!r} check has nothing to check "
                "without a target; only manual_judgment may omit one",
            )


def _plan(document: dict[str, Any]) -> Iterator[ValidationError]:
    bases = document.get("base", [])
    yield from _duplicates(bases, "repo_id", "/base", "duplicate_repo_id")
    repo_ids = {base.get("repo_id") for base in bases}
    tasks = document.get("tasks", [])
    yield from _duplicates(tasks, "task_id", "/tasks", "duplicate_task_id")

    for index, task in enumerate(tasks):
        repo_id = task.get("repo_id")
        if repo_id is None:
            if len(bases) > 1:
                yield _error(
                    f"/tasks/{index}/repo_id",
                    "ambiguous_repo",
                    "the plan freezes more than one repository, so every task "
                    "must name the one it writes to",
                )
        elif repo_id not in repo_ids:
            yield _error(
                f"/tasks/{index}/repo_id",
                "unknown_repo_id",
                f"{repo_id!r} is not among the frozen bases",
            )
        if task.get("flow") == "fanout" and len(task.get("lens_set", [])) < 2:
            yield _error(
                f"/tasks/{index}/lens_set",
                "fanout_requires_lens_set",
                "fan-out is breadth of perspectives; fewer than two lenses "
                "buys redundancy, not coverage",
            )

    # A single-base plan lets a task omit repo_id, so comparing the raw field
    # would silently skip every pair where one task states it and the other
    # does not — the exact pair a disjoint-scope rule exists to catch.
    default_repo = bases[0].get("repo_id") if len(bases) == 1 else None

    def repo_of(task: dict[str, Any]) -> Any:
        return task.get("repo_id", default_repo) or default_repo

    for i, task in enumerate(tasks):
        for j in range(i + 1, len(tasks)):
            other = tasks[j]
            if repo_of(task) != repo_of(other):
                continue
            clash = next(
                (
                    (left, right)
                    for left in task.get("write_scope", [])
                    for right in other.get("write_scope", [])
                    if paths.overlaps(left, right)
                ),
                None,
            )
            if clash is not None:
                yield _error(
                    f"/tasks/{j}/write_scope",
                    "overlapping_write_scope",
                    f"{clash[1]!r} can match the same path as {clash[0]!r} in "
                    f"task {task.get('task_id')!r}; tasks that share a write "
                    "target are one task",
                )


def _run_manifest(document: dict[str, Any]) -> Iterator[ValidationError]:
    steps = document.get("steps", [])
    yield from _duplicates(steps, "step_id", "/steps", "duplicate_step_id")
    for index, step in enumerate(steps):
        started, finished = step.get("started_at"), step.get("finished_at")
        if step.get("state") in ("COMPLETED", "FAILED") and finished is None:
            yield _error(
                f"/steps/{index}/finished_at",
                "finished_step_needs_timestamp",
                "a step that reached a terminal state recorded no finish time, "
                "so resume cannot tell it apart from one still running",
            )
        if started and finished and _timestamp(finished) < _timestamp(started):
            yield _error(
                f"/steps/{index}/finished_at",
                "finished_before_started",
                "the step finished before it started",
            )
    created, updated = document.get("created_at"), document.get("updated_at")
    if created and updated and _timestamp(updated) < _timestamp(created):
        yield _error(
            "/updated_at", "updated_before_created", "the run was updated before it existed"
        )


CHECKS: dict[str, Callable[[dict[str, Any]], Iterator[ValidationError]]] = {
    "envelope.schema.json": _envelope,
    "verdict.schema.json": _verdict,
    "task-contract.schema.json": _task_contract,
    "goal-contract.schema.json": _goal_contract,
    "plan.schema.json": _plan,
    "run-manifest.schema.json": _run_manifest,
}


def semantic_errors(document: Any, schema_ref: str) -> list[ValidationError]:
    """Semantic violations for a whole document; empty for sub-schema refs."""
    document_id, _, fragment = schema_ref.partition("#")
    if fragment or document_id not in CHECKS:
        return []
    if not isinstance(document, dict):
        return []
    return list(CHECKS[document_id](document))


def check_document(
    document: Any, schema_ref: str, *, registry: SchemaRegistry | None = None
) -> list[ValidationError]:
    """Validate a document against its schema, then against the semantic rules."""
    registry = registry if registry is not None else default_registry()
    schema, owner = resolve_schema(schema_ref, registry)
    errors = validate(document, schema, registry=registry, document=owner)
    if errors:
        return errors
    return semantic_errors(document, schema_ref)
