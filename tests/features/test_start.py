"""Characterization tests for ``start.sh`` — entry-point argument handling.

Only tests error paths (unknown arg, missing --workspace value, nonexistent
workspace).  Does **not** walk the full pipeline — those paths are blocked
by ensuring ``scripts/run.sh`` does not exist in the temp skeleton so that a
successful parse + validation would bail on ``exec`` failure rather than
accidentally invoke real Docker.
"""

from __future__ import annotations

import os
import unittest

from tests.features.helpers import TempProject, repo_root
from tests.harness.test_runner import CliRunner


class StartShTest(unittest.TestCase):
    """Error-path tests for the start.sh entry script."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = CliRunner()

    def setUp(self) -> None:
        # Copy start.sh into a temp project; do NOT create scripts/run.sh so
        # that if validation passes the exec will fail (safe).
        self.proj = TempProject()
        real_start = os.path.join(repo_root(), "start.sh")
        import shutil
        self._start_path = os.path.join(self.proj.tmpdir, "start.sh")
        shutil.copy2(real_start, self._start_path)

    def tearDown(self) -> None:
        self.proj.destroy()

    def _run(self, *args, **kw):
        return self.runner.run(
            ["bash", self._start_path, *args],
            cwd=self.proj.tmpdir,
            **kw,
        )

    # ------------------------------------------------------------------
    # Unknown parameter
    # ------------------------------------------------------------------

    def test_unknown_option_exits_one(self) -> None:
        result = self._run("--unknown-flag")
        self.assertEqual(result.exit_code, 1)

    def test_unknown_option_stderr_message(self) -> None:
        result = self._run("--unknown-flag")
        self.assertIn("Unknown option", result.stderr)
        self.assertIn("Usage:", result.stderr)

    # ------------------------------------------------------------------
    # Missing --workspace value
    # ------------------------------------------------------------------

    def test_workspace_missing_value_exits_one(self) -> None:
        """--workspace as last arg → $2 is empty → nonexistent dir → exit 1."""
        result = self._run("--workspace")
        self.assertEqual(result.exit_code, 1)

    def test_workspace_missing_value_error_message(self) -> None:
        """set -u causes bash to abort before validation — expect error on stderr."""
        result = self._run("--workspace")
        # The exact message is locale-dependent (bash "unbound variable" or the
        # script's own error).  Just verify *something* appeared on stderr
        # and exit code is non-zero.
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(
            len(result.stderr) > 0,
            f"expected some error on stderr, got nothing; stdout={result.stdout!r}",
        )

    # ------------------------------------------------------------------
    # Nonexistent workspace
    # ------------------------------------------------------------------

    def test_nonexistent_workspace_exits_one(self) -> None:
        result = self._run("--workspace", "/definitely/not/a/real/path")
        self.assertEqual(result.exit_code, 1)

    def test_nonexistent_workspace_error_message(self) -> None:
        result = self._run("--workspace", "/definitely/not/a/real/path")
        self.assertIn("does not exist", result.stderr.lower())

    # ------------------------------------------------------------------
    # --workspace followed by another --workspace (value overridden)
    # ------------------------------------------------------------------

    def test_workspace_then_another_flag(self) -> None:
        """``--workspace --other`` → workspace becomes '--other' → nonexistent → exit 1."""
        result = self._run("--workspace", "--other-flag")
        self.assertEqual(result.exit_code, 1)
        # The error may be "does not exist" or "Unknown option" depending on
        # parse order (first arg is consumed by --workspace, second is
        # unknown).  Either exit 1 is acceptable for this characterization.
        combined = (result.stderr + result.stdout).lower()
        self.assertTrue(
            "does not exist" in combined or "unknown option" in combined,
            f"expected error message, got: {result.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()
