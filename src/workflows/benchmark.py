"""The `benchmark` flow: a matrix against a corpus with a hidden answer key.

    python -m workflows.benchmark score <corpus.json> <run-root>
    python -m workflows.benchmark run <corpus.json> --matrix models.toml --dry-run

This is the only flow that turns the repository's defaults into
measurements. Everything else here is asserted: three to five workers, a
level-2 threshold of HIGH, a lens set of ten. The benchmark is how those
stop being opinions.

Three rules the scorer takes literally:

* **Recall is reported per defect class.** One aggregate number hides
  exactly the classes that escape, which are the ones worth knowing about.
* **Unmatched findings are not called false positives.** A finding that
  matches no planted defect may be a real defect the corpus author did not
  plant. Calling it a false positive would train the system to reward
  reviewers that find only what is expected.
* **The answer key never enters the worktree.** Only a task's seed tree is
  materialized; a corpus whose key is readable measures nothing.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from workflows import gitcmd
from workflows.flows.base import FlowError
from workflows.runs import utc_now
from workflows.schema import SchemaError, default_registry
from workflows.semantics import check_document

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

MANIFEST_SCHEMA = "defect-manifest.schema.json"
REPORT_SCHEMA = "benchmark-report.schema.json"


class BenchmarkError(RuntimeError):
    """The corpus or the matrix cannot be used as written."""


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Corpus:
    manifest: dict[str, Any]
    root: Path

    @property
    def corpus_id(self) -> str:
        return self.manifest["corpus_id"]

    @property
    def tasks(self) -> list[dict[str, Any]]:
        return self.manifest["tasks"]

    def defects(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            (task["task_id"], defect)
            for task in self.tasks
            for defect in task["defects"]
        ]

    def subset(self, task_ids: Sequence[str]) -> Corpus:
        """The same corpus restricted to named tasks.

        A first live matrix should cost two tasks, not six, and trimming here
        rather than by editing a copy of the corpus keeps the answer key and
        the corpus id identical to the full run's — the scores stay
        comparable, and the report says which subset produced them.
        """
        wanted = list(dict.fromkeys(task_ids))
        known = {task["task_id"] for task in self.tasks}
        missing = [task_id for task_id in wanted if task_id not in known]
        if missing:
            raise BenchmarkError(
                f"corpus {self.corpus_id} has no task {', '.join(missing)}. "
                f"It has: {', '.join(sorted(known))}"
            )
        manifest = dict(self.manifest)
        manifest["tasks"] = [t for t in self.tasks if t["task_id"] in set(wanted)]
        return Corpus(manifest=manifest, root=self.root)


def load_corpus(path: Path, *, registry: Any = None) -> Corpus:
    registry = registry or default_registry()
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    errors = check_document(manifest, MANIFEST_SCHEMA, registry=registry)
    if errors:
        raise BenchmarkError(
            "the defect manifest does not validate:\n"
            + "\n".join(f"  {e}" for e in errors[:20])
        )
    root = path.parent
    seen: set[str] = set()
    for task in manifest["tasks"]:
        if task["task_id"] in seen:
            raise BenchmarkError(f"duplicate task id in corpus: {task['task_id']}")
        seen.add(task["task_id"])
        for relative in (task["contract_path"], task["seed_path"]):
            if not (root / relative).exists():
                raise BenchmarkError(
                    f"task {task['task_id']!r} refers to {relative!r}, which does "
                    "not exist in the corpus"
                )
        ids = [defect["defect_id"] for defect in task["defects"]]
        if len(set(ids)) != len(ids):
            raise BenchmarkError(f"duplicate defect id in task {task['task_id']!r}")
    return Corpus(manifest=manifest, root=root)


BUILD_ARTIFACT_IGNORES = (
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
)


def materialize(
    corpus: Corpus,
    target: Path,
    *,
    task_ids: Sequence[str] | None = None,
    clean: bool = False,
) -> str:
    """Build the benchmark repository a run will see, and commit it.

    Only seed trees are copied. The manifest — the answer key — stays where
    it is, because a corpus a reviewer can read is a corpus that measures
    nothing.

    The repository gets a `.gitignore` for build artifacts, because without
    one every gate downstream misreads the run. A worker that runs the
    project's own tests leaves `__pycache__` behind; those files are
    untracked additions inside the contract's protected paths, so `scope` and
    `protected_hash` fail work the worker never did — and worse,
    `candidate_changed` passes on them, so a worker that changed nothing
    clears the one gate that exists to catch exactly that.
    """
    target.mkdir(parents=True, exist_ok=True)
    if (target / ".git").exists():
        raise BenchmarkError(f"refusing to overwrite an existing repository at {target}")
    for task in corpus.tasks:
        if task_ids is not None and task["task_id"] not in task_ids:
            continue
        shutil.copytree(
            corpus.root / task["seed_path"],
            target / task["task_id"],
            dirs_exist_ok=True,
        )
        if clean:
            overlay = task.get("clean_path")
            if not overlay:
                raise BenchmarkError(
                    f"task {task['task_id']!r} declares no clean_path, so there is "
                    "no defect-free base for a review cell to diff against"
                )
            shutil.copytree(
                corpus.root / overlay, target / task["task_id"], dirs_exist_ok=True
            )
    (target / ".gitignore").write_text(
        "\n".join(BUILD_ARTIFACT_IGNORES) + "\n", encoding="utf-8"
    )
    gitcmd.run(target, "init", "--quiet")
    gitcmd.run(target, "config", "user.email", "benchmark.local")
    gitcmd.run(target, "config", "user.name", "benchmark")
    gitcmd.run(target, "config", "core.autocrlf", "false")
    gitcmd.run(target, "add", "-A")
    gitcmd.run(target, "commit", "--quiet", "-m", f"corpus {corpus.corpus_id}")
    return gitcmd.head_commit(target)


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def location_path(location: str | None) -> str:
    """The path part of a location, without a line number."""
    if not location:
        return ""
    text = str(location).replace("\\", "/").strip()
    for separator in (":", "::"):
        if separator in text:
            text = text.split(separator, 1)[0]
    return text.strip("/")


def matches(finding: dict[str, Any], defect: dict[str, Any]) -> bool:
    """Whether a finding is about the same place as a planted defect.

    Matching is by path, which over-credits a reviewer that flags the right
    file for the wrong reason. That is why per-class recall, not the
    aggregate, is the number worth reading — and why the report says so.
    """
    found = location_path(finding.get("location"))
    planted = location_path(defect.get("location"))
    if not found or not planted:
        return False
    return found == planted or found.endswith("/" + planted) or planted.endswith("/" + found)


PRESENT = "PRESENT"
ABSENT = "ABSENT"
INDETERMINATE = "INDETERMINATE"

PROBE_TIMEOUT_SECONDS = 60
_PROBE_VERDICTS = {"DEFECT_PRESENT": PRESENT, "DEFECT_ABSENT": ABSENT}

_COUNTERS = ("planted", "present", "removed", "indeterminate", "caught", "missed", "detected")


def run_probe(
    probe: Path, task_directory: Path, *, interpreter: str | None = None
) -> tuple[str, str]:
    """Ask a probe whether its defect is still in this candidate.

    The contract is deliberately narrow: print one of `DEFECT_PRESENT` or
    `DEFECT_ABSENT` and exit zero. A probe that crashes, times out, says
    nothing, or says both answers has not decided, and a benchmark that reads
    silence as either answer is worse than one that admits it does not know.

    Returns the verdict and a one-line reason, because an INDETERMINATE with
    no reason cannot be acted on.
    """
    import subprocess

    interpreter = interpreter or sys.executable
    if not probe.is_file():
        return INDETERMINATE, f"no probe at {probe}"
    try:
        completed = subprocess.run(
            [interpreter, str(probe), str(task_directory)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except OSError as exc:
        return INDETERMINATE, f"could not run the probe: {exc}"
    except subprocess.TimeoutExpired:
        return INDETERMINATE, f"the probe exceeded {PROBE_TIMEOUT_SECONDS}s"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        return INDETERMINATE, (
            f"the probe exited {completed.returncode}: {detail[-1] if detail else ''}"
        )
    spoken = [
        _PROBE_VERDICTS[line.strip()]
        for line in completed.stdout.splitlines()
        if line.strip() in _PROBE_VERDICTS
    ]
    if len(spoken) != 1:
        return INDETERMINATE, (
            "the probe printed no verdict"
            if not spoken
            else f"the probe printed {len(spoken)} verdicts"
        )
    return spoken[0], "the probe answered"


def presence_for_task(
    corpus: Corpus,
    task: dict[str, Any],
    candidate_root: Path,
    *,
    interpreter: str | None = None,
) -> dict[str, tuple[str, str]]:
    """Run every probe of one task against the candidate it produced.

    ``candidate_root`` is the repository root of the candidate — the task's own
    directory inside it is what a probe is handed, matching the layout
    :func:`materialize` builds.
    """
    results: dict[str, tuple[str, str]] = {}
    for defect in task["defects"]:
        relative = defect.get("probe_path")
        if not relative:
            results[defect["defect_id"]] = (
                INDETERMINATE,
                "the corpus declares no probe for this defect",
            )
            continue
        results[defect["defect_id"]] = run_probe(
            corpus.root / relative,
            candidate_root / task["task_id"],
            interpreter=interpreter,
        )
    return results


def presence_from_run(
    corpus: Corpus, run_root: Path, *, interpreter: str | None = None
) -> dict[str, dict[str, tuple[str, str]]]:
    """Probe every task's candidate under a program run directory.

    The candidate a cell produced is its task worktree. A task with no
    worktree — never started, or a run whose directory has been cleaned —
    settles as INDETERMINATE with the reason attached, because an unprobed
    candidate is not evidence that its defects survived.
    """
    results: dict[str, dict[str, tuple[str, str]]] = {}
    for task in corpus.tasks:
        candidate = run_root / "worktrees" / task["task_id"]
        if candidate.is_dir():
            results[task["task_id"]] = presence_for_task(
                corpus, task, candidate, interpreter=interpreter
            )
        else:
            results[task["task_id"]] = {
                defect["defect_id"]: (
                    INDETERMINATE,
                    f"no candidate worktree at {candidate}",
                )
                for defect in task["defects"]
            }
    return results


@dataclass
class Score:
    planted: int = 0
    present: int = 0
    removed: int = 0
    indeterminate: int = 0
    caught: int = 0
    missed: int = 0
    detected: int = 0
    unmatched_findings: int = 0
    by_class: dict[int, dict[str, Any]] = field(default_factory=dict)
    lens_yield: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def recall(self) -> float | None:
        """Caught over present. ``None`` when nothing was present to catch."""
        return self.caught / self.present if self.present else None

    def to_document(self) -> dict[str, Any]:
        return {
            "planted": self.planted,
            "present": self.present,
            "removed": self.removed,
            "indeterminate": self.indeterminate,
            "caught": self.caught,
            "missed": self.missed,
            "detected": self.detected,
            "unmatched_findings": self.unmatched_findings,
            "by_class": [
                {
                    "defect_class": defect_class,
                    "class_name": entry["class_name"],
                    **{name: entry[name] for name in _COUNTERS},
                }
                for defect_class, entry in sorted(self.by_class.items())
            ],
            "lens_yield": [
                {"lens_id": lens_id, "findings": entry["findings"], "matched": entry["matched"]}
                for lens_id, entry in sorted(self.lens_yield.items())
            ],
        }


def score(
    corpus: Corpus,
    findings_by_task: dict[str, Iterable[dict[str, Any]]],
    presence_by_task: dict[str, dict[str, tuple[str, str]]] | None = None,
) -> Score:
    """Reviewer recall per defect class, plus lens yield.

    A defect counts as detected when at least one finding points at it. A
    finding counts once per defect it matches; a finding that matches none is
    unmatched, which is not the same as wrong.

    ``presence_by_task`` is what separates a review failure from a review
    success. Without it every defect is INDETERMINATE and `present` is zero,
    so recall is undefined rather than misleadingly zero — which is the honest
    reading of a run whose candidate was never probed.
    """
    presence_by_task = presence_by_task or {}
    result = Score()
    for task in corpus.tasks:
        findings = list(findings_by_task.get(task["task_id"], []))
        presence = presence_by_task.get(task["task_id"], {})
        matched_findings: set[int] = set()

        for defect in task["defects"]:
            result.planted += 1
            entry = result.by_class.setdefault(
                defect["defect_class"],
                {"class_name": defect["class_name"], **{name: 0 for name in _COUNTERS}},
            )
            entry["planted"] += 1
            hits = [
                index for index, finding in enumerate(findings) if matches(finding, defect)
            ]
            if hits:
                result.detected += 1
                entry["detected"] += 1
                matched_findings.update(hits)

            state = presence.get(defect["defect_id"], (INDETERMINATE, ""))[0]
            if state == ABSENT:
                result.removed += 1
                entry["removed"] += 1
            elif state == PRESENT:
                result.present += 1
                entry["present"] += 1
                if hits:
                    result.caught += 1
                    entry["caught"] += 1
                else:
                    result.missed += 1
                    entry["missed"] += 1
            else:
                result.indeterminate += 1
                entry["indeterminate"] += 1

        for index, finding in enumerate(findings):
            lens_id = finding.get("lens_id") or "unattributed"
            counts = result.lens_yield.setdefault(lens_id, {"findings": 0, "matched": 0})
            counts["findings"] += 1
            if index in matched_findings:
                counts["matched"] += 1
            else:
                result.unmatched_findings += 1
    return result


def findings_from_run(run_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Collect open findings per task from a program run directory."""
    findings: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for verdict_path in sorted(run_root.glob("tasks/*/verdict.json")):
        task_id = verdict_path.parent.name
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        findings[task_id].extend(
            finding
            for finding in verdict.get("findings", [])
            if finding.get("status") == "OPEN"
        )
    return dict(findings)


# --------------------------------------------------------------------------
# The matrix
# --------------------------------------------------------------------------


CELL_FLOWS = ("implement", "fanout", "assure")


def seed_candidate(corpus: Corpus, task: dict[str, Any], worktree: Path) -> None:
    """Put the defective source into a worktree cut from the clean base.

    An `assure` cell reviews a candidate it did not produce, so something has
    to place one. Here it is the seed: the diff a reviewer sees is the one
    that *introduces* the planted defects, which is what makes recall over an
    assure cell mean reviewer recall and nothing else.
    """
    shutil.copytree(
        corpus.root / task["seed_path"] / "src",
        worktree / task["task_id"] / "src",
        dirs_exist_ok=True,
    )


@dataclass(frozen=True)
class Cell:
    model: str
    effort: str
    worker_count: int
    flow: str = ""

    @property
    def resolved_flow(self) -> str:
        """What this cell runs. Width picks it when the cell does not say."""
        return self.flow or ("fanout" if self.worker_count > 1 else "implement")

    @property
    def reviews_only(self) -> bool:
        return self.resolved_flow == "assure"

    @property
    def cell_id(self) -> str:
        return (
            f"{self.resolved_flow}-{self.model}-{self.effort}-w{self.worker_count}"
        ).replace("/", "-")


def load_matrix(path: Path) -> list[Cell]:
    document = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    cells = []
    for entry in document.get("cell", []):
        flow = str(entry.get("flow", "") or "")
        if flow and flow not in CELL_FLOWS:
            raise BenchmarkError(
                f"{path}: a cell cannot run {flow!r}. A matrix schedules "
                f"{', '.join(CELL_FLOWS)}; adjudicate is reached from a "
                "conflict inside a flow, not planned"
            )
        cell = Cell(
            model=str(entry["model"]),
            effort=str(entry["effort"]),
            worker_count=int(entry.get("worker_count", 1)),
            flow=flow,
        )
        if cell.resolved_flow == "fanout" and cell.worker_count < 2:
            raise BenchmarkError(f"{path}: a fanout cell needs worker_count above 1")
        if cell.reviews_only and cell.worker_count != 1:
            raise BenchmarkError(
                f"{path}: an assure cell produces nothing, so worker_count "
                "means nothing to it; leave it at 1"
            )
        cells.append(cell)
    if not cells:
        raise BenchmarkError(f"{path} declares no [[cell]] entries")
    return cells


DEFAULT_WORK_LENSES = (
    "work/spec-fidelity",
    "work/defensive-input",
    "work/minimal-change",
    "work/api-design",
)
DEFAULT_REVIEW_LENSES = ("review/scope-integrity", "review/closed-contract")


DEFAULT_CELL_TOKEN_BUDGET = 20_000_000
DEFAULT_CELL_SECONDS_BUDGET = 86_400


def plan_for(
    corpus: Corpus,
    cell: Cell,
    base_commit: str,
    plan_dir: Path,
    *,
    budget_tokens: int = DEFAULT_CELL_TOKEN_BUDGET,
    budget_seconds: int = DEFAULT_CELL_SECONDS_BUDGET,
) -> Path:
    """Write the plan and contracts one matrix cell runs from.

    Generated into the work root rather than the corpus, because a corpus is
    an input and a run's inputs are not written back into it.

    The budgets are per cell, not per matrix. A matrix of four cells can cost
    four times what one cell's budget allows, which is why the caller sets
    them deliberately for a live run instead of taking the defaults.
    """
    contracts = plan_dir / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    tasks = []
    for task in corpus.tasks:
        contract = json.loads(
            (corpus.root / task["contract_path"]).read_text(encoding="utf-8-sig")
        )
        (contracts / f"{task['task_id']}.json").write_text(
            json.dumps(contract, indent=2), encoding="utf-8"
        )
        entry: dict[str, Any] = {
            "task_id": task["task_id"],
            "repo_id": "corpus",
            "contract_path": f"contracts/{task['task_id']}.json",
            "flow": cell.resolved_flow,
            "write_scope": list(contract.get("scope", {}).get("allowed_paths", [])),
            "review_lens_set": list(DEFAULT_REVIEW_LENSES),
        }
        if cell.resolved_flow == "fanout":
            entry["lens_set"] = list(DEFAULT_WORK_LENSES[: cell.worker_count])
        tasks.append(entry)

    plan = {
        "schema_version": "workflows.plan.v1",
        "plan_id": f"bench-{cell.cell_id}"[:60],
        "plan_revision": 1,
        "description": f"Benchmark cell {cell.cell_id} over corpus {corpus.corpus_id}.",
        "base": [{"repo_id": "corpus", "commit": base_commit}],
        "tasks": tasks,
        "concurrency": {"max_parallel_tasks": 1},
        "budgets": {
            "tokens": int(budget_tokens),
            "wall_clock_seconds": int(budget_seconds),
        },
        "escalation": {
            "level_2_on_severity": "HIGH",
            "stop_on_severity": "CRITICAL",
            "max_repair_rounds": 0,
        },
    }
    path = plan_dir / "plan.json"
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return path


def unresolved_models(cells: Sequence[Cell]) -> list[str]:
    """Cell models that are role names rather than models a provider serves.

    The example matrix ships with `worker-class` in it deliberately: a matrix
    is provider-unresolved like everything else here. Sending that to a
    provider fails at the first call, so a live matrix says so first.
    """
    from workflows.flows.base import DEFAULT_BINDINGS

    placeholders = {model for model, _ in DEFAULT_BINDINGS.values()}
    return sorted({cell.model for cell in cells if cell.model in placeholders})


def run_matrix(
    corpus: Corpus,
    cells: Sequence[Cell],
    *,
    work_root: Path,
    dry_run: bool = True,
    registry: Any = None,
    runner_factory: Any = None,
    profile: Any = None,
    budget_tokens: int = DEFAULT_CELL_TOKEN_BUDGET,
    budget_seconds: int = DEFAULT_CELL_SECONDS_BUDGET,
) -> dict[str, Any]:
    """Run every cell against the corpus and score each one.

    The corpus repository is materialized once and every cell starts from the
    same frozen commit, because a matrix whose cells see different inputs
    measures the inputs.

    A cell binds *every* role to its model and effort, so a cell measures a
    configuration and not a reviewer in isolation. An optional profile
    supplies what a cell does not name — per-role sandboxes above all, since
    a worker denied writes produces an empty candidate.
    """
    from workflows import program as program_module
    from workflows.flows.base import Profile

    if not dry_run:
        placeholders = unresolved_models(cells)
        if placeholders:
            raise BenchmarkError(
                "this matrix names role placeholders, not models: "
                + ", ".join(placeholders)
                + ". A provider would reject them at the first call. Replace "
                "them with the model ids your runner serves, or add --dry-run."
            )
    registry = registry or default_registry()
    started_at = utc_now()

    def repository(clean: bool) -> tuple[Path, str]:
        """The repository a cell starts from, built once and reused.

        Producing cells start from the defective seed and are measured on what
        they leave behind. A review cell starts from a defect-free base with
        the seed as its candidate, so the diff it judges is the one that
        introduces the defects. Two bases, deliberately: cells of one kind
        still share theirs, which is what keeps them comparable.
        """
        path = work_root / ("repo-clean" if clean else "repo")
        if (path / ".git").exists():
            return path, gitcmd.head_commit(path)
        return path, materialize(corpus, path, clean=clean)

    by_id = {task["task_id"]: task for task in corpus.tasks}
    results: list[tuple[Cell, Score, dict[str, int], int]] = []
    for cell in cells:
        began = time.monotonic()
        repo, base_commit = repository(cell.reviews_only)
        plan_path = plan_for(
            corpus,
            cell,
            base_commit,
            work_root / "plans" / cell.cell_id,
            budget_tokens=budget_tokens,
            budget_seconds=budget_seconds,
        )
        resolved = program_module.resolve(plan_path, registry=registry, worktree=repo)
        base = profile or Profile()
        bindings = {role: (cell.model, cell.effort) for role in base.bindings}
        engine = program_module.Program(
            resolved,
            worktree=repo,
            runs_root=work_root / "runs",
            program_run_id=f"bench-{cell.cell_id}"[:80],
            dry_run=dry_run,
            registry=registry,
            runner_factory=runner_factory,
            max_parallel_workers=max(1, cell.worker_count),
            profile=Profile(
                bindings=bindings,
                sandbox_for_role=dict(base.sandbox_for_role),
                resolved=True,
            ),
        )
        if cell.reviews_only:
            # The worktrees are cut from the clean base, so the candidate has
            # to be placed in them before the flow looks. prepare() is
            # idempotent and execute() reuses a worktree that already exists.
            engine.prepare()
            for resolved_task in resolved.tasks:
                worktree = engine.task_worktree(resolved_task)
                seed_candidate(corpus, by_id[resolved_task.task_id], worktree)

        program_report = engine.execute()
        # A dry run judged nothing, so probing its untouched worktrees would
        # report every defect present and every one missed. Leaving them
        # INDETERMINATE is the honest reading of a run with no reviewer in it.
        presence = (
            {} if dry_run else presence_from_run(corpus, engine.run.root)
        )
        cell_score = score(corpus, findings_from_run(engine.run.root), presence)
        results.append(
            (
                cell,
                cell_score,
                program_report["telemetry_totals"],
                int((time.monotonic() - began) * 1000),
            )
        )
    return report(
        corpus, results, dry_run=dry_run, started_at=started_at, registry=registry
    )


def report(
    corpus: Corpus,
    results: Sequence[tuple[Cell, Score, dict[str, int], int]],
    *,
    dry_run: bool,
    started_at: str,
    registry: Any = None,
) -> dict[str, Any]:
    registry = registry or default_registry()
    non_claims = [
        "Detection is matched by location, so a finding that names the right "
        "file for the wrong reason counts as a hit. Read recall per class, "
        "not the aggregate.",
        "Unmatched findings are not false positives: the corpus plants a "
        "known set of defects, not every defect in the fixture.",
        "A corpus measures the classes it plants. A class absent from the "
        "corpus is unmeasured, not absent from the system.",
        "Scored over "
        + ", ".join(task["task_id"] for task in corpus.tasks)
        + ". Tasks of this corpus not listed here did not run and are "
        "unmeasured by this report.",
        "A cell binds every role to one model and effort, so a cell scores a "
        "whole configuration. It does not separate which model produced the "
        "candidate from which model reviewed it.",
        "Recall is caught over present, not caught over planted. A defect the "
        "producing step removed was never offered to a reviewer; an "
        "INDETERMINATE one was never settled either way. Neither belongs in a "
        "recall figure, and both are reported separately rather than folded "
        "into one.",
        "A presence probe decides whether the defect is there, not whether "
        "the candidate is good. A candidate that removed a planted defect and "
        "introduced a worse one probes ABSENT.",
    ]
    if dry_run:
        non_claims.insert(
            0,
            "Dry run: no model was called, so every cell scored zero by "
            "construction. This exercises the matrix, not the reviewers.",
        )
    document = {
        "schema_version": "workflows.benchmark-report.v1",
        "corpus_id": corpus.corpus_id,
        "dry_run": dry_run,
        "started_at": started_at,
        "finished_at": utc_now(),
        "cells": [
            {
                "cell_id": cell.cell_id,
                "model": cell.model,
                "effort": cell.effort,
                "worker_count": cell.worker_count,
                "score": cell_score.to_document(),
                "telemetry": tokens,
                "duration_ms": duration,
            }
            for cell, cell_score, tokens, duration in results
        ],
        "non_claims": non_claims,
    }
    errors = check_document(document, REPORT_SCHEMA, registry=registry)
    if errors:
        raise BenchmarkError(
            "the benchmark report does not validate:\n"
            + "\n".join(f"  {e}" for e in errors[:20])
        )
    return document


def summarize(document: dict[str, Any]) -> str:
    lines = [f"benchmark {document['corpus_id']}"]
    for cell in document["cells"]:
        s = cell["score"]
        rate = f"{s['caught']}/{s['present']}" if s["present"] else "n/a"
        tokens = cell["telemetry"]
        lines.append(
            f"  {cell['cell_id']:<28} recall {rate:<8} "
            f"(present {s['present']}, removed {s['removed']}, "
            f"indeterminate {s['indeterminate']} of {s['planted']} planted)  "
            f"tokens {tokens['new_input']}+{tokens['output']} "
            f"{cell['duration_ms']} ms"
        )
        for entry in s["by_class"]:
            if entry["missed"]:
                lines.append(
                    f"      MISSED  class {entry['defect_class']:>2} "
                    f"{entry['class_name']:<28} {entry['missed']}/{entry['present']}"
                )
        for entry in s["by_class"]:
            if entry["indeterminate"]:
                lines.append(
                    f"      unsettled class {entry['defect_class']:>2} "
                    f"{entry['class_name']:<24} {entry['indeterminate']}/{entry['planted']}"
                )
    for claim in document["non_claims"]:
        lines.append(f"  not claimed: {claim}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.benchmark", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    score_parser = sub.add_parser("score", help="score an existing program run")
    score_parser.add_argument("corpus", type=Path)
    score_parser.add_argument("run_root", type=Path)
    score_parser.add_argument("--json", action="store_true")
    score_parser.add_argument(
        "--candidate-root",
        type=Path,
        default=None,
        help=(
            "where the scored candidates live, if not the run root. Probes "
            "look for <root>/worktrees/<task_id>"
        ),
    )
    score_parser.add_argument(
        "--task",
        action="append",
        default=[],
        metavar="TASK_ID",
        help="score only this task; repeatable. Tasks that never ran are noise",
    )
    score_parser.add_argument(
        "--no-probes",
        action="store_true",
        help=(
            "skip presence probes. Every defect then settles INDETERMINATE "
            "and recall is undefined rather than misleadingly zero"
        ),
    )

    build_parser = sub.add_parser("build", help="materialize the corpus repository")
    build_parser.add_argument("corpus", type=Path)
    build_parser.add_argument("target", type=Path)

    run_parser = sub.add_parser("run", help="run the matrix and score every cell")
    run_parser.add_argument("corpus", type=Path)
    run_parser.add_argument("--matrix", type=Path, required=True)
    run_parser.add_argument("--work-root", type=Path, required=True)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--json", action="store_true")
    run_parser.add_argument(
        "--task",
        action="append",
        default=[],
        metavar="TASK_ID",
        help=(
            "run only this task; repeatable. Start a live matrix with two, "
            "not the whole corpus"
        ),
    )
    run_parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help=(
            "deployment profile supplying what a cell does not name, "
            "per-role sandboxes above all. Cells bind the models"
        ),
    )
    run_parser.add_argument(
        "--dangerously-bypass-sandbox",
        action="store_true",
        help=(
            "run producing roles without the provider's sandbox. Only where "
            "the sandbox refuses writes a worker legitimately needs; the "
            "scope and protected-hash gates remain the actual check"
        ),
    )
    run_parser.add_argument(
        "--budget-tokens",
        type=int,
        default=DEFAULT_CELL_TOKEN_BUDGET,
        help="token budget per cell, not per matrix (default: %(default)s)",
    )
    run_parser.add_argument(
        "--budget-seconds",
        type=int,
        default=DEFAULT_CELL_SECONDS_BUDGET,
        help="wall-clock budget per cell, not per matrix (default: %(default)s)",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            corpus = load_corpus(args.corpus)
            commit = materialize(corpus, args.target)
            print(f"{corpus.corpus_id}: {len(corpus.tasks)} task(s) at {commit}")
            return EXIT_OK

        if args.command == "run":
            from workflows.flows.base import Profile
            from workflows.runners.codex import CodexRunner

            corpus = load_corpus(args.corpus)
            if args.task:
                corpus = corpus.subset(args.task)
            bypass = bool(args.dangerously_bypass_sandbox)
            document = run_matrix(
                corpus,
                load_matrix(args.matrix),
                work_root=args.work_root,
                dry_run=bool(args.dry_run),
                profile=Profile.from_toml(args.profile) if args.profile else None,
                runner_factory=(
                    None
                    if args.dry_run
                    else (lambda: CodexRunner(bypass_sandbox=bypass))
                ),
                budget_tokens=args.budget_tokens,
                budget_seconds=args.budget_seconds,
            )
            path = args.work_root / "benchmark-report.json"
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(document, indent=2) if args.json else summarize(document))
            print(f"  report: {path}")
            return EXIT_OK

        corpus = load_corpus(args.corpus)
        if args.task:
            corpus = corpus.subset(args.task)
        started = utc_now()
        candidates = args.candidate_root or args.run_root
        cell_score = score(
            corpus,
            findings_from_run(args.run_root),
            {} if args.no_probes else presence_from_run(corpus, candidates),
        )
        document = report(
            corpus,
            [(Cell("recorded", "recorded", 1), cell_score, {"new_input": 0, "cached_input": 0, "output": 0}, 0)],
            dry_run=False,
            started_at=started,
        )
        print(json.dumps(document, indent=2) if args.json else summarize(document))
        # A miss is a reviewer failure. An unsettled defect is not a pass.
        return EXIT_OK if not (cell_score.missed or cell_score.indeterminate) else EXIT_FAILED
    except (BenchmarkError, FlowError, SchemaError, OSError, ValueError) as exc:
        print(f"cannot run the benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
