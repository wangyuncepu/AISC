"""Unit tests for container commands — status, stop, restart, shell, switch, ps.

Tests use FakeDockerExecutor to avoid real Docker calls.
Also tests state file parsing/writing for flag keys only (DO_RUN, PROXY_ENABLED).
Container discovery now goes through container registry (containers.json).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from aisc.adapters.docker_ import FakeDockerExecutor
from aisc.adapters.state_file import (
    read_state_key,
    write_state_keys,
)
from aisc.adapters.container_registry import (
    register as registry_register,
    unregister as registry_unregister,
    list_containers,
    resolve_target,
)
from aisc.cli.commands.container import (
    cmd_status,
    cmd_stop,
    cmd_restart,
    cmd_shell,
    cmd_switch,
    cmd_ps,
    discover_container,
    StatusResult,
    PsRow,
    _classify_process_error,
)
from aisc.cli.commands.run import run_container, RunResult
from aisc.domain.models import CliError, ProcessResult, RunPlan, ImageInspectStatus
from aisc.domain.models import DockerPreflightResult, ImageInspectResult


# ---------------------------------------------------------------------------
# State file tests — flag keys only (DO_RUN, PROXY_ENABLED)
# CONTAINER_NAME / IMAGE removed; they live in containers.json now.
# ---------------------------------------------------------------------------

class TestStateFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.aisc_dir = self.tmpdir / ".aisc"
        self.state_path = self.aisc_dir / "state.env"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_state(self, content: str) -> None:
        self.aisc_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(content)

    def test_read_key_simple(self):
        self._write_state("DO_RUN=1\n")
        val = read_state_key(self.tmpdir, "DO_RUN")
        self.assertEqual(val, "1")

    def test_read_key_with_comments(self):
        self._write_state(
            "# AISC state\n"
            "DO_RUN=0\n"
            "# comment\n"
            "PROXY_ENABLED=1\n"
        )
        self.assertEqual(read_state_key(self.tmpdir, "DO_RUN"), "0")
        self.assertEqual(read_state_key(self.tmpdir, "PROXY_ENABLED"), "1")

    def test_read_duplicate_key_last_wins(self):
        self._write_state(
            "DO_RUN=1\n"
            "DO_RUN=0\n"
        )
        self.assertEqual(read_state_key(self.tmpdir, "DO_RUN"), "0")

    def test_read_missing_key_returns_none(self):
        self._write_state("DO_RUN=1\n")
        self.assertIsNone(read_state_key(self.tmpdir, "PROXY_ENABLED"))

    def test_read_missing_file(self):
        self.assertIsNone(read_state_key(self.tmpdir, "DO_RUN"))

    def test_write_state_keys_simple(self):
        self._write_state(
            "# state header\n"
        )
        write_state_keys(self.tmpdir, {"DO_RUN": "1", "PROXY_ENABLED": "0"})
        self.assertEqual(read_state_key(self.tmpdir, "DO_RUN"), "1")
        self.assertEqual(read_state_key(self.tmpdir, "PROXY_ENABLED"), "0")

    def test_write_state_updates_existing_key(self):
        self._write_state("DO_RUN=0\nPROXY_ENABLED=0\n")
        write_state_keys(self.tmpdir, {"DO_RUN": "1"})
        self.assertEqual(read_state_key(self.tmpdir, "DO_RUN"), "1")
        self.assertEqual(read_state_key(self.tmpdir, "PROXY_ENABLED"), "0")

    def test_write_state_unknown_key_raises(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"UNKNOWN_KEY": "val"})
        self.assertIn("UNKNOWN_KEY", str(ctx.exception))

    def test_write_state_container_name_rejected(self):
        """CONTAINER_NAME is no longer in _KNOWN_KEYS."""
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"CONTAINER_NAME": "test"})
        self.assertIn("CONTAINER_NAME", str(ctx.exception))

    def test_write_state_workspace_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"WORKSPACE": "/some/path"})
        self.assertIn("WORKSPACE", str(ctx.exception))

    def test_write_state_creates_directory(self):
        self.assertFalse(self.aisc_dir.exists())
        write_state_keys(self.tmpdir, {"DO_RUN": "1"})
        self.assertTrue(self.aisc_dir.exists())

    # --- boolean flag validation ---

    def test_do_run_valid_0(self):
        write_state_keys(self.tmpdir, {"DO_RUN": "0"})
        self.assertEqual(read_state_key(self.tmpdir, "DO_RUN"), "0")

    def test_do_run_valid_1(self):
        write_state_keys(self.tmpdir, {"DO_RUN": "1"})
        self.assertEqual(read_state_key(self.tmpdir, "DO_RUN"), "1")

    def test_do_run_invalid_2(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"DO_RUN": "2"})
        self.assertIn("DO_RUN", str(ctx.exception))

    def test_proxy_enabled_invalid(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"PROXY_ENABLED": "yes"})
        self.assertIn("PROXY_ENABLED", str(ctx.exception))

    # --- newline / CR / NUL rejection ---

    def test_write_state_rejects_newline_in_value(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"DO_RUN": "1\ninjected"})
        self.assertIn("prohibited", str(ctx.exception).lower())

    def test_write_state_rejects_carriage_return_in_value(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"DO_RUN": "1\rCR"})
        self.assertIn("prohibited", str(ctx.exception).lower())

    def test_write_state_rejects_nul_in_value(self):
        with self.assertRaises(ValueError):
            write_state_keys(self.tmpdir, {"DO_RUN": "1\0bad"})

    def test_malformed_key_treated_as_comment(self):
        self._write_state(
            "# header\n"
            "GOOD_KEY=good_value\n"
            "bad line without equals\n"
            "0INVALID_START=val\n"
        )
        self.assertEqual(read_state_key(self.tmpdir, "GOOD_KEY"), "good_value")
        self.assertIsNone(read_state_key(self.tmpdir, "0INVALID_START"))
        write_state_keys(self.tmpdir, {"DO_RUN": "1"})
        content = self.state_path.read_text()
        self.assertIn("bad line without equals", content)
        self.assertIn("DO_RUN=1", content)
        self.assertIn("GOOD_KEY=good_value", content)

    def test_write_state_with_empty_values(self):
        self._write_state("DO_RUN=1\n")
        write_state_keys(self.tmpdir, {"DO_RUN": "", "PROXY_ENABLED": ""})
        self.assertEqual(read_state_key(self.tmpdir, "DO_RUN"), "1")
        self.assertIsNone(read_state_key(self.tmpdir, "PROXY_ENABLED"))


# ---------------------------------------------------------------------------
# Helpers for registry-based tests
# ---------------------------------------------------------------------------

def _write_containers_json(tmpdir: Path, name: str) -> None:
    """Register a container so resolve_target can find it."""
    data = {
        "default": name,
        "containers": {
            name: {
                "image": "super-claude:latest",
                "workspace": str(tmpdir),
                "network": "direct",
                "label": "",
                "created_at": 1721480000.0,
            }
        }
    }
    aisc_dir = tmpdir / ".aisc"
    aisc_dir.mkdir(parents=True, exist_ok=True)
    (aisc_dir / "containers.json").write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# Container discovery tests — now via registry
# ---------------------------------------------------------------------------

class TestContainerDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.executor = FakeDockerExecutor()
        # Default inspect returns "running" so GC doesn't prune
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test\ttrue\trunning\tsuper-claude:latest\tabc\n",
            stderr="", exit_code=0,
        ))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_name_override_wins(self):
        name = discover_container(name_override="my-special-container",
                                  executor=self.executor)
        self.assertEqual(name, "my-special-container")

    def test_no_name_no_root_no_registry_raises(self):
        with self.assertRaises(CliError) as ctx:
            discover_container(explicit_root="/nonexistent/path",
                               executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_CONTAINER_NOT_FOUND")

    def test_resolves_from_registry_default(self):
        _write_containers_json(self.tmpdir, "test-container")
        name = discover_container(explicit_root=str(self.tmpdir),
                                  executor=self.executor)
        self.assertEqual(name, "test-container")

    def test_resolves_from_registry_single(self):
        # Single container even without default set
        data = {
            "default": "",
            "containers": {
                "only-one": {
                    "image": "img", "workspace": "/ws",
                    "network": "direct", "label": "", "created_at": 1.0,
                }
            }
        }
        aisc_dir = self.tmpdir / ".aisc"
        aisc_dir.mkdir(parents=True, exist_ok=True)
        (aisc_dir / "containers.json").write_text(json.dumps(data))
        name = discover_container(explicit_root=str(self.tmpdir),
                                  executor=self.executor)
        self.assertEqual(name, "only-one")

    def test_label_override(self):
        data = {
            "default": "",
            "containers": {
                "a": {"label": "app", "image": "i", "workspace": "/w",
                      "network": "d", "created_at": 1.0},
                "b": {"label": "db", "image": "i", "workspace": "/w",
                      "network": "d", "created_at": 2.0},
            }
        }
        aisc_dir = self.tmpdir / ".aisc"
        aisc_dir.mkdir(parents=True, exist_ok=True)
        (aisc_dir / "containers.json").write_text(json.dumps(data))
        name = discover_container(explicit_root=str(self.tmpdir),
                                  executor=self.executor,
                                  label_override="app")
        self.assertEqual(name, "a")

    def test_multiple_no_hint_raises(self):
        data = {
            "default": "",
            "containers": {
                "a": {"label": "", "image": "i", "workspace": "/w",
                      "network": "d", "created_at": 1.0},
                "b": {"label": "", "image": "i", "workspace": "/w",
                      "network": "d", "created_at": 1.0},
            }
        }
        aisc_dir = self.tmpdir / ".aisc"
        aisc_dir.mkdir(parents=True, exist_ok=True)
        (aisc_dir / "containers.json").write_text(json.dumps(data))
        with self.assertRaises(CliError) as ctx:
            discover_container(explicit_root=str(self.tmpdir),
                               executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_MULTIPLE_CONTAINERS")


# ---------------------------------------------------------------------------
# Status command tests
# ---------------------------------------------------------------------------

class TestStatusCommand(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.executor = FakeDockerExecutor()
        _write_containers_json(self.tmpdir, "test-container")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_status_running_container(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\ttrue\trunning\tsuper-claude:latest\tabc123def456\n",
            stderr="", exit_code=0,
        ))
        result = cmd_status(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertTrue(result.exists)
        self.assertTrue(result.running)
        self.assertEqual(result.status, "running")
        self.assertEqual(result.image, "super-claude:latest")
        self.assertEqual(result.container_id, "abc123def456")

    def test_status_stopped_container(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\tfalse\texited\tsuper-claude:latest\tabc123\n",
            stderr="", exit_code=0,
        ))
        result = cmd_status(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertTrue(result.exists)
        self.assertFalse(result.running)
        self.assertEqual(result.status, "exited")

    def test_status_missing_container(self):
        # GC prunes known entry first, then resolve discovers nothing
        self.executor.set_captured("inspect", ProcessResult(
            stdout="", stderr="Error: No such object: test-container\n",
            exit_code=1,
        ))
        with self.assertRaises(CliError) as ctx:
            cmd_status(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_CONTAINER_NOT_FOUND")

    def test_status_permission_denied(self):
        # First resolve_target GC call succeeds (container exists)
        # Second real status call fails with permission denied
        self.executor.set_captured("inspect", ProcessResult(
            stdout="", stderr="permission denied\n", exit_code=1,
        ))
        with self.assertRaises(CliError) as ctx:
            cmd_status(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_PERMISSION_DENIED")

    def test_status_daemon_unreachable(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="", stderr="Cannot connect to the Docker daemon\n", exit_code=1,
        ))
        with self.assertRaises(CliError) as ctx:
            cmd_status(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_DOCKER_UNAVAILABLE")

    def test_status_name_override_ignores_registry(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/override-container\ttrue\trunning\timg:v1\tid123\n",
            stderr="", exit_code=0,
        ))
        result = cmd_status(name_override="override-container",
                            explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(result.name, "override-container")

    def test_status_to_dict(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/c\ttrue\trunning\timg\tid\n", stderr="", exit_code=0,
        ))
        result = cmd_status(name_override="c", executor=self.executor)
        d = result.to_dict()
        self.assertEqual(d["name"], "c")
        self.assertTrue(d["exists"])
        self.assertTrue(d["running"])


# ---------------------------------------------------------------------------
# Stop command tests
# ---------------------------------------------------------------------------

class TestStopCommand(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.executor = FakeDockerExecutor()
        _write_containers_json(self.tmpdir, "test-container")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stop_running_container(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))
        self.executor.set_captured("stop", ProcessResult(
            stdout="test-container\n", stderr="", exit_code=0,
        ))
        data = cmd_stop(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertTrue(data["stopped"])
        self.assertFalse(data.get("already_stopped", False))
        stop_calls = [c for c in self.executor.calls if c[0] == "stop"]
        self.assertEqual(len(stop_calls), 1)
        self.assertEqual(stop_calls[0], ["stop", "test-container"])

    def test_stop_already_stopped(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\tfalse\texited\timg\tid\n",
            stderr="", exit_code=0,
        ))
        data = cmd_stop(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertTrue(data["already_stopped"])
        self.assertFalse(data.get("stopped", True))
        stop_calls = [c for c in self.executor.calls if c[0] == "stop"]
        self.assertEqual(len(stop_calls), 0)

    def test_stop_missing_container(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="", stderr="No such object\n", exit_code=1,
        ))
        with self.assertRaises(CliError) as ctx:
            cmd_stop(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_CONTAINER_NOT_FOUND")

    def test_stop_failure(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))
        self.executor.set_captured("stop", ProcessResult(
            stdout="", stderr="some error\n", exit_code=1,
        ))
        with self.assertRaises(CliError):
            cmd_stop(explicit_root=str(self.tmpdir), executor=self.executor)


# ---------------------------------------------------------------------------
# Restart command tests
# ---------------------------------------------------------------------------

class TestRestartCommand(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.executor = FakeDockerExecutor()
        _write_containers_json(self.tmpdir, "test-container")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_restart_success(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\tfalse\texited\timg\tid\n",
            stderr="", exit_code=0,
        ))
        self.executor.set_captured("restart", ProcessResult(
            stdout="test-container\n", stderr="", exit_code=0,
        ))
        data = cmd_restart(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertTrue(data["restarted"])
        restart_calls = [c for c in self.executor.calls if c[0] == "restart"]
        self.assertEqual(len(restart_calls), 1)
        self.assertEqual(restart_calls[0], ["restart", "test-container"])

    def test_restart_missing_container(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="", stderr="No such object\n", exit_code=1,
        ))
        with self.assertRaises(CliError) as ctx:
            cmd_restart(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_CONTAINER_NOT_FOUND")

    def test_restart_failure(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\tfalse\texited\timg\tid\n",
            stderr="", exit_code=0,
        ))
        self.executor.set_captured("restart", ProcessResult(
            stdout="", stderr="error\n", exit_code=1,
        ))
        with self.assertRaises(CliError):
            cmd_restart(explicit_root=str(self.tmpdir), executor=self.executor)


# ---------------------------------------------------------------------------
# Shell command tests
# ---------------------------------------------------------------------------

class TestShellCommand(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.executor = FakeDockerExecutor()
        _write_containers_json(self.tmpdir, "test-container")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_shell_streaming_args(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))
        self.executor.set_streaming_exit(0)
        proc = cmd_shell(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(proc.exit_code, 0)
        self.assertEqual(len(self.executor.streaming_calls), 1)
        self.assertEqual(self.executor.streaming_calls[0],
                         ["exec", "-it", "test-container", "bash"])

    def test_shell_stopped_container(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\tfalse\texited\timg\tid\n",
            stderr="", exit_code=0,
        ))
        with self.assertRaises(CliError) as ctx:
            cmd_shell(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertIn("not running", ctx.exception.message.lower())

    def test_shell_missing_container(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="", stderr="No such object\n", exit_code=1,
        ))
        with self.assertRaises(CliError) as ctx:
            cmd_shell(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_CONTAINER_NOT_FOUND")

    def test_shell_command_not_found(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))
        self.executor.set_streaming_exit(-1)
        with self.assertRaises(CliError) as ctx:
            cmd_shell(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_DOCKER_UNAVAILABLE")


# ---------------------------------------------------------------------------
# Switch command tests
# ---------------------------------------------------------------------------

class TestSwitchCommand(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.executor = FakeDockerExecutor()
        _write_containers_json(self.tmpdir, "test-container")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_switch_streaming_args(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))
        self.executor.set_streaming_exit(0)
        proc = cmd_switch(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(proc.exit_code, 0)
        self.assertEqual(len(self.executor.streaming_calls), 1)
        argv = self.executor.streaming_calls[0]
        self.assertEqual(argv[0], "exec")
        self.assertEqual(argv[1], "-it")
        self.assertEqual(argv[2], "test-container")
        self.assertEqual(argv[3], "bash")
        self.assertEqual(argv[4], "-c")
        self.assertIn("CLAUDE_CONFIG_DIR", argv[5])
        self.assertIn("CC_CONFIG_DIR", argv[5])
        self.assertIn('exec "$@"', argv[5])
        self.assertNotIn("eval", argv[5])
        self.assertEqual(argv[6], "aisc-scope")
        self.assertEqual(argv[7], "/proc/1/environ")
        self.assertEqual(argv[8], "--")
        self.assertEqual(argv[9], "cc-switch")
        self.assertNotIn("cc-switch", argv[5])
        self.assertEqual(len(argv), 10)

    def test_quick_switch_streaming_args(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))
        self.executor.set_streaming_exit(0)
        proc = cmd_switch(explicit_root=str(self.tmpdir), executor=self.executor,
                          quick="deepseek")
        self.assertEqual(proc.exit_code, 0)
        self.assertEqual(len(self.executor.streaming_calls), 1)
        argv = self.executor.streaming_calls[0]
        self.assertEqual(argv[0], "exec")
        self.assertEqual(argv[1], "-it")
        self.assertEqual(argv[2], "test-container")
        self.assertEqual(argv[3], "bash")
        self.assertEqual(argv[4], "-c")
        self.assertIn("CLAUDE_CONFIG_DIR", argv[5])
        self.assertIn("CC_CONFIG_DIR", argv[5])
        self.assertNotIn("eval", argv[5])
        self.assertEqual(argv[6], "aisc-scope")
        self.assertEqual(argv[7], "/proc/1/environ")
        self.assertEqual(argv[8], "--")
        self.assertEqual(argv[9], "cs")
        self.assertEqual(argv[10], "deepseek")
        self.assertNotIn("deepseek", argv[5])
        self.assertEqual(len(argv), 11)

    def test_quick_switch_invalid_provider(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))
        with self.assertRaises(CliError) as ctx:
            cmd_switch(explicit_root=str(self.tmpdir), executor=self.executor,
                       quick="")
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_USAGE")

    def test_switch_missing_container(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="", stderr="No such object\n", exit_code=1,
        ))
        with self.assertRaises(CliError) as ctx:
            cmd_switch(explicit_root=str(self.tmpdir), executor=self.executor,
                       quick="deepseek")
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_CONTAINER_NOT_FOUND")

    def test_switch_stopped_container(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\tfalse\texited\timg\tid\n",
            stderr="", exit_code=0,
        ))
        with self.assertRaises(CliError):
            cmd_switch(explicit_root=str(self.tmpdir), executor=self.executor)

    def test_switch_command_not_found(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\ttrue\trunning\timg\tid\n",
            stderr="", exit_code=0,
        ))
        self.executor.set_streaming_exit(-1)
        with self.assertRaises(CliError) as ctx:
            cmd_switch(explicit_root=str(self.tmpdir), executor=self.executor,
                       quick="deepseek")
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_DOCKER_UNAVAILABLE")

    def test_scope_wrapper_fail_closed_contract(self):
        """Wrapper must exit 101 when source is unreadable or vars absent."""
        import subprocess
        from aisc.cli.commands.container import _SCOPE_WRAPPER
        proc = subprocess.run(
            ["bash", "-c", _SCOPE_WRAPPER, "aisc-scope",
             "/nonexistent/proc-environ", "--", "echo", "should-not-run"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 101,
                         f"Expected exit 101, got {proc.returncode}")
        self.assertIn("Cannot read scope environment", proc.stderr)
        self.assertNotIn("should-not-run", proc.stdout)

    def test_scope_wrapper_passes_when_vars_set(self):
        """Wrapper must succeed and exec the target when vars are set."""
        import subprocess, tempfile
        from aisc.cli.commands.container import _SCOPE_WRAPPER
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".env")
        try:
            tmp.write(b"CLAUDE_CONFIG_DIR=/test/claude\0CC_CONFIG_DIR=/test/cc\0")
            tmp.close()
            proc = subprocess.run(
                ["bash", "-c", _SCOPE_WRAPPER, "aisc-scope",
                 tmp.name, "--", "echo", "scope-ok"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0,
                             f"Expected exit 0, got {proc.returncode}: {proc.stderr}")
            self.assertIn("scope-ok", proc.stdout)
        finally:
            os.unlink(tmp.name)

    def test_scope_wrapper_missing_one_var(self):
        """Wrapper must exit 101 when only one of the two vars is present."""
        import subprocess, tempfile
        from aisc.cli.commands.container import _SCOPE_WRAPPER
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".env")
        try:
            tmp.write(b"CLAUDE_CONFIG_DIR=/only-one\0")
            tmp.close()
            proc = subprocess.run(
                ["bash", "-c", _SCOPE_WRAPPER, "aisc-scope",
                 tmp.name, "--", "echo", "nope"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 101)
        finally:
            os.unlink(tmp.name)

    def test_scope_wrapper_preserves_special_chars(self):
        """Wrapper must preserve literal spaces, $, ;, quotes, backticks."""
        import subprocess, tempfile
        from aisc.cli.commands.container import _SCOPE_WRAPPER
        special = (
            "/path with spaces/and\\$dollar;semi'quote\""
            ";backtick`star*"
        )
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".env")
        try:
            tmp.write(
                b"CLAUDE_CONFIG_DIR=" + special.encode() +
                b"\0CC_CONFIG_DIR=/cc\0"
            )
            tmp.close()
            proc = subprocess.run(
                ["bash", "-c", _SCOPE_WRAPPER, "aisc-scope",
                 tmp.name, "--", "printenv", "CLAUDE_CONFIG_DIR"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0,
                             f"Exit {proc.returncode}: {proc.stderr}")
            self.assertEqual(proc.stdout.strip(), special,
                             f"Special chars not preserved: {proc.stdout.strip()!r} != {special!r}")
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Ps command tests
# ---------------------------------------------------------------------------

class TestPsCommand(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.executor = FakeDockerExecutor()
        _write_containers_json(self.tmpdir, "test-container")
        # Add a second entry
        data = json.loads((self.tmpdir / ".aisc" / "containers.json").read_text())
        data["containers"]["second"] = {
            "image": "alpine:latest", "workspace": "/ws2",
            "network": "direct", "label": "db", "created_at": 1721480100.0,
        }
        (self.tmpdir / ".aisc" / "containers.json").write_text(json.dumps(data))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ps_lists_all(self):
        self.executor.set_captured("inspect", ProcessResult(
            stdout="/test-container\ttrue\trunning\tsuper-claude:latest\n",
            stderr="", exit_code=0,
        ))
        rows = cmd_ps(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertEqual(len(rows), 2)
        names = {r.name for r in rows}
        self.assertIn("test-container", names)
        self.assertIn("second", names)

    def test_ps_gc_prunes_dead(self):
        # First inspect returns not-found → GC prunes it
        calls = []
        def _captured(argv, timeout=None):
            calls.append(argv)
            if "second" in argv:
                return ProcessResult(stdout="", stderr="No such object: second\n", exit_code=1)
            return ProcessResult(
                stdout="/test-container\ttrue\trunning\timg\n",
                stderr="", exit_code=0,
            )
        exec_ = FakeDockerExecutor()
        exec_.run_captured = _captured  # type: ignore
        rows = cmd_ps(explicit_root=str(self.tmpdir), executor=exec_)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, "test-container")


# ---------------------------------------------------------------------------
# Process error classification tests
# ---------------------------------------------------------------------------

class TestClassifyProcessError(unittest.TestCase):
    def test_command_not_found(self):
        proc = ProcessResult(stdout="", stderr="", exit_code=-1, command_not_found=True)
        err = _classify_process_error(proc, "c", "action")
        self.assertEqual(err.error_code, "AISC_ERR_DOCKER_UNAVAILABLE")
        self.assertEqual(err.exit_code, 3)

    def test_timed_out(self):
        proc = ProcessResult(stdout="", stderr="", exit_code=-1, timed_out=True)
        err = _classify_process_error(proc, "c", "action")
        self.assertEqual(err.error_code, "AISC_ERR_GENERAL")
        self.assertEqual(err.exit_code, 1)

    def test_permission_denied(self):
        proc = ProcessResult(stdout="", stderr="Permission Denied", exit_code=1)
        err = _classify_process_error(proc, "c", "action")
        self.assertEqual(err.error_code, "AISC_ERR_PERMISSION_DENIED")
        self.assertEqual(err.exit_code, 9)

    def test_daemon_unreachable(self):
        proc = ProcessResult(stdout="", stderr="Cannot connect to the Docker daemon", exit_code=1)
        err = _classify_process_error(proc, "c", "action")
        self.assertEqual(err.error_code, "AISC_ERR_DOCKER_UNAVAILABLE")
        self.assertEqual(err.exit_code, 3)

    def test_generic_failure(self):
        proc = ProcessResult(stdout="", stderr="unknown error", exit_code=1)
        err = _classify_process_error(proc, "c", "action")
        self.assertEqual(err.error_code, "AISC_ERR_GENERAL")
        self.assertEqual(err.exit_code, 1)


# ---------------------------------------------------------------------------
# StatusResult tests
# ---------------------------------------------------------------------------

class TestStatusResult(unittest.TestCase):
    def test_to_dict_fields(self):
        sr = StatusResult(
            name="c", exists=True, running=True, status="running",
            image="img:v1", container_id="abc123",
        )
        d = sr.to_dict()
        self.assertEqual(d["name"], "c")
        self.assertTrue(d["exists"])
        self.assertTrue(d["running"])

    def test_missing_container_dict(self):
        sr = StatusResult(name="c", exists=False)
        d = sr.to_dict()
        self.assertEqual(d["name"], "c")
        self.assertFalse(d["exists"])
        self.assertFalse(d["running"])


# ---------------------------------------------------------------------------
# Run state-write failure test
# ---------------------------------------------------------------------------

class _FakeRunExecutor(FakeDockerExecutor):
    """Executor that passes preflight/inspect but tracks calls."""

    def __init__(self):
        super().__init__()
        self._preflight_result = DockerPreflightResult(
            docker_path="docker", available=True, reason="ok",
        )
        self._default_inspect = ImageInspectResult(
            status=ImageInspectStatus.EXISTS, image="",
        )


class TestRunStateWrite(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_plan(self):
        ws = self.tmpdir / "workspace"
        ws.mkdir()
        return RunPlan(
            image="alpine:latest",
            workspace=str(ws),
            name="test-run-xxxx",
            network="direct",
            dry_run=False,
            interactive=False,
            label="",
        )

    def test_registry_write_failure_raises_clierror_no_docker_calls(self):
        """Registry write failure must raise CliError before any docker run."""
        executor = _FakeRunExecutor()
        plan = self._make_plan()

        # Make .aisc a file (not dir) to cause write failure
        aisc_block = self.tmpdir / ".aisc"
        aisc_block.write_text("x")

        with self.assertRaises(CliError) as ctx:
            run_container(plan, executor=executor, capture=True,
                          aisc_root=self.tmpdir)

        self.assertEqual(ctx.exception.error_code, "AISC_ERR_STATE_WRITE_FAILED")
