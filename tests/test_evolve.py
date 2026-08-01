"""The evolve tournament: blindness, consensus, retention, induction.

The selection step is the foundation the whole loop stands on, so its rules
are tested as rules: a split panel is a tie, a tie keeps the incumbent, a
judge is never told who is who, and a preference without pointed evidence is
rejected rather than counted.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests import support
from workflows import evolve, runners
from workflows.semantics import check_document


def verdict(winner: str, pointed=None) -> dict:
    if pointed is None:
        pointed = (
            []
            if winner == "none"
            else [
                {"candidate": "one", "where": "the summary", "why": "sharper"},
                {"candidate": "two", "where": "the summary", "why": "vaguer"},
            ]
        )
    return {
        "schema_version": "workflows.duel-verdict.v1",
        "winner": winner,
        "pointed": pointed,
        "reasons": "Decided by the first separating criterion.",
        "non_claims": ["This verdict is only as blind as the prompt it answered."],
    }


def amendment() -> dict:
    return {
        "schema_version": "workflows.rubric-amendment.v1",
        "rule": "A decision-first opening outranks density of content.",
        "rationale": "The owner's choice led with the decision.",
        "conflicts": ["K6 richness along the thread"],
        "non_claims": ["An induced rule is a proposal, not law, until ratified."],
    }


class ScriptedRunner:
    """Returns queued outputs in order, recording every prompt it saw."""

    name = "scripted"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    def invoke(self, call):
        self.prompts.append(call.prompt)
        return runners.RunnerResult(
            status="COMPLETED",
            reason_code="clean",
            output=self.outputs.pop(0),
            telemetry=runners.Telemetry(
                runner="scripted",
                model=call.model,
                effort=call.effort,
                dry=False,
                duration_ms=1,
                tokens=runners.TokenUsage(),
            ),
        )


class RefusingRunner:
    """A runner whose invocation is itself a test failure."""

    name = "refusing"

    def invoke(self, call):  # pragma: no cover - reaching this is the failure
        raise AssertionError("a dry run must not call any judge")


class EvolveTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.registry = support.registry()

    def rubric(self) -> str:
        path = self.root / "rubric.md"
        path.write_text(
            "# Rubric\n\n## Disqualifiers\n- D1 wrong numbers\n\n"
            "## Ranking\n- K1 value first\n- K2 evidence\n",
            encoding="utf-8",
        )
        return evolve.load_rubric(path)

    def candidates(self, *texts: str) -> list[evolve.Candidate]:
        result = []
        for index, text in enumerate(texts):
            result.append(evolve.Candidate(f"cand-{index}", text))
        return result

    def tournament(self, runner, candidates, judges=3):
        return evolve.run_tournament(
            candidates,
            rubric_text=self.rubric(),
            out=self.root / "run",
            judges=judges,
            runner=runner,
            registry=self.registry,
            model="m",
            effort="high",
            cwd=self.root,
        )


class RubricTest(EvolveTestCase):
    def test_an_empty_rubric_is_refused(self) -> None:
        path = self.root / "empty.md"
        path.write_text("  \n", encoding="utf-8")
        with self.assertRaises(evolve.EvolveError):
            evolve.load_rubric(path)

    def test_a_rubric_without_sections_cannot_order(self) -> None:
        path = self.root / "flat.md"
        path.write_text("# Only a title\nsome prose\n", encoding="utf-8")
        with self.assertRaises(evolve.EvolveError) as raised:
            evolve.load_rubric(path)
        self.assertIn("precedence", str(raised.exception))

    def test_the_digest_carries_its_algorithm(self) -> None:
        digest = evolve.rubric_digest("text")
        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(len(digest), 71)


class ConsensusTest(EvolveTestCase):
    """Side-swapping means the scripted winners must account for position."""

    def test_a_unanimous_panel_replaces_the_incumbent(self) -> None:
        # Judges 1 and 3 see (incumbent, challenger); judge 2 sees the swap.
        runner = ScriptedRunner([verdict("two"), verdict("one"), verdict("two")])
        report = self.tournament(runner, self.candidates("A", "B"))
        self.assertEqual(report["champion"], "cand-1")
        self.assertEqual(report["duels"][0]["outcome"], "challenger")

    def test_a_split_panel_is_a_tie_and_the_incumbent_stands(self) -> None:
        runner = ScriptedRunner([verdict("two"), verdict("two"), verdict("two")])
        # Unswapped that reads challenger, incumbent, challenger: 2-1.
        report = self.tournament(runner, self.candidates("A", "B"))
        self.assertEqual(report["champion"], "cand-0")
        self.assertEqual(report["duels"][0]["outcome"], "no_difference")

    def test_any_none_verdict_breaks_unanimity(self) -> None:
        runner = ScriptedRunner([verdict("two"), verdict("one"), verdict("none")])
        report = self.tournament(runner, self.candidates("A", "B"))
        self.assertEqual(report["champion"], "cand-0")

    def test_a_unanimous_incumbent_is_recorded_as_a_decision(self) -> None:
        runner = ScriptedRunner([verdict("one"), verdict("two"), verdict("one")])
        report = self.tournament(runner, self.candidates("A", "B"))
        self.assertEqual(report["duels"][0]["outcome"], "incumbent")

    def test_the_hill_is_walked_in_input_order(self) -> None:
        first_duel = [verdict("two"), verdict("one"), verdict("two")]  # challenger
        second_duel = [verdict("one"), verdict("two"), verdict("one")]  # incumbent
        runner = ScriptedRunner(first_duel + second_duel)
        report = self.tournament(runner, self.candidates("A", "B", "C"))
        self.assertEqual(report["champion"], "cand-1")
        self.assertEqual(
            [d["incumbent"] for d in report["duels"]], ["cand-0", "cand-1"]
        )


class BlindnessTest(EvolveTestCase):
    def test_the_prompt_has_no_channel_for_incumbency_or_identity(self) -> None:
        runner = ScriptedRunner([verdict("none")] * 3)
        self.tournament(runner, self.candidates("alpha text", "beta text"))
        for prompt in runner.prompts:
            self.assertNotIn("incumbent", prompt.lower())
            self.assertNotIn("champion", prompt.lower())
            self.assertNotIn("cand-0", prompt)
            self.assertNotIn("cand-1", prompt)

    def test_sides_are_swapped_for_the_second_judge(self) -> None:
        runner = ScriptedRunner([verdict("none")] * 3)
        self.tournament(runner, self.candidates("ALPHA", "BETA"))
        first, second = runner.prompts[0], runner.prompts[1]
        self.assertLess(first.index("ALPHA"), first.index("BETA"))
        self.assertLess(second.index("BETA"), second.index("ALPHA"))

    def test_a_preference_without_pointed_evidence_is_rejected(self) -> None:
        bare = verdict("two", pointed=[])
        runner = ScriptedRunner([bare, bare] + [verdict("none")] * 3)
        with self.assertRaises(evolve.JudgeFailed) as raised:
            self.tournament(runner, self.candidates("A", "B"))
        self.assertIn("failed", str(raised.exception))

    def test_the_bounded_retry_can_rescue_a_bare_preference(self) -> None:
        # Judge 1's first attempt points at nothing and is rejected; the
        # bounded retry answers properly, and the panel still decides.
        runner = ScriptedRunner(
            [verdict("two", pointed=[]), verdict("two")] + [verdict("one"), verdict("two")]
        )
        report = self.tournament(runner, self.candidates("A", "B"))
        self.assertEqual(report["duels"][0]["outcome"], "challenger")
        self.assertEqual(len(runner.prompts), 4, "one retry, not a fresh panel")


class ReportTest(EvolveTestCase):
    def test_the_report_validates_and_every_verdict_is_on_disk(self) -> None:
        runner = ScriptedRunner([verdict("two"), verdict("one"), verdict("two")])
        report = self.tournament(runner, self.candidates("A", "B"))
        errors = check_document(report, evolve.REPORT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [])
        for entry in report["duels"]:
            for name in entry["verdict_files"]:
                self.assertTrue((self.root / "run" / name).is_file())

    def test_a_non_empty_output_directory_is_refused(self) -> None:
        target = self.root / "run"
        target.mkdir()
        (target / "stale.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(evolve.EvolveError):
            self.tournament(ScriptedRunner([]), self.candidates("A", "B"))

    def test_duplicate_candidate_ids_are_refused(self) -> None:
        (self.root / "a").mkdir()
        (self.root / "b").mkdir()
        left = self.root / "a" / "same.md"
        right = self.root / "b" / "same.md"
        left.write_text("A", encoding="utf-8")
        right.write_text("B", encoding="utf-8")
        with self.assertRaises(evolve.EvolveError):
            evolve.load_candidates([left, right])


class DryRunTest(EvolveTestCase):
    def test_a_dry_run_calls_nobody_and_claims_nothing(self) -> None:
        report = evolve.run_tournament(
            self.candidates("A", "B", "C"),
            rubric_text=self.rubric(),
            out=self.root / "dry",
            judges=3,
            runner=RefusingRunner(),
            registry=self.registry,
            dry_run=True,
        )
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["judges"], 0)
        self.assertEqual(report["champion"], "cand-0")
        self.assertEqual(report["duels"], [])
        self.assertTrue(report["non_claims"][0].startswith("Dry run"))
        errors = check_document(report, evolve.REPORT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [])


class InductionTest(EvolveTestCase):
    def test_an_override_becomes_a_proposal_on_disk(self) -> None:
        runner = ScriptedRunner([amendment()])
        out = self.root / "amendments" / "0001.json"
        proposal = evolve.induce(
            runner,
            rubric_text=self.rubric(),
            chosen="the owner's pick",
            over="the machine's champion",
            out_file=out,
            registry=self.registry,
            model="m",
            effort="high",
        )
        self.assertIn("rule", proposal)
        written = json.loads(out.read_text(encoding="utf-8"))
        errors = check_document(written, evolve.AMENDMENT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [])
        prompt = runner.prompts[0]
        self.assertIn("the owner's pick", prompt)
        self.assertIn("ratif", prompt.lower())


class ProfileRoleTest(unittest.TestCase):
    def test_the_judge_role_exists_and_runs_read_only(self) -> None:
        from workflows.flows.base import DEFAULT_BINDINGS, Profile

        self.assertIn("judge", DEFAULT_BINDINGS)
        self.assertEqual(Profile().sandbox("judge"), "read-only")


class CliTest(EvolveTestCase):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = evolve.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_a_dry_tournament_runs_end_to_end(self) -> None:
        rubric = self.root / "rubric.md"
        rubric.write_text("# R\n\n## D\n- x\n\n## K\n- y\n", encoding="utf-8")
        a = self.root / "a.md"
        b = self.root / "b.md"
        a.write_text("candidate a", encoding="utf-8")
        b.write_text("candidate b", encoding="utf-8")
        code, out, err = self.run_cli(
            "tournament", str(a), str(b),
            "--rubric", str(rubric), "--out", str(self.root / "run"), "--dry-run",
        )
        self.assertEqual(code, evolve.EXIT_OK, err)
        self.assertIn("champion: a", out)
        self.assertTrue((self.root / "run" / "report.json").is_file())

    def test_a_live_run_without_a_profile_is_refused(self) -> None:
        rubric = self.root / "rubric.md"
        rubric.write_text("# R\n\n## D\n- x\n\n## K\n- y\n", encoding="utf-8")
        a = self.root / "a.md"
        b = self.root / "b.md"
        a.write_text("A", encoding="utf-8")
        b.write_text("B", encoding="utf-8")
        code, _, err = self.run_cli(
            "tournament", str(a), str(b),
            "--rubric", str(rubric), "--out", str(self.root / "run"),
        )
        self.assertEqual(code, evolve.EXIT_USAGE)
        self.assertIn("profile", err)

    def test_induce_offers_no_dry_mode(self) -> None:
        with self.assertRaises(SystemExit):
            with redirect_stderr(io.StringIO()):
                evolve.main(["induce", "--dry-run"])


if __name__ == "__main__":
    unittest.main()
