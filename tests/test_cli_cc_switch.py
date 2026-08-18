"""Stage 8d host side: ``aisc cc-switch list/add/edit/delete``.

The application layer must address the runtime, pipe the request document
through docker exec -i STDIN (never argv), validate the adapter envelope,
and map adapter error codes onto CliError.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock
from pathlib import Path
import tempfile

from aisc.application import cc_switch_provider as host
from aisc.domain.models import CliError

RUNTIME = "11111111-2222-4333-8444-555555555555"

ENVELOPE_OK = {
    "schema": "aisc.cc-switch-provider/v1",
    "operation_id": "op-1",
    "op": "list",
    "ok": True,
    "providers": [
        {"id": "deepseek", "name": "DeepSeek", "app_type": "claude",
         "base_url": "https://api.deepseek.com/anthropic",
         "model": "deepseek-v4-pro[1m]", "has_api_key": True,
         "api_key_mask": "****3456", "is_current": True},
    ],
}


class FakeExec:
    def __init__(self, envelope, rc=0):
        self.envelope = envelope
        self.rc = rc
        self.argv = None
        self.input_text = None

    def run_captured(self, argv, *, timeout=None, input_text=None):
        from types import SimpleNamespace

        self.argv = list(argv)
        self.input_text = input_text
        out = json.dumps(self.envelope) if self.rc == 0 else ""
        return SimpleNamespace(
            exit_code=self.rc,
            stdout=out,
            stderr="docker: boom" if self.rc else "",
        )


class HostLayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.exec = FakeExec(ENVELOPE_OK)
        patcher = mock.patch.object(
            host, "resolve_running_container", return_value="ct-1"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_list_exec_shape_and_envelope(self):
        data = host.list_providers(RUNTIME, "claude", self.tmp.name, self.exec)
        argv = self.exec.argv
        self.assertEqual(argv[:3], ["exec", "-i", "ct-1"])
        joined = " ".join(argv)
        self.assertIn("aisc-cc-provider list --agent claude", joined)
        self.assertFalse(self.exec.input_text)  # list sends no request body
        self.assertEqual(data["providers"][0]["id"], "deepseek")
        self.assertEqual(data["operation_id"], "op-1")

    def test_add_secrets_travel_stdin_not_argv(self):
        self.exec.envelope = {**ENVELOPE_OK, "op": "add"}
        request = {"mode": "simple", "id": "deepseek", "provider": "deepseek",
                   "api_key": "sk-super-secret-987654"}
        host.add_provider(RUNTIME, "claude", request, self.tmp.name, self.exec)
        argv = " ".join(self.exec.argv)
        self.assertNotIn("sk-super-secret-987654", argv)
        self.assertIn("--id deepseek", argv)
        sent = json.loads(self.exec.input_text)
        self.assertEqual(sent["api_key"], "sk-super-secret-987654")

    def test_edit_delete_addressing(self):
        self.exec.envelope = {**ENVELOPE_OK, "op": "edit"}
        host.edit_provider(RUNTIME, "codex", "zhipu", {"patch": {"model": "m"}},
                           self.tmp.name, self.exec)
        self.assertIn("edit --agent codex --id zhipu", " ".join(self.exec.argv))
        self.exec.envelope = {**ENVELOPE_OK, "op": "delete"}
        host.delete_provider(RUNTIME, "claude", "kimi", self.tmp.name, self.exec)
        self.assertIn("delete --agent claude --id kimi", " ".join(self.exec.argv))

    def test_switch_addressing(self):
        self.exec.envelope = {**ENVELOPE_OK, "op": "switch"}
        host.switch_provider(RUNTIME, "claude", "zhipu",
                              self.tmp.name, self.exec)
        self.assertIn("switch --agent claude --id zhipu", " ".join(self.exec.argv))
        self.assertFalse(self.exec.input_text)  # no request body

    def test_adapter_error_maps_to_cli_error_with_stable_code(self):
        self.exec.envelope = {
            "schema": "aisc.cc-switch-provider/v1", "operation_id": "op-2",
            "op": "delete", "ok": False,
            "error": {"code": "AISC_ERR_CC_SWITCH_PROVIDER_NOT_FOUND",
                      "message": "provider not found: ghost"},
        }
        with self.assertRaises(CliError) as ctx:
            host.delete_provider(RUNTIME, "claude", "ghost",
                                 self.tmp.name, self.exec)
        self.assertEqual(ctx.exception.error_code,
                         "AISC_ERR_CC_SWITCH_PROVIDER_NOT_FOUND")
        self.assertIn("ghost", ctx.exception.message)

    def test_bad_runtime_and_agent_rejected_before_docker(self):
        with self.assertRaises(CliError):
            host.list_providers("not-a-uuid", "claude", self.tmp.name, self.exec)
        with self.assertRaises(CliError):
            host.list_providers(RUNTIME, "gemini", self.tmp.name, self.exec)
        self.assertIsNone(self.exec.argv)  # nothing reached docker

    def test_garbage_adapter_output_is_a_protocol_error(self):
        from types import SimpleNamespace

        self.exec.run_captured = lambda argv, *, timeout=None, input_text=None: (
            SimpleNamespace(exit_code=0, stdout="not json", stderr="")
        )
        with self.assertRaises(CliError) as ctx:
            host.list_providers(RUNTIME, "claude", self.tmp.name, self.exec)
        self.assertEqual(ctx.exception.error_code,
                         "AISC_ERR_CC_SWITCH_PROVIDER_EXEC_FAILED")


if __name__ == "__main__":
    unittest.main()
