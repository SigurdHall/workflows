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


def materialize(corpus: Corpus, target: Path, *, task_ids: Sequence[str] | None = None) -> str:
    """Build the benchmark repository a run will see, and commit it.

    Only seed trees are copied. The manifest — the answer key — stays where
    it is, because a corpus a reviewer can read is a corpus that measures
    nothing.
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


@dataclass
class Score:
    planted: int = 0
    detected: int = 0
    unmatched_findings: int = 0
    by_class: dict[int, dict[str, Any]] = field(default_factory=dict)
    lens_yield: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_document(self) -> dict[str, Any]:
        return {
            "planted": self.planted,
            "detected": self.detected,
            "unmatched_findings": self.unmatched_findings,
            "by_class": [
                {
                    "defect_class": defect_class,
                    "class_name": entry["class_name"],
                    "planted": entry["planted"],
                    "detected": entry["detected"],
                }
                for defect_class, entry in sorted(self.by_class.items())
            ],
            "lens_yield": [
                {"lens_id": lens_id, "findings": entry["findings"], "matched": entry["matched"]}
                for lens_id, entry in sorted(self.lens_yield.items())
            ],
        }


def score(
    corpus: Corpus, findings_by_task: dict[str, Iterable[dict[str, Any]]]
) -> Score:
    """Reviewer recall per defect class, plus lens yield.

    A defect counts as detected when at least one finding points at it. A
    finding counts once per defect it matches; a finding that matches none is
    unmatched, which is not the same as wrong.
    """
    result = Score()
    for task in corpus.tasks:
        findings = list(findings_by_task.get(task["task_id"], []))
        matched_findings: set[int] = set()

        for defect in task["defects"]:
            result.planted += 1
            entry = result.by_class.setdefault(
                defect["defect_class"],
                {"class_name": defect["class_name"], "planted": 0, "detected": 0},
            )
            entry["planted"] += 1
            hits = [
                index for index, finding in enumerate(findings) if matches(finding, defect)
            ]
            if hits:
                result.detected += 1
                entry["detected"] += 1
                matched_findings.update(hits)

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


@dataclass(frozen=True)
class Cell:
    model: str
    effort: str
    worker_count: int

    @property
    def cell_id(self) -> str:
        return f"{self.model}-{self.effort}-w{self.worker_count}".replace("/", "-")


def load_matrix(path: Path) -> list[Cell]:
    document = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    cells = [
        Cell(
            model=str(entry["model"]),
            effort=str(entry["effort"]),
            worker_count=int(entry.get("worker_count", 1)),
        )
        for entry in document.get("cell", [])
    ]
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


def plan_for(corpus: Corpus, cell: Cell, base_commit: str, plan_dir: Path) -> Path:
    """Write the plan and contracts one matrix cell runs from.

    Generated into the work root rather than the corpus, because a corpus is
    an input and a run's inputs are not written back into it.
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
            "flow": "fanout" if cell.worker_count > 1 else "implement",
            "write_scope": list(contract.get("scope", {}).get("allowed_paths", [])),
            "review_lens_set": list(DEFAULT_REVIEW_LENSES),
        }
        if cell.worker_count > 1:
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
        "budgets": {"tokens": 20_000_000, "wall_clock_seconds": 86_400},
        "escalation": {
            "level_2_on_severity": "HIGH",
            "stop_on_severity": "CRITICAL",
            "max_repair_rounds": 0,
        },
    }
    path = plan_dir / "plan.json"
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return path


def run_matrix(
    corpus: Corpus,
    cells: Sequence[Cell],
    *,
    work_root: Path,
    dry_run: bool = True,
    registry: Any = None,
    runner_factory: Any = None,
) -> dict[str, Any]:
    """Run every cell against the corpus and score each one.

    The corpus repository is materialized once and every cell starts from the
    same frozen commit, because a matrix whose cells see different inputs
    measures the inputs.
    """
    from workflows import program as program_module
    from workflows.flows.base import Profile

    registry = registry or default_registry()
    started_at = utc_now()
    repo = work_root / "repo"
    base_commit = (
        gitcmd.head_commit(repo) if (repo / ".git").exists() else materialize(corpus, repo)
    )

    results: list[tuple[Cell, Score, dict[str, int], int]] = []
    for cell in cells:
        began = time.monotonic()
        plan_path = plan_for(corpus, cell, base_commit, work_root / "plans" / cell.cell_id)
        resolved = program_module.resolve(plan_path, registry=registry, worktree=repo)
        bindings = {
            role: (cell.model, cell.effort)
            for role in program_module.Profile().bindings
        }
        engine = program_module.Program(
            resolved,
            worktree=repo,
            runs_root=work_root / "runs",
            program_run_id=f"bench-{cell.cell_id}"[:80],
            dry_run=dry_run,
            registry=registry,
            runner_factory=runner_factory,
            max_parallel_workers=max(1, cell.worker_count),
            profile=Profile(bindings=bindings),
        )
        program_report = engine.execute()
        cell_score = score(corpus, findings_from_run(engine.run.root))
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
        score_document = cell["score"]
        planted, detected = score_document["planted"], score_document["detected"]
        rate = f"{detected}/{planted}" if planted else "0/0"
        tokens = cell["telemetry"]
        lines.append(
            f"  {cell['cell_id']:<28} recall {rate:<8} "
            f"tokens {tokens['new_input']}+{tokens['output']:<8} "
            f"{cell['duration_ms']} ms"
        )
        for entry in score_document["by_class"]:
            if entry["detected"] < entry["planted"]:
                lines.append(
                    f"      class {entry['defect_class']:>2} {entry['class_name']:<28} "
                    f"{entry['detected']}/{entry['planted']}"
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

    build_parser = sub.add_parser("build", help="materialize the corpus repository")
    build_parser.add_argument("corpus", type=Path)
    build_parser.add_argument("target", type=Path)

    run_parser = sub.add_parser("run", help="run the matrix and score every cell")
    run_parser.add_argument("corpus", type=Path)
    run_parser.add_argument("--matrix", type=Path, required=True)
    run_parser.add_argument("--work-root", type=Path, required=True)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            corpus = load_corpus(args.corpus)
            commit = materialize(corpus, args.target)
            print(f"{corpus.corpus_id}: {len(corpus.tasks)} task(s) at {commit}")
            return EXIT_OK

        if args.command == "run":
            corpus = load_corpus(args.corpus)
            document = run_matrix(
                corpus,
                load_matrix(args.matrix),
                work_root=args.work_root,
                dry_run=bool(args.dry_run),
            )
            path = args.work_root / "benchmark-report.json"
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(document, indent=2) if args.json else summarize(document))
            print(f"  report: {path}")
            return EXIT_OK

        corpus = load_corpus(args.corpus)
        started = utc_now()
        cell_score = score(corpus, findings_from_run(args.run_root))
        document = report(
            corpus,
            [(Cell("recorded", "recorded", 1), cell_score, {"new_input": 0, "cached_input": 0, "output": 0}, 0)],
            dry_run=False,
            started_at=started,
        )
        print(json.dumps(document, indent=2) if args.json else summarize(document))
        return EXIT_OK if cell_score.detected == cell_score.planted else EXIT_FAILED
    except (BenchmarkError, SchemaError, OSError, ValueError) as exc:
        print(f"cannot run the benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
