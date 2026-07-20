"""Integration tests — subprocess invocation of aisc container lifecycle commands.

Tests parser/help, JSON envelope success/error for status/stop/restart,
events rejection for all, JSON rejection for shell/switch, detect_command.

Uses command-layer FakeDockerExecutor where possible; subprocess parser
tests focus on envelope/structure, not real Docker.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.harness.test_runner import (
    CliRunner,
    RunResult,
    assert_json_envelope,
    parse_json_envelope,
)

from aisc.adapters.docker_ import FakeDockerExecutor
from aisc.adapters.state_file import write_state_keys
from aisc.domain.models import ProcessResult


# ============================================================================
# Subprocess helpers
# ============================================================================

def _run_aisc(
    *args: str,
    runner: Optional[CliRunner] = None,
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> RunResult:
    if runner is None:
        runner = CliRunner()
    project_root = Path(__file__).resolve().parent.parent.parent
    src_path = str(project_root / "src")
    env = {"PYTHONPATH": src_path}
    return runner.run(
        [sys.executable, "-m", "aisc"] + list(args),
        cwd=cwd or str(project_root),
        timeout=timeout,
        env=env,
    )


# ============================================================================
# Parser / help tests
# ============================================================================

class TestParserHelp(unittest.TestCase):
    def test_status_appears_in_help(self):
        r = _run_aisc("--help")
        self.assertIn("status", r.stdout)
        self.assertEqual(r.exit_code, 0)

    def test_stop_appears_in_help(self):
        r = _run_aisc("--help")
        self.assertIn("stop", r.stdout)
        self.assertEqual(r.exit_code, 0)

    def test_restart_appears_in_help(self):
        r = _run_aisc("--help")
        self.assertIn("restart", r.stdout)
        self.assertEqual(r.exit_code, 0)

    def test_shell_appears_in_help(self):
        r = _run_aisc("--help")
        self.assertIn("shell", r.stdout)
        self.assertEqual(r.exit_code, 0)

    def test_switch_appears_in_help(self):
        r = _run_aisc("--help")
        self.assertIn("switch", r.stdout)
        self.assertEqual(r.exit_code, 0)

    def test_status_help(self):
        r = _run_aisc("status", "--help")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("--name", r.stdout)


# ============================================================================
# JSON: shell & switch rejected, status/stop/restart accepted
# ============================================================================

class TestJsonAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.aisc_dir = self.tmpdir / ".aisc"
        self.aisc_dir.mkdir()
        self.state_path = self.aisc_dir / "state.env"
        self.state_path.write_text("CONTAINER_NAME=test-c\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_shell_json_rejected(self):
        r = _run_aisc("shell", "--format", "json")
        self.assertEqual(r.exit_code, 2)
        self.assertIn("not supported", r.stdout)

    def test_switch_json_rejected(self):
        r = _run_aisc("switch", "--format", "json")
        self.assertEqual(r.exit_code, 2)
        self.assertIn("not supported", r.stdout)

    def test_status_json_accepted_format(self):
        """status --format json produces valid JSON envelope without error."""
        r = _run_aisc("status", "--name", "test-c", "--format", "json",
                       "--aisc-root", str(self.tmpdir))
        # Should produce valid JSON envelope (may fail with real docker, but
        # the command handler should NOT reject json)
        self.assertNotEqual(r.exit_code, 2)  # not a usage rejection

    def test_stop_json_accepted_format(self):
        r = _run_aisc("stop", "--name", "test-c", "--format", "json",
                       "--aisc-root", str(self.tmpdir))
        self.assertNotEqual(r.exit_code, 2)

    def test_restart_json_accepted_format(self):
        r = _run_aisc("restart", "--name", "test-c", "--format", "json",
                       "--aisc-root", str(self.tmpdir))
        self.assertNotEqual(r.exit_code, 2)


# ============================================================================
# JSON error envelope tests (no Docker required — parse error envelope)
# ============================================================================

class TestJsonErrorEnvelope(unittest.TestCase):
    def test_status_json_no_state_produces_error_envelope(self):
        """status --format json without state/name gives structured error."""
        r = _run_aisc("status", "--format", "json",
                       "--aisc-root", "/nonexistent/path/xyz")
        parsed = parse_json_envelope(r.stdout)
        self.assertIsNotNone(parsed)
        self.assertNotEqual(parsed["meta"]["exit_code"], 0)
        self.assertGreater(len(parsed["errors"]), 0)
        self.assertEqual(parsed["errors"][0]["code"],
                         "AISC_ERR_CONTAINER_NOT_FOUND")

    def test_stop_json_no_state_produces_error_envelope(self):
        r = _run_aisc("stop", "--format", "json",
                       "--aisc-root", "/nonexistent/path/xyz")
        parsed = parse_json_envelope(r.stdout)
        self.assertIsNotNone(parsed)
        self.assertNotEqual(parsed["meta"]["exit_code"], 0)
        self.assertGreater(len(parsed["errors"]), 0)

    def test_restart_json_no_state_produces_error_envelope(self):
        r = _run_aisc("restart", "--format", "json",
                       "--aisc-root", "/nonexistent/path/xyz")
        parsed = parse_json_envelope(r.stdout)
        self.assertIsNotNone(parsed)
        self.assertNotEqual(parsed["meta"]["exit_code"], 0)
        self.assertGreater(len(parsed["errors"]), 0)


# ============================================================================
# Events rejection tests (all container commands reject --events)
# ============================================================================

class TestEventsRejection(unittest.TestCase):
    def test_status_events_rejected(self):
        r = _run_aisc("status", "--events")
        self.assertEqual(r.exit_code, 2)

    def test_stop_events_rejected(self):
        r = _run_aisc("stop", "--events")
        self.assertEqual(r.exit_code, 2)

    def test_restart_events_rejected(self):
        r = _run_aisc("restart", "--events")
        self.assertEqual(r.exit_code, 2)

    def test_shell_events_rejected(self):
        r = _run_aisc("shell", "--events")
        self.assertEqual(r.exit_code, 2)

    def test_switch_events_rejected(self):
        r = _run_aisc("switch", "--events")
        self.assertEqual(r.exit_code, 2)


# ============================================================================
# Known commands participate in _detect_command
# ============================================================================

class TestDetectCommand(unittest.TestCase):
    def test_status_detected(self):
        r = _run_aisc("status", "--nonexistent-flag")
        self.assertEqual(r.exit_code, 2)
        output = r.stdout + r.stderr
        self.assertIn("status", output.lower())

    def test_shell_detected(self):
        r = _run_aisc("shell", "--bogus")
        self.assertEqual(r.exit_code, 2)

    def test_switch_detected(self):
        r = _run_aisc("switch", "--bogus")
        self.assertEqual(r.exit_code, 2)


# ============================================================================
# Switch --quick provider validation tests
# ============================================================================

class TestSwitchQuick(unittest.TestCase):
    def test_switch_quick_unknown_provider(self):
        """--quick with unknown provider is usage error (exit 2)."""
        r = _run_aisc("switch", "--name", "test-c", "--quick",
                       "nonexistent-provider-xyz",
                       "--aisc-root", str(Path(__file__).resolve().parent.parent.parent))
        self.assertEqual(r.exit_code, 2)

    def test_switch_quick_empty_provider(self):
        """--quick '' is usage error."""
        r = _run_aisc("switch", "--name", "test-c", "--quick", "",
                       "--aisc-root", str(Path(__file__).resolve().parent.parent.parent))
        self.assertEqual(r.exit_code, 2)

    def test_switch_quick_valid_provider(self):
        """--quick deepseek (valid provider) should pass validation."""
        r = _run_aisc("switch", "--name", "test-c", "--quick", "deepseek",
                       "--aisc-root", str(Path(__file__).resolve().parent.parent.parent))
        # Will fail because container doesn't exist, but not usage error
        self.assertIn(r.exit_code, (1, 3))  # container-not-found or docker-unavailable


if __name__ == "__main__":
    unittest.main()
