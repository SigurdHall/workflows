"""Git access by subprocess, against one worktree path.

No third-party git library: gates must run wherever Python and git run, and
the surface used here is small enough that a wrapper would hide more than it
saves. Every function takes the worktree it operates on; nothing reads an
ambient current directory.

The candidate a gate inspects is the *working tree*, not a commit. A worker
may or may not have committed its work, and a gate that only compared
commits would miss exactly the changes it exists to catch — including
untracked files, which `git diff` does not report at all.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

MISSING = object()


class GitError(RuntimeError):
    """A git invocation failed, or git itself is unavailable."""


@dataclass(frozen=True)
class Change:
    """One path that differs between the frozen base and the working tree."""

    status: str  # A added, M modified, D deleted, R renamed, T type change
    path: str
    old_path: str | None = None

    @property
    def paths(self) -> tuple[str, ...]:
        if self.old_path is None:
            return (self.path,)
        return (self.old_path, self.path)


def run(
    worktree: Path | str, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:  # git itself is missing
        raise GitError("git is not available on PATH") from exc
    if check and completed.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed ({completed.returncode}): "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed


def rev_exists(worktree: Path | str, rev: str) -> bool:
    completed = run(worktree, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
    return completed.returncode == 0


def head_commit(worktree: Path | str) -> str:
    return run(worktree, "rev-parse", "HEAD").stdout.strip()


def parents(worktree: Path | str, rev: str = "HEAD") -> list[str]:
    output = run(worktree, "rev-list", "--parents", "-n", "1", rev).stdout.split()
    return output[1:]


def is_clean(worktree: Path | str) -> bool:
    return not run(worktree, "status", "--porcelain").stdout.strip()


def dirty_paths(worktree: Path | str) -> list[str]:
    paths: list[str] = []
    for line in run(worktree, "status", "--porcelain").stdout.splitlines():
        entry = line[3:].strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        paths.append(entry.strip('"'))
    return sorted(paths)


def tracked_changes(worktree: Path | str, base: str) -> list[Change]:
    """Tracked differences between ``base`` and the working tree."""
    output = run(
        worktree, "diff", "--name-status", "--find-renames", "-z", base
    ).stdout
    fields = [field for field in output.split("\0") if field != ""]
    changes: list[Change] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if status.startswith("R") or status.startswith("C"):
            old_path, new_path = fields[index], fields[index + 1]
            index += 2
            changes.append(Change(status[0], new_path, old_path))
        else:
            changes.append(Change(status[0], fields[index]))
            index += 1
    return changes


def untracked_files(worktree: Path | str) -> list[str]:
    output = run(
        worktree, "ls-files", "--others", "--exclude-standard", "-z"
    ).stdout
    return [path for path in output.split("\0") if path]


def changes(worktree: Path | str, base: str) -> list[Change]:
    """Every difference between ``base`` and the working tree.

    Untracked files are reported as additions. Leaving them out would let a
    worker add a file anywhere outside its scope unobserved, because
    ``git diff`` never mentions them.
    """
    found = tracked_changes(worktree, base)
    known = {path for change in found for path in change.paths}
    found.extend(
        Change("A", path) for path in untracked_files(worktree) if path not in known
    )
    return sorted(found, key=lambda change: (change.path, change.status))


def add_worktree(repo: Path | str, path: Path | str, commit: str) -> None:
    """Create a detached worktree at ``commit``.

    Worktree creation writes to the repository's refs, so callers create them
    one at a time: parallel creation is how you meet `packed-refs.lock`.

    Stale registrations are pruned first. A run directory deleted by hand —
    or lost with the machine it lived on — leaves git holding a registration
    for a directory that is gone, and every later attempt to recreate it
    fails with "missing but already registered worktree". Pruning only
    removes registrations whose directories no longer exist.
    """
    run(repo, "worktree", "prune", check=False)
    run(repo, "worktree", "add", "--detach", "--quiet", str(path), commit)


def remove_worktree(repo: Path | str, path: Path | str) -> None:
    """Remove a worktree, tolerating one that is already gone."""
    run(repo, "worktree", "remove", "--force", str(path), check=False)
    run(repo, "worktree", "prune", check=False)


def files_at(worktree: Path | str, rev: str) -> list[str]:
    output = run(worktree, "ls-tree", "-r", "--name-only", "-z", rev).stdout
    return [path for path in output.split("\0") if path]


def blob_hash_at(worktree: Path | str, rev: str, path: str) -> str | None:
    """The blob hash of ``path`` in ``rev``, or None when it does not exist."""
    completed = run(worktree, "rev-parse", "--verify", "--quiet", f"{rev}:{path}", check=False)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def blob_hash_now(worktree: Path | str, path: str) -> str | None:
    """The blob hash of the file as it is on disk, or None when it is gone."""
    target = Path(worktree) / path
    if not target.is_file():
        return None
    return run(worktree, "hash-object", "--", path).stdout.strip()
