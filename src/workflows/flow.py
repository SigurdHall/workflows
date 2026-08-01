"""Run one flow against one contract.

    python -m workflows.flow implement --contract c.json --worktree . --dry-run

Every flow supports ``--dry-run``: worktrees, prompts and the run manifest
are materialized and no model is called. That is the cheap way to find out
what a plan would actually do before it does it.

Exit codes: 0 the verdict passed, 1 it did not, 2 usage or configuration
error.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from workflows import gitcmd
from workflows.flows import assure, base, fanout, implement
from workflows.flows.base import FlowContext, FlowError, Profile
from workflows.flows.ladder import Escalation
from workflows.runners.codex import CodexRunner, DryRunner
from workflows.runs import RunDirectory, utc_now
from workflows.schema import SchemaError, default_registry
from workflows.semantics import check_document

EXIT_OK = 0
EXIT_VERDICT_FAILED = 1
EXIT_USAGE = 2

RUNNABLE = {"implement": implement.run, "assure": assure.run, "fanout": fanout.run}

CONTRACT_SCHEMAS = {
    "task": "task-contract.schema.json",
    "goal": "goal-contract.schema.json",
}


def load_contract(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".toml":
        return tomllib.loads(text)
    return json.loads(text)


def contract_digest(path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _check_run_directory_is_invisible(runs: Path, worktree: Path) -> None:
    """A run must not make the worktree it is judging look dirty.

    Run artifacts are written while the flow is running, so a run directory
    inside the worktree and visible to git turns every scope and identity
    gate into a report about the run's own bookkeeping.
    """
    try:
        relative = runs.relative_to(worktree)
    except ValueError:
        return  # outside the worktree: nothing to hide
    # Ask about a path *inside* the directory: a `runs/` pattern does not
    # match the bare name until the directory exists on disk, and the first
    # run is exactly the case where it does not.
    probe = (relative / "run-id" / "manifest.json").as_posix()
    ignored = gitcmd.run(worktree, "check-ignore", "-q", "--", probe, check=False)
    if ignored.returncode != 0:
        raise FlowError(
            f"the run directory {relative.as_posix()!r} is inside the worktree "
            "and is not ignored by git, so every gate would see the run's own "
            "files as changes. Add it to .gitignore, or pass --runs outside "
            "the worktree."
        )


def _check_resume_matches(
    manifest: dict[str, Any], flow: str, digest: str, base_commit: str
) -> None:
    """A resume continues the run it says it continues.

    A contract is frozen at run start; changing it mid-run is a new run. Left
    unchecked, a resume runs gates and prompts against a different contract
    while every envelope stays stamped with the original one — an audit trail
    that lies about which contract governed the work.
    """
    recorded_digest = manifest.get("contract_ref", {}).get("digest")
    recorded_base = (manifest.get("base") or [{}])[0].get("commit")
    recorded_flow = manifest.get("flow")
    problems = []
    if recorded_flow and recorded_flow != flow:
        problems.append(f"flow {recorded_flow!r}, not {flow!r}")
    if recorded_digest and recorded_digest != digest:
        problems.append("a different contract (the digest does not match)")
    if recorded_base and recorded_base != base_commit:
        problems.append(f"base {recorded_base[:12]}, not {base_commit[:12]}")
    if problems:
        raise FlowError(
            "this run was created against " + "; ".join(problems) + ". "
            "A contract and a base are frozen at run start: continue with the "
            "originals, or start a new run id."
        )


def build_context(args: argparse.Namespace) -> FlowContext:
    registry = default_registry()
    contract = load_contract(args.contract)
    contract_type = contract.get("contract_type", "task")
    schema_ref = CONTRACT_SCHEMAS.get(contract_type)
    if schema_ref is None:
        raise FlowError(f"unknown contract_type {contract_type!r}")
    errors = check_document(contract, schema_ref, registry=registry)
    if errors:
        raise FlowError(
            "the contract does not validate:\n"
            + "\n".join(f"  {error}" for error in errors[:20])
        )

    profile = Profile.from_toml(args.profile) if args.profile else Profile()
    if not args.dry_run and not profile.resolved:
        raise FlowError(
            "a live run needs a deployment profile: the built-in bindings are "
            "role names such as 'worker-class', not models, and a provider "
            "would reject them at the first call. Pass --profile <file.toml> "
            "(see examples/profile.example.toml), or add --dry-run."
        )

    worktree = args.worktree.resolve()
    _check_run_directory_is_invisible(args.runs.resolve(), worktree)
    frozen = args.base or gitcmd.head_commit(worktree)
    run_id = args.run_id or f"run-{frozen[:12]}-{args.flow}"
    run_directory = RunDirectory(args.runs / run_id)
    if not run_directory.exists:
        run_directory.create(
            {
                "schema_version": "workflows.run-manifest.v1",
                "run_id": run_id,
                "kind": "flow",
                "flow": args.flow,
                "dry_run": bool(args.dry_run),
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "contract_ref": {
                    "contract_id": contract["contract_id"],
                    "contract_revision": contract["contract_revision"],
                    "digest": contract_digest(args.contract),
                },
                "base": [{"repo_id": args.repo_id, "commit": frozen}],
                "steps": [],
            }
        )

    manifest = run_directory.read_manifest()
    _check_resume_matches(manifest, args.flow, contract_digest(args.contract), frozen)
    return FlowContext(
        contract=contract,
        contract_ref=manifest["contract_ref"],
        worktree=worktree,
        base=frozen,
        run=run_directory,
        run_id=run_id,
        runner=DryRunner(registry=registry)
        if args.dry_run
        else CodexRunner(registry=registry, bypass_sandbox=args.dangerously_bypass_sandbox),
        profile=profile,
        escalation=Escalation(max_repair_rounds=args.max_repair_rounds),
        registry=registry,
        dry_run=bool(args.dry_run),
        work_lenses=tuple(args.work_lens),
        review_lenses=tuple(args.review_lens),
        focus_hint=args.focus_hint,
        allow_reset=not args.no_reset,
        max_parallel_workers=args.max_parallel_workers,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.flow", description=__doc__.split("\n")[0]
    )
    parser.add_argument("flow", choices=sorted(RUNNABLE))
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, default=Path("."))
    parser.add_argument("--base", default=None, help="frozen base commit (default: HEAD)")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--repo-id", default="target")
    parser.add_argument("--work-lens", action="append", default=[])
    parser.add_argument("--review-lens", action="append", default=[])
    parser.add_argument("--focus-hint", default=None)
    parser.add_argument(
        "--dangerously-bypass-sandbox",
        action="store_true",
        help=(
            "run producing roles without the provider's sandbox. Only where "
            "the sandbox refuses writes a worker legitimately needs; the scope "
            "and protected-hash gates remain the actual check"
        ),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="deployment profile binding roles to concrete models; required for a live run",
    )
    parser.add_argument("--max-repair-rounds", type=int, default=2)
    parser.add_argument(
        "--max-parallel-workers",
        type=int,
        default=1,
        help="fan-out concurrency; workers always get their own worktree",
    )
    parser.add_argument("--no-reset", action="store_true", help="never reset the worktree")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="materialize prompts, gates and the manifest; call no model",
    )
    args = parser.parse_args(argv)

    try:
        context = build_context(args)
    except (FlowError, SchemaError, OSError, ValueError) as exc:
        print(f"cannot start the flow: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        verdict = RUNNABLE[args.flow](context)
    except (FlowError, SchemaError) as exc:
        # A configuration fault mid-flow is still a configuration fault, not
        # something a user should read a traceback to understand.
        print(f"the flow could not run: {exc}", file=sys.stderr)
        return EXIT_USAGE
    errors = check_document(verdict, base.VERDICT_SCHEMA, registry=context.schemas())
    if errors:
        print("the verdict this flow produced does not validate:", file=sys.stderr)
        for error in errors[:20]:
            print(f"  {error}", file=sys.stderr)
        return EXIT_USAGE

    print(f"{verdict['flow']}: {verdict['result']}  ({context.run.root})")
    for claim in verdict["non_claims"]:
        print(f"  not claimed: {claim}")
    if verdict["result"] == "PASS":
        return EXIT_OK
    # A dry run never reports PASS, so judging it by that alone would make
    # every dry run look like a failure. INCONCLUSIVE is the success shape of
    # a dry run; FAIL and BLOCKED still are not.
    if verdict["dry_run"] and verdict["result"] == "INCONCLUSIVE":
        return EXIT_OK
    return EXIT_VERDICT_FAILED


if __name__ == "__main__":
    sys.exit(main())
