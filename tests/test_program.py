"""The program level: one plan, one checkpoint, one report.

Every mandatory M6 case in docs/test-charter.md is here: overlapping write
scopes rejected at resolve before the checkpoint, resume re-running no
completed flow, a budget breach stopping cleanly with a report rather than
crashing, and the checkpoint firing exactly once per program rather than
once per task.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests import support
from tests.gitrepo import TempRepo
from workflows import program
from workflows.runs import RunDirectory
from workflows.semantics import check_document

CONTRACT_TEMPLATE = {
    "schema_version": "workflows.task-contract.v1",
    "contract_revision": 1,
    "contract_type": "task",
    "goal": "Keep the calculator correct while leaving the test suite untouched.",
    "protected": ["tests/**"],
    "acceptance": [{"id": "AC-1", "statement": "The verification command exits zero."}],
    "verification": {"command": [sys.executable, "-c", "pass"], "expect_exit_code": 0},
}


def cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = program.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ProgramTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)
        self.repo.write(".gitignore", "runs/\nplans/\n")
        self.repo.seed()
        self.base = self.repo.head
        self.registry = support.registry()
        self.plans = self.repo.path / "plans"
        self.plans.mkdir()
        self.addCleanup(self.prune)

    def prune(self) -> None:
        from workflows import gitcmd

        gitcmd.run(self.repo.path, "worktree", "prune", check=False)

    def contract(self, name: str, scope: list[str]) -> str:
        document = dict(
            CONTRACT_TEMPLATE, contract_id=f"contract-{name}", scope={"allowed_paths": scope}
        )
        (self.plans / f"{name}.json").write_text(json.dumps(document), encoding="utf-8")
        return f"{name}.json"

    def plan(self, tasks: list[dict], **overrides) -> Path:
        document = {
            "schema_version": "workflows.plan.v1",
            "plan_id": "plan-test",
            "plan_revision": 1,
            "description": "A test plan.",
            "base": [{"repo_id": "target", "commit": self.base}],
            "tasks": tasks,
            "concurrency": {"max_parallel_tasks": 1},
            "budgets": {"tokens": 1000000, "wall_clock_seconds": 3600},
            "escalation": {
                "level_2_on_severity": "HIGH",
                "stop_on_severity": "CRITICAL",
                "max_repair_rounds": 1,
            },
        }
        document.update(overrides)
        path = self.plans / "plan.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def three_task_plan(self) -> Path:
        return self.plan(
            [
                {
                    "task_id": "task-parser",
                    "contract_path": self.contract("parser", ["src/example/parser/**"]),
                    "flow": "implement",
                    "write_scope": ["src/example/parser/**"],
                    "review_lens_set": ["review/scope-integrity"],
                },
                {
                    "task_id": "task-report",
                    "contract_path": self.contract("report", ["src/example/report/**"]),
                    "flow": "implement",
                    "write_scope": ["src/example/report/**"],
                    "review_lens_set": ["review/closed-contract"],
                },
                {
                    "task_id": "task-canonical",
                    "contract_path": self.contract("canonical", ["src/example/canonical/**"]),
                    "flow": "fanout",
                    "write_scope": ["src/example/canonical/**"],
                    "lens_set": ["work/spec-fidelity", "work/defensive-input"],
                    "review_lens_set": ["review/determinism"],
                },
            ]
        )

    def args(self, plan: Path, *extra: str) -> list[str]:
        return [
            "run",
            str(plan),
            "--worktree",
            str(self.repo.path),
            "--runs",
            str(self.repo.path / "runs"),
            *extra,
        ]


class ResolveTest(ProgramTestCase):
    def test_overlapping_write_scopes_are_rejected_at_resolve(self) -> None:
        """Before the checkpoint, so the human is never asked to approve it."""
        plan = self.plan(
            [
                {
                    "task_id": "task-a",
                    "contract_path": self.contract("a", ["src/example/**"]),
                    "flow": "implement",
                    "write_scope": ["src/example/**"],
                },
                {
                    "task_id": "task-b",
                    "contract_path": self.contract("b", ["src/example/util.py"]),
                    "flow": "implement",
                    "write_scope": ["src/example/util.py"],
                },
            ]
        )
        with self.assertRaises(program.ProgramError) as ctx:
            program.resolve(plan)
        self.assertIn("overlapping_write_scope", str(ctx.exception))

        code, out, err = cli(*self.args(plan, "--approve", "--dry-run"))
        self.assertEqual(code, program.EXIT_USAGE)
        self.assertIn("overlapping_write_scope", err)
        self.assertFalse((self.repo.path / "runs").exists(), "nothing ran")

    def test_a_missing_contract_is_rejected_at_resolve(self) -> None:
        plan = self.plan(
            [
                {
                    "task_id": "task-a",
                    "contract_path": "absent.json",
                    "flow": "implement",
                    "write_scope": ["src/example/**"],
                }
            ]
        )
        with self.assertRaises(program.ProgramError) as ctx:
            program.resolve(plan)
        self.assertIn("does not exist", str(ctx.exception))

    def test_an_invalid_contract_is_rejected_at_resolve(self) -> None:
        broken = dict(CONTRACT_TEMPLATE, contract_id="contract-broken")
        broken.pop("verification")
        broken["scope"] = {"allowed_paths": ["src/**"]}
        (self.plans / "broken.json").write_text(json.dumps(broken), encoding="utf-8")
        plan = self.plan(
            [
                {
                    "task_id": "task-a",
                    "contract_path": "broken.json",
                    "flow": "implement",
                    "write_scope": ["src/example/**"],
                }
            ]
        )
        with self.assertRaises(program.ProgramError) as ctx:
            program.resolve(plan)
        self.assertIn("does not validate", str(ctx.exception))

    def test_a_flow_this_version_cannot_run_is_rejected_at_resolve(self) -> None:
        plan = self.plan(
            [
                {
                    "task_id": "task-a",
                    "contract_path": self.contract("a", ["src/example/**"]),
                    "flow": "benchmark",
                    "write_scope": ["src/example/**"],
                }
            ]
        )
        with self.assertRaises(program.ProgramError) as ctx:
            program.resolve(plan)
        self.assertIn("cannot run", str(ctx.exception))

    def test_the_resolved_plan_prints_scopes_flows_and_budgets(self) -> None:
        described = program.describe(program.resolve(self.three_task_plan()))
        for expected in (
            "task-parser",
            "implement",
            "fanout",
            "src/example/canonical/**",
            "tokens",
            "wall clock",
            "level 2 at HIGH",
            self.base,
        ):
            self.assertIn(expected, described)


class ReviewRegressionTest(ProgramTestCase):
    """Counter-examples an independent review of M6 found reaching execution."""

    def test_a_write_scope_the_contract_does_not_match_is_rejected(self) -> None:
        """The checkpoint showed disjoint scopes while the gates allowed both
        tasks to write the same file."""
        plan = self.plan(
            [
                {
                    "task_id": "task-a",
                    "contract_path": self.contract("a", ["src/example/shared.py"]),
                    "flow": "implement",
                    "write_scope": ["src/example/a-only.py"],
                },
                {
                    "task_id": "task-b",
                    "contract_path": self.contract("b", ["src/example/shared.py"]),
                    "flow": "implement",
                    "write_scope": ["src/example/b-only.py"],
                },
            ]
        )
        with self.assertRaises(program.ProgramError) as ctx:
            program.resolve(plan)
        self.assertIn("the contract does not match", str(ctx.exception))

    def test_two_tasks_sharing_one_contract_are_rejected(self) -> None:
        shared = self.contract("shared", ["src/example/**"])
        plan = self.plan(
            [
                {
                    "task_id": "task-a",
                    "contract_path": shared,
                    "flow": "implement",
                    "write_scope": ["src/example/**"],
                },
                {
                    "task_id": "task-b",
                    "contract_path": shared,
                    "flow": "implement",
                    "write_scope": ["src/example/**"],
                },
            ]
        )
        with self.assertRaises(program.ProgramError) as ctx:
            program.resolve(plan)
        self.assertIn("are one task", str(ctx.exception))

    def test_a_base_that_does_not_exist_is_rejected_at_resolve(self) -> None:
        plan = self.plan(
            [
                {
                    "task_id": "task-a",
                    "contract_path": self.contract("a", ["src/example/**"]),
                    "flow": "implement",
                    "write_scope": ["src/example/**"],
                }
            ],
            base=[{"repo_id": "target", "commit": "e" * 40}],
        )
        with self.assertRaises(program.ProgramError) as ctx:
            program.resolve(plan, worktree=self.repo.path)
        self.assertIn("does not exist", str(ctx.exception))

        code, _, err = cli(*self.args(plan, "--approve", "--dry-run"))
        self.assertEqual(code, program.EXIT_USAGE)
        self.assertFalse((self.repo.path / "runs").exists(), "nothing ran")

    def test_one_task_raising_does_not_take_down_the_batch(self) -> None:
        plan = self.three_task_plan()
        resolved = program.resolve(plan)
        engine = program.Program(
            resolved,
            worktree=self.repo.path,
            runs_root=self.repo.path / "runs",
            program_run_id="p-crash",
            dry_run=True,
            registry=self.registry,
        )
        original = engine.task_worktree

        def explode(task):
            if task.task_id == "task-report":
                raise RuntimeError("git worktree add failed (128)")
            return original(task)

        engine.task_worktree = explode
        report = engine.execute()

        by_id = {task["task_id"]: task for task in report["tasks"]}
        self.assertEqual(len(by_id), 3, "every task is reported")
        self.assertEqual(by_id["task-report"]["state"], "FAILED")
        self.assertIn("git worktree add failed", by_id["task-report"]["note"])
        self.assertEqual(by_id["task-parser"]["state"], "COMPLETED")
        self.assertEqual(by_id["task-canonical"]["state"], "COMPLETED")
        errors = check_document(report, program.REPORT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [])

    def test_a_budget_breach_stops_before_the_rest_of_a_parallel_batch(self) -> None:
        tasks = json.loads(self.three_task_plan().read_text(encoding="utf-8"))["tasks"]
        plan = self.plan(
            tasks,
            concurrency={"max_parallel_tasks": 2},
            budgets={"tokens": 1, "wall_clock_seconds": 3600},
        )
        resolved = program.resolve(plan)

        from dataclasses import replace as _replace

        from workflows.runners.codex import DryRunner

        class Spender:
            name = "spender"

            def __init__(self, inner):
                self.inner = inner

            def invoke(self, call):
                result = self.inner.invoke(call)
                return _replace(
                    result,
                    telemetry=_replace(
                        result.telemetry,
                        tokens=type(result.telemetry.tokens)(
                            new_input=5000, cached_input=10, output=100
                        ),
                    ),
                )

        engine = program.Program(
            resolved,
            worktree=self.repo.path,
            runs_root=self.repo.path / "runs",
            program_run_id="p-early-stop",
            dry_run=True,
            registry=self.registry,
            runner_factory=lambda: Spender(DryRunner(registry=self.registry)),
        )
        report = engine.execute()
        started = [task for task in report["tasks"] if task["state"] != "BLOCKED"]
        self.assertLess(
            len(started),
            3,
            "a breach must stop the program before every task in the batch runs",
        )
        self.assertEqual(report["stops"][0]["kind"], "token_budget")

    def test_the_wall_clock_budget_does_not_restart_on_resume(self) -> None:
        plan = self.three_task_plan()
        resolved = program.resolve(plan)
        first = program.Program(
            resolved,
            worktree=self.repo.path,
            runs_root=self.repo.path / "runs",
            program_run_id="p-clock-resume",
            dry_run=True,
            registry=self.registry,
        )
        first.prepare()

        manifest = first.run.read_manifest()
        manifest["created_at"] = "2020-01-01T00:00:00Z"
        first.run.write_manifest(manifest)

        second = program.Program(
            resolved,
            worktree=self.repo.path,
            runs_root=self.repo.path / "runs",
            program_run_id="p-clock-resume",
            dry_run=True,
            registry=self.registry,
        )
        report = second.execute()
        self.assertEqual(report["stops"][0]["kind"], "wall_clock_budget")
        self.assertEqual(report["result"], "BLOCKED")


class CheckpointTest(ProgramTestCase):
    def test_without_approval_nothing_runs(self) -> None:
        plan = self.three_task_plan()
        code, out, _ = cli(*self.args(plan, "--dry-run"))
        self.assertEqual(code, program.EXIT_OK)
        self.assertIn("single checkpoint", out)
        self.assertIn("Nothing has run", out)
        self.assertFalse((self.repo.path / "runs").exists())

    def test_the_checkpoint_fires_once_per_program_not_once_per_task(self) -> None:
        plan = self.three_task_plan()
        code, out, err = cli(*self.args(plan, "--approve", "--dry-run", "--run-id", "p1"))
        # A dry run concludes nothing, so INCONCLUSIVE is its success shape.
        self.assertEqual(code, program.EXIT_OK, out + err)
        self.assertEqual(out.count("single checkpoint"), 0)
        report = json.loads(
            (self.repo.path / "runs" / "p1" / "reports" / "1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(report["tasks"]), 3)


class ExecutionTest(ProgramTestCase):
    def test_a_three_task_dry_run_produces_one_valid_report(self) -> None:
        plan = self.three_task_plan()
        code, out, err = cli(*self.args(plan, "--approve", "--dry-run", "--run-id", "p2"))
        self.assertIn("program p2", out, err)

        root = self.repo.path / "runs" / "p2"
        report = json.loads((root / "reports" / "1.json").read_text(encoding="utf-8"))
        errors = check_document(report, program.REPORT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [])
        self.assertEqual(
            [task["task_id"] for task in report["tasks"]],
            ["task-parser", "task-report", "task-canonical"],
        )
        self.assertTrue(report["dry_run"])
        self.assertTrue(
            any("Dry run" in claim for claim in report["non_claims"]),
            "a dry-run report must say so first",
        )
        for task in report["tasks"]:
            self.assertTrue((root / "tasks" / task["task_id"] / "manifest.json").is_file())
        self.assertTrue((root / "plan.json").is_file())
        manifest = RunDirectory(root).read_manifest()
        self.assertEqual(manifest["kind"], "program")
        self.assertEqual(len(manifest["steps"]), 3)

    def test_each_task_gets_its_own_worktree_at_the_frozen_base(self) -> None:
        from workflows import gitcmd

        plan = self.three_task_plan()
        cli(*self.args(plan, "--approve", "--dry-run", "--run-id", "p3"))
        worktrees = self.repo.path / "runs" / "p3" / "worktrees"
        self.assertEqual(
            sorted(path.name for path in worktrees.iterdir()),
            ["task-canonical", "task-parser", "task-report"],
        )
        for path in worktrees.iterdir():
            self.assertEqual(gitcmd.head_commit(path), self.base)

    def test_parallel_tasks_produce_the_same_task_set(self) -> None:
        plan = self.plan(
            json.loads(self.three_task_plan().read_text(encoding="utf-8"))["tasks"],
            concurrency={"max_parallel_tasks": 3},
        )
        code, out, err = cli(*self.args(plan, "--approve", "--dry-run", "--run-id", "p4"))
        report = json.loads(
            (self.repo.path / "runs" / "p4" / "reports" / "1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(report["tasks"]), 3)


class BudgetTest(ProgramTestCase):
    def test_a_token_budget_breach_stops_cleanly_with_a_report(self) -> None:
        tasks = json.loads(self.three_task_plan().read_text(encoding="utf-8"))["tasks"]
        plan = self.plan(tasks, budgets={"tokens": 1, "wall_clock_seconds": 3600})
        resolved = program.resolve(plan)

        class Spender:
            name = "spender"

            def __init__(self, inner):
                self.inner = inner

            def invoke(self, call):
                from dataclasses import replace as _replace

                result = self.inner.invoke(call)
                return _replace(
                    result,
                    telemetry=_replace(
                        result.telemetry,
                        tokens=type(result.telemetry.tokens)(
                            new_input=1000, cached_input=10, output=100
                        ),
                    ),
                )

        from workflows.runners.codex import DryRunner

        engine = program.Program(
            resolved,
            worktree=self.repo.path,
            runs_root=self.repo.path / "runs",
            program_run_id="p-budget",
            dry_run=True,
            registry=self.registry,
            runner_factory=lambda: Spender(DryRunner(registry=self.registry)),
        )
        report = engine.execute()

        self.assertEqual(report["result"], "BLOCKED")
        self.assertEqual(report["stops"][0]["kind"], "token_budget")
        self.assertEqual(len(report["tasks"]), 3)
        blocked = [task for task in report["tasks"] if task["state"] == "BLOCKED"]
        self.assertTrue(blocked, "unstarted tasks are reported, not dropped")
        self.assertTrue(
            any("never attempted" in claim for claim in report["non_claims"])
        )
        errors = check_document(report, program.REPORT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [])

    def test_cached_input_is_not_counted_against_the_budget(self) -> None:
        self.assertEqual(
            program.budget_spend({"new_input": 100, "cached_input": 9000, "output": 50}),
            150,
        )

    def test_a_wall_clock_breach_stops_cleanly(self) -> None:
        tasks = json.loads(self.three_task_plan().read_text(encoding="utf-8"))["tasks"]
        plan = self.plan(tasks, budgets={"tokens": 1000000, "wall_clock_seconds": 1})
        resolved = program.resolve(plan)
        engine = program.Program(
            resolved,
            worktree=self.repo.path,
            runs_root=self.repo.path / "runs",
            program_run_id="p-clock",
            dry_run=True,
            registry=self.registry,
        )
        engine.started -= 10  # ten seconds ago, against a one-second budget
        report = engine.execute()
        self.assertEqual(report["result"], "BLOCKED")
        self.assertEqual(report["stops"][0]["kind"], "wall_clock_budget")


class ResumeTest(ProgramTestCase):
    def test_resume_reruns_no_completed_flow(self) -> None:
        plan = self.three_task_plan()
        cli(*self.args(plan, "--approve", "--dry-run", "--run-id", "p5"))
        root = self.repo.path / "runs" / "p5"
        finished = {
            path.parent.name: path.read_text(encoding="utf-8")
            for path in root.glob("tasks/*/verdict.json")
        }
        self.assertEqual(len(finished), 3)

        code, out, err = cli(
            "resume",
            "p5",
            "--worktree",
            str(self.repo.path),
            "--runs",
            str(self.repo.path / "runs"),
        )
        self.assertIn("program p5", out, err)
        again = {
            path.parent.name: path.read_text(encoding="utf-8")
            for path in root.glob("tasks/*/verdict.json")
        }
        self.assertEqual(again, finished, "a completed flow is not re-run")
        # The resume writes its own report; the first one is never overwritten.
        first = json.loads((root / "reports" / "1.json").read_text(encoding="utf-8"))
        second = json.loads((root / "reports" / "2.json").read_text(encoding="utf-8"))
        self.assertTrue(
            all("not re-run" in (task.get("note") or "") for task in second["tasks"])
        )
        self.assertFalse(
            any("not re-run" in (task.get("note") or "") for task in first["tasks"])
        )
        self.assertEqual(second["telemetry_totals"]["new_input"], 0)

    def test_resuming_an_unknown_run_is_a_usage_error(self) -> None:
        code, _, err = cli(
            "resume", "nope", "--runs", str(self.repo.path / "runs")
        )
        self.assertEqual(code, program.EXIT_USAGE)
        self.assertIn("no program run", err)

    def test_a_plan_edited_after_the_run_started_is_refused(self) -> None:
        plan = self.three_task_plan()
        cli(*self.args(plan, "--approve", "--dry-run", "--run-id", "p6"))
        document = json.loads(plan.read_text(encoding="utf-8"))
        document["description"] = "Changed after approval."
        plan.write_text(json.dumps(document), encoding="utf-8")
        code, _, err = cli(
            "resume",
            "p6",
            "--worktree",
            str(self.repo.path),
            "--runs",
            str(self.repo.path / "runs"),
        )
        self.assertEqual(code, program.EXIT_USAGE)
        self.assertIn("frozen at run start", err)


if __name__ == "__main__":
    unittest.main()
