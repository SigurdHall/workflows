"""A throwaway git repository for gate tests.

Gates read a real worktree through real git, so the tests give them one.
The repository is configured explicitly — identity, line endings, default
branch — because a gate that only passes under one machine's git config is
not a deterministic check.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


class TempRepo:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self._tmp.name)
        self.git("init", "--quiet")
        # Not an address: the content policy forbids committing anything
        # email-shaped, and git is happy with any identity string.
        self.git("config", "user.email", "tests.local")
        self.git("config", "user.name", "tests")
        self.git("config", "commit.gpgsign", "false")
        # Byte-identical is the whole point of the protected-hash gate; a
        # platform that rewrites line endings on checkout would defeat it.
        self.git("config", "core.autocrlf", "false")

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(self.path),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr}")
        return completed.stdout

    def write(self, relative: str, content: str) -> Path:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return target

    def delete(self, relative: str) -> None:
        (self.path / relative).unlink()

    def commit(self, message: str = "change") -> str:
        self.git("add", "-A")
        self.git("commit", "--quiet", "--allow-empty", "-m", message)
        return self.head

    @property
    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def seed(self) -> str:
        """A base commit with a small tree: source, tests, docs."""
        self.write("src/example/calc.py", "def add(a, b):\n    return a + b\n")
        self.write("src/example/util.py", "VALUE = 1\n")
        self.write("tests/test_calc.py", "def test_add():\n    assert True\n")
        self.write("docs/guide.md", "# Guide\n\nSee [calc](../src/example/calc.py).\n")
        return self.commit("base")
