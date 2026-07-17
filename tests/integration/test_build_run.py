"""Integration tests — subprocess invocation of aisc build and run commands.

Verifies text/json/events output modes, dry-run, global args positioning,
format/events conflict, error exit codes, workspace validation, legacy unchanged.
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
    assert_jsonl_protocol,
    parse_json_envelope,
    parse_jsonl,
)


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


def _parse_stdout(result: RunResult):
    try:
        return json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return None


# ============================================================================
# Build — text
# ============================================================================

class TestBuildText(unittest.TestCase):
    def test_dry_run_shows_plan(self):
        r = _run_aisc("build", "--dry-run")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("Build plan", r.stdout)

    def test_dry_run_uses_shlex_formatting(self):
        r = _run_aisc("build", "--dry-run", "--tag", "test img:v1")
        self.assertEqual(r.exit_code, 0)
        # shlex.join quotes tags with spaces
        self.assertIn("test img:v1", r.stdout)

    def test_no_cache_flag(self):
        r = _run_aisc("build", "--dry-run", "--no-cache")
        self.assertIn("--no-cache", r.stdout)

    def test_pull_flag(self):
        r = _run_aisc("build", "--dry-run", "--pull")
        self.assertIn("--pull", r.stdout)

    def test_short_tag(self):
        r = _run_aisc("build", "--dry-run", "-t", "short:v1")
        self.assertIn("short:v1", r.stdout)

    def test_auto_latest(self):
        r = _run_aisc("build", "--dry-run", "--tag", "myimg")
        self.assertIn("myimg:latest", r.stdout)

    def test_build_args_from_env(self):
        r = _run_aisc("build", "--dry-run")
        self.assertIn("USE_CN_MIRROR=1", r.stdout)
        self.assertIn("NODE_IMAGE=node:20-slim", r.stdout)


# ============================================================================
# Build — JSON
# ============================================================================

class TestBuildJson(unittest.TestCase):
    def test_dry_run_envelope(self):
        r = _run_aisc("build", "--dry-run", "--format", "json")
        data = assert_json_envelope(r)
        self.assertEqual(data["meta"]["command"], "build")
        self.assertIn("image_tag", data["data"])
        self.assertIn("docker_exit_code", data["data"])
        self.assertTrue(data["data"]["dry_run"])

    def test_data_fields_complete(self):
        r = _run_aisc("build", "--dry-run", "--format", "json")
        parsed = parse_json_envelope(r.stdout)
        d = parsed["data"]
        for field in ("image_tag", "dry_run", "executed", "docker_argv",
                       "docker_exit_code"):
            self.assertIn(field, d)

    def test_format_before_command(self):
        r = _run_aisc("--format", "json", "build", "--dry-run")
        self.assertEqual(parse_json_envelope(r.stdout)["meta"]["command"], "build")

    def test_format_after_command(self):
        r = _run_aisc("build", "--dry-run", "--format", "json")
        self.assertEqual(parse_json_envelope(r.stdout)["meta"]["command"], "build")


# ============================================================================
# Build — events
# ============================================================================

class TestBuildEvents(unittest.TestCase):
    def test_dry_run_events_protocol(self):
        r = _run_aisc("build", "--dry-run", "--events")
        lines = parse_jsonl(r.stdout)
        self.assertGreater(len(lines), 0)
        assert_jsonl_protocol(lines, expect_exit_code=0)

    def test_events_has_start_plan_terminal(self):
        r = _run_aisc("build", "--dry-run", "--events")
        lines = parse_jsonl(r.stdout)
        types = [l["type"] for l in lines if l]
        self.assertIn("build.start", types)
        self.assertIn("build.plan", types)
        last = lines[-1]["type"]
        self.assertIn(last, ("build.complete", "build.failed", "build.cancelled"))

    def test_events_terminal_is_last_and_unique(self):
        r = _run_aisc("build", "--dry-run", "--events")
        lines = parse_jsonl(r.stdout)
        terminals = [l for l in lines if l and l["type"] in
                     ("build.complete", "build.failed", "build.cancelled")]
        self.assertEqual(len(terminals), 1)
        self.assertIs(lines[-1], terminals[0])

    def test_events_seq_monotonic(self):
        r = _run_aisc("build", "--dry-run", "--events")
        lines = parse_jsonl(r.stdout)
        for i, l in enumerate(lines):
            self.assertEqual(l["seq"], i + 1)

    def test_events_with_no_cache_in_argv(self):
        r = _run_aisc("build", "--dry-run", "--no-cache", "--events")
        lines = parse_jsonl(r.stdout)
        plan_events = [l for l in lines if l and l["type"] == "build.plan"]
        if plan_events:
            argv = plan_events[0]["data"].get("docker_argv", [])
            self.assertIn("--no-cache", argv)


# ============================================================================
# Run — text
# ============================================================================

class TestRunText(unittest.TestCase):
    def test_dry_run_shows_plan(self):
        r = _run_aisc("run", "--dry-run")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("Run plan", r.stdout)

    def test_dry_run_with_image(self):
        r = _run_aisc("run", "--dry-run", "-i", "test:v2")
        self.assertIn("test:v2", r.stdout)

    def test_dry_run_with_name(self):
        r = _run_aisc("run", "--dry-run", "--name", "my-station")
        self.assertIn("my-station", r.stdout)

    def test_dry_run_network_proxy(self):
        r = _run_aisc("run", "--dry-run", "--network", "proxy")
        self.assertIn("NET_ADMIN", r.stdout)

    def test_dry_run_network_direct_no_proxy(self):
        r = _run_aisc("run", "--dry-run", "--network", "direct")
        self.assertNotIn("NET_ADMIN", r.stdout)

    def test_dry_run_text_mode_has_it(self):
        r = _run_aisc("run", "--dry-run")
        self.assertIn("-it", r.stdout)

    def test_dry_run_includes_term(self):
        r = _run_aisc("run", "--dry-run")
        self.assertIn("TERM=xterm-256color", r.stdout)


# ============================================================================
# Run — JSON
# ============================================================================

class TestRunJson(unittest.TestCase):
    def test_dry_run_envelope(self):
        r = _run_aisc("run", "--dry-run", "--format", "json")
        data = assert_json_envelope(r)
        self.assertEqual(data["meta"]["command"], "run")
        self.assertTrue(data["data"]["dry_run"])

    def test_data_fields_complete(self):
        r = _run_aisc("run", "--dry-run", "--format", "json")
        parsed = parse_json_envelope(r.stdout)
        d = parsed["data"]
        for field in ("image", "container_id", "dry_run", "executed",
                       "docker_argv", "container_exit_code"):
            self.assertIn(field, d)

    def test_json_no_it(self):
        r = _run_aisc("run", "--dry-run", "--format", "json")
        parsed = parse_json_envelope(r.stdout)
        argv = parsed["data"]["docker_argv"]
        self.assertNotIn("-it", argv)


# ============================================================================
# Run — events
# ============================================================================

class TestRunEvents(unittest.TestCase):
    def test_dry_run_events_protocol(self):
        r = _run_aisc("run", "--dry-run", "--events")
        lines = parse_jsonl(r.stdout)
        assert_jsonl_protocol(lines, expect_exit_code=0)

    def test_events_has_start_plan_terminal(self):
        r = _run_aisc("run", "--dry-run", "--events")
        lines = parse_jsonl(r.stdout)
        types = [l["type"] for l in lines if l]
        self.assertIn("run.start", types)
        self.assertIn("run.plan", types)
        self.assertIn("run.complete", types)

    def test_dry_run_no_container_events(self):
        r = _run_aisc("run", "--dry-run", "--events")
        lines = parse_jsonl(r.stdout)
        types = [l["type"] for l in lines if l]
        self.assertNotIn("run.container.start", types)

    def test_events_no_it_in_argv(self):
        r = _run_aisc("run", "--dry-run", "--events")
        lines = parse_jsonl(r.stdout)
        plan = next((l for l in lines if l and l["type"] == "run.plan"), None)
        self.assertIsNotNone(plan)
        self.assertNotIn("-it", plan["data"].get("docker_argv", []))


# ============================================================================
# Global args positioning
# ============================================================================

class TestGlobalArgs(unittest.TestCase):
    def test_events_before_build(self):
        r = _run_aisc("--events", "build", "--dry-run")
        self.assertEqual(r.exit_code, 0)
        lines = parse_jsonl(r.stdout)
        self.assertGreater(len(lines), 0)

    def test_events_after_build(self):
        r = _run_aisc("build", "--dry-run", "--events")
        self.assertEqual(r.exit_code, 0)

    def test_events_before_run(self):
        r = _run_aisc("--events", "run", "--dry-run")
        self.assertEqual(r.exit_code, 0)

    def test_format_before_run(self):
        r = _run_aisc("--format", "json", "run", "--dry-run")
        parsed = parse_json_envelope(r.stdout)
        self.assertEqual(parsed["meta"]["command"], "run")


# ============================================================================
# format / events conflict
# ============================================================================

class TestFormatEventsConflict(unittest.TestCase):
    def test_build_conflict(self):
        r = _run_aisc("build", "--dry-run", "--format", "json", "--events")
        self.assertEqual(r.exit_code, 2)

    def test_run_conflict(self):
        r = _run_aisc("run", "--dry-run", "--format", "json", "--events")
        self.assertEqual(r.exit_code, 2)

    def test_events_first_conflict(self):
        r = _run_aisc("build", "--dry-run", "--events", "--format", "json")
        self.assertEqual(r.exit_code, 2)


# ============================================================================
# Error exit codes
# ============================================================================

class TestErrorExitCodes(unittest.TestCase):
    def test_build_invalid_root(self):
        r = _run_aisc("build", "--dry-run", "--aisc-root", "/nonexistent",
                       "--format", "json")
        self.assertEqual(r.exit_code, 1)

    def test_run_invalid_workspace(self):
        r = _run_aisc("run", "--dry-run", "--workspace", "/nonexistent",
                       "--format", "json")
        self.assertEqual(r.exit_code, 9)

    def test_no_traceback(self):
        r = _run_aisc("build", "--aisc-root", "/nonexistent")
        self.assertNotIn("Traceback", r.stderr)


# ============================================================================
# Workspace with spaces / Chinese
# ============================================================================

class TestWorkspacePaths(unittest.TestCase):
    def test_workspace_with_spaces(self):
        with tempfile.TemporaryDirectory(suffix=" my dir") as td:
            r = _run_aisc("run", "--dry-run", "--workspace", td)
            self.assertEqual(r.exit_code, 0)

    def test_workspace_chinese(self):
        # Create a dir with Chinese chars if possible on the platform
        import tempfile
        try:
            td = tempfile.mkdtemp(prefix="test_项目_")
            r = _run_aisc("run", "--dry-run", "--workspace", td)
            self.assertEqual(r.exit_code, 0)
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)


# ============================================================================
# Legacy commands unchanged
# ============================================================================

class TestLegacyCommandsUnchanged(unittest.TestCase):
    def test_version_text(self):
        r = _run_aisc("version")
        self.assertEqual(r.exit_code, 0)
        self.assertIn("AISC CLI version", r.stdout)

    def test_version_json(self):
        r = _run_aisc("version", "--format", "json")
        data = assert_json_envelope(r)

    def test_doctor_text(self):
        r = _run_aisc("doctor")
        self.assertIn(r.exit_code, (0, 3, 9))

    def test_doctor_json(self):
        r = _run_aisc("doctor", "--format", "json")
        data = assert_json_envelope(r)

    def test_events_not_for_version(self):
        r = _run_aisc("version", "--events")
        self.assertEqual(r.exit_code, 2)

    def test_unknown_command(self):
        r = _run_aisc("nonexistent")
        self.assertEqual(r.exit_code, 2)


if __name__ == "__main__":
    unittest.main()
