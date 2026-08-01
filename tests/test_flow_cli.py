"""The flow CLI, end to end against a real worktree."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.gitrepo import TempRepo
from workflows import flow

CONTRACT = {
    "schema_version": "workflows.task-contract.v1",
    "contract_id": "contract-cli",
    "contract_revision": 1,
    "contract_type": "task",
    "goal": "Keep the calculator correct while leaving the test suite untouched.",
    "scope": {"allowed_paths": ["src/example/**"]},
    "protected": ["tests/**"],
    "acceptance": [{"id": "AC-1", "statement": "The verification command exits zero."}],
    "verification": {"command": [sys.executable, "-c", "pass"], "expect_exit_code": 0},
}


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = flow.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class FlowCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)
        self.repo.write(".gitignore", "runs/\n")
        self.contract = self.repo.path / "contract.json"
        self.contract.write_text(json.dumps(CONTRACT), encoding="utf-8")
        self.repo.seed()
        self._outside = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._outside.cleanup)

    def args(self, *extra: str) -> list[str]:
        return [
            "implement",
            "--contract",
            str(self.contract),
            "--worktree",
            str(self.repo.path),
            "--runs",
            str(self.repo.path / "runs"),
            "--review-lens",
            "review/scope-integrity",
            *extra,
        ]

    def test_a_dry_run_materializes_a_complete_run_and_exits_zero(self) -> None:
        code, out, err = run(*self.args("--dry-run", "--run-id", "run-cli"))
        self.assertEqual(code, flow.EXIT_OK, out + err)
        self.assertIn("INCONCLUSIVE", out)
        self.assertIn("not claimed:", out)

        root = self.repo.path / "runs" / "run-cli"
        self.assertTrue((root / "manifest.json").is_file())
        self.assertTrue((root / "verdict.json").is_file())
        self.assertTrue((root / "telemetry.jsonl").is_file())
        self.assertTrue(list((root / "envelopes").glob("*.json")))
        self.assertTrue(list((root / "prompts").glob("*.json")))
        self.assertTrue(list((root / "gates").glob("*/*.json")))

    def test_a_dry_run_is_resumable_and_repeats_nothing(self) -> None:
        run(*self.args("--dry-run", "--run-id", "run-twice"))
        manifest = json.loads(
            (self.repo.path / "runs" / "run-twice" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        finished = {step["step_id"]: step["finished_at"] for step in manifest["steps"]}

        code, _, _ = run(*self.args("--dry-run", "--run-id", "run-twice"))
        self.assertEqual(code, flow.EXIT_OK)
        again = json.loads(
            (self.repo.path / "runs" / "run-twice" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            {step["step_id"]: step["finished_at"] for step in again["steps"]},
            finished,
            "a resumed run must not re-run a completed step",
        )

    def test_a_run_directory_inside_a_visible_worktree_is_refused(self) -> None:
        self.repo.write(".gitignore", "nothing-here\n")
        self.repo.commit("stop ignoring runs")
        code, _, err = run(*self.args("--dry-run", "--run-id", "run-visible"))
        self.assertEqual(code, flow.EXIT_USAGE)
        self.assertIn("not ignored by git", err)

    def test_a_run_directory_outside_the_worktree_is_allowed(self) -> None:
        code, _, err = run(
            "implement",
            "--contract",
            str(self.contract),
            "--worktree",
            str(self.repo.path),
            "--runs",
            str(Path(self._outside.name) / "runs"),
            "--review-lens",
            "review/scope-integrity",
            "--dry-run",
            "--run-id",
            "run-outside",
        )
        self.assertEqual(code, flow.EXIT_OK, err)

    def test_resuming_with_a_different_contract_is_refused(self) -> None:
        run(*self.args("--dry-run", "--run-id", "run-frozen"))
        changed = dict(CONTRACT, goal=CONTRACT["goal"] + " And also something else.")
        self.contract.write_text(json.dumps(changed), encoding="utf-8")
        code, _, err = run(*self.args("--dry-run", "--run-id", "run-frozen"))
        self.assertEqual(code, flow.EXIT_USAGE)
        self.assertIn("a different contract", err)

    def test_resuming_against_a_different_base_is_refused(self) -> None:
        run(*self.args("--dry-run", "--run-id", "run-based"))
        self.repo.write("src/example/other.py", "X = 1\n")
        moved = self.repo.commit("move the base")
        code, _, err = run(
            *self.args("--dry-run", "--run-id", "run-based", "--base", moved)
        )
        self.assertEqual(code, flow.EXIT_USAGE)
        self.assertIn("base", err)

    def test_resuming_with_a_different_flow_is_refused(self) -> None:
        run(*self.args("--dry-run", "--run-id", "run-flow"))
        code, _, err = run(
            "assure",
            "--contract",
            str(self.contract),
            "--worktree",
            str(self.repo.path),
            "--runs",
            str(self.repo.path / "runs"),
            "--dry-run",
            "--run-id",
            "run-flow",
        )
        self.assertEqual(code, flow.EXIT_USAGE)
        self.assertIn("flow", err)

    def test_a_live_run_without_a_profile_is_refused(self) -> None:
        """Otherwise the first call goes out as `-m worker-class`."""
        code, _, err = run(*self.args("--run-id", "run-live"))
        self.assertEqual(code, flow.EXIT_USAGE)
        self.assertIn("deployment profile", err)
        self.assertFalse((self.repo.path / "runs" / "run-live").exists())

    def test_a_dry_run_needs_no_profile(self) -> None:
        code, _, err = run(*self.args("--dry-run", "--run-id", "run-noprofile"))
        self.assertEqual(code, flow.EXIT_OK, err)

    def test_a_profile_is_accepted_and_bound(self) -> None:
        # Outside the worktree: an untracked file inside it would make the
        # base-identity gate report a dirty base, which it should.
        profile = Path(self._outside.name) / "profile.toml"
        profile.write_text(
            '[bindings.worker]\nmodel = "m"\neffort = "max"\n', encoding="utf-8"
        )
        code, _, err = run(
            *self.args("--dry-run", "--run-id", "run-profiled", "--profile", str(profile))
        )
        self.assertEqual(code, flow.EXIT_OK, err)
        telemetry = (
            self.repo.path / "runs" / "run-profiled" / "telemetry.jsonl"
        ).read_text(encoding="utf-8")
        self.assertIn('"model": "m"', telemetry)

    def test_an_invalid_contract_is_refused_before_anything_runs(self) -> None:
        broken = dict(CONTRACT)
        broken.pop("verification")
        self.contract.write_text(json.dumps(broken), encoding="utf-8")
        code, _, err = run(*self.args("--dry-run", "--run-id", "run-broken"))
        self.assertEqual(code, flow.EXIT_USAGE)
        self.assertIn("does not validate", err)
        self.assertFalse((self.repo.path / "runs" / "run-broken").exists())

    def test_assure_runs_against_an_existing_candidate(self) -> None:
        self.repo.write("src/example/util.py", "VALUE = 2\n")
        code, out, err = run(
            "assure",
            "--contract",
            str(self.contract),
            "--worktree",
            str(self.repo.path),
            "--runs",
            str(self.repo.path / "runs"),
            "--review-lens",
            "review/scope-integrity",
            "--dry-run",
            "--run-id",
            "run-assure",
        )
        self.assertEqual(code, flow.EXIT_OK, out + err)
        self.assertIn("assure", out)


if __name__ == "__main__":
    unittest.main()
