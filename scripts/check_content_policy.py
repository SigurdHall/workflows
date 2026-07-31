"""Check the repository against the content policy.

Scans tracked text files for patterns defined in content-policy.toml and,
when present, the gitignored .content-policy.local.toml (private terms).
Exit code 0 = clean, 1 = violations found, 2 = configuration error.

Usage:
    python scripts/check_content_policy.py [--root PATH]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2"}
SELF = Path(__file__).name


def load_rules(root: Path) -> list[tuple[str, re.Pattern[str]]]:
    rules: list[tuple[str, re.Pattern[str]]] = []
    for name in ("content-policy.toml", ".content-policy.local.toml"):
        path = root / name
        if not path.exists():
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for rule in data.get("rules", []):
            try:
                rules.append((rule["id"], re.compile(rule["pattern"])))
            except (KeyError, re.error) as exc:
                print(f"config error in {name}: {exc}", file=sys.stderr)
                sys.exit(2)
        for term in data.get("terms", []):
            rules.append((f"private-term:{term}", re.compile(re.escape(term), re.IGNORECASE)))
    if not rules:
        print("config error: no rules loaded", file=sys.stderr)
        sys.exit(2)
    return rules


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    )
    return [root / line for line in out.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    rules = load_rules(args.root)
    violations = 0
    for path in tracked_files(args.root):
        if path.suffix.lower() in SKIP_SUFFIXES or path.name == SELF:
            continue
        if path.name in ("content-policy.toml",):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for rule_id, pattern in rules:
                if pattern.search(line):
                    rel = path.relative_to(args.root)
                    print(f"{rel}:{lineno}: {rule_id}")
                    violations += 1

    if violations:
        print(f"\n{violations} content policy violation(s).", file=sys.stderr)
        return 1
    print("content policy: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
