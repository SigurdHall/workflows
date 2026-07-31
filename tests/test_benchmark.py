"""The benchmark tooling: corpus, materialization and the scorer.

The scorer is tested against a hand-computed answer key, because a scorer
nobody checked would let every later measurement inherit its error.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests import support
from workflows import benchmark, gitcmd
from workflows.semantics import check_document


def defect(defect_id: str, defect_class: int, class_name: str, location: str, severity="HIGH"):
    return {
        "defect_id": defect_id,
        "defect_class": defect_class,
        "class_name": class_name,
        "location": location,
        "severity": severity,
        "triggering_probe": "Run the probe that exercises the described edge.",
        "description": "A defect planted for the benchmark corpus.",
    }


def finding(identifier: str, location: str, lens_id: str = "review/determinism"):
    return {
        "id": identifier,
        "severity": "HIGH",
        "status": "OPEN",
        "claim": "Something is wrong here.",
        "location": location,
        "evidence_refs": ["probe-1"],
        "required_action": "Fix it.",
        "negative_path_claim": False,
        "lens_id": lens_id,
    }


class CorpusTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.registry = support.registry()

    def build_corpus(self, tasks=None) -> Path:
        """A two-task toy corpus with a hand-computed answer key."""
        tasks = tasks or [
            {
                "task_id": "measure-variance",
                "archetype": "Measure logic",
                "domain": "bi-analytics",
                "tier": "A",
                "contract_path": "contracts/measure-variance.json",
                "seed_path": "seeds/measure-variance",
                "defects": [
                    defect("D-1", 11, "Aggregation misuse", "measure-variance/src/variance.py:23"),
                    defect("D-2", 14, "Blank/zero conflation", "measure-variance/src/variance.py:31"),
                ],
            },
            {
                "task_id": "triage-router",
                "archetype": "Information triage",
                "domain": "agent-engineering",
                "tier": "A",
                "contract_path": "contracts/triage-router.json",
                "seed_path": "seeds/triage-router",
                "defects": [
                    defect("D-3", 4, "Open contract", "triage-router/src/router.py:12"),
                ],
            },
        ]
        manifest = {
            "schema_version": "workflows.defect-manifest.v1",
            "corpus_id": "toy-corpus",
            "description": "A two-task toy corpus used to test the benchmark tooling.",
            "tasks": tasks,
        }
        for task in manifest["tasks"]:
            contract = self.root / task["contract_path"]
            contract.parent.mkdir(parents=True, exist_ok=True)
            contract.write_text("{}", encoding="utf-8")
            seed = self.root / task["seed_path"] / "src"
            seed.mkdir(parents=True, exist_ok=True)
            (seed / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        path = self.root / "corpus.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return path


class LoadTest(CorpusTestCase):
    def test_a_valid_corpus_loads(self) -> None:
        corpus = benchmark.load_corpus(self.build_corpus(), registry=self.registry)
        self.assertEqual(corpus.corpus_id, "toy-corpus")
        self.assertEqual(len(corpus.tasks), 2)
        self.assertEqual(len(corpus.defects()), 3)

    def test_a_manifest_that_does_not_validate_is_refused(self) -> None:
        path = self.build_corpus()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["tasks"][0]["defects"][0].pop("triggering_probe")
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(benchmark.BenchmarkError) as ctx:
            benchmark.load_corpus(path, registry=self.registry)
        self.assertIn("does not validate", str(ctx.exception))

    def test_a_missing_seed_or_contract_is_refused(self) -> None:
        path = self.build_corpus()
        (self.root / "contracts" / "triage-router.json").unlink()
        with self.assertRaises(benchmark.BenchmarkError) as ctx:
            benchmark.load_corpus(path, registry=self.registry)
        self.assertIn("does not exist", str(ctx.exception))

    def test_duplicate_defect_ids_are_refused(self) -> None:
        path = self.build_corpus()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["tasks"][0]["defects"][1]["defect_id"] = "D-1"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(benchmark.BenchmarkError):
            benchmark.load_corpus(path, registry=self.registry)


class MaterializeTest(CorpusTestCase):
    def test_the_answer_key_never_enters_the_repository(self) -> None:
        corpus = benchmark.load_corpus(self.build_corpus(), registry=self.registry)
        target = self.root / "repo"
        commit = benchmark.materialize(corpus, target)

        self.assertEqual(len(commit), 40)
        tracked = gitcmd.files_at(target, commit)
        self.assertIn("measure-variance/src/module.py", tracked)
        self.assertIn("triage-router/src/module.py", tracked)
        self.assertFalse(
            [path for path in tracked if "corpus.json" in path],
            "a corpus a reviewer can read measures nothing",
        )

    def test_it_refuses_to_overwrite_an_existing_repository(self) -> None:
        corpus = benchmark.load_corpus(self.build_corpus(), registry=self.registry)
        target = self.root / "repo"
        benchmark.materialize(corpus, target)
        with self.assertRaises(benchmark.BenchmarkError):
            benchmark.materialize(corpus, target)


class ScorerTest(CorpusTestCase):
    """Hand-computed: 3 planted defects, and each case states its expected numbers."""

    def setUp(self) -> None:
        super().setUp()
        self.corpus = benchmark.load_corpus(self.build_corpus(), registry=self.registry)

    def test_nothing_found_scores_zero(self) -> None:
        result = benchmark.score(self.corpus, {})
        self.assertEqual((result.planted, result.detected), (3, 0))
        self.assertEqual(result.unmatched_findings, 0)

    def test_every_defect_found_scores_full_recall(self) -> None:
        result = benchmark.score(
            self.corpus,
            {
                "measure-variance": [
                    finding("F-1", "measure-variance/src/variance.py:23"),
                    finding("F-2", "measure-variance/src/variance.py:31"),
                ],
                "triage-router": [finding("F-3", "triage-router/src/router.py:12")],
            },
        )
        self.assertEqual((result.planted, result.detected), (3, 3))
        self.assertEqual(result.unmatched_findings, 0)

    def test_recall_is_reported_per_class(self) -> None:
        result = benchmark.score(
            self.corpus,
            {"triage-router": [finding("F-1", "triage-router/src/router.py:12")]},
        )
        by_class = {entry["defect_class"]: entry for entry in result.to_document()["by_class"]}
        self.assertEqual(by_class[4]["detected"], 1)
        self.assertEqual(by_class[11]["detected"], 0)
        self.assertEqual(by_class[14]["detected"], 0)
        self.assertEqual({entry["planted"] for entry in by_class.values()}, {1})
        self.assertEqual((result.planted, result.detected), (3, 1))

    def test_a_line_number_does_not_have_to_match(self) -> None:
        result = benchmark.score(
            self.corpus,
            {"triage-router": [finding("F-1", "triage-router/src/router.py:99")]},
        )
        self.assertEqual(result.detected, 1)

    def test_a_finding_matching_nothing_is_unmatched_not_wrong(self) -> None:
        result = benchmark.score(
            self.corpus,
            {"triage-router": [finding("F-1", "triage-router/src/elsewhere.py:3")]},
        )
        self.assertEqual((result.detected, result.unmatched_findings), (0, 1))

    def test_one_finding_can_cover_two_defects_in_one_file(self) -> None:
        result = benchmark.score(
            self.corpus,
            {"measure-variance": [finding("F-1", "measure-variance/src/variance.py")]},
        )
        self.assertEqual(result.detected, 2, "both defects live in that file")
        self.assertEqual(result.unmatched_findings, 0)

    def test_a_finding_without_a_location_matches_nothing(self) -> None:
        nowhere = finding("F-1", "measure-variance/src/variance.py")
        nowhere.pop("location")
        result = benchmark.score(self.corpus, {"measure-variance": [nowhere]})
        self.assertEqual((result.detected, result.unmatched_findings), (0, 1))

    def test_lens_yield_joins_findings_to_the_lens_that_raised_them(self) -> None:
        result = benchmark.score(
            self.corpus,
            {
                "measure-variance": [
                    finding("F-1", "measure-variance/src/variance.py:23", "review/determinism"),
                    finding("F-2", "measure-variance/src/nothing.py", "review/boundary-values"),
                ]
            },
        )
        yields = {entry["lens_id"]: entry for entry in result.to_document()["lens_yield"]}
        self.assertEqual(yields["review/determinism"], {"lens_id": "review/determinism", "findings": 1, "matched": 1})
        self.assertEqual(yields["review/boundary-values"]["matched"], 0)

    def test_a_finding_with_no_lens_is_attributed_to_nobody_not_dropped(self) -> None:
        anonymous = finding("F-1", "triage-router/src/router.py")
        anonymous.pop("lens_id")
        result = benchmark.score(self.corpus, {"triage-router": [anonymous]})
        yields = {entry["lens_id"]: entry for entry in result.to_document()["lens_yield"]}
        self.assertEqual(yields["unattributed"]["findings"], 1)


class ReportTest(CorpusTestCase):
    def test_the_report_validates_and_says_what_it_does_not_claim(self) -> None:
        corpus = benchmark.load_corpus(self.build_corpus(), registry=self.registry)
        cells = [
            (
                benchmark.Cell("worker-class", "medium", 1),
                benchmark.score(corpus, {}),
                {"new_input": 1000, "cached_input": 200, "output": 50},
                1234,
            ),
            (
                benchmark.Cell("worker-class", "high", 5),
                benchmark.score(
                    corpus,
                    {"measure-variance": [finding("F-1", "measure-variance/src/variance.py")]},
                ),
                {"new_input": 5000, "cached_input": 900, "output": 300},
                9876,
            ),
        ]
        document = benchmark.report(
            corpus, cells, dry_run=False, started_at="2026-07-31T15:00:00Z", registry=self.registry
        )
        errors = check_document(document, benchmark.REPORT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [])
        self.assertEqual([cell["cell_id"] for cell in document["cells"]],
                         ["worker-class-medium-w1", "worker-class-high-w5"])
        joined = " ".join(document["non_claims"])
        self.assertIn("not false positives", joined)
        self.assertIn("matched by location", joined)

    def test_a_dry_run_report_says_every_cell_scored_zero_by_construction(self) -> None:
        corpus = benchmark.load_corpus(self.build_corpus(), registry=self.registry)
        document = benchmark.report(
            corpus,
            [(benchmark.Cell("m", "low", 1), benchmark.score(corpus, {}), {"new_input": 0, "cached_input": 0, "output": 0}, 0)],
            dry_run=True,
            started_at="2026-07-31T15:00:00Z",
            registry=self.registry,
        )
        self.assertTrue(document["non_claims"][0].startswith("Dry run"))

    def test_the_summary_names_the_classes_that_escaped(self) -> None:
        corpus = benchmark.load_corpus(self.build_corpus(), registry=self.registry)
        document = benchmark.report(
            corpus,
            [(benchmark.Cell("m", "low", 1), benchmark.score(corpus, {}), {"new_input": 0, "cached_input": 0, "output": 0}, 0)],
            dry_run=False,
            started_at="2026-07-31T15:00:00Z",
            registry=self.registry,
        )
        text = benchmark.summarize(document)
        self.assertIn("Aggregation misuse", text)
        self.assertIn("0/1", text)


class MatrixTest(CorpusTestCase):
    def test_a_matrix_file_declares_cells(self) -> None:
        path = self.root / "matrix.toml"
        path.write_text(
            "\n".join(
                [
                    "[[cell]]",
                    'model = "worker-class"',
                    'effort = "medium"',
                    "worker_count = 1",
                    "",
                    "[[cell]]",
                    'model = "worker-class"',
                    'effort = "high"',
                    "worker_count = 5",
                ]
            ),
            encoding="utf-8",
        )
        cells = benchmark.load_matrix(path)
        self.assertEqual([cell.cell_id for cell in cells],
                         ["worker-class-medium-w1", "worker-class-high-w5"])

    def test_a_matrix_with_no_cells_is_refused(self) -> None:
        path = self.root / "empty.toml"
        path.write_text("# nothing here\n", encoding="utf-8")
        with self.assertRaises(benchmark.BenchmarkError):
            benchmark.load_matrix(path)


class MatrixRunTest(CorpusTestCase):
    """A dry-run matrix over a toy corpus, end to end through the program."""

    def runnable_corpus(self) -> Path:
        import sys

        path = self.build_corpus()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for task in manifest["tasks"]:
            task_id = task["task_id"]
            contract = {
                "schema_version": "workflows.task-contract.v1",
                "contract_id": f"contract-{task_id}",
                "contract_revision": 1,
                "contract_type": "task",
                "goal": f"Correct the planted defects in the {task_id} fixture without touching its tests.",
                "scope": {"allowed_paths": [f"{task_id}/src/**"]},
                "protected": [f"{task_id}/tests/**"],
                "acceptance": [
                    {"id": "AC-1", "statement": "The verification command exits zero."}
                ],
                "verification": {
                    "command": [sys.executable, "-c", "pass"],
                    "expect_exit_code": 0,
                },
            }
            (self.root / task["contract_path"]).write_text(
                json.dumps(contract, indent=2), encoding="utf-8"
            )
            tests = self.root / task["seed_path"] / "tests"
            tests.mkdir(parents=True, exist_ok=True)
            (tests / "test_module.py").write_text(
                "def test_placeholder():\n    assert True\n", encoding="utf-8"
            )
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return path

    def test_a_dry_run_matrix_scores_every_cell(self) -> None:
        corpus = benchmark.load_corpus(self.runnable_corpus(), registry=self.registry)
        cells = [
            benchmark.Cell("worker-class", "medium", 1),
            benchmark.Cell("worker-class", "high", 2),
        ]
        document = benchmark.run_matrix(
            corpus,
            cells,
            work_root=self.root / "work",
            dry_run=True,
            registry=self.registry,
        )
        errors = check_document(document, benchmark.REPORT_SCHEMA, registry=self.registry)
        self.assertEqual([str(e) for e in errors], [])
        self.assertEqual(
            [cell["cell_id"] for cell in document["cells"]],
            ["worker-class-medium-w1", "worker-class-high-w2"],
        )
        for cell in document["cells"]:
            self.assertEqual(cell["score"]["planted"], 3)
            self.assertEqual(cell["score"]["detected"], 0, "a dry run detects nothing")
        self.assertTrue(document["non_claims"][0].startswith("Dry run"))

    def test_every_cell_starts_from_the_same_frozen_commit(self) -> None:
        corpus = benchmark.load_corpus(self.runnable_corpus(), registry=self.registry)
        work = self.root / "work"
        benchmark.run_matrix(
            corpus,
            [benchmark.Cell("m", "low", 1), benchmark.Cell("m", "high", 1)],
            work_root=work,
            dry_run=True,
            registry=self.registry,
        )
        bases = set()
        for plan in sorted((work / "plans").glob("*/plan.json")):
            document = json.loads(plan.read_text(encoding="utf-8"))
            bases.add(document["base"][0]["commit"])
        self.assertEqual(len(bases), 1, "a matrix whose cells differ measures the inputs")

    def test_a_wider_cell_plans_a_fanout_with_that_many_lenses(self) -> None:
        corpus = benchmark.load_corpus(self.runnable_corpus(), registry=self.registry)
        work = self.root / "work"
        benchmark.run_matrix(
            corpus,
            [benchmark.Cell("m", "high", 3)],
            work_root=work,
            dry_run=True,
            registry=self.registry,
        )
        plan = json.loads((work / "plans" / "m-high-w3" / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual({task["flow"] for task in plan["tasks"]}, {"fanout"})
        self.assertEqual({len(task["lens_set"]) for task in plan["tasks"]}, {3})


class CliTest(CorpusTestCase):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = benchmark.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_build_materializes_and_reports_the_commit(self) -> None:
        path = self.build_corpus()
        code, out, err = self.run_cli("build", str(path), str(self.root / "repo"))
        self.assertEqual(code, benchmark.EXIT_OK, err)
        self.assertIn("toy-corpus: 2 task(s)", out)

    def test_score_reads_a_program_run_directory(self) -> None:
        path = self.build_corpus()
        run_root = self.root / "run"
        directory = run_root / "tasks" / "triage-router"
        directory.mkdir(parents=True)
        (directory / "verdict.json").write_text(
            json.dumps({"findings": [finding("F", "triage-router/src/router.py:12")]}),
            encoding="utf-8",
        )
        code, out, err = self.run_cli("score", str(path), str(run_root))
        self.assertEqual(code, benchmark.EXIT_FAILED, "two defects were missed")
        self.assertIn("1/3", out)
        self.assertIn("Aggregation misuse", out, "the escaped classes are named")

    def test_an_unreadable_corpus_is_a_usage_error(self) -> None:
        code, _, err = self.run_cli("score", str(self.root / "absent.json"), str(self.root))
        self.assertEqual(code, benchmark.EXIT_USAGE)
        self.assertIn("cannot run the benchmark", err)


if __name__ == "__main__":
    unittest.main()
