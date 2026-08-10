"""Unit tests for session commands (Workbench Phase 0 S0.3).

Covers validate_session_id/validate_agent, the controlled argv built by
open_session/list_sessions/terminate_session (no shell=True), JSON parsing,
error-code mapping, _resolve_running_container error paths, CLI command
wiring, and the aisc.cli/v1 JSON envelope for ``aisc session``.

Docker is mocked throughout; the container-side ``aisc-session-wrapper`` is
exercised by tests/integration/docker/test_session_*.py.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from aisc.adapters.docker_ import FakeDockerExecutor
from aisc.application.session import (
    _resolve_running_container,
    list_sessions,
    open_session,
    terminate_session,
    validate_agent,
    validate_session_id,
)
from aisc.domain.models import (
    CliError,
    ProcessResult,
    RuntimeErrorCode,
    RuntimeExitCode,
    SessionAgent,
)

RT = "550e8400-e29b-41d4-a716-446655440000"
SID = "660e8400-e29b-41d4-a716-446655440000"
WRAP = "/usr/local/bin/aisc-session-wrapper"
CONTAINER = "aisc-wb-550e8400"
REG = Path("/tmp/reg-fake")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestSessionIdValidation(unittest.TestCase):
    def test_valid_uuid_v4(self):
        assert validate_session_id(SID)
        assert validate_session_id("f47ac10b-58cc-4372-a567-0e02b2c3d479")

    def test_invalid_uuid(self):
        assert not validate_session_id("not-a-uuid")
        assert not validate_session_id("550e8400-e29b-41d4-3716-446655440000")  # v3
        assert not validate_session_id("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # v1
        assert not validate_session_id("")
        # Path-traversal-like values must be rejected (contract: UUID-only segment).
        assert not validate_session_id("../../etc/passwd")


class TestAgentValidation(unittest.TestCase):
    def test_valid_agents(self):
        for agent in SessionAgent.ALL:
            assert validate_agent(agent), agent

    def test_invalid_agent(self):
        assert not validate_agent("claude --dangerous")
        assert not validate_agent("rm -rf")
        assert not validate_agent("")


# ---------------------------------------------------------------------------
# open_session
# ---------------------------------------------------------------------------

class TestOpenSession(unittest.TestCase):
    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_open_constructs_controlled_argv(self, _resolve):
        exec_ = FakeDockerExecutor()
        proc = open_session(RT, SID, "claude", exec_, REG)
        expected = [WRAP, "open",
                    "--session-id", SID, "--runtime-id", RT, "--agent", "claude"]
        assert exec_.interactive_calls[0] == (CONTAINER, expected)
        # No shell token anywhere; agent is a single controlled argv token.
        assert "claude --dangerously-skip-permissions" not in exec_.interactive_calls[0][1]
        assert proc.exit_code == 0

    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_open_each_agent_maps_to_single_token(self, _resolve):
        for agent in SessionAgent.ALL:
            exec_ = FakeDockerExecutor()
            open_session(RT, SID, agent, exec_, REG)
            argv = exec_.interactive_calls[-1][1]
            assert argv[-2] == "--agent"
            assert argv[-1] == agent

    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_open_propagates_nonzero_exit(self, _resolve):
        exec_ = FakeDockerExecutor()
        exec_.set_streaming_exit(42)
        proc = open_session(RT, SID, "bash", exec_, REG)
        assert proc.exit_code == 42

    def test_open_invalid_session_id_short_circuits(self):
        exec_ = FakeDockerExecutor()
        with self.assertRaises(CliError) as cm:
            open_session(RT, "not-a-uuid", "claude", exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.INVALID_SESSION_ID
        assert cm.exception.exit_code == RuntimeExitCode.USAGE_ERROR  # not 15 (INVALID_RUNTIME_ID)
        assert exec_.interactive_calls == []

    def test_open_invalid_agent_short_circuits(self):
        exec_ = FakeDockerExecutor()
        with self.assertRaises(CliError) as cm:
            open_session(RT, SID, "evil", exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.INVALID_AGENT
        assert exec_.interactive_calls == []

    def test_open_invalid_runtime_id_short_circuits(self):
        exec_ = FakeDockerExecutor()
        with self.assertRaises(CliError) as cm:
            open_session("not-a-uuid", SID, "claude", exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.INVALID_RUNTIME_ID
        assert exec_.interactive_calls == []


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

class TestListSessions(unittest.TestCase):
    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_list_parses_json_array(self, _resolve):
        exec_ = FakeDockerExecutor()
        rec = [{"session_id": SID, "agent": "claude", "state": "running"}]
        exec_.set_captured("list", ProcessResult(stdout=json.dumps(rec), exit_code=0))
        out = list_sessions(RT, exec_, REG)
        assert out == rec
        argv = exec_.calls[0]
        assert argv[:2] == ["exec", CONTAINER]
        assert argv[-1] == "list"
        # list is non-interactive: no -it.
        assert "-it" not in argv

    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_list_empty_stdout(self, _resolve):
        exec_ = FakeDockerExecutor()
        exec_.set_captured("list", ProcessResult(stdout="", exit_code=0))
        assert list_sessions(RT, exec_, REG) == []

    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_list_wrapper_failure(self, _resolve):
        exec_ = FakeDockerExecutor()
        exec_.set_captured("list", ProcessResult(stdout="", stderr="boom", exit_code=1))
        with self.assertRaises(CliError) as cm:
            list_sessions(RT, exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.SESSION_FAILED

    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_list_invalid_json(self, _resolve):
        exec_ = FakeDockerExecutor()
        exec_.set_captured("list", ProcessResult(stdout="not json", exit_code=0))
        with self.assertRaises(CliError) as cm:
            list_sessions(RT, exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.SESSION_FAILED

    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_list_non_array_json(self, _resolve):
        exec_ = FakeDockerExecutor()
        exec_.set_captured("list", ProcessResult(stdout='{"not": "array"}', exit_code=0))
        with self.assertRaises(CliError) as cm:
            list_sessions(RT, exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.SESSION_FAILED


# ---------------------------------------------------------------------------
# terminate_session
# ---------------------------------------------------------------------------

class TestTerminateSession(unittest.TestCase):
    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_terminate_constructs_argv(self, _resolve):
        exec_ = FakeDockerExecutor()
        term = {"session_id": SID, "state": "exited", "exit_code": 0}
        exec_.set_captured("terminate", ProcessResult(stdout=json.dumps(term), exit_code=0))
        out = terminate_session(RT, SID, exec_, REG, grace_seconds=7.5)
        assert out == term
        argv = exec_.calls[0]
        assert "terminate" in argv
        assert "--session-id" in argv and SID in argv
        assert "--runtime-id" in argv and RT in argv
        assert "--grace" in argv and "7.5" in argv
        assert "-it" not in argv  # non-interactive

    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_terminate_empty_stdout_is_exited(self, _resolve):
        exec_ = FakeDockerExecutor()
        exec_.set_captured("terminate", ProcessResult(stdout="", exit_code=0))
        out = terminate_session(RT, SID, exec_, REG)
        assert out["session_id"] == SID
        assert out["state"] == "exited"

    def test_terminate_invalid_session_id_short_circuits(self):
        exec_ = FakeDockerExecutor()
        with self.assertRaises(CliError) as cm:
            terminate_session(RT, "nope", exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.INVALID_SESSION_ID
        assert cm.exception.exit_code == RuntimeExitCode.USAGE_ERROR  # not 15 (INVALID_RUNTIME_ID)
        assert exec_.calls == []

    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_terminate_wrapper_failure(self, _resolve):
        exec_ = FakeDockerExecutor()
        exec_.set_captured("terminate", ProcessResult(stdout="", stderr="x", exit_code=1))
        with self.assertRaises(CliError) as cm:
            terminate_session(RT, SID, exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.SESSION_FAILED

    def test_terminate_invalid_runtime_id_short_circuits(self):
        exec_ = FakeDockerExecutor()
        with self.assertRaises(CliError) as cm:
            terminate_session("not-a-uuid", SID, exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.INVALID_RUNTIME_ID
        assert exec_.calls == []

    def test_terminate_rejects_non_finite_or_out_of_range_grace(self):
        exec_ = FakeDockerExecutor()
        for bad in (-1, 601, float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(CliError) as cm:
                terminate_session(RT, SID, exec_, REG, grace_seconds=bad)
            assert cm.exception.exit_code == 2
            assert cm.exception.error_code == "AISC_ERR_USAGE"
        # validation happens before any Docker call
        assert exec_.calls == []

    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_terminate_accepts_zero_grace(self, _resolve):
        exec_ = FakeDockerExecutor()
        exec_.set_captured("terminate", ProcessResult(stdout=json.dumps(
            {"session_id": SID, "state": "exited"}), exit_code=0))
        terminate_session(RT, SID, exec_, REG, grace_seconds=0)
        assert "--grace" in exec_.calls[0] and "0" in exec_.calls[0]

    @patch("aisc.application.session._resolve_running_container", return_value=CONTAINER)
    def test_terminate_timeout_follows_grace(self, _resolve):
        exec_ = Mock()
        exec_.run_captured.return_value = ProcessResult(
            stdout=json.dumps({"session_id": SID, "state": "exited"}), exit_code=0)
        terminate_session(RT, SID, exec_, REG, grace_seconds=12.0)
        exec_.run_captured.assert_called_once()
        # outer transport budget is grace + 1s (05 §4.2)
        assert exec_.run_captured.call_args.kwargs["timeout"] == 13.0


# ---------------------------------------------------------------------------
# _resolve_running_container error paths (contract §6.1 / §8)
# ---------------------------------------------------------------------------

class TestResolveRunningContainer(unittest.TestCase):
    @patch("aisc.application.runtime._get_container_state")
    @patch("aisc.application.runtime._find_docker_container_by_runtime_id")
    @patch("aisc.adapters.container_registry.find_by_runtime_id")
    @patch("aisc.application.runtime._check_docker", return_value=False)
    def test_docker_unavailable(self, _cd, _fri, _fdc, _gcs):
        with self.assertRaises(CliError) as cm:
            _resolve_running_container(RT, FakeDockerExecutor(), REG)
        assert cm.exception.error_code == RuntimeErrorCode.DOCKER_UNAVAILABLE
        assert cm.exception.exit_code == RuntimeExitCode.DOCKER_UNAVAILABLE

    @patch("aisc.application.runtime._get_container_state")
    @patch("aisc.application.runtime._find_docker_container_by_runtime_id", return_value=None)
    @patch("aisc.adapters.container_registry.find_by_runtime_id", return_value=None)
    @patch("aisc.application.runtime._check_docker", return_value=True)
    def test_runtime_not_found(self, _cd, _fri, _fdc, _gcs):
        with self.assertRaises(CliError) as cm:
            _resolve_running_container(RT, FakeDockerExecutor(), REG)
        assert cm.exception.error_code == RuntimeErrorCode.RUNTIME_NOT_FOUND

    @patch("aisc.application.runtime._get_container_state", return_value="stopped")
    @patch("aisc.application.runtime._find_docker_container_by_runtime_id")
    @patch("aisc.adapters.container_registry.find_by_runtime_id",
           return_value=(CONTAINER, {"runtime_id": RT}))
    @patch("aisc.application.runtime._check_docker", return_value=True)
    def test_runtime_not_running(self, _cd, _fri, _fdc, _gcs):
        with self.assertRaises(CliError) as cm:
            _resolve_running_container(RT, FakeDockerExecutor(), REG)
        assert cm.exception.error_code == RuntimeErrorCode.RUNTIME_NOT_RUNNING
        assert cm.exception.exit_code == RuntimeExitCode.RUNTIME_NOT_RUNNING

    @patch("aisc.application.runtime._get_container_state", return_value="running")
    @patch("aisc.application.runtime._find_docker_container_by_runtime_id")
    @patch("aisc.adapters.container_registry.find_by_runtime_id",
           return_value=(CONTAINER, {"runtime_id": RT}))
    @patch("aisc.application.runtime._check_docker", return_value=True)
    def test_happy_path_returns_container(self, _cd, _fri, _fdc, _gcs):
        assert _resolve_running_container(RT, FakeDockerExecutor(), REG) == CONTAINER

    @patch("aisc.application.runtime._get_container_state", return_value="running")
    @patch("aisc.application.runtime._find_docker_container_by_runtime_id",
           return_value={"container_name": CONTAINER, "container_id": "abc",
                         "state": "running"})
    @patch("aisc.adapters.container_registry.find_by_runtime_id", return_value=None)
    @patch("aisc.application.runtime._check_docker", return_value=True)
    def test_falls_back_to_docker_label_discovery(self, _cd, _fri, _fdc, _gcs):
        # Registry miss but Docker label finds the runtime -> still resolves.
        assert _resolve_running_container(RT, FakeDockerExecutor(), REG) == CONTAINER


# ---------------------------------------------------------------------------
# CLI command wiring
# ---------------------------------------------------------------------------

class TestCmdSessionWiring(unittest.TestCase):
    def test_cmd_session_list_wraps_result(self):
        from aisc.cli.commands.session import cmd_session_list
        with tempfile.TemporaryDirectory() as tmp:
            with patch("aisc.cli.commands.session.list_sessions",
                       return_value=[{"session_id": SID}]) as ls:
                data = cmd_session_list(RT, workspace=tmp,
                                        executor=FakeDockerExecutor())
        assert data == {"sessions": [{"session_id": SID}], "count": 1}
        ls.assert_called_once()

    def test_cmd_session_open_returns_exit_code(self):
        from aisc.cli.commands.session import cmd_session_open
        with tempfile.TemporaryDirectory() as tmp:
            with patch("aisc.cli.commands.session.open_session",
                       return_value=ProcessResult(exit_code=7)):
                data, code = cmd_session_open(RT, SID, "claude", workspace=tmp,
                                              executor=FakeDockerExecutor())
        assert code == 7
        assert data["session_id"] == SID
        assert data["exit_code"] == 7

    def test_cmd_session_open_negative_exit_becomes_1(self):
        from aisc.cli.commands.session import cmd_session_open
        with tempfile.TemporaryDirectory() as tmp:
            with patch("aisc.cli.commands.session.open_session",
                       return_value=ProcessResult(exit_code=-1, command_not_found=True)):
                data, code = cmd_session_open(RT, SID, "bash", workspace=tmp,
                                              executor=FakeDockerExecutor())
        assert code == 1
        assert data["error"] == "docker command not found"


# ---------------------------------------------------------------------------
# aisc.cli/v1 JSON envelope (contract §二.2)
# ---------------------------------------------------------------------------

class TestSessionJsonEnvelope(unittest.TestCase):
    def test_list_json_envelope(self):
        from aisc.cli.main import main
        with patch("aisc.cli.commands.session.cmd_session_list",
                   return_value={"sessions": [], "count": 0}):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as cm:
                    main(["session", "list", "--runtime-id", RT, "--format", "json"])
        assert cm.exception.code == 0
        env = json.loads(buf.getvalue())
        assert env["meta"]["protocol"] == "aisc.cli/v1"
        assert env["meta"]["command"] == "session"
        assert env["meta"]["exit_code"] == 0
        assert env["data"]["count"] == 0
        assert env["errors"] == []

    def test_terminate_json_envelope(self):
        from aisc.cli.main import main
        term = {"session_id": SID, "state": "exited", "exit_code": 0}
        with patch("aisc.cli.commands.session.cmd_session_terminate", return_value=term):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as cm:
                    main(["session", "terminate", "--runtime-id", RT,
                          "--session-id", SID, "--format", "json"])
        assert cm.exception.code == 0
        env = json.loads(buf.getvalue())
        assert env["meta"]["command"] == "session"
        assert env["data"]["session_id"] == SID

    def test_open_rejects_json_format(self):
        # contract §6.1: session open is text-only; --format json must be rejected
        # before any docker exec, so PTY data never mixes with a JSON envelope.
        from aisc.cli.main import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                main(["session", "open", "--runtime-id", RT, "--session-id", SID,
                      "--agent", "bash", "--format", "json"])
        assert cm.exception.code == 2
        env = json.loads(buf.getvalue())
        assert env["meta"]["command"] == "session"
        assert env["meta"]["exit_code"] != 0
        assert env["errors"]


if __name__ == "__main__":
    unittest.main()
