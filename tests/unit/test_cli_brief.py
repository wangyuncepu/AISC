"""Unit tests for _cmd_brief — frozen vs dev mode, argv passing, exit codes.

Covers the PyInstaller frozen-mode in-process path and the dev-mode subprocess
path without requiring network or a real ``brief.py`` execution.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY

# Ensure src is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from aisc.cli.main import _cmd_brief
from aisc.domain.models import CliError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_root(td: str) -> Path:
    """Create a minimal valid AISC root with a brief.py stub."""
    root = Path(td)
    for marker in ["VERSION", "container/Dockerfile", "config/versions.env"]:
        p = root / marker
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("content")
    apps_brief = root / "apps" / "ai-brief"
    apps_brief.mkdir(parents=True)
    (apps_brief / "brief.py").write_text("def main(argv=None): return 0\n")
    return root


def _make_default_args(**overrides) -> argparse.Namespace:
    """Return an argparse.Namespace with default brief flags."""
    ns = argparse.Namespace()
    ns.aisc_root = None
    ns.date = None
    ns.source = "all"
    ns.days = 1
    ns.top = 5
    ns.ai = False
    ns.save = False
    ns.no_cache = False
    ns.strict = False
    ns.debug = False
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


# ---------------------------------------------------------------------------
# Frozen-mode tests
# ---------------------------------------------------------------------------

class TestCmdBriefFrozen(unittest.TestCase):
    """Frozen mode: ``_cmd_brief`` runs brief.py in-process, no subprocess."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _make_fake_root(self.tmpdir.name)
        self.brief_script = self.root / "apps" / "ai-brief" / "brief.py"

    def tearDown(self):
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------
    # Frozen: subprocess is NOT called
    # ------------------------------------------------------------------

    def test_frozen_does_not_spawn_subprocess(self):
        """In frozen mode, subprocess.run must NOT be called."""
        ns = _make_default_args()

        # Write a brief.py whose main() returns 0
        self.brief_script.write_text(
            "def main(argv=None):\n"
            "    import sys\n"
            "    sys.stdout.write('frozen output\\n')\n"
            "    return 0\n"
        )

        mock_subprocess_run = MagicMock()

        with patch.object(sys, "frozen", True, create=True), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root), \
             patch("subprocess.run", mock_subprocess_run):

            data, exit_code, errors = _cmd_brief(ns, "text")

        # subprocess.run must NOT be called in frozen mode
        mock_subprocess_run.assert_not_called()
        self.assertEqual(exit_code, 0)
        self.assertEqual(data["brief_exit_code"], 0)
        self.assertEqual(len(errors), 0)

    # ------------------------------------------------------------------
    # Frozen: argv passing
    # ------------------------------------------------------------------

    def test_frozen_passes_args_to_main(self):
        """Frozen mode passes command-line flags to brief.main(argv)."""
        captured_argv = None

        # Write a brief.py that captures its argv
        self.brief_script.write_text(
            "def main(argv=None):\n"
            "    import json, sys\n"
            f"    _capture_file = {repr(str(self.tmpdir.name))} + '/captured.json'\n"
            "    with open(_capture_file, 'w') as f:\n"
            "        json.dump(argv, f)\n"
            "    return 0\n"
        )

        ns = _make_default_args(source="tldr,simon", ai=True, strict=True, debug=True)

        with patch.object(sys, "frozen", True, create=True), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            data, exit_code, errors = _cmd_brief(ns, "text")

        self.assertEqual(exit_code, 0)

        # Read captured argv from the side-effect file
        import json as _json
        captured_path = Path(self.tmpdir.name) / "captured.json"
        self.assertTrue(captured_path.exists(), "brief.main was not called")
        captured_argv = _json.loads(captured_path.read_text())

        self.assertIn("--source", captured_argv)
        self.assertIn("tldr,simon", captured_argv)
        self.assertIn("--ai", captured_argv)
        self.assertIn("--strict", captured_argv)
        self.assertIn("--debug", captured_argv)

    # ------------------------------------------------------------------
    # Frozen: exit code propagation
    # ------------------------------------------------------------------

    def test_frozen_exit_code_from_main_return(self):
        """Exit code from main() return value is propagated."""
        self.brief_script.write_text("def main(argv=None): return 3\n")
        ns = _make_default_args()

        with patch.object(sys, "frozen", True, create=True), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            data, exit_code, errors = _cmd_brief(ns, "text")

        self.assertEqual(exit_code, 3)
        self.assertEqual(data["brief_exit_code"], 3)

    # ------------------------------------------------------------------
    # Frozen: SystemExit from argparse (--help, usage error)
    # ------------------------------------------------------------------

    def test_frozen_catches_system_exit_from_main(self):
        """SystemExit raised inside main() (e.g. argparse --help) is caught."""
        self.brief_script.write_text(
            "def main(argv=None):\n"
            "    raise SystemExit(2)\n"
        )
        ns = _make_default_args()

        with patch.object(sys, "frozen", True, create=True), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            data, exit_code, errors = _cmd_brief(ns, "text")

        self.assertEqual(exit_code, 2)
        self.assertEqual(data["brief_exit_code"], 2)

    def test_frozen_system_exit_none_code(self):
        """SystemExit(None) → exit_code 0."""
        self.brief_script.write_text(
            "def main(argv=None):\n"
            "    raise SystemExit(None)\n"
        )
        ns = _make_default_args()

        with patch.object(sys, "frozen", True, create=True), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            data, exit_code, errors = _cmd_brief(ns, "text")

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["brief_exit_code"], 0)

    def test_frozen_system_exit_str_code(self):
        """SystemExit('error') → exit_code 1 (non-int code)."""
        self.brief_script.write_text(
            "def main(argv=None):\n"
            "    raise SystemExit('some error')\n"
        )
        ns = _make_default_args()

        with patch.object(sys, "frozen", True, create=True), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            data, exit_code, errors = _cmd_brief(ns, "text")

        self.assertEqual(exit_code, 1)
        self.assertEqual(data["brief_exit_code"], 1)

    # ------------------------------------------------------------------
    # Frozen: spec_from_file_location failure
    # ------------------------------------------------------------------

    def test_frozen_spec_creation_failure_raises_cli_error(self):
        """When importlib.spec_from_file_location returns None, CliError raised."""
        ns = _make_default_args()

        with patch.object(sys, "frozen", True, create=True), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root), \
             patch("importlib.util.spec_from_file_location", return_value=None):

            with self.assertRaises(CliError) as ctx:
                _cmd_brief(ns, "text")
            self.assertIn("Failed to create module spec", str(ctx.exception.message))

    # ------------------------------------------------------------------
    # Frozen: output goes to real stdout (brief.py writes to sys.stdout)
    # ------------------------------------------------------------------

    def test_frozen_stdout_passthrough(self):
        """In frozen mode, brief.py stdout goes to the process stdout."""
        self.brief_script.write_text(
            "def main(argv=None):\n"
            "    print('hello from brief')\n"
            "    return 0\n"
        )
        ns = _make_default_args()

        with patch.object(sys, "frozen", True, create=True), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            data, exit_code, errors = _cmd_brief(ns, "text")

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["brief_exit_code"], 0)


# ---------------------------------------------------------------------------
# Dev-mode tests (subprocess path)
# ---------------------------------------------------------------------------

class TestCmdBriefDev(unittest.TestCase):
    """Dev / editable mode: ``_cmd_brief`` spawns subprocess (existing behaviour)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _make_fake_root(self.tmpdir.name)
        self.brief_script = self.root / "apps" / "ai-brief" / "brief.py"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_dev_spawns_subprocess_with_correct_argv(self):
        """Dev mode must call subprocess.run with sys.executable + script."""
        ns = _make_default_args()
        captured_argv = []

        def _fake_run(argv, **kwargs):
            captured_argv.extend(argv)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_fake_run), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            data, exit_code, errors = _cmd_brief(ns, "text")

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["brief_exit_code"], 0)
        # First two positional args are [sys.executable, brief.py path]
        self.assertEqual(captured_argv[0], sys.executable)
        self.assertEqual(captured_argv[1], str(self.brief_script))

    def test_dev_passes_flags_to_subprocess(self):
        """Dev mode passes --ai, --source, --date etc. to subprocess."""
        ns = _make_default_args(source="tools", ai=True, date="2025-01-01",
                                top=3)
        captured_argv = []

        def _fake_run(argv, **kwargs):
            captured_argv.extend(argv)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_fake_run), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            _cmd_brief(ns, "text")

        self.assertIn("--source", captured_argv)
        self.assertIn("tools", captured_argv)
        self.assertIn("--ai", captured_argv)
        self.assertIn("--date", captured_argv)
        self.assertIn("2025-01-01", captured_argv)
        # top=3 is non-default → passed
        self.assertIn("--top", captured_argv)
        self.assertIn("3", captured_argv)

    def test_dev_does_not_pass_default_int_flags(self):
        """Dev mode skips --days and --top when they equal defaults."""
        ns = _make_default_args()  # days=1, top=5 (defaults)
        captured_argv = []

        def _fake_run(argv, **kwargs):
            captured_argv.extend(argv)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_fake_run), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            _cmd_brief(ns, "text")

        self.assertNotIn("--days", captured_argv)
        self.assertNotIn("--top", captured_argv)

    def test_dev_subprocess_file_not_found_error(self):
        """Dev mode: FileNotFoundError from subprocess → CliError."""
        ns = _make_default_args()

        with patch("subprocess.run", side_effect=FileNotFoundError("python not found")), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            with self.assertRaises(CliError) as ctx:
                _cmd_brief(ns, "text")
            self.assertIn("Python interpreter not found", str(ctx.exception.message))

    def test_brief_script_missing_raises(self):
        """Missing brief.py raises CliError regardless of mode."""
        # Remove the brief.py
        self.brief_script.unlink()
        ns = _make_default_args()

        with patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            with self.assertRaises(CliError) as ctx:
                _cmd_brief(ns, "text")
            self.assertIn("Brief script not found", str(ctx.exception.message))

    def test_json_format_rejected_in_dev_mode(self):
        """--format json is rejected before reaching subprocess/in-process."""
        ns = _make_default_args()

        with patch("aisc.application.resources.locate_aisc_root", return_value=self.root):

            with self.assertRaises(SystemExit) as ctx:
                _cmd_brief(ns, "json")
            self.assertEqual(ctx.exception.code, 2)


# ---------------------------------------------------------------------------
# Integration-style: verify frozen does NOT use sys.executable
# ---------------------------------------------------------------------------

class TestCmdBriefFrozenNoExecutable(unittest.TestCase):
    """Frozen mode must never invoke sys.executable (recursive aisc call)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = _make_fake_root(self.tmpdir.name)
        self.brief_script = self.root / "apps" / "ai-brief" / "brief.py"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_frozen_does_not_use_sys_executable_as_interpreter(self):
        """When frozen, sys.executable is aisc itself — must NOT be used."""
        self.brief_script.write_text("def main(argv=None): return 0\n")
        ns = _make_default_args()

        mock_subprocess_run = MagicMock()

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", "/usr/local/bin/aisc"), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root), \
             patch("subprocess.run", mock_subprocess_run):

            data, exit_code, errors = _cmd_brief(ns, "text")

        # The key assertion: subprocess.run was never called
        mock_subprocess_run.assert_not_called()
        self.assertEqual(exit_code, 0)
        self.assertEqual(data["brief_exit_code"], 0)

    def test_frozen_subprocess_unavailable_but_brief_runs(self):
        """Even if Python interpreter is missing, frozen brief must work."""
        self.brief_script.write_text("def main(argv=None): return 0\n")
        ns = _make_default_args()

        # subprocess.run raises FileNotFoundError, but frozen path bypasses it
        with patch.object(sys, "frozen", True, create=True), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root), \
             patch("subprocess.run", side_effect=FileNotFoundError("no python")):

            data, exit_code, errors = _cmd_brief(ns, "text")

        # Frozen path succeeded — no exception
        self.assertEqual(exit_code, 0)

    def test_frozen_runs_brief_even_with_bogus_sys_executable(self):
        """Frozen path uses importlib, ignores sys.executable entirely."""
        self.brief_script.write_text("def main(argv=None): return 0\n")
        ns = _make_default_args()

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", "/dev/null/nonexistent"), \
             patch("aisc.application.resources.locate_aisc_root", return_value=self.root), \
             patch("subprocess.run") as mock_run:

            data, exit_code, errors = _cmd_brief(ns, "text")

        mock_run.assert_not_called()
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
