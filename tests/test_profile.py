"""Deployment profiles: the thing that makes a live run possible at all.

The built-in bindings are role names, not models. Sending "worker-class" to a
provider fails at the first call, so a live run without a profile is refused
here rather than discovered there.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import support
from workflows.flows.base import DEFAULT_BINDINGS, FlowError, Profile

PROFILE = """
[bindings.worker]
model = "worker-model"
effort = "max"

[bindings.review-1]
model = "reviewer-model"
effort = "medium"
sandbox = "read-only"
"""


class ProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, text: str, name: str = "profile.toml") -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_built_in_profile_is_unresolved(self) -> None:
        profile = Profile()
        self.assertFalse(profile.resolved)
        self.assertEqual(profile.resolve("worker"), ("worker-class", "medium"))

    def test_a_profile_binds_roles_to_models(self) -> None:
        profile = Profile.from_toml(self.write(PROFILE))
        self.assertTrue(profile.resolved)
        self.assertEqual(profile.resolve("worker"), ("worker-model", "max"))
        self.assertEqual(profile.resolve("review-1"), ("reviewer-model", "medium"))

    def test_unbound_roles_keep_their_defaults(self) -> None:
        profile = Profile.from_toml(self.write(PROFILE))
        self.assertEqual(profile.resolve("synthesis"), DEFAULT_BINDINGS["synthesis"])

    def test_a_sandbox_override_is_honoured(self) -> None:
        profile = Profile.from_toml(self.write(PROFILE))
        self.assertEqual(profile.sandbox("review-1"), "read-only")
        self.assertEqual(profile.sandbox("worker"), "workspace-write")

    def test_a_role_missing_its_model_or_effort_is_refused(self) -> None:
        for text in (
            '[bindings.worker]\nmodel = "m"\n',
            '[bindings.worker]\neffort = "max"\n',
        ):
            with self.subTest(text=text):
                with self.assertRaises(FlowError):
                    Profile.from_toml(self.write(text))

    def test_an_unknown_role_is_refused_rather_than_ignored(self) -> None:
        text = '[bindings.reviewer]\nmodel = "m"\neffort = "max"\n'
        with self.assertRaises(FlowError) as ctx:
            Profile.from_toml(self.write(text))
        self.assertIn("does not use", str(ctx.exception))

    def test_a_profile_with_no_bindings_is_refused(self) -> None:
        with self.assertRaises(FlowError):
            Profile.from_toml(self.write("# nothing here\n"))

    def test_the_shipped_example_profile_loads(self) -> None:
        path = support.REPO_ROOT / "examples" / "profile.example.toml"
        profile = Profile.from_toml(path)
        self.assertTrue(profile.resolved)
        for role in DEFAULT_BINDINGS:
            model, effort = profile.resolve(role)
            self.assertTrue(model and effort, role)


if __name__ == "__main__":
    unittest.main()
