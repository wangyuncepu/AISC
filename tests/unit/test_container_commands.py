"""Unit tests for container commands — status, stop, restart, shell, switch.

Tests use FakeDockerExecutor to avoid real Docker calls.
Also tests state file parsing/writing, value safety, and run state-write failure.
"""

from __future__ import annotations

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
from aisc.cli.commands.container import (
    cmd_status,
    cmd_stop,
    cmd_restart,
    cmd_shell,
    cmd_switch,
    discover_container,
    StatusResult,
    _classify_process_error,
)
from aisc.cli.commands.run import run_container, RunResult
from aisc.domain.models import CliError, ProcessResult, RunPlan, ImageInspectStatus
from aisc.domain.models import DockerPreflightResult, ImageInspectResult


# ---------------------------------------------------------------------------
# State file tests
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
        self._write_state("CONTAINER_NAME=my-container-abc123\n")
        val = read_state_key(self.tmpdir, "CONTAINER_NAME")
        self.assertEqual(val, "my-container-abc123")

    def test_read_key_with_comments(self):
        self._write_state(
            "# AISC launcher state\n"
            "CONTAINER_NAME=my-container\n"
            "# comment\n"
            "IMAGE=super-claude:latest\n"
        )
        self.assertEqual(read_state_key(self.tmpdir, "CONTAINER_NAME"), "my-container")
        self.assertEqual(read_state_key(self.tmpdir, "IMAGE"), "super-claude:latest")

    def test_read_duplicate_key_last_wins(self):
        self._write_state(
            "CONTAINER_NAME=first\n"
            "CONTAINER_NAME=second\n"
        )
        self.assertEqual(read_state_key(self.tmpdir, "CONTAINER_NAME"), "second")

    def test_read_missing_key_returns_none(self):
        self._write_state("CONTAINER_NAME=my-container\n")
        self.assertIsNone(read_state_key(self.tmpdir, "DO_RUN"))

    def test_read_missing_file(self):
        self.assertIsNone(read_state_key(self.tmpdir, "CONTAINER_NAME"))

    def test_write_state_keys_simple(self):
        self._write_state(
            "# state header\n"
            "DO_RUN=1\n"
            "PROXY_ENABLED=0\n"
        )
        write_state_keys(self.tmpdir, {
            "CONTAINER_NAME": "test-123",
            "IMAGE": "test-img:latest",
        })
        self.assertEqual(read_state_key(self.tmpdir, "CONTAINER_NAME"), "test-123")
        self.assertEqual(read_state_key(self.tmpdir, "IMAGE"), "test-img:latest")
        self.assertEqual(read_state_key(self.tmpdir, "DO_RUN"), "1")
        self.assertEqual(read_state_key(self.tmpdir, "PROXY_ENABLED"), "0")

    def test_write_state_updates_existing_key(self):
        self._write_state("CONTAINER_NAME=old-name\nIMAGE=old-img\n")
        write_state_keys(self.tmpdir, {"CONTAINER_NAME": "new-name"})
        self.assertEqual(read_state_key(self.tmpdir, "CONTAINER_NAME"), "new-name")
        self.assertEqual(read_state_key(self.tmpdir, "IMAGE"), "old-img")

    def test_write_state_unknown_key_raises(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"UNKNOWN_KEY": "val"})
        self.assertIn("UNKNOWN_KEY", str(ctx.exception))

    def test_write_state_workspace_rejected(self):
        """WORKSPACE is intentionally excluded from _KNOWN_KEYS."""
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"WORKSPACE": "/some/path"})
        self.assertIn("WORKSPACE", str(ctx.exception))

    def test_write_state_creates_directory(self):
        self.assertFalse(self.aisc_dir.exists())
        write_state_keys(self.tmpdir, {"CONTAINER_NAME": "test"})
        self.assertTrue(self.aisc_dir.exists())

    # --- container name validation ---

    def test_container_name_valid_simple(self):
        write_state_keys(self.tmpdir, {"CONTAINER_NAME": "test"})
        self.assertEqual(read_state_key(self.tmpdir, "CONTAINER_NAME"), "test")

    def test_container_name_valid_with_dots_dashes(self):
        write_state_keys(self.tmpdir, {"CONTAINER_NAME": "super-claude-station.1"})
        self.assertEqual(read_state_key(self.tmpdir, "CONTAINER_NAME"),
                         "super-claude-station.1")

    def test_container_name_invalid_starts_with_dash(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"CONTAINER_NAME": "-bad"})
        self.assertIn("CONTAINER_NAME", str(ctx.exception))

    def test_container_name_invalid_has_space(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"CONTAINER_NAME": "bad name"})
        self.assertIn("prohibited", str(ctx.exception).lower())

    def test_container_name_invalid_shell_metachar(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"CONTAINER_NAME": "bad;rm"})
        self.assertIn("prohibited", str(ctx.exception).lower())

    def test_container_name_invalid_backtick(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"CONTAINER_NAME": "bad`cmd`"})
        self.assertIn("prohibited", str(ctx.exception).lower())

    def test_container_name_invalid_dollar(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"CONTAINER_NAME": "bad$VAR"})
        self.assertIn("prohibited", str(ctx.exception).lower())

    # --- image validation ---

    def test_image_valid_simple(self):
        write_state_keys(self.tmpdir, {"IMAGE": "alpine"})
        self.assertEqual(read_state_key(self.tmpdir, "IMAGE"), "alpine")

    def test_image_valid_with_tag(self):
        write_state_keys(self.tmpdir, {"IMAGE": "super-claude:latest"})
        self.assertEqual(read_state_key(self.tmpdir, "IMAGE"), "super-claude:latest")

    def test_image_valid_with_registry(self):
        write_state_keys(self.tmpdir, {"IMAGE": "registry.example.com/ns/img:v1"})
        self.assertEqual(read_state_key(self.tmpdir, "IMAGE"),
                         "registry.example.com/ns/img:v1")

    def test_image_valid_with_digest(self):
        write_state_keys(self.tmpdir, {"IMAGE": "img@sha256:abc123"})
        self.assertEqual(read_state_key(self.tmpdir, "IMAGE"), "img@sha256:abc123")

    def test_image_invalid_has_space(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"IMAGE": "bad image"})
        self.assertIn("prohibited", str(ctx.exception).lower())

    def test_image_invalid_semicolon(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"IMAGE": "img;cmd"})
        self.assertIn("prohibited", str(ctx.exception).lower())

    def test_image_invalid_pipe(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"IMAGE": "img|cat"})
        self.assertIn("prohibited", str(ctx.exception).lower())

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
            write_state_keys(self.tmpdir, {"CONTAINER_NAME": "safe\ninjected"})
        self.assertIn("prohibited", str(ctx.exception).lower())

    def test_write_state_rejects_carriage_return_in_value(self):
        with self.assertRaises(ValueError) as ctx:
            write_state_keys(self.tmpdir, {"IMAGE": "img\rCR"})
        self.assertIn("prohibited", str(ctx.exception).lower())

    def test_write_state_rejects_nul_in_value(self):
        with self.assertRaises(ValueError):
            write_state_keys(self.tmpdir, {"IMAGE": "img\0bad"})

    # --- existing tests preserved ---

    def test_malformed_key_treated_as_comment(self):
        self._write_state(
            "# header\n"
            "GOOD_KEY=good_value\n"
            "bad line without equals\n"
            "0INVALID_START=val\n"
        )
        self.assertEqual(read_state_key(self.tmpdir, "GOOD_KEY"), "good_value")
        self.assertIsNone(read_state_key(self.tmpdir, "0INVALID_START"))
        write_state_keys(self.tmpdir, {"CONTAINER_NAME": "test"})
        content = self.state_path.read_text()
        self.assertIn("bad line without equals", content)
        self.assertIn("CONTAINER_NAME=test", content)
        self.assertIn("GOOD_KEY=good_value", content)

    def test_write_state_with_empty_values(self):
        self._write_state("CONTAINER_NAME=existing\n")
        write_state_keys(self.tmpdir, {"CONTAINER_NAME": "", "IMAGE": ""})
        self.assertEqual(read_state_key(self.tmpdir, "CONTAINER_NAME"), "existing")
        self.assertIsNone(read_state_key(self.tmpdir, "IMAGE"))


# ---------------------------------------------------------------------------
# Container discovery tests
# ---------------------------------------------------------------------------

class TestContainerDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_name_override_wins(self):
        name = discover_container(name_override="my-special-container")
        self.assertEqual(name, "my-special-container")

    def test_no_name_no_root_no_state_raises(self):
        with self.assertRaises(CliError) as ctx:
            discover_container(explicit_root="/nonexistent/path")
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_CONTAINER_NOT_FOUND")

    def test_reads_from_state_file(self):
        aisc_dir = self.tmpdir / ".aisc"
        aisc_dir.mkdir()
        (aisc_dir / "state.env").write_text("CONTAINER_NAME=state-container-abc\n")
        name = discover_container(explicit_root=str(self.tmpdir))
        self.assertEqual(name, "state-container-abc")


# ---------------------------------------------------------------------------
# Status command tests
# ---------------------------------------------------------------------------

class TestStatusCommand(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.aisc_dir = self.tmpdir / ".aisc"
        self.aisc_dir.mkdir()
        self.state_path = self.aisc_dir / "state.env"
        self.state_path.write_text("CONTAINER_NAME=test-container\n")
        self.executor = FakeDockerExecutor()

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
        # Exact argv check
        self.assertEqual(len(self.executor.calls), 1)
        self.assertIn("inspect", self.executor.calls[0])
        self.assertIn("test-container", self.executor.calls[0])

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
        self.executor.set_captured("inspect", ProcessResult(
            stdout="", stderr="Error: No such object: test-container\n",
            exit_code=1,
        ))
        result = cmd_status(explicit_root=str(self.tmpdir), executor=self.executor)
        self.assertFalse(result.exists)
        self.assertEqual(result.name, "test-container")
        # Zero streaming calls
        self.assertEqual(len(self.executor.streaming_calls), 0)

    def test_status_permission_denied(self):
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

    def test_status_name_override_ignores_state(self):
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
        self.aisc_dir = self.tmpdir / ".aisc"
        self.aisc_dir.mkdir()
        self.state_path = self.aisc_dir / "state.env"
        self.state_path.write_text("CONTAINER_NAME=test-container\n")
        self.executor = FakeDockerExecutor()

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
        # Exact argv: stop name
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
        # No stop call when already stopped
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
        self.aisc_dir = self.tmpdir / ".aisc"
        self.aisc_dir.mkdir()
        self.state_path = self.aisc_dir / "state.env"
        self.state_path.write_text("CONTAINER_NAME=test-container\n")
        self.executor = FakeDockerExecutor()

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
        # Exact argv: restart name
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
        self.aisc_dir = self.tmpdir / ".aisc"
        self.aisc_dir.mkdir()
        self.state_path = self.aisc_dir / "state.env"
        self.state_path.write_text("CONTAINER_NAME=test-container\n")
        self.executor = FakeDockerExecutor()

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
        self.aisc_dir = self.tmpdir / ".aisc"
        self.aisc_dir.mkdir()
        self.state_path = self.aisc_dir / "state.env"
        self.state_path.write_text("CONTAINER_NAME=test-container\n")
        self.executor = FakeDockerExecutor()

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
        # Structure: exec -it NAME bash -c SCRIPT aisc-scope /proc/1/environ -- cc-switch
        self.assertEqual(argv[0], "exec")
        self.assertEqual(argv[1], "-it")
        self.assertEqual(argv[2], "test-container")
        self.assertEqual(argv[3], "bash")
        self.assertEqual(argv[4], "-c")
        # Wrapper script at index 5
        self.assertIn("CLAUDE_CONFIG_DIR", argv[5])
        self.assertIn("CC_CONFIG_DIR", argv[5])
        self.assertIn('exec "$@"', argv[5])
        self.assertNotIn("eval", argv[5])  # no eval
        # Positional guard args
        self.assertEqual(argv[6], "aisc-scope")
        self.assertEqual(argv[7], "/proc/1/environ")
        self.assertEqual(argv[8], "--")
        self.assertEqual(argv[9], "cc-switch")
        # Provider is positional, never in wrapper string
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
        # Structure: exec -it NAME bash -c SCRIPT aisc-scope /proc/1/environ -- cs deepseek
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
        # Provider is positional (argv[10]), never in wrapper string
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
        # Non-existent source file → loop body never runs → vars empty → exit 101
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
        # Build a NUL-delimited environ file
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
        )

    def test_state_write_failure_raises_clierror_no_docker_calls(self):
        """State write failure must raise CliError before any docker run."""
        executor = _FakeRunExecutor()
        plan = self._make_plan()

        # Make .aisc a file (not dir) to cause write failure
        aisc_block = self.tmpdir / ".aisc"
        aisc_block.write_text("x")

        with self.assertRaises(CliError) as ctx:
            run_container(plan, executor=executor, capture=True,
                          aisc_root=self.tmpdir)

        self.assertEqual(ctx.exception.error_code, "AISC_ERR_STATE_WRITE_FAILED")
        # result data must be structured
        self.assertIsNotNone(ctx.exception.data)
        self.assertIn("image", ctx.exception.data or {})
        # Zero docker run calls (no captured or streaming calls)
        self.assertEqual(len(executor.calls), 0)
        self.assertEqual(len(executor.streaming_calls), 0)

    def test_run_invalid_state_value_zero_docker_calls(self):
        """Invalid state value (e.g. spaces in CONTAINER_NAME) must raise before docker run."""
        executor = _FakeRunExecutor()
        plan = RunPlan(
            image="alpine:latest",
            workspace=str(self.tmpdir),
            name="bad name with spaces",
            network="direct",
            dry_run=False,
            interactive=False,
        )

        with self.assertRaises(CliError) as ctx:
            run_container(plan, executor=executor, capture=True,
                          aisc_root=self.tmpdir)

        self.assertEqual(ctx.exception.error_code, "AISC_ERR_STATE_WRITE_FAILED")
        self.assertIsNotNone(ctx.exception.data)
        # Zero docker run calls
        self.assertEqual(len(executor.calls), 0)
        self.assertEqual(len(executor.streaming_calls), 0)


if __name__ == "__main__":
    unittest.main()
