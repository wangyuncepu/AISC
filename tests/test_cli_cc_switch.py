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


class CommandLayerTests(unittest.TestCase):
    """KI-7① regression: the CLI command layer must NOT clobber the stdin
    request's ``mode`` with an argparse default (the Workbench never passes
    --mode; a truthy default turned every custom add into a broken simple
    add with an empty preset id)."""

    def setUp(self):
        # The host-layer tests that follow this class in the file share the
        # same fixtures (they predate the class split).
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.exec = FakeExec(ENVELOPE_OK)
        patcher = mock.patch.object(
            host, "resolve_running_container", return_value="ct-1"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, stdin_json: str, args_over: dict | None = None):
        from types import SimpleNamespace

        from aisc.cli.commands import cc_switch as cmd

        args = SimpleNamespace(
            runtime_id=RUNTIME, agent="claude", workspace="C:/ws",
            mode=None, provider=None, new_id=None,
        )
        for k, v in (args_over or {}).items():
            setattr(args, k, v)
        with mock.patch("sys.stdin", SimpleNamespace(read=lambda: stdin_json)), \
                mock.patch.object(host, "add_provider") as add:
            add.return_value = {"providers": []}
            data = cmd.cmd_cc_switch_add(args)
        self.assertEqual(data, {"providers": []})
        return add

    def test_stdin_mode_custom_survives_without_flag(self):
        add = self._run(json.dumps({
            "mode": "custom", "id": "myprov", "name": "My Provider",
            "base_url": "https://example.com", "api_key": "sk-x",
        }))
        sent = add.call_args.kwargs["request"]
        self.assertEqual(sent["mode"], "custom")  # the KI-7① regression

    def test_flag_still_overrides_and_default_is_simple(self):
        # Explicit --mode custom with no stdin mode.
        add = self._run(json.dumps({"id": "a", "api_key": "sk-x"}),
                        args_over={"mode": "custom"})
        self.assertEqual(add.call_args.kwargs["request"]["mode"], "custom")
        # Neither flag nor stdin mode → simple.
        add = self._run(json.dumps({"id": "deepseek", "api_key": "sk-x"}))
        self.assertEqual(add.call_args.kwargs["request"]["mode"], "simple")

    def test_switch_addressing(self):
        self.exec.envelope = {**ENVELOPE_OK, "op": "switch"}
        host.switch_provider(RUNTIME, "claude", "zhipu",
                              self.tmp.name, self.exec)
        self.assertIn("switch --agent claude --id zhipu", " ".join(self.exec.argv))
        self.assertFalse(self.exec.input_text)  # no request body

    def test_fetch_models_addressing_and_result(self):
        # IDEA-5 (5c): the op addresses the adapter with --id and surfaces
        # the envelope's fetch_models payload verbatim.
        self.exec.envelope = {
            **ENVELOPE_OK, "op": "fetch-models",
            "fetch_models": {"available": True,
                             "models": ["deepseek-chat", "deepseek-v4-pro[1m]"],
                             "message": ""},
        }
        data = host.fetch_models(RUNTIME, "claude", "deepseek",
                                 self.tmp.name, self.exec)
        self.assertIn("fetch-models --agent claude --id deepseek",
                      " ".join(self.exec.argv))
        self.assertTrue(data["available"])
        self.assertEqual(data["models"][1], "deepseek-v4-pro[1m]")

    def test_fetch_models_degrades_when_payload_missing(self):
        # Older adapter / unexpected payload → the documented empty degrade,
        # never an exception.
        self.exec.envelope = {**ENVELOPE_OK, "op": "fetch-models"}
        data = host.fetch_models(RUNTIME, "claude", "deepseek",
                                 self.tmp.name, self.exec)
        self.assertFalse(data["available"])
        self.assertEqual(data["models"], [])

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
