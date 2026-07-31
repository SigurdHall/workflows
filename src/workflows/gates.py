"""Deterministic checks. Zero tokens, milliseconds, always right about what
they check.

A gate is a pure function ``(contract, context) -> GateResult``. Gates run
before *and* after every model stage, and a gate failure is terminal for the
step: the result goes back to repair, never onward to review. Expensive
reviewers only ever see gate-clean work.

Three rules the implementation takes literally:

* **A gate that cannot fail is documentation.** Every gate returns a result
  and a machine-readable reason code. Nothing is warned about.
* **No silent fallbacks.** If the verification command's executable is
  missing, that is ``command_not_found`` and a FAIL — never a skip, never a
  pass, and never a quiet retry with a different interpreter. A fallback
  interpreter is something a contract states, not something a gate guesses.
* **Ask a hash, not a model.** The most expensive finding in the motivating
  experiments was a protected-file modification found by an eleven-minute
  review; a blob comparison finds it in milliseconds.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from workflows import gitcmd, paths
from workflows.runs import utc_now
from workflows.schema import SchemaRegistry, default_registry
from workflows.semantics import check_document

GATE_SCHEMA = "gate-result.schema.json"
SCHEMA_VERSION = "workflows.gate-result.v1"

EXTERNAL_LINK = ("http://", "https://", "mailto:", "#")
JUDGMENT_CHECKS = frozenset({"number_traceable", "manual_judgment"})


class GateError(RuntimeError):
    """The gate could not be configured — an author error, not a data error."""


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    ref: str
    exit_code: int | None = None
    excerpt: str | None = None
    digest: str | None = None

    def to_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {"id": self.id, "kind": self.kind, "ref": self.ref}
        if self.exit_code is not None:
            document["exit_code"] = self.exit_code
        if self.excerpt:
            document["excerpt"] = self.excerpt[:4000]
        if self.digest:
            document["digest"] = self.digest
        return document


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    result: str
    reason_code: str
    checked_at: str
    detail: str | None = None
    evidence: tuple[Evidence, ...] = ()
    findings: tuple[dict[str, Any], ...] = ()
    non_claims: tuple[str, ...] = ()
    duration_ms: int | None = None

    @property
    def passed(self) -> bool:
        return self.result == "PASS"

    @property
    def failed(self) -> bool:
        return self.result == "FAIL"

    def to_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "gate_id": self.gate_id,
            "result": self.result,
            "reason_code": self.reason_code,
            "checked_at": self.checked_at,
        }
        if self.detail:
            document["detail"] = self.detail[:4000]
        if self.duration_ms is not None:
            document["duration_ms"] = self.duration_ms
        document["evidence"] = [item.to_document() for item in self.evidence]
        document["findings"] = list(self.findings)
        document["non_claims"] = list(self.non_claims) or [
            "Deterministic check only; nothing here is a judgment about quality."
        ]
        return document


@dataclass(frozen=True)
class DocumentRef:
    """A document the schema gate must validate, and the schema it must match."""

    path: str
    schema: str


@dataclass(frozen=True)
class GateContext:
    """Everything a gate may look at besides the contract."""

    worktree: Path
    base: str
    require_clean: bool = True
    documents: tuple[DocumentRef, ...] = ()
    registry: SchemaRegistry | None = None
    clock: Callable[[], str] = utc_now
    command_timeout: int = 900
    options: dict[str, Any] = field(default_factory=dict)

    def now(self) -> str:
        return self.clock()

    def schemas(self) -> SchemaRegistry:
        return self.registry if self.registry is not None else default_registry()


def _finding(
    identifier: str,
    severity: str,
    claim: str,
    action: str,
    evidence_refs: Sequence[str],
    location: str | None = None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "id": identifier,
        "severity": severity,
        "status": "OPEN",
        "claim": claim,
        "evidence_refs": list(evidence_refs),
        "required_action": action,
        "negative_path_claim": False,
    }
    if location:
        finding["location"] = location
    return finding


def _slug(value: str) -> str:
    """A path or command turned into something the identifier pattern accepts."""
    cleaned = "".join(
        character if character.isalnum() or character in "._-/" else "-"
        for character in value
    ).strip("-/.")
    return cleaned[:80] or "item"


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------


def base_identity(contract: dict[str, Any], context: GateContext) -> GateResult:
    """The candidate stands on the frozen base, and only on it."""
    now = context.now()
    if not gitcmd.rev_exists(context.worktree, context.base):
        return GateResult(
            "base_identity",
            "FAIL",
            "unknown_base",
            now,
            detail=f"the frozen base {context.base} does not exist in this worktree",
        )

    head = gitcmd.head_commit(context.worktree)
    evidence = [
        Evidence("base_identity/head", "command", "git rev-parse HEAD", excerpt=head),
        Evidence("base_identity/base", "command", f"git rev-parse {context.base}", excerpt=context.base),
    ]
    if head != context.base and context.base not in gitcmd.parents(context.worktree, head):
        return GateResult(
            "base_identity",
            "FAIL",
            "base_mismatch",
            now,
            detail=(
                f"HEAD is {head}, which is neither the frozen base {context.base} "
                "nor a commit directly on top of it"
            ),
            evidence=tuple(evidence),
            findings=(
                _finding(
                    "base-identity-mismatch",
                    "CRITICAL",
                    "The candidate was built on a different base than the run froze.",
                    "Rebuild the candidate from the frozen base.",
                    ["base_identity/head"],
                ),
            ),
        )

    if context.require_clean:
        dirty = gitcmd.dirty_paths(context.worktree)
        if dirty:
            return GateResult(
                "base_identity",
                "FAIL",
                "dirty_worktree",
                now,
                detail="uncommitted changes before any work started: " + ", ".join(dirty[:20]),
                evidence=tuple(
                    evidence
                    + [Evidence("base_identity/status", "command", "git status --porcelain", excerpt="\n".join(dirty))]
                ),
                findings=(
                    _finding(
                        "base-identity-dirty",
                        "HIGH",
                        "The worktree already differed from the base before work started.",
                        "Reset the worktree to the frozen base, or freeze a different base.",
                        ["base_identity/status"],
                    ),
                ),
            )

    return GateResult("base_identity", "PASS", "clean", now, evidence=tuple(evidence))


def scope(contract: dict[str, Any], context: GateContext) -> GateResult:
    """Nothing changed outside the paths the contract allows."""
    now = context.now()
    allowed = list(contract.get("scope", {}).get("allowed_paths", []))
    if not allowed:
        raise GateError("the scope gate needs a contract with allowed_paths")

    changes = gitcmd.changes(context.worktree, context.base)
    evidence = [
        Evidence(
            "scope/diff",
            "command",
            f"git diff --name-status --find-renames {context.base} (plus untracked)",
            excerpt="\n".join(f"{change.status}\t{change.path}" for change in changes),
        )
    ]

    violations: list[tuple[str, str]] = []
    for change in changes:
        # A rename is judged on both ends: moving a file out of scope is a
        # change to a path the contract never allowed.
        for path in change.paths:
            if not paths.matches_any(allowed, path):
                violations.append((change.status, path))

    if violations:
        findings = tuple(
            _finding(
                f"scope-{_slug(path)}",
                "HIGH",
                f"{path!r} was changed ({status}) but is not in the contract's scope.",
                f"Revert {path!r}, or widen the contract's scope and re-approve the plan.",
                ["scope/diff"],
                location=path,
            )
            for status, path in violations
        )
        return GateResult(
            "scope",
            "FAIL",
            "out_of_scope_change",
            now,
            detail="; ".join(f"{status} {path}" for status, path in violations),
            evidence=tuple(evidence),
            findings=findings,
        )

    return GateResult(
        "scope",
        "PASS",
        "clean",
        now,
        detail=f"{len(changes)} changed path(s), all within scope",
        evidence=tuple(evidence),
    )


def protected_hash(contract: dict[str, Any], context: GateContext) -> GateResult:
    """Protected files are byte-identical to the base, or the gate fails."""
    now = context.now()
    patterns = list(contract.get("protected", []))
    if not patterns:
        return GateResult(
            "protected_hash",
            "NOT_RUN",
            "not_applicable",
            now,
            detail="the contract declares no protected paths",
            non_claims=("No file was protected by this contract, so nothing was compared.",),
        )

    at_base = gitcmd.files_at(context.worktree, context.base)
    protected_at_base = [path for path in at_base if paths.matches_any(patterns, path)]

    evidence = [
        Evidence(
            "protected/base-listing",
            "command",
            f"git ls-tree -r --name-only {context.base}",
            excerpt="\n".join(protected_at_base[:200]),
        )
    ]
    violations: list[tuple[str, str]] = []

    for path in protected_at_base:
        before = gitcmd.blob_hash_at(context.worktree, context.base, path)
        after = gitcmd.blob_hash_now(context.worktree, path)
        if after is None:
            violations.append(("protected_deleted", path))
        elif after != before:
            violations.append(("protected_modified", path))

    known = set(protected_at_base)
    for change in gitcmd.changes(context.worktree, context.base):
        for path in change.paths:
            if path not in known and paths.matches_any(patterns, path):
                violations.append(("protected_modified", path))

    # A protected path spelled as a literal that does not exist at the base is
    # a typo, and a typo in a protection list protects nothing.
    for pattern in patterns:
        if "*" in pattern and not any(paths.matches(pattern, p) for p in at_base):
            continue
        if not any(paths.matches(pattern, p) for p in at_base):
            violations.append(("protected_missing_at_base", pattern))

    if violations:
        reason = violations[0][0]
        findings = tuple(
            _finding(
                f"protected-{_slug(path)}",
                "CRITICAL",
                {
                    "protected_deleted": f"The protected file {path!r} was deleted.",
                    "protected_modified": f"The protected file {path!r} is not byte-identical to the base.",
                    "protected_missing_at_base": (
                        f"The protected path {path!r} does not exist at the frozen base, "
                        "so it protects nothing."
                    ),
                }[kind],
                (
                    f"Restore {path!r} to its base content."
                    if kind != "protected_missing_at_base"
                    else f"Correct the protected path {path!r} in the contract."
                ),
                ["protected/base-listing"],
                location=path,
            )
            for kind, path in violations
        )
        return GateResult(
            "protected_hash",
            "FAIL",
            reason,
            now,
            detail="; ".join(f"{kind}: {path}" for kind, path in violations),
            evidence=tuple(evidence),
            findings=findings,
        )

    return GateResult(
        "protected_hash",
        "PASS",
        "clean",
        now,
        detail=f"{len(protected_at_base)} protected file(s) byte-identical to the base",
        evidence=tuple(evidence),
    )


def verification_command(contract: dict[str, Any], context: GateContext) -> GateResult:
    """The contract's command runs, and its exit code is the primary oracle."""
    now = context.now()
    verification = contract.get("verification")
    if not verification:
        raise GateError("the verification gate needs a contract with a verification command")

    command = list(verification["command"])
    expected = verification.get("expect_exit_code", 0)
    timeout = verification.get("timeout_seconds", context.command_timeout)
    cwd = context.worktree / verification.get("cwd", ".")
    printable = " ".join(command)

    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        # Fails closed, with its own reason code. Never "skipped", never green,
        # and never silently retried through a different interpreter: a
        # fallback is something a contract states explicitly.
        return GateResult(
            "verification_command",
            "FAIL",
            "command_not_found",
            now,
            detail=f"{command[0]!r} is not executable here: {exc}",
            evidence=(Evidence("verification/command", "command", printable),),
            findings=(
                _finding(
                    "verification-command-not-found",
                    "CRITICAL",
                    f"The verification command {command[0]!r} does not exist in this environment.",
                    "Install it, or state the exact interpreter in the contract. "
                    "A missing oracle is not a passing oracle.",
                    ["verification/command"],
                ),
            ),
            non_claims=("Nothing was verified: the command never ran.",),
        )
    except subprocess.TimeoutExpired:
        return GateResult(
            "verification_command",
            "FAIL",
            "timeout",
            now,
            detail=f"{printable!r} exceeded {timeout}s",
            evidence=(Evidence("verification/command", "command", printable),),
            findings=(
                _finding(
                    "verification-timeout",
                    "HIGH",
                    f"The verification command did not finish within {timeout} seconds.",
                    "Reduce the command's work or raise timeout_seconds deliberately.",
                    ["verification/command"],
                ),
            ),
            non_claims=("Nothing was verified: the command did not finish.",),
        )

    tail = (completed.stdout + completed.stderr).strip()[-3000:]
    evidence = (
        Evidence(
            "verification/command",
            "command",
            printable,
            exit_code=completed.returncode,
            excerpt=tail,
        ),
    )
    if completed.returncode != expected:
        return GateResult(
            "verification_command",
            "FAIL",
            "nonzero_exit",
            now,
            detail=f"exit {completed.returncode}, expected {expected}",
            evidence=evidence,
            findings=(
                _finding(
                    "verification-failed",
                    "HIGH",
                    f"The verification command exited {completed.returncode}, expected {expected}.",
                    "Make the candidate satisfy the contract's verification command.",
                    ["verification/command"],
                ),
            ),
        )
    return GateResult("verification_command", "PASS", "clean", now, evidence=evidence)


def schema(contract: dict[str, Any], context: GateContext) -> GateResult:
    """Every document crossing a step boundary validates before it crosses."""
    now = context.now()
    if not context.documents:
        return GateResult(
            "schema",
            "NOT_RUN",
            "not_applicable",
            now,
            detail="no documents were presented to this gate",
            non_claims=("No document was validated at this point in the flow.",),
        )

    registry = context.schemas()
    evidence: list[Evidence] = []
    findings: list[dict[str, Any]] = []
    for reference in context.documents:
        target = context.worktree / reference.path
        evidence_id = f"schema/{_slug(reference.path)}"
        try:
            document = _load_document(target)
        except (OSError, ValueError) as exc:
            evidence.append(Evidence(evidence_id, "file", reference.path, excerpt=str(exc)))
            findings.append(
                _finding(
                    f"schema-unreadable-{_slug(reference.path)}",
                    "CRITICAL",
                    f"{reference.path!r} could not be read as a document: {exc}",
                    "Produce a parseable document for this step.",
                    [evidence_id],
                    location=reference.path,
                )
            )
            continue

        errors = check_document(document, reference.schema, registry=registry)
        evidence.append(
            Evidence(
                evidence_id,
                "file",
                reference.path,
                excerpt="\n".join(str(error) for error in errors[:50]) or "valid",
            )
        )
        findings.extend(
            _finding(
                f"schema-{_slug(reference.path)}-{_slug(error.keyword)}-{index}",
                "HIGH",
                f"{reference.path}{error.path or '/'}: {error.keyword}: {error.message}",
                "Emit a document that satisfies its schema; free-text protocol data is forbidden.",
                [evidence_id],
                location=f"{reference.path}{error.path}",
            )
            for index, error in enumerate(errors)
        )

    if findings:
        return GateResult(
            "schema",
            "FAIL",
            "schema_invalid",
            now,
            detail=f"{len(findings)} violation(s) across {len(context.documents)} document(s)",
            evidence=tuple(evidence),
            findings=tuple(findings),
        )
    return GateResult("schema", "PASS", "clean", now, evidence=tuple(evidence))


def evidence_obligations(contract: dict[str, Any], context: GateContext) -> GateResult:
    """Goal contracts: deliverables exist and references resolve.

    Weaker than a hash and honest about it. Obligations that no deterministic
    check can settle come back INCONCLUSIVE with ``requires_judgment``, which
    keeps a goal from being declared attained on the strength of gates alone.
    """
    now = context.now()
    requirements = contract.get("evidence_requirements")
    if not requirements:
        raise GateError("the evidence gate needs a goal contract with evidence_requirements")

    evidence: list[Evidence] = []
    findings: list[dict[str, Any]] = []
    judged: list[str] = []
    reason = "clean"

    for requirement in requirements:
        identifier = requirement["id"]
        check = requirement["check"]
        target = requirement.get("target", "")
        evidence_id = f"evidence/{_slug(identifier)}"

        if check in JUDGMENT_CHECKS:
            judged.append(identifier)
            evidence.append(
                Evidence(evidence_id, "citation", target or identifier, excerpt="requires judgment")
            )
            continue

        if check == "command_succeeds":
            outcome, detail = _run_obligation_command(target, context)
            evidence.append(Evidence(evidence_id, "command", target, excerpt=detail))
            if outcome != "clean":
                reason = outcome
                findings.append(
                    _finding(
                        f"evidence-{_slug(identifier)}",
                        "HIGH",
                        f"Evidence obligation {identifier!r} failed: {detail}",
                        f"Satisfy {identifier!r} or restate the obligation.",
                        [evidence_id],
                        location=target,
                    )
                )
            continue

        path = context.worktree / target
        if check == "artifact_exists":
            if not path.is_file():
                reason = "missing_artifact"
                detail = "the deliverable does not exist"
            elif path.stat().st_size == 0:
                reason = "empty_artifact"
                detail = "the deliverable exists but is empty"
            else:
                detail = f"{path.stat().st_size} bytes"
            evidence.append(Evidence(evidence_id, "file", target, excerpt=detail))
            if reason in ("missing_artifact", "empty_artifact"):
                findings.append(
                    _finding(
                        f"evidence-{_slug(identifier)}",
                        "HIGH",
                        f"Evidence obligation {identifier!r} is unmet: {detail}.",
                        f"Produce {target!r}, or remove the obligation from the contract.",
                        [evidence_id],
                        location=target,
                    )
                )
            continue

        if check == "reference_resolves":
            unresolved = _unresolved_references(path, context.worktree)
            evidence.append(
                Evidence(
                    evidence_id,
                    "file",
                    target,
                    excerpt="\n".join(unresolved) if unresolved else "all references resolve",
                )
            )
            if not path.is_file():
                reason = "missing_artifact"
                findings.append(
                    _finding(
                        f"evidence-{_slug(identifier)}",
                        "HIGH",
                        f"Evidence obligation {identifier!r} points at {target!r}, which does not exist.",
                        f"Produce {target!r}, or restate the obligation.",
                        [evidence_id],
                        location=target,
                    )
                )
            elif unresolved:
                reason = "unresolved_reference"
                findings.append(
                    _finding(
                        f"evidence-{_slug(identifier)}",
                        "HIGH",
                        f"{target!r} references paths that do not exist: {', '.join(unresolved[:10])}.",
                        "Make every reference resolve, or remove the claim it supports.",
                        [evidence_id],
                        location=target,
                    )
                )
            continue

        raise GateError(f"unsupported evidence check: {check!r}")

    non_claims = [
        "Evidence obligations are weaker than hashes: this gate checks that "
        "deliverables exist and references resolve, not that they are right.",
    ]
    if judged:
        non_claims.append(
            "Not checked deterministically, left to review: " + ", ".join(judged) + "."
        )

    if findings:
        return GateResult(
            "evidence_obligations",
            "FAIL",
            reason,
            now,
            detail=f"{len(findings)} unmet obligation(s)",
            evidence=tuple(evidence),
            findings=tuple(findings),
            non_claims=tuple(non_claims),
        )
    if judged:
        return GateResult(
            "evidence_obligations",
            "INCONCLUSIVE",
            "requires_judgment",
            now,
            detail=f"{len(judged)} obligation(s) need a reviewer",
            evidence=tuple(evidence),
            non_claims=tuple(non_claims),
        )
    return GateResult(
        "evidence_obligations",
        "PASS",
        "clean",
        now,
        evidence=tuple(evidence),
        non_claims=tuple(non_claims),
    )


def _load_document(path: Path) -> Any:
    import json
    import tomllib

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".toml":
        return tomllib.loads(text)
    return json.loads(text)


def _run_obligation_command(target: str, context: GateContext) -> tuple[str, str]:
    command = target.split()
    if not command:
        return "missing_artifact", "the obligation names no command"
    try:
        completed = subprocess.run(
            command,
            cwd=str(context.worktree),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=context.command_timeout,
        )
    except FileNotFoundError:
        return "command_not_found", f"{command[0]!r} is not executable here"
    except subprocess.TimeoutExpired:
        return "timeout", f"{target!r} did not finish"
    if completed.returncode != 0:
        return "nonzero_exit", f"exit {completed.returncode}"
    return "clean", "exit 0"


def _unresolved_references(document: Path, worktree: Path) -> list[str]:
    """Relative links in a markdown-ish document that point at nothing."""
    import re

    if not document.is_file():
        return []
    text = document.read_text(encoding="utf-8", errors="replace")
    targets = re.findall(r"\]\(([^)\s]+)\)", text)
    unresolved: list[str] = []
    for target in targets:
        if target.startswith(EXTERNAL_LINK):
            continue
        candidate = (document.parent / target.split("#", 1)[0]).resolve()
        try:
            candidate.relative_to(worktree.resolve())
        except ValueError:
            unresolved.append(target)
            continue
        if not candidate.exists():
            unresolved.append(target)
    return unresolved


GATES: dict[str, Callable[[dict[str, Any], GateContext], GateResult]] = {
    "base_identity": base_identity,
    "scope": scope,
    "protected_hash": protected_hash,
    "verification_command": verification_command,
    "schema": schema,
    "evidence_obligations": evidence_obligations,
}


# --------------------------------------------------------------------------
# The runner
# --------------------------------------------------------------------------


def run_gates(
    names: Iterable[str], contract: dict[str, Any], context: GateContext
) -> list[GateResult]:
    """Run a named gate list in order. Every gate runs; none is skipped."""
    results: list[GateResult] = []
    for name in names:
        try:
            gate = GATES[name]
        except KeyError:
            raise GateError(f"unknown gate: {name!r}; known: {sorted(GATES)}") from None
        results.append(gate(contract, context))
    return results


def aggregate_result(results: Sequence[GateResult]) -> str:
    if any(result.result == "FAIL" for result in results):
        return "FAIL"
    if any(result.result == "INCONCLUSIVE" for result in results):
        return "INCONCLUSIVE"
    if results and all(result.result == "NOT_RUN" for result in results):
        return "NOT_RUN"
    return "PASS"


def gate_envelope(
    results: Sequence[GateResult],
    *,
    run_id: str,
    step_id: str,
    contract_ref: dict[str, Any],
    dry_run: bool,
    produced_at: str,
    candidate: dict[str, Any] | None = None,
    side_effects: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Fold gate results into one step envelope.

    Gate evidence enters the same record as model evidence, so a consumer
    reads a hash comparison and a reviewer's finding the same way.
    """
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        for item in result.evidence:
            if item.id in seen:
                continue
            seen.add(item.id)
            evidence.append(item.to_document())

    envelope: dict[str, Any] = {
        "schema_version": "workflows.envelope.v1",
        "envelope_id": f"{run_id}/{step_id}",
        "run_id": run_id,
        "step_id": step_id,
        "step_kind": "gate",
        "status": "COMPLETED",
        "terminal": True,
        "result": aggregate_result(results),
        "dry_run": dry_run,
        "produced_at": produced_at,
        "contract_ref": contract_ref,
        "ladder_level": 0,
        "evidence": evidence,
        "criterion_results": [
            {
                "criterion_id": result.gate_id,
                "result": result.result,
                "evidence_refs": [item.id for item in result.evidence],
                "negative_path_claim": False,
                "note": f"{result.reason_code}: {result.detail}" if result.detail else result.reason_code,
            }
            for result in results
        ],
        "findings": [finding for result in results for finding in result.findings],
        "non_claims": _envelope_non_claims(results),
        "side_effects": list(side_effects) or [{"kind": "none", "target": "none"}],
    }
    if candidate is not None:
        envelope["candidate"] = candidate
    return envelope


def _envelope_non_claims(results: Sequence[GateResult]) -> list[str]:
    non_claims = [
        "Deterministic checks only: no model judged this candidate, and a "
        "gate-clean candidate is not a reviewed candidate.",
    ]
    for result in results:
        for claim in result.non_claims:
            if claim not in non_claims:
                non_claims.append(claim)
    not_run = [result.gate_id for result in results if result.result == "NOT_RUN"]
    if not_run:
        non_claims.append("Gates that did not run: " + ", ".join(sorted(not_run)) + ".")
    return non_claims


def write_gate_results(
    results: Sequence[GateResult], run_directory: Any, *, attempt: int = 1
) -> list[str]:
    """Write one file per gate result into the run directory's gates/ folder."""
    written: list[str] = []
    for result in results:
        relative = f"gates/{result.gate_id}.{attempt}.json"
        run_directory.write_artifact(relative, result.to_document())
        written.append(relative)
    return written
