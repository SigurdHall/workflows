"""Path pattern matching for scopes and protected files.

Scope declarations are the thing a human approves and a gate enforces, so
the matching rules are written down here once and used by every consumer
(contract validation, the scope gate, plan resolution). Three rules:

* ``*`` matches within one path segment; ``**`` matches any number of
  segments, including zero.
* A pattern with no wildcard matches that exact path *and* everything under
  it, so ``docs`` covers ``docs/guide.md`` and a protected file path still
  matches only itself.
* Paths are repository-relative and use forward slashes. Backslashes and
  parent-directory segments never appear — the schema rejects them before
  anything reaches this module.

Overlap detection is deliberately conservative: when it cannot prove two
patterns are disjoint it reports them as overlapping. The consumer of that
answer rejects plans, and a false rejection costs an edit while a false
acceptance costs two flows writing the same file.
"""

from __future__ import annotations

import re
from functools import lru_cache

WILDCARD = re.compile(r"[*]")


def normalize(pattern: str) -> str:
    """Trim a trailing slash into an explicit ``/**``."""
    if pattern.endswith("/"):
        return pattern + "**"
    return pattern


@lru_cache(maxsize=4096)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    pattern = normalize(pattern)
    if not WILDCARD.search(pattern):
        # A literal path covers itself and everything beneath it.
        literal = re.escape(pattern)
        return re.compile(f"^{literal}(?:/.*)?$")
    tokens = pattern.split("/")
    parts: list[str] = []
    for index, token in enumerate(tokens):
        last = index == len(tokens) - 1
        if token == "**":
            parts.append(".+" if last else "(?:[^/]+/)*")
            continue
        segment = "".join(
            "[^/]*" if char == "*" else re.escape(char) for char in token
        )
        parts.append(segment if last else segment + "/")
    return re.compile("^" + "".join(parts) + "$")


def matches(pattern: str, path: str) -> bool:
    """True when ``path`` falls inside ``pattern``."""
    return compile_pattern(pattern).match(path) is not None


def matches_any(patterns: list[str], path: str) -> bool:
    return any(matches(pattern, path) for pattern in patterns)


def literal_prefix(pattern: str) -> list[str]:
    """The leading segments of a pattern that contain no wildcard."""
    segments: list[str] = []
    for token in normalize(pattern).split("/"):
        if WILDCARD.search(token):
            break
        segments.append(token)
    return segments


def overlaps(left: str, right: str) -> bool:
    """Conservatively true when two patterns can match a common path.

    Exact intersection of two wildcard patterns is not decidable cheaply, so
    anything the literal prefixes cannot separate counts as an overlap.
    """
    if matches(left, right) or matches(right, left):
        return True
    a, b = literal_prefix(left), literal_prefix(right)
    shared = min(len(a), len(b))
    return a[:shared] == b[:shared]
