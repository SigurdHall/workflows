"""The `evolve` flow, stage one: the blind tournament and the rule inducer.

    python -m workflows.evolve tournament <candidates...> --rubric r.md --out <dir>
    python -m workflows.evolve induce --rubric r.md --chosen b.md --over a.md --out <file>

Search under judgment, where every other flow here is verification under
gates: there is no oracle, so the unit of progress is a comparison, not a
check. Three rules this module takes literally:

* **Judges are blind.** A duel prompt has no field for lineage, authorship
  or incumbency — bias needs a channel, and the prompt is built without one.
* **A split panel is a tie, and a tie keeps the incumbent.** Unanimity
  decides. Reading 2-1 as a decision is how marginal noise compounds into
  drift, which is the one known disease of loops without a human in them.
* **An override becomes a law, not a data point.** When the owner ranks a
  candidate above the machine's champion, the inducer proposes the rubric
  rule that would have produced the owner's ranking. Nothing enters the
  rubric until the owner ratifies it by editing the rubric file themselves.

The loop that feeds this tournament — lineages, grafts, a director — arrives
with the next stage. This module is deliberately the foundation alone,
because a selection step that cannot be trusted makes everything built on
top of it noise with confidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from workflows import prompts
from workflows.runners import RunnerCall, invoke_validated
from workflows.schema import SchemaError, default_registry
from workflows.semantics import check_document

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

DUEL_SCHEMA = "duel-verdict.schema.json"
AMENDMENT_SCHEMA = "rubric-amendment.schema.json"
REPORT_SCHEMA = "tournament-report.schema.json"
JUDGE_ROLE = "judge"


class EvolveError(RuntimeError):
    """The tournament was configured wrongly — an author error, not a verdict."""


class JudgeFailed(EvolveError):
    """A judge call did not conclude. A failed call is not a preference."""


# --------------------------------------------------------------------------
# Rubric
# --------------------------------------------------------------------------


def load_rubric(path: Path) -> str:
    """The rubric text, refused when it cannot order anything.

    The rubric is injected into judge prompts verbatim — it is data, like a
    lens, and its language belongs to the product it governs. The only
    structural demand made here is that it has structure at all: a rubric is
    a precedence list, and a document with fewer than two sections has no
    order to walk.
    """
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise EvolveError(f"{path} is empty; an empty rubric prefers everything")
    headings = [line for line in text.splitlines() if line.lstrip().startswith("#")]
    if len(headings) < 2:
        raise EvolveError(
            f"{path} has {len(headings)} heading(s). A rubric is a precedence "
            "structure; a document without sections cannot order candidates."
        )
    return text


def rubric_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    text: str


def candidate_id(path: Path) -> str:
    """A stable identity from a filename, safe for the report schema."""
    stem = re.sub(r"[^A-Za-z0-9._-]", "-", path.stem).strip("-.")
    return stem if stem and stem[0].isalnum() else f"c-{stem or 'unnamed'}"


def load_candidates(paths: Sequence[Path]) -> list[Candidate]:
    if len(paths) < 2:
        raise EvolveError("a tournament needs at least two candidates")
    candidates = []
    for path in paths:
        if not path.is_file():
            raise EvolveError(f"no candidate at {path}")
        candidates.append(Candidate(candidate_id(path), path.read_text(encoding="utf-8-sig")))
    ids = [c.candidate_id for c in candidates]
    if len(set(ids)) != len(ids):
        raise EvolveError(
            "two candidate files reduce to the same id: " + ", ".join(sorted(ids))
        )
    return candidates


# --------------------------------------------------------------------------
# Judging
# --------------------------------------------------------------------------


def _pointed_when_decided(output: dict[str, Any]) -> list[str]:
    """The extra rule no schema keyword expresses: preference needs evidence."""
    if output.get("winner") in ("one", "two") and not output.get("pointed"):
        return [
            "winner is set but pointed is empty: a preference that points at "
            "nothing is taste, not judgment"
        ]
    return []


def judge_once(
    runner: Any,
    *,
    rubric: str,
    one: str,
    two: str,
    registry: Any,
    cwd: Path,
    model: str,
    effort: str,
    step_id: str,
) -> dict[str, Any]:
    call = RunnerCall(
        prompt=prompts.duel(
            rubric=rubric, output_schema=registry.get(DUEL_SCHEMA), one=one, two=two
        ),
        output_schema=registry.get(DUEL_SCHEMA),
        model=model,
        effort=effort,
        cwd=cwd,
        sandbox="read-only",
        step_id=step_id,
    )
    result = invoke_validated(
        runner, call, registry=registry, extra_validator=_pointed_when_decided
    )
    if result.status != "COMPLETED":
        raise JudgeFailed(
            f"{step_id}: the judge call failed ({result.reason_code}): "
            f"{result.detail or 'no detail'}"
        )
    return result.output


def duel(
    runner: Any,
    *,
    rubric: str,
    incumbent: Candidate,
    challenger: Candidate,
    judges: int,
    registry: Any,
    cwd: Path,
    model: str,
    effort: str,
    duel_index: int,
) -> tuple[str, list[dict[str, Any]]]:
    """One duel: the full panel, sides swapped per judge, unanimity or nothing.

    Judge order alternates which candidate is shown first, so a position
    bias cannot decide a panel by itself. The mapping back to
    incumbent/challenger happens here, after the verdict — the judge never
    holds those words.
    """
    verdicts: list[dict[str, Any]] = []
    mapped: list[str] = []
    for index in range(judges):
        swapped = index % 2 == 1
        first, second = (
            (challenger, incumbent) if swapped else (incumbent, challenger)
        )
        verdict = judge_once(
            runner,
            rubric=rubric,
            one=first.text,
            two=second.text,
            registry=registry,
            cwd=cwd,
            model=model,
            effort=effort,
            step_id=f"duel-{duel_index:03d}-judge-{index + 1}",
        )
        winner = verdict.get("winner")
        if winner == "one":
            mapped.append("challenger" if swapped else "incumbent")
        elif winner == "two":
            mapped.append("incumbent" if swapped else "challenger")
        else:
            mapped.append("none")
        verdicts.append(verdict)
    if mapped and all(side == "challenger" for side in mapped):
        return "challenger", verdicts
    if mapped and all(side == "incumbent" for side in mapped):
        return "incumbent", verdicts
    return "no_difference", verdicts


# --------------------------------------------------------------------------
# The tournament
# --------------------------------------------------------------------------


def run_tournament(
    candidates: Sequence[Candidate],
    *,
    rubric_text: str,
    out: Path,
    judges: int,
    runner: Any = None,
    registry: Any = None,
    model: str = "",
    effort: str = "",
    cwd: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """King of the hill over the candidate list, every duel on disk.

    The incumbent starts as the first candidate and is replaced only by a
    unanimous panel. Input order therefore matters exactly when candidates
    are indistinguishable — that is the retention rule doing its job, not an
    accident, and the report says so in its non-claims.
    """
    registry = registry if registry is not None else default_registry()
    if out.exists() and any(out.iterdir()):
        raise EvolveError(f"refusing to overwrite a non-empty directory at {out}")
    (out / "duels").mkdir(parents=True, exist_ok=True)

    non_claims = [
        "A tournament finds the best of what was entered, not an optimum: a "
        "better candidate that was never generated is invisible to it.",
        "Judges were blind to lineage, authorship and incumbency, but not to "
        "their own model family's prior; a rubric judged by the family that "
        "wrote the candidates caps the search at that family's taste.",
        "King-of-the-hill ordering: a tie keeps the incumbent by design, so "
        "input order matters exactly when candidates are indistinguishable.",
    ]

    duels: list[dict[str, Any]] = []
    champion = candidates[0]
    if dry_run:
        judges = 0
        non_claims.insert(
            0,
            "Dry run: no judge was called, so nothing was compared. The "
            "champion is the first candidate by input order, which is an "
            "ordering, not a judgment.",
        )
    else:
        if runner is None or not model:
            raise EvolveError("a live tournament needs a runner and a bound model")
        for index, challenger in enumerate(candidates[1:], start=1):
            outcome, verdicts = duel(
                runner,
                rubric=rubric_text,
                incumbent=champion,
                challenger=challenger,
                judges=judges,
                registry=registry,
                cwd=cwd or out,
                model=model,
                effort=effort,
                duel_index=index,
            )
            verdict_files = []
            for judge_index, verdict in enumerate(verdicts, start=1):
                name = f"duels/duel-{index:03d}-judge-{judge_index}.json"
                (out / name).write_text(
                    json.dumps(verdict, indent=2) + "\n", encoding="utf-8"
                )
                verdict_files.append(name)
            duels.append(
                {
                    "incumbent": champion.candidate_id,
                    "challenger": challenger.candidate_id,
                    "outcome": outcome,
                    "verdict_files": verdict_files,
                }
            )
            if outcome == "challenger":
                champion = challenger

    report = {
        "schema_version": "workflows.tournament-report.v1",
        "rubric_digest": rubric_digest(rubric_text),
        "dry_run": dry_run,
        "judges": judges,
        "candidates": [c.candidate_id for c in candidates],
        "champion": champion.candidate_id,
        "duels": duels,
        "non_claims": non_claims,
    }
    errors = check_document(report, REPORT_SCHEMA, registry=registry)
    if errors:
        raise EvolveError(
            "the tournament report does not validate:\n"
            + "\n".join(f"  {e}" for e in errors[:20])
        )
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


# --------------------------------------------------------------------------
# Rule induction
# --------------------------------------------------------------------------


def induce(
    runner: Any,
    *,
    rubric_text: str,
    chosen: str,
    over: str,
    out_file: Path,
    registry: Any = None,
    model: str = "",
    effort: str = "",
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Turn an override into a proposed law.

    There is deliberately no dry mode: a stub rule looks exactly like a
    proposal, and a proposal the owner might ratify must never be a stub.
    """
    registry = registry if registry is not None else default_registry()
    call = RunnerCall(
        prompt=prompts.induction(
            rubric=rubric_text,
            output_schema=registry.get(AMENDMENT_SCHEMA),
            chosen=chosen,
            over=over,
        ),
        output_schema=registry.get(AMENDMENT_SCHEMA),
        model=model,
        effort=effort,
        cwd=cwd or out_file.parent,
        sandbox="read-only",
        step_id="induce",
    )
    result = invoke_validated(runner, call, registry=registry)
    if result.status != "COMPLETED":
        raise JudgeFailed(
            f"the induction call failed ({result.reason_code}): "
            f"{result.detail or 'no detail'}"
        )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result.output, indent=2) + "\n", encoding="utf-8")
    return result.output


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _profile_for(args: argparse.Namespace, *, live: bool) -> Any:
    from workflows.flows.base import Profile

    profile = Profile.from_toml(args.profile) if args.profile else Profile()
    if live and not profile.resolved:
        raise EvolveError(
            "a live run needs a deployment profile: the built-in bindings are "
            "role names, not models. Pass --profile <file.toml> "
            "(see examples/profile.example.toml), or add --dry-run."
        )
    return profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.evolve", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("tournament", help="rank candidates by blind pairwise duels")
    t.add_argument("candidates", nargs="+", type=Path)
    t.add_argument("--rubric", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--judges", type=int, default=3)
    t.add_argument("--profile", type=Path, default=None)
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--json", action="store_true")

    i = sub.add_parser(
        "induce",
        help="turn a human override into a proposed rubric amendment (no dry mode)",
    )
    i.add_argument("--rubric", type=Path, required=True)
    i.add_argument("--chosen", type=Path, required=True)
    i.add_argument("--over", type=Path, required=True)
    i.add_argument("--out", type=Path, required=True)
    i.add_argument("--profile", type=Path, default=None)
    i.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        from workflows.flows.base import FlowError

        registry = default_registry()
        if args.command == "tournament":
            if args.judges < 1:
                raise EvolveError("a panel needs at least one judge")
            rubric_text = load_rubric(args.rubric)
            candidates = load_candidates(args.candidates)
            runner = model = effort = None
            if not args.dry_run:
                from workflows.runners.codex import CodexRunner

                profile = _profile_for(args, live=True)
                model, effort = profile.resolve(JUDGE_ROLE)
                runner = CodexRunner(registry=registry)
            report = run_tournament(
                candidates,
                rubric_text=rubric_text,
                out=args.out,
                judges=args.judges,
                runner=runner,
                registry=registry,
                model=model or "",
                effort=effort or "",
                cwd=args.candidates[0].parent,
                dry_run=bool(args.dry_run),
            )
            print(json.dumps(report, indent=2) if args.json else _summarize(report))
            print(f"  report: {args.out / 'report.json'}")
            return EXIT_OK

        from workflows.runners.codex import CodexRunner

        rubric_text = load_rubric(args.rubric)
        profile = _profile_for(args, live=True)
        model, effort = profile.resolve(JUDGE_ROLE)
        amendment = induce(
            CodexRunner(registry=registry),
            rubric_text=rubric_text,
            chosen=args.chosen.read_text(encoding="utf-8-sig"),
            over=args.over.read_text(encoding="utf-8-sig"),
            out_file=args.out,
            registry=registry,
            model=model,
            effort=effort,
        )
        if args.json:
            print(json.dumps(amendment, indent=2))
        else:
            print("proposed rule (nothing is ratified until you edit the rubric):")
            print(f"  {amendment['rule']}")
            for conflict in amendment.get("conflicts", []):
                print(f"  fights with: {conflict}")
        print(f"  proposal: {args.out}")
        return EXIT_OK
    except JudgeFailed as exc:
        print(f"the run did not conclude: {exc}", file=sys.stderr)
        return EXIT_FAILED
    except (EvolveError, FlowError, SchemaError, OSError, ValueError) as exc:
        print(f"cannot run evolve: {exc}", file=sys.stderr)
        return EXIT_USAGE


def _summarize(report: dict[str, Any]) -> str:
    lines = [
        f"tournament over {len(report['candidates'])} candidate(s), "
        f"{report['judges']} judge(s) per duel"
    ]
    for entry in report["duels"]:
        lines.append(
            f"  {entry['incumbent']:<24} vs {entry['challenger']:<24} "
            f"-> {entry['outcome']}"
        )
    lines.append(f"  champion: {report['champion']}")
    for claim in report["non_claims"]:
        lines.append(f"  not claimed: {claim}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
