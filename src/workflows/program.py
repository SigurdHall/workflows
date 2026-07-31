"""One plan, many contracts, one human checkpoint.

    python -m workflows.program run plan.toml            # resolve and print
    python -m workflows.program run plan.toml --approve  # execute
    python -m workflows.program resume <run-id>

The program level exists so a human administers *one* thing: one plan file
in, one decision, one consolidated report out. Everything after approval is
signal-driven — the program stops only on an escalation above threshold or a
budget breach, and it says which in the report.

Per-task approval would defeat the level: the human becomes the bottleneck N
times per batch. So the checkpoint is the resolve step, it prints scopes,
flows and budgets, and it happens exactly once.

Exit codes: 0 every task passed (or the plan resolved and awaits approval),
1 the program finished with a failure or a stop, 2 usage or configuration
error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from workflows import gitcmd
from workflows.flows import assure, base, fanout, implement, ladder
from workflows.flows.base import FlowContext, FlowError, Profile
from workflows.flows.ladder import Escalation
from workflows.runners.codex import CodexRunner, DryRunner
from workflows.runs import RunDirectory, utc_now
from workflows.schema import SchemaError, default_registry
from workflows.semantics import check_document

EXIT_OK = 0
EXIT_STOPPED = 1
EXIT_USAGE = 2

PLAN_SCHEMA = "plan.schema.json"
REPORT_SCHEMA = "program-report.schema.json"

FLOW_RUNNERS = {
    "implement": implement.run,
    "fanout": fanout.run,
    "assure": assure.run,
}

CONTRACT_SCHEMAS = {"task": "task-contract.schema.json", "goal": "goal-contract.schema.json"}


class ProgramError(RuntimeError):
    """The plan cannot be executed as written."""


# --------------------------------------------------------------------------
# Resolve — everything that must be true before a human is asked anything
# --------------------------------------------------------------------------


@dataclass
class ResolvedTask:
    task_id: str
    flow: str
    repo_id: str
    contract_path: Path
    contract: dict[str, Any]
    contract_ref: dict[str, Any]
    write_scope: list[str]
    lens_set: tuple[str, ...]
    review_lens_set: tuple[str, ...]
    focus_hint: str | None


@dataclass
class ResolvedPlan:
    plan: dict[str, Any]
    plan_path: Path
    digest: str
    tasks: list[ResolvedTask]
    escalation: Escalation

    @property
    def plan_ref(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan["plan_id"],
            "plan_revision": self.plan["plan_revision"],
            "digest": self.digest,
        }

    @property
    def budgets(self) -> dict[str, int]:
        return self.plan["budgets"]

    def base_for(self, repo_id: str) -> str:
        for entry in self.plan["base"]:
            if entry["repo_id"] == repo_id:
                return entry["commit"]
        raise ProgramError(f"no frozen base for repository {repo_id!r}")


def load(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".toml":
        return tomllib.loads(text)
    return json.loads(text)


def digest_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(plan_path: Path, *, registry: Any = None) -> ResolvedPlan:
    """Validate everything that can be validated before anyone approves.

    Scope overlap, a missing contract, a contract that does not validate, a
    flow that needs lenses it was not given: all of it is settled here, so
    the human sees a plan that could actually run.
    """
    registry = registry or default_registry()
    plan = load(plan_path)
    errors = check_document(plan, PLAN_SCHEMA, registry=registry)
    if errors:
        raise ProgramError(
            "the plan does not validate:\n" + "\n".join(f"  {e}" for e in errors[:20])
        )

    root = plan_path.parent
    default_repo = plan["base"][0]["repo_id"] if len(plan["base"]) == 1 else None
    tasks: list[ResolvedTask] = []
    for entry in plan["tasks"]:
        contract_path = (root / entry["contract_path"]).resolve()
        if not contract_path.is_file():
            raise ProgramError(
                f"task {entry['task_id']!r} names a contract that does not "
                f"exist: {entry['contract_path']}"
            )
        contract = load(contract_path)
        schema_ref = CONTRACT_SCHEMAS.get(contract.get("contract_type", "task"))
        if schema_ref is None:
            raise ProgramError(
                f"task {entry['task_id']!r}: unknown contract_type "
                f"{contract.get('contract_type')!r}"
            )
        contract_errors = check_document(contract, schema_ref, registry=registry)
        if contract_errors:
            raise ProgramError(
                f"the contract for task {entry['task_id']!r} does not validate:\n"
                + "\n".join(f"  {e}" for e in contract_errors[:20])
            )
        tasks.append(
            ResolvedTask(
                task_id=entry["task_id"],
                flow=entry["flow"],
                repo_id=entry.get("repo_id") or default_repo or "",
                contract_path=contract_path,
                contract=contract,
                contract_ref={
                    "contract_id": contract["contract_id"],
                    "contract_revision": contract["contract_revision"],
                    "digest": digest_of(contract_path),
                },
                write_scope=list(entry["write_scope"]),
                lens_set=tuple(entry.get("lens_set", ())),
                review_lens_set=tuple(entry.get("review_lens_set", ())),
                focus_hint=entry.get("focus_hint"),
            )
        )

    unsupported = [task.task_id for task in tasks if task.flow not in FLOW_RUNNERS]
    if unsupported:
        raise ProgramError(
            "these tasks name a flow this version cannot run: "
            + ", ".join(unsupported)
            + f" (available: {', '.join(sorted(FLOW_RUNNERS))})"
        )
    return ResolvedPlan(
        plan=plan,
        plan_path=plan_path,
        digest=digest_of(plan_path),
        tasks=tasks,
        escalation=Escalation.from_plan(plan.get("escalation")),
    )


def describe(resolved: ResolvedPlan) -> str:
    """The resolved plan, as the human sees it at the single checkpoint."""
    plan = resolved.plan
    lines = [
        f"plan {plan['plan_id']} revision {plan['plan_revision']}",
        f"  digest      {resolved.digest}",
    ]
    if plan.get("description"):
        lines.append(f"  description {plan['description']}")
    lines.append("  frozen base:")
    for entry in plan["base"]:
        lines.append(f"    {entry['repo_id']:<16} {entry['commit']}")
    lines.append(f"  tasks ({len(resolved.tasks)}):")
    for task in resolved.tasks:
        lines.append(f"    {task.task_id}  [{task.flow}]  repo={task.repo_id}")
        lines.append(f"      contract    {task.contract_path.name} ({task.contract_ref['digest'][:19]}...)")
        lines.append(f"      write scope {', '.join(task.write_scope)}")
        if task.lens_set:
            lines.append(f"      work lenses {', '.join(task.lens_set)}")
        if task.review_lens_set:
            lines.append(f"      review      {', '.join(task.review_lens_set)}")
        if task.focus_hint:
            lines.append(f"      focus       {task.focus_hint}")
    budgets = resolved.budgets
    lines.append(
        f"  budgets     {budgets['tokens']} tokens, "
        f"{budgets['wall_clock_seconds']} s wall clock"
    )
    escalation = resolved.escalation
    lines.append(
        f"  escalation  level 2 at {escalation.level_2_on_severity}, "
        f"stop at {escalation.stop_on_severity}, "
        f"{escalation.max_repair_rounds} repair round(s)"
    )
    concurrency = resolved.plan["concurrency"]
    lines.append(f"  concurrency {concurrency['max_parallel_tasks']} task(s) at a time")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Execute
# --------------------------------------------------------------------------


@dataclass
class TaskOutcome:
    task: ResolvedTask
    run_id: str
    state: str
    result: str
    verdict: dict[str, Any] | None = None
    tokens: dict[str, int] = field(default_factory=lambda: {"new_input": 0, "cached_input": 0, "output": 0})
    duration_ms: int = 0
    note: str | None = None


def _token_totals(records: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"new_input": 0, "cached_input": 0, "output": 0}
    for record in records:
        tokens = record.get("tokens", {})
        for key in totals:
            totals[key] += int(tokens.get(key, 0) or 0)
    return totals


def budget_spend(totals: dict[str, int]) -> int:
    """What a token budget counts.

    New input plus output. Cached input is recorded and reported, never
    folded in: an aggregate that mixes cached and new input overstates cost
    several-fold, and a budget built on it would stop runs that cost little.
    """
    return totals["new_input"] + totals["output"]


class Program:
    def __init__(
        self,
        resolved: ResolvedPlan,
        *,
        worktree: Path,
        runs_root: Path,
        program_run_id: str,
        dry_run: bool,
        registry: Any = None,
        runner_factory: Any = None,
        max_parallel_workers: int = 1,
    ) -> None:
        self.resolved = resolved
        self.worktree = worktree
        self.runs_root = runs_root
        self.program_run_id = program_run_id
        self.dry_run = dry_run
        self.registry = registry or default_registry()
        self.runner_factory = runner_factory or (
            (lambda: DryRunner(registry=self.registry)) if dry_run else (lambda: CodexRunner())
        )
        self.max_parallel_workers = max_parallel_workers
        self.run = RunDirectory(runs_root / program_run_id)
        self.stops: list[dict[str, Any]] = []
        self.started = time.monotonic()
        self.report_path = "reports/1.json"

    # -- setup ------------------------------------------------------------

    def prepare(self) -> None:
        if not self.run.exists:
            self.run.create(
                {
                    "schema_version": "workflows.run-manifest.v1",
                    "run_id": self.program_run_id,
                    "kind": "program",
                    "dry_run": self.dry_run,
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                    "plan_ref": self.resolved.plan_ref,
                    "base": [
                        {"repo_id": entry["repo_id"], "commit": entry["commit"]}
                        for entry in self.resolved.plan["base"]
                    ],
                    "steps": [],
                    "budgets": self.resolved.budgets,
                }
            )
            self.run.write_artifact("plan.json", self.resolved.plan)
            # Where the plan came from, so a resume reads the original file
            # rather than this copy — contract paths are relative to it.
            self.run.write_artifact(
                "plan-source.json",
                {
                    "plan_path": str(self.resolved.plan_path.resolve()),
                    "digest": self.resolved.digest,
                },
            )
        else:
            recorded = self.run.read_manifest().get("plan_ref", {}).get("digest")
            if recorded and recorded != self.resolved.digest:
                raise ProgramError(
                    "this program run was created against a different plan. A "
                    "plan is frozen at run start: resume with the original, or "
                    "start a new run id."
                )

    def task_worktree(self, task: ResolvedTask) -> Path:
        path = self.run.root / "worktrees" / task.task_id
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        gitcmd.add_worktree(self.worktree, path, self.resolved.base_for(task.repo_id))
        return path

    # -- one task ---------------------------------------------------------

    def run_task(self, task: ResolvedTask) -> TaskOutcome:
        run_id = f"{self.program_run_id}--{task.task_id}"
        directory = RunDirectory(self.run.root / "tasks" / task.task_id)
        started = time.monotonic()

        if directory.exists and (directory.root / "verdict.json").is_file():
            verdict = directory.read_artifact("verdict.json")
            return TaskOutcome(
                task=task,
                run_id=run_id,
                state="COMPLETED",
                result=verdict["result"],
                verdict=verdict,
                tokens=_token_totals(directory.telemetry()),
                note="already completed; not re-run",
            )

        worktree = self.task_worktree(task)
        frozen = self.resolved.base_for(task.repo_id)
        if not directory.exists:
            directory.create(
                {
                    "schema_version": "workflows.run-manifest.v1",
                    "run_id": run_id,
                    "kind": "flow",
                    "flow": task.flow,
                    "dry_run": self.dry_run,
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                    "plan_ref": self.resolved.plan_ref,
                    "contract_ref": task.contract_ref,
                    "base": [{"repo_id": task.repo_id, "commit": frozen}],
                    "steps": [],
                    "budgets": self.resolved.budgets,
                }
            )

        context = FlowContext(
            contract=task.contract,
            contract_ref=task.contract_ref,
            worktree=worktree,
            base=frozen,
            run=directory,
            run_id=run_id,
            runner=self.runner_factory(),
            profile=Profile(),
            escalation=self.resolved.escalation,
            registry=self.registry,
            dry_run=self.dry_run,
            work_lenses=task.lens_set,
            review_lenses=task.review_lens_set,
            focus_hint=task.focus_hint,
            max_parallel_workers=self.max_parallel_workers,
            worker_worktrees=directory.root / "worktrees",
        )
        try:
            verdict = FLOW_RUNNERS[task.flow](context)
        except FlowError as exc:
            return TaskOutcome(
                task=task,
                run_id=run_id,
                state="FAILED",
                result="BLOCKED",
                tokens=_token_totals(directory.telemetry()),
                duration_ms=int((time.monotonic() - started) * 1000),
                note=f"the flow could not run: {exc}",
            )
        return TaskOutcome(
            task=task,
            run_id=run_id,
            state="COMPLETED",
            result=verdict["result"],
            verdict=verdict,
            tokens=_token_totals(directory.telemetry()),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # -- the batch --------------------------------------------------------

    def execute(self) -> dict[str, Any]:
        self.prepare()
        started_at = utc_now()
        outcomes: list[TaskOutcome] = []
        totals = {"new_input": 0, "cached_input": 0, "output": 0}
        budgets = self.resolved.budgets
        width = max(1, int(self.resolved.plan["concurrency"]["max_parallel_tasks"]))
        pending = list(self.resolved.tasks)

        while pending:
            if self.stops:
                break
            batch, pending = pending[:width], pending[width:]
            if width == 1 or len(batch) == 1:
                results = [self.run_task(task) for task in batch]
            else:
                with ThreadPoolExecutor(max_workers=width) as pool:
                    results = list(pool.map(self.run_task, batch))
            for outcome in results:
                outcomes.append(outcome)
                for key in totals:
                    totals[key] += outcome.tokens.get(key, 0)
                self.run.record_step(
                    {
                        "step_id": outcome.task.task_id,
                        "kind": "flow",
                        "state": outcome.state,
                        "attempt": 1,
                        "task_id": outcome.task.task_id,
                        "finished_at": utc_now(),
                        "note": outcome.note or outcome.result,
                    }
                )
                self._check_signals(outcome, totals, budgets)

        for task in pending:
            outcomes.append(
                TaskOutcome(
                    task=task,
                    run_id=f"{self.program_run_id}--{task.task_id}",
                    state="BLOCKED",
                    result="BLOCKED",
                    note="the program stopped before this task started",
                )
            )
        return self._report(started_at, outcomes, totals, budgets)

    def _check_signals(
        self, outcome: TaskOutcome, totals: dict[str, int], budgets: dict[str, int]
    ) -> None:
        spend = budget_spend(totals)
        if spend >= budgets["tokens"]:
            self.stops.append(
                {
                    "kind": "token_budget",
                    "detail": (
                        f"{spend} tokens spent (new input plus output) against a "
                        f"budget of {budgets['tokens']}"
                    ),
                }
            )
        elapsed = time.monotonic() - self.started
        if elapsed >= budgets["wall_clock_seconds"]:
            self.stops.append(
                {
                    "kind": "wall_clock_budget",
                    "detail": f"{int(elapsed)}s elapsed against a budget of "
                    f"{budgets['wall_clock_seconds']}s",
                }
            )
        if outcome.verdict is not None and ladder.must_stop(
            [outcome.verdict], self.resolved.escalation
        ):
            self.stops.append(
                {
                    "kind": "escalation",
                    "task_id": outcome.task.task_id,
                    "detail": (
                        f"task {outcome.task.task_id} left a finding at or above "
                        f"{self.resolved.escalation.stop_on_severity} open"
                    ),
                }
            )

    def _report(
        self,
        started_at: str,
        outcomes: list[TaskOutcome],
        totals: dict[str, int],
        budgets: dict[str, int],
    ) -> dict[str, Any]:
        tasks = []
        for outcome in outcomes:
            entry: dict[str, Any] = {
                "task_id": outcome.task.task_id,
                "flow": outcome.task.flow,
                "run_id": outcome.run_id,
                "state": outcome.state,
                "result": outcome.result,
                "open_findings": [
                    finding
                    for finding in (outcome.verdict or {}).get("findings", [])
                    if finding.get("status") == "OPEN"
                ],
                "telemetry": dict(outcome.tokens),
            }
            if outcome.verdict is not None:
                entry["verdict_ref"] = f"tasks/{outcome.task.task_id}/verdict.json"
            if outcome.duration_ms:
                entry["duration_ms"] = outcome.duration_ms
            if outcome.note:
                entry["note"] = outcome.note
            tasks.append(entry)

        results = {outcome.result for outcome in outcomes}
        if self.stops or "BLOCKED" in results:
            result = "BLOCKED"
        elif "FAIL" in results:
            result = "FAIL"
        elif results == {"PASS"}:
            result = "PASS"
        else:
            result = "INCONCLUSIVE"

        non_claims = [
            ladder.LEVEL_4_NON_CLAIM,
            "A program report consolidates verdicts; it does not re-judge "
            "them, and a task's non-claims still bound what its verdict means.",
        ]
        if self.dry_run:
            non_claims.insert(
                0,
                "Dry run: every task materialized its prompts, gates and "
                "manifest without calling a model. Nothing here is evidence.",
            )
        if self.stops:
            non_claims.append(
                "The program stopped early, so tasks marked BLOCKED were never "
                "attempted and nothing is claimed about them."
            )
        report = {
            "schema_version": "workflows.program-report.v1",
            "program_run_id": self.program_run_id,
            "plan_ref": self.resolved.plan_ref,
            "result": result,
            "dry_run": self.dry_run,
            "started_at": started_at,
            "finished_at": utc_now(),
            "tasks": tasks,
            "telemetry_totals": totals,
            "budgets": budgets,
            "stops": self.stops,
            "non_claims": non_claims,
        }
        errors = check_document(report, REPORT_SCHEMA, registry=self.registry)
        if errors:
            raise ProgramError(
                "the program report does not validate:\n"
                + "\n".join(f"  {e}" for e in errors[:20])
            )
        # Every execution writes its own report. A resume that completed more
        # tasks has something new to say, and run artifacts are append-only,
        # so it says it in the next numbered file rather than over the last.
        self.report_path = self.next_report_path()
        self.run.write_artifact(self.report_path, report)
        return report

    def next_report_path(self) -> str:
        directory = self.run.root / "reports"
        existing = sorted(int(p.stem) for p in directory.glob("*.json") if p.stem.isdigit())
        return f"reports/{(existing[-1] + 1) if existing else 1}.json"

    def latest_report(self) -> dict[str, Any] | None:
        directory = self.run.root / "reports"
        reports = sorted(
            (int(p.stem), p) for p in directory.glob("*.json") if p.stem.isdigit()
        )
        if not reports:
            return None
        return json.loads(reports[-1][1].read_text(encoding="utf-8"))


def summarize(report: dict[str, Any]) -> str:
    lines = [f"program {report['program_run_id']}: {report['result']}"]
    for task in report["tasks"]:
        open_count = len(task["open_findings"])
        suffix = f", {open_count} open finding(s)" if open_count else ""
        lines.append(f"  {task['task_id']:<20} {task['result']:<13} [{task['flow']}]{suffix}")
        if task.get("note"):
            lines.append(f"    {task['note']}")
    totals = report["telemetry_totals"]
    lines.append(
        f"  tokens: {totals['new_input']} new input + {totals['output']} output "
        f"({totals['cached_input']} cached, not counted against the budget)"
    )
    for stop in report.get("stops", []):
        lines.append(f"  stopped: {stop['kind']} — {stop['detail']}")
    for claim in report["non_claims"]:
        lines.append(f"  not claimed: {claim}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _program_run_id(resolved: ResolvedPlan, given: str | None) -> str:
    if given:
        return given
    return f"program-{resolved.plan['plan_id']}-{resolved.digest[7:19]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.program", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="resolve a plan, then execute it once approved")
    run_parser.add_argument("plan", type=Path)
    run_parser.add_argument("--worktree", type=Path, default=Path("."))
    run_parser.add_argument("--runs", type=Path, default=Path("runs"))
    run_parser.add_argument("--run-id", default=None)
    run_parser.add_argument(
        "--approve",
        action="store_true",
        help="the single human checkpoint: execute the resolved plan",
    )
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--max-parallel-workers", type=int, default=1)

    resume_parser = sub.add_parser("resume", help="continue a program run")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("--worktree", type=Path, default=Path("."))
    resume_parser.add_argument("--runs", type=Path, default=Path("runs"))
    resume_parser.add_argument("--max-parallel-workers", type=int, default=1)

    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        return _resume(args)
    except (ProgramError, FlowError, SchemaError, OSError, ValueError) as exc:
        print(f"cannot run the program: {exc}", file=sys.stderr)
        return EXIT_USAGE


def _run(args: argparse.Namespace) -> int:
    resolved = resolve(args.plan)
    print(describe(resolved))
    if not args.approve:
        print(
            "\nThis is the single checkpoint. Nothing has run and nothing will "
            "until you approve.\nRe-run the same command with --approve to "
            "execute it."
        )
        return EXIT_OK

    program = Program(
        resolved,
        worktree=args.worktree.resolve(),
        runs_root=args.runs,
        program_run_id=_program_run_id(resolved, args.run_id),
        dry_run=bool(args.dry_run),
        max_parallel_workers=args.max_parallel_workers,
    )
    report = program.execute()
    print("\n" + summarize(report))
    print(f"  report: {program.run.root / program.report_path}")
    return EXIT_OK if report["result"] == "PASS" else EXIT_STOPPED


def _resume(args: argparse.Namespace) -> int:
    directory = RunDirectory(args.runs / args.run_id)
    if not directory.exists:
        raise ProgramError(f"no program run at {directory.root}")
    manifest = directory.read_manifest()
    if manifest.get("kind") != "program":
        raise ProgramError(f"{args.run_id} is a flow run, not a program run")

    source = directory.read_artifact("plan-source.json")
    plan_path = Path(source["plan_path"])
    if not plan_path.is_file():
        raise ProgramError(
            f"the plan this run was created from is gone: {plan_path}. A plan "
            "is frozen at run start, and a resume continues that plan."
        )
    resolved = resolve(plan_path)
    if resolved.digest != source["digest"]:
        raise ProgramError(
            "the plan file has changed since this run was created. A plan is "
            "frozen at run start: changing it mid-run is a new run."
        )
    program = Program(
        resolved,
        worktree=args.worktree.resolve(),
        runs_root=args.runs,
        program_run_id=args.run_id,
        dry_run=bool(manifest.get("dry_run")),
        max_parallel_workers=args.max_parallel_workers,
    )
    report = program.execute()
    print(summarize(report))
    print(f"  report: {program.run.root / program.report_path}")
    return EXIT_OK if report["result"] == "PASS" else EXIT_STOPPED


if __name__ == "__main__":
    sys.exit(main())
