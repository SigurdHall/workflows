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
        parts.append(_segment(token) if last else _segment(token) + "/")
    return re.compile("^" + "".join(parts) + "$")


def _segment(token: str) -> str:
    """Translate one path segment. ``**`` crosses separators wherever it sits.

    ``src/vendor-**`` reads as "everything under src/vendor-*", and it now
    behaves that way. Treating ``**`` as recursive only when it is a whole
    segment made that pattern quietly protect one directory entry and
    nothing beneath it.
    """
    out: list[str] = []
    index = 0
    while index < len(token):
        if token.startswith("**", index):
            out.append(".*")
            index += 2
        elif token[index] == "*":
            out.append("[^/]*")
            index += 1
        else:
            out.append(re.escape(token[index]))
            index += 1
    return "".join(out)


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

    Comparison folds case, unlike :func:`matches`. Git paths are
    case-sensitive but Windows and macOS filesystems are not, so two scopes
    differing only in case can name the same file on the machine a flow runs
    on. Reporting them as overlapping is the conservative direction; matching
    stays exact, because that is what git actually reports.
    """
    left, right = left.lower(), right.lower()
    if matches(left, right) or matches(right, left):
        return True
    a, b = literal_prefix(left), literal_prefix(right)
    shared = min(len(a), len(b))
    return a[:shared] == b[:shared]
