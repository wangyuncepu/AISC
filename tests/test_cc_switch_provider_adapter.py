"""Stage 8d: the in-container provider adapter (aisc.cc-switch-provider/v1).

Hermetic: the cc-switch CLI is faked (argv+stdin recorded, or a SQLite-backed
fake that REALLY writes the temp DB so concurrency is exercised for real);
the DB is a temp cc-switch.db; secrets must never appear in any envelope.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "container" / "aisc-cc-provider"

# The adapter ships without a .py suffix (installed as an executable); load
# it explicitly via SourceFileLoader.
_loader = SourceFileLoader("aisc_cc_provider_adapter", str(ADAPTER_PATH))
_spec = importlib.util.spec_from_loader("aisc_cc_provider_adapter", _loader)
assert _spec and _spec.loader
A = importlib.util.module_from_spec(_spec)
_loader.exec_module(A)

CLAUDE_ENV = {
    "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
    "ANTHROPIC_MODEL": "deepseek-v4-pro[1m]",
    "ANTHROPIC_AUTH_TOKEN": "sk-live-abcdef123456",
}


def create_db(dir_path: Path):
    conn = sqlite3.connect(dir_path / "cc-switch.db")
    conn.execute(
        "CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT, "
        "settings_config TEXT, website_url TEXT, category TEXT, created_at INTEGER, "
        "sort_index INTEGER, notes TEXT, icon TEXT, icon_color TEXT, meta TEXT, "
        "is_current INTEGER, in_failover_queue INTEGER)"
    )
    conn.commit()
    conn.close()


def seed_provider(dir_path: Path, pid: str, env: dict, *, is_current=False,
                  name=None, agent="claude", settings=None, meta=None,
                  notes="", website_url="", icon="", icon_color=""):
    if settings is None:
        raw = json.dumps({"env": env})
    elif isinstance(settings, str):
        raw = settings
    else:
        raw = json.dumps(settings)
    conn = sqlite3.connect(dir_path / "cc-switch.db")
    try:
        conn.execute(
            "INSERT INTO providers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, agent, name or pid, raw,
             website_url or "https://x", "custom", 1, 0, notes or "",
             icon or None, icon_color or None,
             json.dumps(meta or {}),
             1 if is_current else 0, 0),
        )
        conn.commit()
    finally:
        conn.close()


class FakeCall:
    def __init__(self, args, stdin_text):
        self.args = args
        self.stdin_text = stdin_text


class RecordingCli:
    """Replayable fake: routes add/delete/switch to a handler list."""

    def __init__(self):
        self.calls: list[FakeCall] = []
        self.fail_on: dict[str, str] = {}  # substring of argv -> error
        self.stub: str | None = None  # IDEA-5 tests: canned stdout

    def stub_stdout(self, text: str) -> None:
        self.stub = text

    def __call__(self, args, stdin_text, secrets):
        call = FakeCall(list(args), stdin_text)
        self.calls.append(call)
        for marker, message in self.fail_on.items():
            if marker in " ".join(args):
                return subprocess.CompletedProcess(args, 1, stdout="", stderr=message)
        stdout = self.stub if self.stub is not None else \
            "Switched to provider 'x'\n✓ ok (API Key: sk-leak)"
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    def argv(self) -> list[list[str]]:
        return [c.args for c in self.calls]


class AdapterTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        create_db(self.dir)
        self._env = {"CC_SWITCH_CONFIG_DIR": str(self.dir),
                     "CODEX_CONFIG_DIR": str(self.dir)}
        self._patcher = mock.patch.dict("os.environ", self._env, clear=False)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.cli = RecordingCli()
        self._orig_cli = A.run_cli
        A.run_cli = self.cli
        self.addCleanup(setattr, A, "run_cli", self._orig_cli)
        # The pty path uses the raw runner (no automatic cc-switch prefix);
        # route it through the same recorder.
        self._orig_raw = A.run_raw
        A.run_raw = lambda argv, inp, _cli=self.cli: _cli(argv, inp, [])
        self.addCleanup(setattr, A, "run_raw", self._orig_raw)

    def _install_show_cli(self, show_stdout_fn):
        def fake_cli(args, stdin_text, secrets):
            call = FakeCall(list(args), stdin_text)
            self.cli.calls.append(call)
            stdout = show_stdout_fn(args) or (
                "Switched to provider 'x'\n✓ ok")
            return subprocess.CompletedProcess(args, 0, stdout=stdout,
                                               stderr="")
        A.run_cli = fake_cli

    def _install_dance_cli(self):
        """RecordingCli whose provider-add ALSO inserts the row into the
        sqlite db (the real CLI would), so delete-re-add dances are
        observable via op_list. PP (D-12) tests assert on views."""
        def fake_cli(args, stdin_text, secrets):
            call = FakeCall(list(args), stdin_text)
            self.cli.calls.append(call)
            joined = " ".join(args)
            if "provider" in joined and " add" in joined:
                agent = args[args.index("-a") + 1]
                pid = args[args.index("--id") + 1]
                name = args[args.index("--name") + 1]
                conn = sqlite3.connect(self.dir / "cc-switch.db")
                try:
                    conn.execute(
                        "INSERT INTO providers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, agent, name, stdin_text or "{}",
                         "", "custom", 1, 99, "", None, None, "{}", 0, 0),
                    )
                    conn.commit()
                finally:
                    conn.close()
            return subprocess.CompletedProcess(
                args, 0, stdout="Switched to provider 'x'\nOK", stderr="")
        A.run_cli = fake_cli

    @staticmethod
    def _open_listener():
        import socket as _socket
        listener = _socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        return listener, listener.getsockname()[1]


class SnapshotAndRedactionTests(AdapterTestCase):
    def test_list_masks_keys_and_never_emits_secrets(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "bare", {"ANTHROPIC_BASE_URL": "https://x"})
        providers = A.op_list("claude")
        by_id = {p["id"]: p for p in providers}
        self.assertTrue(by_id["deepseek"]["has_api_key"])
        self.assertEqual(by_id["deepseek"]["api_key_mask"], "****3456")
        self.assertFalse(by_id["bare"]["has_api_key"])
        self.assertEqual(by_id["bare"]["api_key_mask"], "")
        self.assertTrue(by_id["deepseek"]["is_current"])
        # The full key appears nowhere in the serialized envelope.
        self.assertNotIn("sk-live-abcdef123456", json.dumps(providers))

    def test_cli_stdout_redaction_even_on_success(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV)
        A.op_delete("claude", "deepseek")
        # The fake CLI echoes a leak; the adapter redacts before anyone sees it.
        # (Recorded call succeeded; here we assert the redact() primitive.)
        red = A.redact("API Key: sk-live-abcdef123456 tail", ["sk-live-abcdef123456"])
        self.assertNotIn("sk-live-abcdef123456", red)
        self.assertIn("****3456", red)
        # Generic sk- pattern also scrubbed.
        self.assertNotIn("sk-zzzzzzzzzz", A.redact("x sk-zzzzzzzzzz y", []))

    def test_codex_snapshot_fields(self):
        toml_config = (
            'model_provider = "deepseek"\nmodel = "deepseek-v4-pro"\n'
            '[model_providers.deepseek]\nname = "deepseek"\n'
            'base_url = "https://api.deepseek.com"\nwire_api = "chat"\n'
            'api_key = "sk-codex-key-999888"\n'
        )
        seed_provider(self.dir, "deepseek", {}, agent="codex",
                      settings={"config": toml_config, "auth": {}})
        providers = A.op_list("codex")
        p = providers[0]
        self.assertEqual(p["base_url"], "https://api.deepseek.com")
        self.assertEqual(p["model"], "deepseek-v4-pro")
        self.assertTrue(p["has_api_key"])
        self.assertEqual(p["api_key_mask"], "****9888")

    def test_codex_snapshot_prefers_auth_channel_over_toml(self):
        # auth.OPENAI_API_KEY is the live channel; the TOML api_key line is
        # the legacy fallback — when both exist, auth wins the mask.
        toml_config = (
            'model_provider = "deepseek"\n[model_providers.deepseek]\n'
            'base_url = "https://api.deepseek.com"\n'
            'api_key = "sk-toml-stale-1111"\n'
        )
        seed_provider(self.dir, "deepseek", {}, agent="codex",
                      settings={"config": toml_config,
                                "auth": {"OPENAI_API_KEY": "sk-auth-live-7788"}})
        p = A.op_list("codex")[0]
        self.assertTrue(p["has_api_key"])
        self.assertEqual(p["api_key_mask"], "****7788")


class AddTests(AdapterTestCase):
    def test_simple_add_uses_preset_env_and_stdin_secret(self):
        request = {"mode": "simple", "id": "deepseek", "provider": "deepseek",
                   "api_key": "sk-new-secret-777"}
        providers = A.op_add("claude", request)
        add_calls = [c for c in self.cli.calls if "add" in c.args]
        self.assertEqual(len(add_calls), 1)
        argv = " ".join(add_calls[0].args)
        self.assertIn("--config-file /dev/stdin", argv)
        self.assertNotIn("--api-key", argv)            # argv never carries the key
        self.assertNotIn("sk-new-secret-777", argv)
        sent = json.loads(add_calls[0].stdin_text)
        self.assertEqual(sent["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-new-secret-777")
        # Preset-derived official set present.
        self.assertEqual(sent["env"]["ANTHROPIC_BASE_URL"],
                         "https://api.deepseek.com/anthropic")
        self.assertEqual(sent["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"],
                         "deepseek-v4-pro[1m]")
        # Envelope snapshot never carries the secret.
        self.assertNotIn("sk-new-secret-777", json.dumps(providers))

    def test_custom_add_requires_base_url_and_valid_id(self):
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_add("claude", {"mode": "custom", "id": "mine", "name": "Mine",
                                "model": "m"})
        self.assertEqual(ctx.exception.code, A.ERR_BAD_REQUEST)
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_add("claude", {"mode": "custom", "id": "Bad Id!", "name": "x",
                                "base_url": "https://y"})
        self.assertEqual(ctx.exception.code, A.ERR_BAD_REQUEST)

    def test_custom_codex_add_carries_auth_field(self):
        providers = A.op_add("codex", {"mode": "custom", "id": "mine",
                                       "name": "Mine",
                                       "base_url": "https://api.mine"})
        sent = json.loads(self.cli.calls[0].stdin_text)
        self.assertIn("auth", sent)
        self.assertIn("config", sent)

    def test_custom_codex_add_key_rides_auth_channel(self):
        # The key must land in auth.OPENAI_API_KEY (what live auth.json is
        # written from — and what the proxy worker captures at enable).
        A.op_add("codex", {"mode": "custom", "id": "mine", "name": "Mine",
                           "base_url": "https://api.mine",
                           "api_key": "sk-add-live-556677"})
        sent = json.loads(self.cli.calls[0].stdin_text)
        self.assertEqual(sent["auth"], {"OPENAI_API_KEY": "sk-add-live-556677"})
        self.assertIn('api_key = "sk-add-live-556677"', sent["config"])

    def test_duplicate_id_rejected_before_any_cli_call(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV)
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_add("claude", {"mode": "simple", "id": "deepseek",
                                "provider": "deepseek", "api_key": "k"})
        self.assertEqual(ctx.exception.code, A.ERR_BAD_REQUEST)
        self.assertEqual(self.cli.calls, [])


class EditDanceTests(AdapterTestCase):
    def _seed_two(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "zhipu", {
            "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "sk-zhipu-key-2222",
        })

    def test_edit_non_current_is_delete_then_readd(self):
        self._seed_two()
        A.op_edit("claude", "zhipu", {
            "patch": {"model": "glm-5.2"}, "api_key": "sk-rotated-4444",
        })
        add_calls = [c for c in self.cli.calls if "add" in c.args]
        self.assertEqual(len(add_calls), 1)  # no switch dance; delete is DB-side
        sent = json.loads(add_calls[0].stdin_text)
        self.assertEqual(sent["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-rotated-4444")
        self.assertEqual(sent["env"]["ANTHROPIC_MODEL"], "glm-5.2")
        self.assertEqual(sent["env"]["ANTHROPIC_BASE_URL"],
                         "https://open.bigmodel.cn/api/anthropic")

    def test_edit_current_switches_away_and_back(self):
        self._seed_two()
        A.op_edit("claude", "deepseek", {"patch": {"name": "DeepSeek 2"}})

        def kind(call):
            args = call.args
            if "switch" in args:
                return ("switch", args[-1])
            if "delete" in args:
                return ("delete", args[-1])
            if "add" in args:
                return ("add", args[args.index("--id") + 1])
            return None

        kinds = [k for k in (kind(c) for c in self.cli.calls) if k]
        # Delete is the adapter's DB transaction (no CLI call).
        self.assertEqual(kinds, [
            ("switch", "zhipu"),
            ("add", "deepseek"),
            ("switch", "deepseek"),
        ])
        # The re-add carries the FULL preserved settings (incl. old token).
        sent = json.loads(self.cli.calls[1].stdin_text)
        self.assertEqual(sent["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-live-abcdef123456")

    def test_edit_failure_restores_previous_state(self):
        self._seed_two()
        # PP r4: the re-add fails (upstream CLI locked out of a newer db —
        # live incident 2026-09-03: image shipped 5.9.0 against a db the
        # desktop had migrated to v18). The captured row must come back
        # verbatim via DIRECT SQL — no second upstream add, error surfaced.
        def fail_add(args, stdin_text, secrets):
            call = FakeCall(list(args), stdin_text)
            self.cli.calls.append(call)
            if "add" in args:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

        A.run_cli = fail_add
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_edit("claude", "zhipu", {"patch": {"model": "x"}})
        self.assertEqual(ctx.exception.code, A.ERR_CLI)
        # Exactly ONE upstream add (the failed re-add); the restore is the
        # adapter's own DB write, never a second CLI attempt.
        adds = [c for c in self.cli.calls if "add" in c.args]
        self.assertEqual(len(adds), 1)
        # The row is back verbatim (original token/URL) via direct SQL.
        rows = [r for r in A.read_snapshot("claude") if r["id"] == "zhipu"]
        self.assertEqual(len(rows), 1)
        env = rows[0]["settings"]["env"]
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-zhipu-key-2222")
        self.assertEqual(env["ANTHROPIC_BASE_URL"],
                         "https://open.bigmodel.cn/api/anthropic")
        self.assertFalse(rows[0]["is_current"])

    def test_edit_of_sole_current_provider_fails_closed(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_edit("claude", "deepseek", {"patch": {"model": "x"}})
        self.assertEqual(ctx.exception.code, A.ERR_NO_SWITCH_TARGET)
        self.assertEqual(self.cli.calls, [])

    def test_edit_unknown_provider(self):
        self._seed_two()
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_edit("claude", "nope", {"patch": {}})
        self.assertEqual(ctx.exception.code, A.ERR_NOT_FOUND)


class CodexEditShapeTests(AdapterTestCase):
    """codex auth-channel round (2026-08-21): the user's key rides
    settings auth.OPENAI_API_KEY (the channel live ~/.codex/auth.json is
    written from and the local proxy worker captures at enable), and an
    edit no longer flattens the preset row's probed working shape."""

    PRESET_TOML = (
        'model_provider = "deepseek"\nmodel = "deepseek-v4-pro"\n'
        'model_context_window = 1000000\nmodel_reasoning_effort = "high"\n\n'
        '[model_providers.deepseek]\nname = "deepseek"\n'
        'base_url = "https://api.deepseek.com/anthropic"\n'
        'wire_api = "responses"\nrequires_openai_auth = true\n'
    )

    def _seed_row(self, settings: dict) -> None:
        seed_provider(self.dir, "codex-official", {}, agent="codex",
                      is_current=True, settings={"auth": {}, "config": ""})
        seed_provider(self.dir, "deepseek", {}, agent="codex",
                      settings=settings)

    def _sent_settings(self) -> dict:
        adds = [c for c in self.cli.calls if "add" in c.args]
        self.assertEqual(len(adds), 1)
        return json.loads(adds[0].stdin_text)

    def test_edit_writes_auth_channel_and_preserves_shape(self):
        self._seed_row({"auth": {}, "config": self.PRESET_TOML,
                        "modelCatalog": {"models": [{"model": "deepseek-v4-pro"}]}})
        A.op_edit("codex", "deepseek",
                  {"patch": {"name": "DeepSeek"}, "api_key": "sk-live-112233"})
        sent = self._sent_settings()
        self.assertEqual(sent["auth"].get("OPENAI_API_KEY"), "sk-live-112233")
        self.assertIn('api_key = "sk-live-112233"', sent["config"])
        self.assertIn('wire_api = "responses"', sent["config"])
        self.assertIn("model_context_window = 1000000", sent["config"])
        self.assertIn('base_url = "https://api.deepseek.com/anthropic"',
                      sent["config"])
        self.assertEqual(sent["modelCatalog"],
                         {"models": [{"model": "deepseek-v4-pro"}]})

    def test_edit_upgrades_legacy_toml_key_into_auth(self):
        self._seed_row({"auth": {},
                        "config": self.PRESET_TOML + 'api_key = "sk-legacy-4455"\n'})
        A.op_edit("codex", "deepseek", {"patch": {"name": "DeepSeek"}})
        sent = self._sent_settings()
        self.assertEqual(sent["auth"].get("OPENAI_API_KEY"), "sk-legacy-4455")

    def test_edit_preserves_oauth_auth_mirror(self):
        self._seed_row({"auth": {"tokens": {"id_token": "tok"}},
                        "config": self.PRESET_TOML})
        A.op_edit("codex", "deepseek", {"patch": {}, "api_key": "sk-rotate-99"})
        sent = self._sent_settings()
        self.assertEqual(sent["auth"]["tokens"], {"id_token": "tok"})
        self.assertEqual(sent["auth"]["OPENAI_API_KEY"], "sk-rotate-99")


class ClaudeSettingsBaseTests(AdapterTestCase):
    """Retest round 2 (2026-08-21): upstream's claude switch REPLACES
    settings.json with the row's settings_config wholesale — every claude
    settings_config the adapter writes must carry the non-env base
    (statusLine/enabledPlugins/...) or the user's setup is wiped on the
    next switch (live-probed)."""

    def _add_settings(self, request: dict) -> dict:
        A.op_add("claude", request)
        adds = [c for c in self.cli.calls if "add" in c.args]
        self.assertEqual(len(adds), 1)
        return json.loads(adds[0].stdin_text)

    def test_simple_add_carries_settings_base(self):
        sent = self._add_settings({
            "mode": "simple", "id": "deepseek", "provider": "deepseek",
            "api_key": "sk-new-secret-777",
        })
        self.assertIn("statusLine", sent)
        self.assertIn("enabledPlugins", sent)
        self.assertEqual(sent["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-new-secret-777")

    def test_custom_add_carries_settings_base(self):
        sent = self._add_settings({
            "mode": "custom", "id": "my-endpoint", "name": "My Endpoint",
            "base_url": "https://api.example.com", "api_key": "sk-k",
        })
        self.assertIn("statusLine", sent)
        self.assertEqual(sent["env"]["ANTHROPIC_BASE_URL"], "https://api.example.com")

    def test_edit_preserves_non_env_keys_through_the_dance(self):
        statusline = {"type": "command", "command": "echo hi"}
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True,
                      settings={"env": CLAUDE_ENV, "statusLine": statusline})
        seed_provider(self.dir, "zhipu", {"ANTHROPIC_BASE_URL": "https://z"})
        A.op_edit("claude", "deepseek", {"patch": {"name": "DS"}})
        adds = [c for c in self.cli.calls if "add" in c.args]
        self.assertEqual(len(adds), 1)  # the dance's re-add
        sent = json.loads(adds[0].stdin_text)
        self.assertEqual(sent["statusLine"], statusline)


class RouteGuardTests(AdapterTestCase):
    """Manual round 3 (2026-08-21): upstream `proxy enable` silently
    no-ops when the daemon's supervisor state is stale or the daemon is
    down (rc 0, "enabled" printed, nothing listening) — the switch must
    verify the route actually serves and self-heal via a daemon restart."""

    def _seed_codex_switch(self) -> None:
        toml_cfg = (
            'model_provider = "deepseek"\n[model_providers.deepseek]\n'
            'base_url = "https://api.deepseek.com"\n'
        )
        seed_provider(self.dir, "codex-official", {}, agent="codex",
                      is_current=True, settings={"auth": {}, "config": ""})
        seed_provider(self.dir, "deepseek", {}, agent="codex",
                      settings={"auth": {}, "config": toml_cfg})

    @staticmethod
    def _closed_port() -> int:
        import socket as _socket
        sock = _socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    @staticmethod
    def _open_listener():
        import socket as _socket
        listener = _socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        return listener, listener.getsockname()[1]

    def _install_show_cli(self, show_stdout_fn):
        def fake_cli(args, stdin_text, secrets):
            call = FakeCall(list(args), stdin_text)
            self.cli.calls.append(call)
            stdout = show_stdout_fn(args) or (
                "Switched to provider 'x'\n✓ ok")
            return subprocess.CompletedProcess(args, 0, stdout=stdout,
                                               stderr="")
        A.run_cli = fake_cli

    def test_guard_verifies_the_agents_own_port(self):
        # `proxy show` lists EVERY app (claude's line first) — the guard
        # must anchor to the switching agent's own line (report 2026-08-21:
        # a codex switch verified claude's legitimately-closed 15721 and
        # failed the whole dance).
        listener, codex_port = self._open_listener()
        self.addCleanup(listener.close)
        claude_port = self._closed_port()

        def show_stdout_fn(args):
            if "show" not in args:
                return None
            return (
                "Local Proxy\n"
                f"- Claude: disabled, configured {claude_port}\n"
                f"- Codex: enabled, configured {codex_port}\n"
            )

        self._install_show_cli(show_stdout_fn)
        self._seed_codex_switch()
        A.op_switch("codex", "deepseek")  # claude port CLOSED — must not matter
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertFalse(any("daemon" in a for a in argvs))

    def test_already_current_row_heals_tail_state(self):
        # A guard failure mid-dance leaves the row current WITHOUT the
        # catalog applied — the user's re-click takes the idempotent path,
        # which must re-run the cheap post-healing (route verify + catalog).
        listener, port = self._open_listener()
        self.addCleanup(listener.close)
        self._install_show_cli(
            lambda args: f"- Codex: enabled, configured {port}\n"
            if "show" in args else None)
        toml_cfg = ('model_provider = "deepseek"\n[model_providers.deepseek]\n'
                    'base_url = "https://api.deepseek.com"\n')
        seed_provider(self.dir, "deepseek", {}, agent="codex", is_current=True,
                      settings={"auth": {}, "config": toml_cfg,
                                "modelCatalog": {"models": [
                                    {"model": "deepseek-v4-pro",
                                     "contextWindow": 1000000}]}})
        providers = A.op_switch("codex", "deepseek")
        self.assertTrue(providers[0]["is_current"])
        catalog = self.dir / "aisc-model-catalog.json"
        self.assertTrue(catalog.is_file())
        self.assertIn("deepseek-v4-pro",
                      catalog.read_text(encoding="utf-8"))
        config_toml = self.dir / "config.toml"
        self.assertIn("model_catalog_json",
                      config_toml.read_text(encoding="utf-8"))

    def test_listening_route_passes_without_recovery(self):
        listener, port = self._open_listener()
        self.addCleanup(listener.close)
        self._install_show_cli(
            lambda args: f"Local Proxy\n- Codex: enabled, configured {port}\n"
            if "show" in args else None)
        self._seed_codex_switch()
        A.op_switch("codex", "deepseek")
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertFalse(any("daemon" in a for a in argvs))
        self.assertEqual(sum("enable" in a for a in argvs), 1)

    def test_stale_route_recovered_via_daemon_restart(self):
        port = self._closed_port()
        import socket as _socket

        def show_stdout_fn(args):
            if "show" not in args:
                return None
            return f"- Codex: enabled, configured {port}\n"

        original_cli = A.run_cli
        enable_seen: list[int] = []

        def fake_cli(args, stdin_text, secrets):
            call = FakeCall(list(args), stdin_text)
            self.cli.calls.append(call)
            joined = " ".join(args)
            if "enable" in joined and "proxy" in joined:
                enable_seen.append(1)
                if len(enable_seen) > 1:  # the recovery re-enable → route up
                    sock = _socket.socket()
                    sock.bind(("127.0.0.1", port))
                    sock.listen(4)
                    self.addCleanup(sock.close)
            stdout = show_stdout_fn(args) or "Switched to provider 'x'\n✓ ok"
            return subprocess.CompletedProcess(args, 0, stdout=stdout,
                                               stderr="")
        A.run_cli = fake_cli
        self._seed_codex_switch()
        A.op_switch("codex", "deepseek")  # must NOT raise
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertTrue(any("daemon" in a and "stop" in a for a in argvs))
        self.assertTrue(any("daemon" in a and "start" in a for a in argvs))
        self.assertEqual(sum("enable" in a for a in argvs), 2)

    def test_unrecoverable_route_fails_the_switch(self):
        port = self._closed_port()
        self._install_show_cli(
            lambda args: f"- Codex: enabled, configured {port}\n"
            if "show" in args else None)
        self._seed_codex_switch()
        with mock.patch.object(A.time, "sleep", lambda s: None):
            with self.assertRaises(A.AdapterError) as ctx:
                A.op_switch("codex", "deepseek")
        self.assertEqual(ctx.exception.code, A.ERR_SWITCH_FAILED)
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertTrue(any("daemon" in a and "start" in a for a in argvs))

    def test_disable_failure_still_switches_and_forces_recovery(self):
        # Live-probed worst mode (2026-08-21): zombie worker → the dance's
        # precautionary disable itself errors ("managed proxy session did
        # not exit") — the switch must proceed, and because the disable
        # failed, recovery runs UNCONDITIONALLY (an orphaned old worker can
        # hold the port open while serving a stale route).
        listener, port = self._open_listener()
        self.addCleanup(listener.close)

        def fake_cli(args, stdin_text, secrets):
            call = FakeCall(list(args), stdin_text)
            self.cli.calls.append(call)
            joined = " ".join(args)
            if "disable" in joined and "proxy" in joined:
                return subprocess.CompletedProcess(
                    args, 1, stdout="",
                    stderr="Error: managed proxy session did not exit")
            stdout = (f"- Codex: enabled, configured {port}\n"
                      if "show" in args else "Switched to provider 'x'\n✓ ok")
            return subprocess.CompletedProcess(args, 0, stdout=stdout,
                                               stderr="")

        A.run_cli = fake_cli
        self._seed_codex_switch()
        A.op_switch("codex", "deepseek")  # must NOT raise
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertIn("switch", argvs[0])  # O4 r2: the switch runs FIRST now
        self.assertTrue(any("daemon" in a and "stop" in a for a in argvs))
        self.assertTrue(any("daemon" in a and "start" in a for a in argvs))
        self.assertEqual(sum("enable" in a for a in argvs), 2)  # forced

    def test_official_switch_skips_the_guard(self):
        self._install_show_cli(lambda args: "should never be asked")
        seed_provider(self.dir, "deepseek", {}, agent="codex", is_current=True,
                      settings={"auth": {}, "config": 'model_provider = "d"\n'})
        seed_provider(self.dir, "codex-official", {}, agent="codex",
                      settings={"auth": {}, "config": ""})
        A.op_switch("codex", "official")
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertFalse(any("show" in a for a in argvs))
        self.assertFalse(any("daemon" in a for a in argvs))


class SwitchTests(AdapterTestCase):
    def test_switch_runs_cli_switch_and_returns_snapshot(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "zhipu", {"ANTHROPIC_BASE_URL": "https://z"})
        providers = A.op_switch("claude", "zhipu")
        # Retest round 2 (2026-08-21): the provider-page choice owns the
        # agent's proxy route — disable → switch → enable for BOTH agents.
        argvs = [" ".join(c.args) for c in self.cli.calls]
        # O4 r2: the dance is switch -> disable -> enable -> show (a disable
        # right before the switch makes the upstream CLI block ~6.5s in
        # daemon teardown — live-probed 2026-09-02). The enable is followed
        # by a route liveness verify (`proxy show` for the port —
        # unparseable output skips the check).
        self.assertEqual(len(argvs), 4)
        self.assertIn("switch", argvs[0])
        self.assertTrue(argvs[0].endswith("zhipu"))
        self.assertIn("proxy -a claude disable", argvs[1])
        self.assertIn("proxy -a claude enable", argvs[2])
        self.assertIn("proxy -a claude show", argvs[3])
        # snapshot returned unchanged (the CLI owns is_current truth)
        self.assertEqual([p["id"] for p in providers][0], "deepseek")

    def test_claude_switch_reenables_proxy_route_after_switch(self):
        # Symmetric with codex (retest round 2): activating a provider leaves
        # the agent's local route ON (proxy on ⟺ third-party provider
        # current); disable-first lets the switch write the row's direct env,
        # enable re-arms the local-route stub (live-probed 2026-08-21).
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "zhipu", {"ANTHROPIC_BASE_URL": "https://z"})
        A.op_switch("claude", "zhipu")
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertIn("switch", argvs[0])  # O4 r2: switch first
        self.assertEqual(argvs[1], "proxy -a claude disable")
        self.assertEqual(argvs[2], "proxy -a claude enable")

    def test_claude_switch_to_official_leaves_route_disabled(self):
        # Cancel-proxy: official-direct rows leave the agent's route OFF —
        # the invariant's other half (and the fix for "claude stuck on
        # default with the proxy on").
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "claude-official", {})
        self.cli.stdout_for = None
        A.op_switch("claude", "official")
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertIn("provider switch claude-official", argvs[0])  # O4 r2: first
        self.assertIn("proxy -a claude disable", argvs[1])
        self.assertFalse(any("enable" in a for a in argvs))

    def test_codex_switch_reenables_proxy_route_after_switch(self):
        # Codex reaches third parties only through the local proxy route
        # (default OFF). The worker serves the upstream token it captures
        # from live auth.json at ENABLE time (live-probed 2026-08-21) — so
        # the route is torn down first, the switch rewrites live files, and
        # only then is it re-enabled to capture the new row's key.
        toml_cfg = (
            'model_provider = "deepseek"\n[model_providers.deepseek]\n'
            'base_url = "https://api.deepseek.com"\n'
        )
        seed_provider(self.dir, "codex-official", {}, agent="codex", is_current=True,
                      settings={"auth": {}, "config": ""})
        seed_provider(self.dir, "deepseek", {}, agent="codex",
                      settings={"auth": {}, "config": toml_cfg})
        A.op_switch("codex", "deepseek")
        argvs = [" ".join(c.args) for c in self.cli.calls]
        # O4 r2: switch first, disable second (see the claude twin above).
        self.assertIn("switch", argvs[0])
        self.assertIn("proxy -a codex disable", argvs[1])
        self.assertIn("proxy -a codex enable", argvs[2])

    def test_codex_switch_manages_auth_placeholder(self):
        import os as _os
        # Enable path: absent auth.json gets the marker placeholder.
        toml_cfg = 'model_provider = "deepseek"\n[model_providers.deepseek]\nbase_url = "https://x"\n'
        seed_provider(self.dir, "codex-official", {}, agent="codex", is_current=True,
                      settings={"auth": {}, "config": ""})
        seed_provider(self.dir, "deepseek", {}, agent="codex",
                      settings={"auth": {}, "config": toml_cfg})
        A.op_switch("codex", "deepseek")
        auth = self.dir / "auth.json"
        self.assertEqual(auth.read_text(encoding="utf-8").strip(),
                         A._AUTH_PLACEHOLDER)

        # The fake CLI never flips is_current — drive it with direct DB
        # updates between switches, as the real CLI would.
        def set_current(pid: str) -> None:
            db = sqlite3.connect(self.dir / "cc-switch.db")
            db.execute("UPDATE providers SET is_current=0 WHERE app_type='codex'")
            db.execute("UPDATE providers SET is_current=1 WHERE id=? AND app_type='codex'", (pid,))
            db.commit()
            db.close()

        seed_provider(self.dir, "kimi", {}, agent="codex",
                      settings={"auth": {}, "config": toml_cfg.replace("deepseek", "kimi")})
        set_current("deepseek")
        # A REAL login is never overwritten.
        auth.write_text('{"tokens":{"id_token":"real"}}', encoding="utf-8")
        A.op_switch("codex", "kimi")
        self.assertIn("real", auth.read_text(encoding="utf-8"))

        # Back to official: our marker is removed, a real login stays.
        set_current("kimi")
        auth.write_text(A._AUTH_PLACEHOLDER, encoding="utf-8")
        A.op_switch("codex", "official")
        self.assertFalse(auth.exists())
        auth.write_text('{"tokens":{"id_token":"real"}}', encoding="utf-8")
        set_current("kimi")
        A.op_switch("codex", "deepseek")
        set_current("deepseek")
        A.op_switch("codex", "official")
        self.assertTrue(auth.exists())

        # User report 2026-08-21: a BARE third-party key left in auth.json
        # silences the not-configured guide under official-direct — removed
        # on cancel (the provider row keeps its copy for switch-back); a
        # tokens login (with or without a key) is never touched.
        set_current("deepseek")
        auth.write_text('{"OPENAI_API_KEY":"sk-third-party-42"}',
                        encoding="utf-8")
        A.op_switch("codex", "official")
        self.assertFalse(auth.exists())
        set_current("deepseek")
        auth.write_text(
            '{"OPENAI_API_KEY":"sk-third-party-42","tokens":{"id_token":"t"}}',
            encoding="utf-8")
        A.op_switch("codex", "official")
        self.assertTrue(auth.exists())

    def test_codex_switch_to_official_disables_route(self):
        seed_provider(self.dir, "deepseek", {}, agent="codex", is_current=True,
                      settings={"auth": {}, "config": 'model_provider = "d"\n'})
        seed_provider(self.dir, "codex-official", {}, agent="codex",
                      settings={"auth": {}, "config": ""})
        A.op_switch("codex", "official")
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertIn("switch", argvs[0])  # O4 r2: switch first
        self.assertIn("proxy -a codex disable", argvs[1])

    def test_switch_to_current_is_idempotent_plus_tail_heal(self):
        # Idempotent success for the current row — but the cheap post-heal
        # (route verify) runs; unparseable show output skips verification
        # and no other CLI call is made.
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        A.op_switch("claude", "deepseek")
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertEqual(argvs, ["proxy -a claude show"])

    def test_switch_to_empty_config_row_uses_pty_path(self):
        # Empty-config rows (official/direct placeholders) prompt upstream —
        # the adapter answers them under a pty via `script -qec` + "y".
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "claude-official", {})
        self.cli.stdout_for = None
        A.op_switch("claude", "claude-official")
        pty_calls = [c for c in self.cli.calls if c.args[0] == "script"]
        self.assertEqual(len(pty_calls), 1)
        call = pty_calls[0]
        self.assertIn("provider switch claude-official", call.args[2])
        self.assertEqual(call.stdin_text, "y\ny\n")

    def test_switch_official_pseudo_target_maps_to_agent_row(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "claude-official", {})
        self.cli.stdout_for = None
        A.op_switch("claude", "official")
        argvs = [" ".join(c.args) for c in self.cli.calls]
        self.assertTrue(any("provider switch claude-official" in a for a in argvs))

    def test_switch_injection_guard_rejects_bad_ids(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "bad; rm -rf /", {})
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_switch("claude", "bad; rm -rf /")
        self.assertEqual(ctx.exception.code, A.ERR_BAD_REQUEST)
        # The dance's route calls may run first — the GUARD is that the bad
        # id never reaches any shell command string.
        for call in self.cli.calls:
            self.assertNotIn("bad; rm -rf /", " ".join(call.args))

    def test_switch_unknown_provider(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_switch("claude", "ghost")
        self.assertEqual(ctx.exception.code, A.ERR_NOT_FOUND)

    def test_main_switch_envelope(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "zhipu", {"ANTHROPIC_BASE_URL": "https://z"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = A.main(["switch", "--agent", "claude", "--id", "zhipu"])
        self.assertEqual(rc, 0)
        env = json.loads(buf.getvalue())
        self.assertTrue(env["ok"])
        self.assertEqual(env["op"], "switch")


    # --- O4 (opt-batch, D-11, 2026-09-02): switch-path slimming ---

    def test_switch_writes_static_catalog_without_live_fetch(self):
        # The critical path must be ZERO-network for codex: the static
        # catalog lands synchronously, the live /models fetch is spawned in
        # the background instead (it was the p95 culprit at up to ~12s).
        live_called = []
        spawned = []
        orig_live = A._live_fetch_catalog_ids
        orig_spawn = A._spawn_catalog_refresh
        A._live_fetch_catalog_ids = lambda *a, **k: live_called.append(1) or []
        A._spawn_catalog_refresh = lambda agent: spawned.append(agent)
        self.addCleanup(setattr, A, "_live_fetch_catalog_ids", orig_live)
        self.addCleanup(setattr, A, "_spawn_catalog_refresh", orig_spawn)

        import socket as _socket
        listener = _socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        self.addCleanup(listener.close)
        self._install_show_cli(
            lambda args: f"- Codex: enabled, configured {port}\n"
            if "show" in args else None)
        toml_cfg = ('model_provider = "deepseek"\n[model_providers.deepseek]\n'
                    'base_url = "https://api.deepseek.com"\n')
        seed_provider(self.dir, "deepseek", {}, agent="codex",
                      settings={"auth": {}, "config": toml_cfg,
                                "modelCatalog": {"models": [
                                    {"model": "deepseek-v4-pro",
                                     "contextWindow": 1000000}]}})
        A.op_switch("codex", "deepseek")
        self.assertEqual(live_called, [], "live fetch must stay off the switch path")
        self.assertEqual(spawned, ["codex"], "background refresh must spawn once")
        # The STATIC catalog still landed synchronously.
        self.assertIn("deepseek-v4-pro",
                      (self.dir / "aisc-model-catalog.json")
                      .read_text(encoding="utf-8"))

    def test_spawn_catalog_refresh_is_codex_only_and_silent_on_failure(self):
        # claude needs no catalog refresh; a failed Popen (path absent on
        # the host) is silently dropped — the spawn is best-effort.
        A._spawn_catalog_refresh("claude")  # no-op, no exception
        A._spawn_catalog_refresh("codex")   # host: path absent -> OSError swallowed

    def test_idempotent_switch_probes_the_route_once(self):
        # Fast path: a single TCP attempt (not the 4× retry ring) — a
        # healthy route answers in ~ms; a miss still heals via full recovery.
        attempts_seen = []
        orig = A._tcp_listening
        A._tcp_listening = (
            lambda port, attempts=4, delay=0.4:
            attempts_seen.append(attempts) or True)
        self.addCleanup(setattr, A, "_tcp_listening", orig)
        self._install_show_cli(
            lambda args: f"- Codex: enabled, configured 12345\n"
            if "show" in args else None)
        toml_cfg = ('model_provider = "deepseek"\n[model_providers.deepseek]\n'
                    'base_url = "https://api.deepseek.com"\n')
        seed_provider(self.dir, "deepseek", {}, agent="codex", is_current=True,
                      settings={"auth": {}, "config": toml_cfg})
        A.op_switch("codex", "deepseek")
        self.assertEqual(attempts_seen, [1])


class DeleteTests(AdapterTestCase):
    def test_delete_current_switches_away_first(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "zhipu", {"ANTHROPIC_BASE_URL": "https://z"})
        A.op_delete("claude", "deepseek")
        # switch via CLI, delete via adapter DB transaction.
        self.assertEqual(
            [c.args[-1] for c in self.cli.calls if "switch" in c.args],
            ["zhipu"],
        )
        self.assertNotIn("deepseek", {r["id"] for r in A.op_list("claude")})

    def test_delete_requires_confirm_at_host_but_sole_current_fails_here(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        with self.assertRaises(A.AdapterError):
            A.op_delete("claude", "deepseek")


class EnvelopeTests(AdapterTestCase):
    def test_main_list_envelope_shape(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = A.main(["list", "--agent", "claude"])
        self.assertEqual(rc, 0)
        env = json.loads(buf.getvalue())
        self.assertEqual(env["schema"], "aisc.cc-switch-provider/v1")
        self.assertTrue(env["ok"])
        self.assertEqual(env["op"], "list")
        self.assertTrue(env["operation_id"])
        self.assertNotIn("sk-live-abcdef123456", buf.getvalue())

    def test_main_error_envelope(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = A.main(["delete", "--agent", "claude", "--id", "ghost"])
        self.assertEqual(rc, 1)
        env = json.loads(buf.getvalue())
        self.assertFalse(env["ok"])
        self.assertEqual(env["error"]["code"], A.ERR_NOT_FOUND)


class SqliteBackedCliTests(AdapterTestCase):
    """A fake cc-switch that REALLY writes the temp DB — real BEGIN IMMEDIATE
    concurrency for the dance and parallel writers."""

    def _row_meta(self, pid: str, agent: str) -> dict:
        db = sqlite3.connect(self.dir / "cc-switch.db")
        try:
            return json.loads(db.execute(
                "SELECT meta FROM providers WHERE id=? AND app_type=?",
                (pid, agent),
            ).fetchone()[0])
        finally:
            db.close()

    def test_simple_codex_add_seeds_preset_api_format_meta(self):
        # The router routes by meta.apiFormat; since S9a every preset
        # declares anthropic (the router translates Responses to Anthropic).
        # Upstream add seeds its own default — the adapter must fix the meta
        # or the fresh row routes wrong.
        self._install_sql_cli()
        A.op_add("codex", {"mode": "simple", "id": "deepseek",
                           "provider": "deepseek", "api_key": "sk-live-1"})
        self.assertEqual(self._row_meta("deepseek", "codex").get("apiFormat"),
                         "anthropic")

    def test_codex_edit_restores_row_meta_through_the_dance(self):
        # The re-add seeds upstream defaults (apiFormat=openai_responses);
        # the original meta must be restored or every routed request 404s.
        self._install_sql_cli()
        seed_provider(self.dir, "codex-official", {}, agent="codex",
                      is_current=True, settings={"auth": {}, "config": ""})
        seed_provider(self.dir, "deepseek", {}, agent="codex",
                      settings={"auth": {}, "config": (
                          'model_provider = "deepseek"\n'
                          '[model_providers.deepseek]\nbase_url = "https://x"\n'
                      )}, meta={"apiFormat": "anthropic"})
        A.op_edit("codex", "deepseek", {"patch": {"name": "DeepSeek"}})
        self.assertEqual(self._row_meta("deepseek", "codex").get("apiFormat"),
                         "anthropic")

    def _install_sql_cli(self):
        dir_path = self.dir

        def sql_cli(args, stdin_text, secrets):
            argv = list(args)
            try:
                if "add" in argv:
                    body = json.loads(stdin_text)
                    pid = argv[argv.index("--id") + 1]
                    agent = argv[argv.index("-a") + 1]
                    # Mirror upstream's seeded defaults: codex rows get
                    # apiFormat=openai_responses unless someone fixes it.
                    seeded_meta = (
                        '{"commonConfigEnabled":false,'
                        '"apiFormat":"openai_responses"}'
                        if agent == "codex" else "{}"
                    )
                    conn = sqlite3.connect(dir_path / "cc-switch.db", timeout=15)
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "INSERT INTO providers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, agent, pid,
                         json.dumps(body), "https://x", "custom", 1, 0, "",
                         None, None, seeded_meta, 1, 0),
                    )
                    conn.commit()
                    conn.close()
                elif "delete" in argv:
                    pid = argv[-1]
                    conn = sqlite3.connect(dir_path / "cc-switch.db", timeout=15)
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "DELETE FROM providers WHERE id=? AND app_type=?",
                        (pid, argv[argv.index("-a") + 1]),
                    )
                    conn.commit()
                    conn.close()
                return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")
            except sqlite3.IntegrityError as exc:
                return subprocess.CompletedProcess(argv, 1, stdout=str(exc), stderr="")

        A.run_cli = sql_cli
        self.addCleanup(setattr, A, "run_cli", self._orig_cli)

    def test_two_parallel_adds_both_persist(self):
        self._install_sql_cli()
        errors = []

        def worker(pid: str):
            try:
                A.op_add("claude", {"mode": "custom", "id": pid, "name": pid,
                                    "base_url": f"https://{pid}",
                                    "api_key": f"sk-{pid}-key-9999"})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(f"p{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        ids = {row["id"] for row in A.op_list("claude")}
        self.assertTrue({f"p{i}" for i in range(4)} <= ids)

    def test_snapshot_read_survives_writer_lock(self):
        self._install_sql_cli()
        seed_provider(self.dir, "deepseek", CLAUDE_ENV)
        hold = sqlite3.connect(self.dir / "cc-switch.db", timeout=15)
        hold.execute("BEGIN IMMEDIATE")
        hold.execute(
            "UPDATE providers SET notes='x' WHERE id='deepseek'"
        )
        try:
            # Reader with busy_timeout must still snapshot (WAL/rollback or
            # not — the adapter must not crash, worst case it waits).
            rows = A.read_snapshot("claude")
            self.assertTrue(any(r["id"] == "deepseek" for r in rows))
        finally:
            hold.rollback()
            hold.close()




class RoleEnvAndFetchModelsTests(AdapterTestCase):
    """IDEA-5 (5c): the secret-free role_env view, known_models for preset
    rows, and the fetch-models op's defensive parse + degrade."""

    def test_role_env_whitelist_never_carries_credentials(self):
        env = {
            "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "sk-live-abcdef123456",
            "ANTHROPIC_MODEL": "deepseek-v4-pro[1m]",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash",
            "ANTHROPIC_SMALL_FAST_MODEL": "user-added",
        }
        seed_provider(self.dir, "deepseek", env)
        view = {p["id"]: p for p in A.op_list("claude")}["deepseek"]
        self.assertEqual(view["role_env"]["ANTHROPIC_MODEL"], "deepseek-v4-pro[1m]")
        self.assertEqual(view["role_env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"],
                         "deepseek-v4-flash")
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", view["role_env"])
        self.assertNotIn("ANTHROPIC_SMALL_FAST_MODEL", view["role_env"])
        # Secrets still only ever appear as the mask.
        self.assertNotIn("sk-live-abcdef123456", json.dumps(view))
        # codex rows carry the empty shape (mapping UI is claude-only).
        seed_provider(self.dir, "codexprov", {"config": 'model_provider = "x"'},
                      agent="codex")
        codex_view = {p["id"]: p for p in A.op_list("codex")}["codexprov"]
        self.assertEqual(codex_view["role_env"], {})
        self.assertEqual(codex_view["known_models"], [])

    def test_known_models_for_preset_rows(self):
        seed_provider(self.dir, "deepseek", {"ANTHROPIC_BASE_URL": "https://x"})
        view = {p["id"]: p for p in A.op_list("claude")}["deepseek"]
        for historical in ("deepseek-chat", "deepseek-v4-pro",
                           "deepseek-v4-pro[1m]", "deepseek-v4-flash"):
            self.assertIn(historical, view["known_models"])
        # Custom rows get nothing.
        seed_provider(self.dir, "mine", {"ANTHROPIC_BASE_URL": "https://y"})
        custom = {p["id"]: p for p in A.op_list("claude")}["mine"]
        self.assertEqual(custom["known_models"], [])

    def test_fetch_models_cli_text_is_last_resort_and_filters_headers(self):
        # Chain-first order: the JSON candidates all fail (stubbed), the CLI
        # subcommand succeeds with a human TABLE — the tightened parse must
        # keep the real ids and drop header words (Model/Fetched/model).
        seed_provider(self.dir, "deepseek", {"ANTHROPIC_BASE_URL": "https://x"})
        self.cli.stub_stdout(
            "Fetched models for 'DeepSeek':\n"
            "Endpoint: https://api.deepseek.com\n\n"
            "  Model             ID\n"
            "  deepseek-chat     deepseek-chat\n"
            "  deepseek-reasoner\n"
            "  default: deepseek-v4-flash[1m]\n"
        )
        orig_http = A._http_get_json
        A._http_get_json = lambda url, headers, timeout: (404, None)
        try:
            result = A.op_fetch_models("claude", "deepseek")
        finally:
            A._http_get_json = orig_http
        self.assertTrue(result["available"])
        self.assertEqual(result["models"],
                         ["deepseek-chat", "deepseek-reasoner",
                          "deepseek-v4-flash[1m]"])
        for junk in ("Model", "Fetched", "model", "Endpoint"):
            self.assertNotIn(junk, result["models"])
        argv = self.cli.argv()
        self.assertIn(["-a", "claude", "provider", "fetch-models", "deepseek"],
                      argv)

    def test_fetch_models_degrades_on_upstream_failure(self):
        seed_provider(self.dir, "deepseek", {"ANTHROPIC_BASE_URL": "https://x"})
        self.cli.stub_stdout(
            "Fetching models for 'DeepSeek'...\n"
            "Endpoint: https://api.deepseek.com/anthropic\n\n"
            "Error: HTTP 401 Unauthorized\n"
        )
        # No fallback base to derive (https://x has no /anthropic suffix and
        # the stub HTTP seam returns nothing) → documented degrade.
        orig_http = A._http_get_json
        A._http_get_json = lambda url, headers, timeout: (404, None)
        try:
            result = A.op_fetch_models("claude", "deepseek")
        finally:
            A._http_get_json = orig_http
        self.assertFalse(result["available"])
        self.assertEqual(result["models"], [])
        self.assertIn("401", result["message"])

    def test_fetch_models_falls_back_to_openai_compatible_endpoint(self):
        # Ported upstream chain (services/model_fetch.rs): the anthropic-compat
        # candidate 401s, then the stripped-root /v1/models wins. The CLI also
        # failed — only the fallback delivers.
        seed_provider(self.dir, "prov", {
            "ANTHROPIC_BASE_URL": "https://api.prov.example/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "sk-live-abcdef123456",
        })
        self.cli.stub_stdout(
            "Fetching models for 'prov'...\nError: HTTP 401 Unauthorized\n"
        )
        calls: list[str] = []

        def fake_http(url, headers, timeout):
            calls.append(url)
            if url == "https://api.prov.example/v1/models":
                self.assertIn("Bearer sk-live-abcdef123456",
                              headers.get("Authorization", ""))
                return 200, {"data": [{"id": "prov-xl"}, {"id": "prov-lite"}]}
            return 401, None

        orig_http = A._http_get_json
        A._http_get_json = fake_http
        try:
            result = A.op_fetch_models("claude", "prov")
        finally:
            A._http_get_json = orig_http
        self.assertEqual(calls[0], "https://api.prov.example/anthropic/v1/models")
        self.assertTrue(result["available"])
        self.assertEqual(result["models"], ["prov-xl", "prov-lite"])
        # The key never leaks into the envelope.
        self.assertNotIn("sk-live-abcdef123456", json.dumps(result))

    def test_fetch_models_uses_unsaved_form_key_override(self):
        # PP r3: the editor's key may not be saved yet — a request-document
        # override (stdin channel, never argv) must drive the upstream call
        # instead of the stored key, and never leak into the envelope.
        seed_provider(self.dir, "prov", {
            "ANTHROPIC_BASE_URL": "https://api.prov.example/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "sk-stored-000000",
        })
        seen: list[str] = []

        def fake_http(url, headers, timeout):
            auth = headers.get("Authorization", "")
            seen.append(auth)
            if "Bearer sk-form-999999" in auth:
                return 200, {"data": [{"id": "prov-xl"}]}
            return 401, None

        orig_http = A._http_get_json
        A._http_get_json = fake_http
        try:
            result = A.op_fetch_models("claude", "prov", {"api_key": "sk-form-999999"})
        finally:
            A._http_get_json = orig_http
        self.assertTrue(result["available"])
        self.assertEqual(result["models"], ["prov-xl"])
        self.assertTrue(seen)
        for auth in seen:
            self.assertNotIn("sk-stored-000000", auth)
        self.assertNotIn("sk-form-999999", json.dumps(result))

    def test_fetch_models_candidate_chain_includes_bare_models(self):
        # DeepSeek-style: only the BARE /models (no /v1) on the stripped root
        # answers — the last candidate in the upstream chain.
        seed_provider(self.dir, "ds", {
            "ANTHROPIC_BASE_URL": "https://api.ds.example/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "sk-live-abcdef123456",
        })
        self.cli.stub_stdout("Fetching models for 'ds'...\nError: HTTP 401\n")

        def fake_http(url, headers, timeout):
            if url == "https://api.ds.example/models":
                # Only answers with the anthropic-style header set.
                if headers.get("x-api-key") == "sk-live-abcdef123456":
                    return 200, {"data": [{"id": "ds-chat"}]}
            return 401, None

        orig_http = A._http_get_json
        A._http_get_json = fake_http
        try:
            result = A.op_fetch_models("claude", "ds")
        finally:
            A._http_get_json = orig_http
        self.assertTrue(result["available"])
        self.assertEqual(result["models"], ["ds-chat"])

    def test_models_url_candidates_rules(self):
        # Plain base: single candidate.
        self.assertEqual(
            A._models_url_candidates("https://x.example"),
            ["https://x.example/v1/models"],
        )
        # Versioned base (paas/v4): /models first.
        self.assertEqual(
            A._models_url_candidates("https://x.example/api/paas/v4"),
            ["https://x.example/api/paas/v4/models",
             "https://x.example/api/paas/v4/v1/models"],
        )
        # Anthropic-compat suffix: as-is + stripped root with BOTH forms.
        self.assertEqual(
            A._models_url_candidates("https://api.ds.example/anthropic/"),
            ["https://api.ds.example/anthropic/v1/models",
             "https://api.ds.example/v1/models",
             "https://api.ds.example/models"],
        )

    def test_fetch_models_unknown_provider_is_adapter_error(self):
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_fetch_models("claude", "ghost")
        self.assertEqual(ctx.exception.code, A.ERR_NOT_FOUND)

    def test_fetch_models_main_envelope_shape(self):
        seed_provider(self.dir, "deepseek", {"ANTHROPIC_BASE_URL": "https://x"})
        self.cli.stub_stdout("deepseek-chat\ndeepseek-reasoner\n")
        buf = io.StringIO()
        # PP r3: main reads an optional stdin request document (empty here).
        with redirect_stdout(buf), mock.patch.object(sys, "stdin", io.StringIO("")):
            code = A.main(["fetch-models", "--agent", "claude", "--id", "deepseek"])
        self.assertEqual(code, 0)
        envelope = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(envelope["ok"])
        self.assertTrue(envelope["fetch_models"]["available"])
        self.assertEqual(envelope["fetch_models"]["models"][0], "deepseek-chat")

    def test_fetch_models_main_reads_stdin_override_key(self):
        seed_provider(self.dir, "prov", {
            "ANTHROPIC_BASE_URL": "https://api.prov.example/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "sk-stored-000000",
        })
        seen: list[str] = []

        def fake_http(url, headers, timeout):
            auth = headers.get("Authorization", "")
            seen.append(auth)
            if "Bearer sk-form-999999" in auth:
                return 200, {"data": [{"id": "prov-xl"}]}
            return 401, None

        orig_http = A._http_get_json
        A._http_get_json = fake_http
        buf = io.StringIO()
        try:
            with redirect_stdout(buf), mock.patch.object(
                    sys, "stdin",
                    io.StringIO(json.dumps({"api_key": "sk-form-999999"}))):
                code = A.main(["fetch-models", "--agent", "claude", "--id", "prov"])
        finally:
            A._http_get_json = orig_http
        self.assertEqual(code, 0)
        envelope = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(envelope["fetch_models"]["available"])
        self.assertTrue(seen and all("sk-stored-000000" not in a for a in seen))
        self.assertNotIn("sk-form-999999", buf.getvalue())


class CodexModelCatalogHookTests(unittest.TestCase):
    """codex-adapt 修复轮：切换后自动生成模型目录（零多余操作目标）——
    catalog 文件写入 + config.toml 顶层键注入/回收，所有权规则不碰
    cc-switch/用户的目录。"""

    def setUp(self):
        import os
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        os.environ["CODEX_CONFIG_DIR"] = str(self.dir / ".codex")
        (self.dir / ".codex").mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.environ.pop, "CODEX_CONFIG_DIR", None)

    def _config(self, text: str):
        (self.dir / ".codex" / "config.toml").write_text(text, encoding="utf-8")

    def _config_text(self) -> str:
        return (self.dir / ".codex" / "config.toml").read_text(encoding="utf-8")

    ROW = {"id": "deepseek", "settings_config": {}}

    def test_switch_writes_catalog_file_and_injects_key(self):
        self._config('model = "deepseek-v4-pro"\n\n[model_providers.deepseek]\nname = "deepseek"\n')
        A._apply_codex_model_catalog(self.ROW)
        catalog = json.loads(
            (self.dir / ".codex" / A._CODEX_CATALOG_FILENAME).read_text(encoding="utf-8"))
        slugs = [m["slug"] for m in catalog["models"]]
        self.assertEqual(slugs, ["deepseek-v4-pro", "deepseek-v4-flash"])
        self.assertEqual(catalog["models"][0]["context_window"], 1_000_000)
        self.assertEqual(catalog["models"][0]["priority"], 1000)
        # serde-required fields present on every entry
        for entry in catalog["models"]:
            for key in ("slug", "display_name", "supported_reasoning_levels",
                        "shell_type", "visibility", "supported_in_api", "priority",
                        "truncation_policy", "base_instructions"):
                self.assertIn(key, entry)
        # codex's post-parse validation requires instructions; the value
        # mirrors cc-switch's own catalog (live-probed 2026-08-21)
        self.assertEqual(
            catalog["models"][0]["base_instructions"],
            "You are Codex, a coding agent. You and the user share the same "
            "workspace and collaborate to achieve the user's goals.",
        )
        # key injected top-level (before the first table header), absolute path
        text = self._config_text()
        self.assertIn(f'model_catalog_json = "{self.dir / ".codex" / A._CODEX_CATALOG_FILENAME}"', text)
        self.assertLess(text.index("model_catalog_json"), text.index("[model_providers"))
        # window fallback key also lands top-level; deepseek preset is
        # anthropic (S9a) → the dead web_search hosted tool is disabled
        self.assertIn("model_context_window = 1000000", text)
        self.assertIn('web_search = "disabled"', text)

    def test_live_model_1m_suffix_cleaned_to_catalog_slug(self):
        # the user's claude-convention typo ([1m]) is rewritten to the clean id
        self._config('model = "deepseek-v4-flash[1m]"\n')
        A._apply_codex_model_catalog(self.ROW)
        self.assertIn('model = "deepseek-v4-flash"', self._config_text())
        self.assertNotIn("[1m]", self._config_text())

    def test_custom_provider_gets_single_row_catalog_from_live_model(self):
        self._config('model = "my-custom-model"\n')
        A._apply_codex_model_catalog({"id": "custom-thing", "settings_config": {}})
        catalog = json.loads(
            (self.dir / ".codex" / A._CODEX_CATALOG_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual([m["slug"] for m in catalog["models"]], ["my-custom-model"])
        self.assertEqual(catalog["models"][0]["context_window"], 128_000)
        self.assertIn("model_catalog_json", self._config_text())

    def test_switch_takes_over_a_stale_foreign_catalog(self):
        # PP r6 (live report 2026-09-03): config.toml pinned cc-switch's own
        # catalog file — written under the PREVIOUS provider via the TUI
        # mapping page. After switching providers that file is a stale list
        # of the OLD provider's models, yet the deference guard kept it
        # pinned. The switch/catalog-sync paths (override_foreign=True) take
        # over: our file, our key, the NEW provider's preset list.
        foreign = self.dir / ".codex" / "cc-switch-model-catalog.json"
        foreign.write_text(json.dumps({"models": [
            {"slug": "deepseek-v4-pro"}, {"slug": "deepseek-v4-flash"},
        ]}), encoding="utf-8")
        self._config(
            'model = "glm-5.3"\n'
            f'model_catalog_json = "{foreign}"\n'
            '\n[model_providers.zhipu]\nname = "zhipu"\n'
        )
        row = {"id": "zhipu", "settings_config": {}}
        # Default (no override) still DEFERS — the idempotent fast path keeps
        # the user's live TUI intent untouched.
        A._apply_codex_model_catalog(row)
        self.assertNotIn(A._CODEX_CATALOG_FILENAME, self._config_text())
        # The switch path's override takes over with the new provider's list.
        A._apply_codex_model_catalog(row, override_foreign=True)
        catalog = json.loads(
            (self.dir / ".codex" / A._CODEX_CATALOG_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual([m["slug"] for m in catalog["models"]], ["glm-5.3"])
        self.assertIn(A._CODEX_CATALOG_FILENAME, self._config_text())
        self.assertNotIn("cc-switch-model-catalog.json", self._config_text())

    def test_catalog_sync_main_envelope_and_takeover(self):
        # PP r6: the catalog-sync main branch passes provider= to _envelope —
        # a live TypeError (the write landed, then the envelope crashed, so
        # every background --live refresh exited nonzero and silently).
        import os
        import sqlite3
        db_dir = self.dir / ".cc-switch"
        db_dir.mkdir(exist_ok=True)
        conn = sqlite3.connect(db_dir / "cc-switch.db")
        conn.execute(
            "CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT, "
            "settings_config TEXT, is_current INTEGER, sort_index INTEGER, "
            "meta TEXT, notes TEXT, website_url TEXT, icon TEXT, "
            "icon_color TEXT)")
        settings = {"config": 'model = "glm-5.3"\n\n[model_providers.zhipu]\n'
                               'name = "zhipu"\n'
                               'base_url = "https://open.bigmodel.cn/api/anthropic"\n'}
        conn.execute(
            "INSERT INTO providers VALUES ('zhipu', 'codex', 'Zhipu', ?, "
            "1, 0, '{}', '', '', '', '')",
            (json.dumps(settings),))
        conn.commit()
        conn.close()
        with mock.patch.dict(
                os.environ,
                {"CC_SWITCH_CONFIG_DIR": str(db_dir),
                 "CODEX_CONFIG_DIR": str(self.dir / ".codex")}):
            self._config('model = "glm-5.3"\n')
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = A.main(["catalog-sync"])
        self.assertEqual(code, 0)
        envelope = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["provider"], "zhipu")
        self.assertIn(A._CODEX_CATALOG_FILENAME, self._config_text())

    # --- S9: live model catalog (spike 05) ----------------------------------

    LIVE_ROW = {
        "id": "deepseek",
        "settings_config": {},
        "settings": {"auth": {"OPENAI_API_KEY": "sk-live-9"}},
    }

    def _config_with_base(self):
        self._config(
            'model = "deepseek-v4-pro"\n\n'
            "[model_providers.deepseek]\n"
            'name = "deepseek"\n'
            'base_url = "https://api.deepseek.com"\n'
        )

    def test_live_fetch_merges_new_ids_behind_curated_rows(self):
        from unittest import mock

        self._config_with_base()
        payload = {"data": [
            {"id": "deepseek-v4-pro"},          # dedupe against curated
            {"id": "deepseek-v4-next"},          # NEW — appended
            {"id": "text-embedding-3"},          # junk — dropped
        ]}
        with mock.patch.object(
            A, "_http_get_json", return_value=(200, payload)
        ) as http:
            A._apply_codex_model_catalog(self.LIVE_ROW)
        self.assertEqual(http.call_count, 1)
        auth_header = http.call_args[0][1]["Authorization"]
        self.assertEqual(auth_header, "Bearer sk-live-9")
        self.assertEqual(http.call_args[0][2], 6.0)  # switch-time budget (CN providers need DNS+TLS+API)
        catalog = json.loads(
            (self.dir / ".codex" / A._CODEX_CATALOG_FILENAME).read_text(encoding="utf-8"))
        slugs = [m["slug"] for m in catalog["models"]]
        self.assertEqual(
            slugs, ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-next"]
        )
        # The appended row inherits the curated family window (1M).
        self.assertEqual(catalog["models"][2]["context_window"], 1_000_000)

    def test_live_fetch_failure_keeps_the_static_catalog(self):
        from unittest import mock

        self._config_with_base()
        with mock.patch.object(A, "_http_get_json", return_value=(0, None)):
            A._apply_codex_model_catalog(self.LIVE_ROW)
        catalog = json.loads(
            (self.dir / ".codex" / A._CODEX_CATALOG_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(
            [m["slug"] for m in catalog["models"]],
            ["deepseek-v4-pro", "deepseek-v4-flash"],
        )

    def test_live_fetch_skipped_without_a_key(self):
        from unittest import mock

        self._config_with_base()
        row = {"id": "deepseek", "settings_config": {}}  # no auth key
        with mock.patch.object(A, "_http_get_json") as http:
            A._apply_codex_model_catalog(row)
        http.assert_not_called()

    def test_merge_caps_and_dedupes(self):
        static = [{"model": "m1", "contextWindow": 1_000_000}]
        merged = A._merge_live_catalog_models(
            static, ["m1"] + [f"gen-{i}" for i in range(80)]
        )
        self.assertEqual(len(merged), 1 + A._LIVE_APPEND_CAP)
        # S9c: version-descending — gen-49 is the highest among the
        # capped-50 appended (gen-0..49), so it sorts first.
        self.assertEqual(merged[0]["model"], "gen-49")
        self.assertIn("m1", [m["model"] for m in merged])  # still present
        self.assertEqual(merged[-1]["contextWindow"], 1_000_000)

    def test_official_switch_removes_our_key_and_file(self):
        self._config(
            'model_catalog_json = "%s"\n\n[t]\na = 1\n'
            % (self.dir / ".codex" / A._CODEX_CATALOG_FILENAME)
        )
        (self.dir / ".codex" / A._CODEX_CATALOG_FILENAME).write_text("{}", encoding="utf-8")
        A._apply_codex_model_catalog(None)
        self.assertNotIn("model_catalog_json", self._config_text())
        self.assertFalse((self.dir / ".codex" / A._CODEX_CATALOG_FILENAME).exists())

    def test_foreign_catalog_value_is_never_touched(self):
        foreign = 'model_catalog_json = "cc-switch-model-catalog.json"\n'
        self._config(foreign)
        A._apply_codex_model_catalog(self.ROW)
        self.assertIn("cc-switch-model-catalog.json", self._config_text())

    def test_row_without_model_or_catalog_removes_our_stale_key(self):
        self._config(
            'model_catalog_json = "%s"\n'
            % (self.dir / ".codex" / A._CODEX_CATALOG_FILENAME)
        )
        A._apply_codex_model_catalog({"id": "x", "settings_config": {}})
        self.assertNotIn("model_catalog_json", self._config_text())


if __name__ == "__main__":
    unittest.main()


class ProviderParityTests(AdapterTestCase):
    """PP (D-12, 2026-09-03): desktop-parity fields — upstream format,
    display columns, and the codex mapping catalog."""

    def test_api_format_priority_meta_over_preset_over_default(self):
        toml = ('model_provider = "d"\n[model_providers.d]\n'
                'base_url = "https://x"\n')
        # meta wins over everything
        row_meta = {"id": "deepseek", "settings": {"auth": {}, "config": toml},
                    "meta": {"apiFormat": "anthropic"}}
        self.assertEqual(A.resolve_api_format("codex", row_meta), "anthropic")
        # no meta -> preset declaration (deepseek preset says anthropic)
        row_preset = {"id": "deepseek", "settings": {"auth": {}, "config": toml},
                      "meta": {}}
        self.assertEqual(A.resolve_api_format("codex", row_preset), "anthropic")
        # unknown id (no preset) -> agent default
        row_unknown = {"id": "my-own", "settings": {"auth": {}, "config": toml},
                       "meta": {}}
        self.assertEqual(A.resolve_api_format("codex", row_unknown),
                         "openai_responses")
        self.assertEqual(A.resolve_api_format("claude", row_unknown), "anthropic")

    def test_provider_view_surfaces_pp_fields_secret_free(self):
        toml = ('model_provider = "d"\n[model_providers.d]\n'
                'base_url = "https://x"\n')
        seed_provider(self.dir, "deepseek", {}, agent="codex", is_current=True,
                      settings={"auth": {"OPENAI_API_KEY": "sk-secret-value-1"},
                                "config": toml,
                                "modelCatalog": {"models": [
                                    {"model": "m1", "contextWindow": 64000,
                                     "display_name": "M One"}]}},
                      meta={"apiFormat": "openai_chat"},
                      notes="my note", website_url="https://deepseek.com",
                      icon="star", icon_color="#ff0")
        views = A.op_list("codex")
        v = next(x for x in views if x["id"] == "deepseek")
        self.assertEqual(v["api_format"], "openai_chat")
        self.assertEqual(v["notes"], "my note")
        self.assertEqual(v["website_url"], "https://deepseek.com")
        self.assertEqual(v["icon"], "star")
        self.assertEqual(v["icon_color"], "#ff0")
        self.assertEqual(v["model_catalog"], [
            {"model": "m1", "display_name": "M One", "context_window": 64000}])
        # secret-free: no key anywhere in the view
        self.assertNotIn("sk-secret-value-1", json.dumps(views))

    def test_edit_patch_writes_format_and_display_columns_through_dance(self):
        self._install_dance_cli()
        seed_provider(self.dir, "kimi", {"ANTHROPIC_BASE_URL": "https://kimi"})
        seed_provider(self.dir, "zhipu", CLAUDE_ENV, is_current=True,
                      notes="old note", icon="old-icon")
        views = A.op_edit("claude", "zhipu", {"patch": {
            "api_format": "openai_responses",
            "notes": "new note",
            "icon": "zap",
            "icon_color": "#0f0",
        }})
        v = next(x for x in views if x["id"] == "zhipu")
        self.assertEqual(v["api_format"], "openai_responses")
        self.assertEqual(v["notes"], "new note")
        self.assertEqual(v["icon"], "zap")
        self.assertEqual(v["icon_color"], "#0f0")
        # (currency through the dance is covered by the EditDance suite; the
        # dance CLI does not flip db is_current on switch)

    def test_edit_rejects_unknown_api_format(self):
        seed_provider(self.dir, "zhipu", CLAUDE_ENV, is_current=True)
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_edit("claude", "zhipu", {"patch": {"api_format": "grpc"}})
        self.assertIn("api_format", ctx.exception.message)

    def test_add_persists_extras(self):
        self._install_dance_cli()
        views = A.op_add("claude", {
            "mode": "custom", "id": "acme", "name": "Acme",
            "base_url": "https://acme", "api_key": "sk-acme-key-123",
            "api_format": "openai_chat",
            "notes": "acme note", "website_url": "https://acme.dev",
            "icon": "bolt", "icon_color": "#00f",
        })
        v = next(x for x in views if x["id"] == "acme")
        self.assertEqual(v["api_format"], "openai_chat")
        self.assertEqual(v["notes"], "acme note")
        self.assertEqual(v["website_url"], "https://acme.dev")
        self.assertEqual(v["icon"], "bolt")
        self.assertEqual(v["icon_color"], "#00f")

    def test_codex_edit_mapping_patch_replaces_catalog(self):
        self._install_dance_cli()
        toml = ('model_provider = "d"\n[model_providers.d]\n'
                'base_url = "https://x"\n')
        seed_provider(self.dir, "kimi", {}, agent="codex",
                      settings={"auth": {}, "config": toml + 'x = "k"\n'})
        seed_provider(self.dir, "deepseek", {}, agent="codex", is_current=True,
                      settings={"auth": {}, "config": toml,
                                "modelCatalog": {"models": [
                                    {"model": "old-model", "contextWindow": 1}]}})
        views = A.op_edit("codex", "deepseek", {"patch": {
            "model_catalog": {"models": [
                {"model": "new-a", "contextWindow": 128000,
                 "display_name": "A"},
                {"model": "", "contextWindow": 5},      # dropped: no model
                {"model": "new-b"},                     # default window
            ]},
        }})
        v = next(x for x in views if x["id"] == "deepseek")
        self.assertEqual(
            v["model_catalog"],
            [{"model": "new-a", "display_name": "A", "context_window": 128000},
             {"model": "new-b", "display_name": "", "context_window": 128000}],
        )
