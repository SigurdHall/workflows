"""Shared plumbing for presence probes.

A probe answers one question about one candidate: **is this planted defect
still here?** It is not a review and not a quality judgement. A candidate that
removed the planted defect and introduced a worse one probes ABSENT, and the
report says so in its non-claims.

The contract, deliberately narrow:

* invoked as ``<interpreter> <probe.py> <task directory inside the candidate>``
* prints exactly one line, ``DEFECT_PRESENT`` or ``DEFECT_ABSENT``
* exits zero

Anything else — a crash, silence, two answers — is INDETERMINATE to the
scorer. That is why `answer` catches nothing: an unexpected exception must
reach the scorer as "not settled" rather than be guessed at here.

Probes live in the corpus, never in a seed tree. A probe copied into the
worktree would be an answer key the reviewers can read.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

PRESENT = "DEFECT_PRESENT"
ABSENT = "DEFECT_ABSENT"


def task_directory() -> Path:
    if len(sys.argv) < 2:
        raise SystemExit("usage: probe.py <task directory inside the candidate>")
    directory = Path(sys.argv[1])
    if not directory.is_dir():
        raise SystemExit(f"not a directory: {directory}")
    return directory


def load(module_name: str) -> Any:
    """Import one module out of the candidate's `src`, by path.

    By path rather than by `sys.path` so that two probes in one process could
    never bind to the same module name, and so the candidate's own layout is
    what decides what gets loaded.
    """
    directory = task_directory()
    source = directory / "src" / f"{module_name}.py"
    if not source.is_file():
        raise SystemExit(f"the candidate has no {source}")
    # The seeds' own tests import their neighbours off sys.path; a candidate
    # may keep that habit, so give it the same directory to find them on.
    sys.path.insert(0, str((directory / "src").resolve()))
    spec = importlib.util.spec_from_file_location(f"candidate_{module_name}", source)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answer(verdict: Callable[[], bool]) -> None:
    """Print the verdict. True means the planted defect is still present."""
    print(PRESENT if verdict() else ABSENT)
