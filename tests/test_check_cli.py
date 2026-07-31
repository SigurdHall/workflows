"""The validator CLI: exit codes are the contract other repositories depend on."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests import support
from workflows import check


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = check.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def fixture_data(name: str) -> object:
    return json.loads((support.FIXTURE_ROOT / name).read_text(encoding="utf-8"))["data"]


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name: str, payload: object) -> Path:
        path = self.tmp / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_valid_document_exits_zero(self) -> None:
        path = self.write("envelope.json", fixture_data("m1/valid/envelope-review.json"))
        code, out, _ = run("envelope.schema.json", str(path))
        self.assertEqual(code, check.EXIT_OK)
        self.assertIn("ok", out)

    def test_schema_violation_exits_one_and_names_the_keyword(self) -> None:
        path = self.write(
            "bad.json", fixture_data("m1/invalid/envelope-empty-non-claims.json")
        )
        code, out, _ = run("envelope.schema.json", str(path))
        self.assertEqual(code, check.EXIT_VIOLATIONS)
        self.assertIn("minItems", out)
        self.assertIn("/non_claims", out)

    def test_semantic_violation_exits_one(self) -> None:
        path = self.write(
            "verdict.json", fixture_data("m1/invalid/verdict-pass-with-open-high.json")
        )
        code, out, _ = run("verdict.schema.json", str(path))
        self.assertEqual(code, check.EXIT_VIOLATIONS)
        self.assertIn("semantic:pass_with_open_blocking_finding", out)

    def test_toml_plan_is_parsed_and_validated(self) -> None:
        plan = support.REPO_ROOT / "examples" / "plan.example.toml"
        code, out, _ = run("plan.schema.json", str(plan))
        self.assertEqual(code, check.EXIT_OK, out)

    def test_invalid_toml_plan_reports_the_semantic_rule(self) -> None:
        source = (support.REPO_ROOT / "examples" / "plan.example.toml").read_text(
            encoding="utf-8"
        )
        broken = source.replace('write_scope = ["src/report/**"]', 'write_scope = ["src/parser/lex.py"]')
        path = self.tmp / "broken-plan.toml"
        path.write_text(broken, encoding="utf-8")
        code, out, _ = run("plan.schema.json", str(path))
        self.assertEqual(code, check.EXIT_VIOLATIONS)
        self.assertIn("semantic:overlapping_write_scope", out)

    def test_sub_schema_reference_is_accepted(self) -> None:
        path = self.write("finding.json", fixture_data("core/valid/finding-minimal.json"))
        code, _, _ = run("core.defs.schema.json#/$defs/finding", str(path))
        self.assertEqual(code, check.EXIT_OK)

    def test_schema_given_as_a_path(self) -> None:
        schema = support.CONTRACTS_DIR / "envelope.schema.json"
        path = self.write("envelope.json", fixture_data("m1/valid/envelope-review.json"))
        code, _, _ = run(str(schema), str(path))
        self.assertEqual(code, check.EXIT_OK)

    def test_unknown_schema_exits_two_and_lists_known_schemas(self) -> None:
        path = self.write("x.json", {})
        code, _, err = run("no-such.schema.json", str(path))
        self.assertEqual(code, check.EXIT_USAGE)
        self.assertIn("envelope.schema.json", err)

    def test_missing_file_exits_two(self) -> None:
        code, _, err = run("envelope.schema.json", str(self.tmp / "absent.json"))
        self.assertEqual(code, check.EXIT_USAGE)
        self.assertIn("cannot read", err)

    def test_unparseable_json_exits_two(self) -> None:
        path = self.tmp / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        code, _, err = run("envelope.schema.json", str(path))
        self.assertEqual(code, check.EXIT_USAGE)
        self.assertIn("cannot parse", err)

    def test_unparseable_toml_exits_two(self) -> None:
        path = self.tmp / "broken.toml"
        path.write_text("this is = = not toml", encoding="utf-8")
        code, _, err = run("plan.schema.json", str(path))
        self.assertEqual(code, check.EXIT_USAGE)
        self.assertIn("cannot parse", err)

    def test_one_bad_file_among_several_fails_the_run(self) -> None:
        good = self.write("good.json", fixture_data("m1/valid/envelope-review.json"))
        bad = self.write("bad.json", fixture_data("m1/invalid/envelope-unknown-field.json"))
        code, _, _ = run("envelope.schema.json", str(good), str(bad))
        self.assertEqual(code, check.EXIT_VIOLATIONS)

    def test_json_output_is_machine_readable(self) -> None:
        path = self.write(
            "bad.json", fixture_data("m1/invalid/envelope-empty-non-claims.json")
        )
        code, out, _ = run("envelope.schema.json", str(path), "--json")
        self.assertEqual(code, check.EXIT_VIOLATIONS)
        payload = json.loads(out)
        self.assertEqual(payload["errors"][0]["keyword"], "minItems")

    def test_quiet_reports_nothing_but_still_fails(self) -> None:
        path = self.write(
            "bad.json", fixture_data("m1/invalid/envelope-empty-non-claims.json")
        )
        code, out, _ = run("envelope.schema.json", str(path), "--quiet")
        self.assertEqual(code, check.EXIT_VIOLATIONS)
        self.assertEqual(out, "")

    def test_schema_dir_override(self) -> None:
        path = self.write("envelope.json", fixture_data("m1/valid/envelope-review.json"))
        code, _, _ = run(
            "envelope.schema.json", str(path), "--schema-dir", str(support.CONTRACTS_DIR)
        )
        self.assertEqual(code, check.EXIT_OK)

    def test_unsound_schema_directory_exits_two(self) -> None:
        (self.tmp / "broken.schema.json").write_text(
            json.dumps({"$id": "broken.schema.json", "type": "object", "oneOf": []}),
            encoding="utf-8",
        )
        path = self.write("doc.json", {})
        code, _, err = run("broken.schema.json", str(path), "--schema-dir", str(self.tmp))
        self.assertEqual(code, check.EXIT_USAGE)
        self.assertIn("oneOf", err)


if __name__ == "__main__":
    unittest.main()
