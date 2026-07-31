"""Lenses: a perspective a model works from, as a versioned file.

A lens is markdown, injected into a prompt verbatim. Nothing rewrites it at
run time — that is what makes the same lens plus the same contract produce a
byte-identical prompt, and what makes lens yield (which lens found which
finding) measurable across runs.

Every lens file starts with a machine-readable header:

    <!-- lens: review/closed-contract v1 -->

and carries the four sections `concepts/lens.md` requires. Both are checked
on load: an unversioned lens breaks attribution, and a lens without a
"Does not cover" section is how ten perspectives become three findings.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

HEADER = re.compile(r"^<!--\s*lens:\s*(?P<id>[a-z0-9]+/[a-z0-9-]+)\s+v(?P<version>\d+)\s*-->\s*$")
REQUIRED_SECTIONS = ("Targets", "Method", "Does not cover", "Output obligations")
FAMILIES = ("work", "review")


class LensError(ValueError):
    """A lens file is missing, misnamed, or malformed."""


@dataclass(frozen=True)
class Lens:
    id: str
    version: int
    text: str
    path: Path

    @property
    def family(self) -> str:
        return self.id.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.id.split("/", 1)[1]

    @property
    def reference(self) -> str:
        return f"{self.id} v{self.version}"


def lenses_dir() -> Path:
    """Directory holding the lens files.

    They ship inside the package for the same reason the schemas do: a
    prompt composed without its lens is a different prompt.
    """
    override = os.environ.get("WORKFLOWS_LENSES_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "lenses"


def parse(text: str, path: Path) -> Lens:
    lines = text.splitlines()
    if not lines:
        raise LensError(f"{path}: empty lens file")
    match = HEADER.match(lines[0])
    if match is None:
        raise LensError(
            f"{path}: first line must be a lens header, e.g. "
            "<!-- lens: review/closed-contract v1 -->"
        )
    missing = [
        section
        for section in REQUIRED_SECTIONS
        if not re.search(rf"^#+\s*{re.escape(section)}\s*$", text, re.MULTILINE | re.IGNORECASE)
    ]
    if missing:
        raise LensError(f"{path}: lens is missing section(s): {', '.join(missing)}")
    return Lens(
        id=match.group("id"),
        version=int(match.group("version")),
        text=text,
        path=path,
    )


@lru_cache(maxsize=None)
def _load(identifier: str, directory: str) -> Lens:
    family, _, name = identifier.partition("/")
    if family not in FAMILIES or not name:
        raise LensError(
            f"unknown lens id {identifier!r}: expected <family>/<name> with "
            f"family in {FAMILIES}"
        )
    path = Path(directory) / family / f"{name}.md"
    if not path.is_file():
        raise LensError(f"no lens file at {path}")
    lens = parse(path.read_text(encoding="utf-8-sig"), path)
    if lens.id != identifier:
        raise LensError(
            f"{path}: header declares {lens.id!r} but the file path says {identifier!r}"
        )
    return lens


def load(identifier: str, directory: Path | str | None = None) -> Lens:
    return _load(identifier, str(directory or lenses_dir()))


def load_many(identifiers: list[str], directory: Path | str | None = None) -> list[Lens]:
    return [load(identifier, directory) for identifier in identifiers]


def catalog(family: str | None = None, directory: Path | str | None = None) -> list[Lens]:
    """Every lens on disk, sorted by id."""
    root = Path(directory or lenses_dir())
    families = (family,) if family else FAMILIES
    found: list[Lens] = []
    for name in families:
        for path in sorted((root / name).glob("*.md")):
            found.append(load(f"{name}/{path.stem}", root))
    return found
