"""Unit tests for ``aisc provider current`` (Workbench S0.4).

Mocks Docker; the container-side inspector is covered by test_provider_inspect.py
and the E2E fixtures by tests/integration/docker/test_provider_current.py.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aisc.adapters.docker_ import FakeDockerExecutor, ProcessResult
from aisc.application.provider import current_provider
from aisc.domain.models import CliError, ProviderStatus, RuntimeErrorCode, RuntimeExitCode

RT = "550e8400-e29b-41d4-a716-446655440000"
CONTAINER = "aisc-wb-550e8400"
REG = Path("/tmp/reg-fake")
_INSPECT_CLAUDE = {"provider_id": "deepseek", "provider_name": "DeepSeek",
                   "route_mode": "cc-switch-proxy", "auth_status": "configured"}


class TestCurrentProvider(unittest.TestCase):
    @patch("aisc.application.provider.resolve_running_container", return_value=CONTAINER)
    def test_returns_status_with_runtime_id_and_observed_at(self, _rr):
        exec_ = FakeDockerExecutor()
        exec_.set_captured("aisc-provider-inspect",
                           ProcessResult(stdout=json.dumps(_INSPECT_CLAUDE), exit_code=0))
        st = current_provider(RT, "claude", exec_, REG)
        d = st.to_dict()
        assert d["runtime_id"] == RT
        assert d["agent"] == "claude"
        assert d["provider_id"] == "deepseek"
        assert d["route_mode"] == "cc-switch-proxy"
        assert d["auth_status"] == "configured"
        assert d["observed_at"]
        # argv: exec <container> <inspector> <agent>, non-interactive (no -it)
        argv = exec_.calls[0]
        assert argv[:2] == ["exec", CONTAINER]
        assert argv[-1] == "claude"
        assert "-it" not in argv

    @patch("aisc.application.provider.resolve_running_container", return_value=CONTAINER)
    def test_codex_official_login_required(self, _rr):
        exec_ = FakeDockerExecutor()
        out = {"provider_id": "codex-official", "provider_name": "OpenAI Official",
               "route_mode": "official-direct", "auth_status": "login_required"}
        exec_.set_captured("aisc-provider-inspect",
                           ProcessResult(stdout=json.dumps(out), exit_code=0))
        st = current_provider(RT, "codex", exec_, REG)
        assert st.route_mode == "official-direct"
        assert st.auth_status == "login_required"

    def test_invalid_runtime_id_short_circuits(self):
        exec_ = FakeDockerExecutor()
        with self.assertRaises(CliError) as cm:
            current_provider("not-a-uuid", "claude", exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.INVALID_RUNTIME_ID
        assert exec_.calls == []

    def test_invalid_agent_short_circuits(self):
        exec_ = FakeDockerExecutor()
        with self.assertRaises(CliError) as cm:
            current_provider(RT, "bash", exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.INVALID_AGENT
        assert exec_.calls == []

    @patch("aisc.application.provider.resolve_running_container", return_value=CONTAINER)
    def test_inspect_exec_failure(self, _rr):
        exec_ = FakeDockerExecutor()
        exec_.set_captured("aisc-provider-inspect",
                           ProcessResult(stdout="", stderr="boom", exit_code=1))
        with self.assertRaises(CliError) as cm:
            current_provider(RT, "claude", exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.PROVIDER_STATUS_FAILED
        assert cm.exception.exit_code == RuntimeExitCode.PROVIDER_STATUS_FAILED

    @patch("aisc.application.provider.resolve_running_container", return_value=CONTAINER)
    def test_inspect_bad_json(self, _rr):
        exec_ = FakeDockerExecutor()
        exec_.set_captured("aisc-provider-inspect",
                           ProcessResult(stdout="not json", exit_code=0))
        with self.assertRaises(CliError) as cm:
            current_provider(RT, "claude", exec_, REG)
        assert cm.exception.error_code == RuntimeErrorCode.PROVIDER_STATUS_FAILED


class TestCmdProviderCurrent(unittest.TestCase):
    def test_wiring_returns_dict(self):
        from aisc.cli.commands.provider import cmd_provider_current
        with tempfile.TemporaryDirectory() as tmp:
            with patch("aisc.cli.commands.provider.current_provider") as cp:
                cp.return_value = ProviderStatus(
                    runtime_id=RT, agent="claude", provider_id="deepseek",
                    provider_name="DeepSeek", route_mode="cc-switch-proxy",
                    auth_status="configured", observed_at="t")
                data = cmd_provider_current(RT, "claude", workspace=tmp,
                                            executor=FakeDockerExecutor())
        assert data["provider_id"] == "deepseek"
        assert data["route_mode"] == "cc-switch-proxy"
        cp.assert_called_once()


class TestProviderCurrentJsonEnvelope(unittest.TestCase):
    def test_current_json_envelope(self):
        from aisc.cli.main import main
        payload = {"runtime_id": RT, "agent": "claude", "provider_id": "deepseek",
                   "provider_name": "DeepSeek", "route_mode": "cc-switch-proxy",
                   "auth_status": "configured", "observed_at": "t"}
        with patch("aisc.cli.commands.provider.cmd_provider_current", return_value=payload):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as cm:
                    main(["provider", "current", "--runtime-id", RT,
                          "--agent", "claude", "--format", "json"])
        assert cm.exception.code == 0
        env = json.loads(buf.getvalue())
        assert env["meta"]["command"] == "provider"
        assert env["data"]["provider_id"] == "deepseek"
        assert env["data"]["route_mode"] == "cc-switch-proxy"

    def test_set_key_still_rejects_json(self):
        # set-key remains text-only interactive; only `current` supports JSON.
        from aisc.cli.main import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                main(["provider", "set-key", "deepseek", "--format", "json"])
        assert cm.exception.code == 2


if __name__ == "__main__":
    unittest.main()
