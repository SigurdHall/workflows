"""Every corpus probe must discriminate, not just fire.

A probe that always says DEFECT_PRESENT passes a seed-only check and measures
nothing. So each probe is run three ways:

* against the seed, where its defect is planted        -> PRESENT
* against a variant that fixes *its* defect            -> ABSENT
* against a variant that fixes the *other* defect      -> PRESENT

The third is what proves the probe answers about its own defect rather than
reacting to any change at all. The corrected variants live in
`tests/fixtures/corrected/<defect_id>/` and overlay the seed file by file.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflows import benchmark  # noqa: E402

CORPUS = Path(__file__).resolve().parents[1] / "examples" / "corpus" / "tier-a"
CORRECTED = Path(__file__).resolve().parent / "fixtures" / "corrected"


def defects_by_task() -> dict[str, list[dict]]:
    manifest = json.loads((CORPUS / "corpus.json").read_text(encoding="utf-8-sig"))
    return {task["task_id"]: task["defects"] for task in manifest["tasks"]}


class ProbeContractTest(unittest.TestCase):
    """The corpus declares a probe for every defect, and each one is a file."""

    def test_every_planted_defect_declares_a_probe(self) -> None:
        missing = [
            defect["defect_id"]
            for defects in defects_by_task().values()
            for defect in defects
            if not defect.get("probe_path")
        ]
        self.assertEqual(missing, [], "a defect with no probe cannot be told from a fix")

    def test_every_declared_probe_exists(self) -> None:
        for defects in defects_by_task().values():
            for defect in defects:
                path = CORPUS / defect["probe_path"]
                self.assertTrue(path.is_file(), f"{defect['defect_id']}: no {path}")

    def test_probes_stay_out_of_the_seed_trees(self) -> None:
        """A probe inside a seed would be an answer key the reviewers can read."""
        for defects in defects_by_task().values():
            for defect in defects:
                self.assertNotIn(
                    "seeds",
                    Path(defect["probe_path"]).parts,
                    f"{defect['defect_id']}: probes are inputs, not candidate content",
                )


class ProbeDiscriminationTest(unittest.TestCase):
    """Seed says present; the matching fix says absent; the other fix does not."""

    def variant(self, task_id: str, defect_id: str | None) -> Path:
        """A copy of the seed, optionally overlaid with one corrected file."""
        scratch = Path(tempfile.mkdtemp(prefix="probe-variant-"))
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        target = scratch / task_id
        shutil.copytree(CORPUS / "seeds" / task_id, target)
        if defect_id is not None:
            overlay = CORRECTED / defect_id
            self.assertTrue(overlay.is_dir(), f"no corrected variant for {defect_id}")
            for source in overlay.rglob("*"):
                if source.is_file():
                    destination = target / source.relative_to(overlay)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
        return target

    def verdict(self, defect: dict, task_directory: Path) -> str:
        state, reason = benchmark.run_probe(
            CORPUS / defect["probe_path"], task_directory
        )
        self.assertNotEqual(
            state, benchmark.INDETERMINATE, f"{defect['defect_id']}: {reason}"
        )
        return state

    def test_each_probe_reports_its_defect_present_in_the_seed(self) -> None:
        for task_id, defects in defects_by_task().items():
            seed = self.variant(task_id, None)
            for defect in defects:
                with self.subTest(defect=defect["defect_id"]):
                    self.assertEqual(
                        self.verdict(defect, seed),
                        benchmark.PRESENT,
                        "the corpus plants this defect in this seed",
                    )

    def test_each_probe_flips_when_its_own_defect_is_fixed(self) -> None:
        for task_id, defects in defects_by_task().items():
            for defect in defects:
                with self.subTest(defect=defect["defect_id"]):
                    corrected = self.variant(task_id, defect["defect_id"])
                    self.assertEqual(
                        self.verdict(defect, corrected),
                        benchmark.ABSENT,
                        "a probe that cannot see its own fix measures nothing",
                    )

    def test_a_probe_ignores_the_other_defect_being_fixed(self) -> None:
        for task_id, defects in defects_by_task().items():
            if len(defects) != 2:
                continue
            for defect, other in ((defects[0], defects[1]), (defects[1], defects[0])):
                with self.subTest(defect=defect["defect_id"], fixed=other["defect_id"]):
                    corrected = self.variant(task_id, other["defect_id"])
                    self.assertEqual(
                        self.verdict(defect, corrected),
                        benchmark.PRESENT,
                        "this probe must answer about its own defect, not any change",
                    )


class ProbeFailureModeTest(unittest.TestCase):
    """A probe that cannot decide must not be read as either answer."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "task").mkdir()

    def probe(self, body: str) -> Path:
        path = self.root / "probe.py"
        path.write_text(body, encoding="utf-8")
        return path

    def test_a_missing_probe_is_indeterminate(self) -> None:
        state, reason = benchmark.run_probe(self.root / "absent.py", self.root / "task")
        self.assertEqual(state, benchmark.INDETERMINATE)
        self.assertIn("no probe", reason)

    def test_a_crashing_probe_is_indeterminate_not_absent(self) -> None:
        state, reason = benchmark.run_probe(
            self.probe("raise SystemExit('boom')"), self.root / "task"
        )
        self.assertEqual(state, benchmark.INDETERMINATE)
        self.assertIn("boom", reason)

    def test_a_silent_probe_is_indeterminate(self) -> None:
        state, reason = benchmark.run_probe(self.probe("pass\n"), self.root / "task")
        self.assertEqual(state, benchmark.INDETERMINATE)
        self.assertIn("no verdict", reason)

    def test_a_probe_that_says_both_is_indeterminate(self) -> None:
        state, reason = benchmark.run_probe(
            self.probe("print('DEFECT_PRESENT')\nprint('DEFECT_ABSENT')\n"),
            self.root / "task",
        )
        self.assertEqual(state, benchmark.INDETERMINATE)
        self.assertIn("2 verdicts", reason)

    def test_chatter_around_a_single_verdict_is_still_a_verdict(self) -> None:
        state, _ = benchmark.run_probe(
            self.probe("print('checking')\nprint('DEFECT_ABSENT')\nprint('done')\n"),
            self.root / "task",
        )
        self.assertEqual(state, benchmark.ABSENT)

    def test_the_probe_is_handed_the_task_directory(self) -> None:
        state, _ = benchmark.run_probe(
            self.probe(
                "import sys\n"
                "print('DEFECT_PRESENT' if sys.argv[1].endswith('task') else 'DEFECT_ABSENT')\n"
            ),
            self.root / "task",
        )
        self.assertEqual(state, benchmark.PRESENT)


if __name__ == "__main__":
    unittest.main()
