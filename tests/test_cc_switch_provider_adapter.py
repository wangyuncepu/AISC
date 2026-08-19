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
                  name=None, agent="claude", settings=None):
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
             "https://x", "custom", 1, 0, "", None, None, "{}",
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
        # Fail ONLY the first add (the re-add); the restore add must succeed.
        first_add_failed = []

        def fail_first_add(args, stdin_text, secrets):
            call = FakeCall(list(args), stdin_text)
            self.cli.calls.append(call)
            if "add" in args and not first_add_failed:
                first_add_failed.append(True)
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

        A.run_cli = fail_first_add
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_edit("claude", "zhipu", {"patch": {"model": "x"}})
        self.assertEqual(ctx.exception.code, A.ERR_CLI)
        # Restore attempted: delete, add(fail), add(restore)
        adds = [c for c in self.cli.calls if "add" in c.args]
        self.assertEqual(len(adds), 2)
        restore = json.loads(adds[1].stdin_text)
        self.assertEqual(restore["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-zhipu-key-2222")
        self.assertEqual(restore["env"]["ANTHROPIC_BASE_URL"],
                         "https://open.bigmodel.cn/api/anthropic")

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


class SwitchTests(AdapterTestCase):
    def test_switch_runs_cli_switch_and_returns_snapshot(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "zhipu", {"ANTHROPIC_BASE_URL": "https://z"})
        providers = A.op_switch("claude", "zhipu")
        self.assertEqual(len(self.cli.calls), 1)
        argv = self.cli.calls[0].args
        self.assertIn("switch", argv)
        self.assertEqual(argv[-1], "zhipu")
        # snapshot returned unchanged (the CLI owns is_current truth)
        self.assertEqual([p["id"] for p in providers][0], "deepseek")

    def test_codex_switch_enables_proxy_route_first(self):
        # Codex reaches third parties only through the local proxy route
        # (default OFF) — the adapter enables it before switching.
        toml_cfg = (
            'model_provider = "deepseek"\n[model_providers.deepseek]\n'
            'base_url = "https://api.deepseek.com"\n'
        )
        seed_provider(self.dir, "codex-official", {}, agent="codex", is_current=True,
                      settings={"auth": {}, "config": ""})
        seed_provider(self.dir, "deepseek", {}, agent="codex",
                      settings={"auth": {}, "config": toml_cfg})
        A.op_switch("codex", "deepseek")
        first = " ".join(self.cli.calls[0].args)
        self.assertIn("proxy -a codex enable", first)
        self.assertIn("switch", " ".join(self.cli.calls[1].args))

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

    def test_codex_switch_to_official_disables_route(self):
        seed_provider(self.dir, "deepseek", {}, agent="codex", is_current=True,
                      settings={"auth": {}, "config": 'model_provider = "d"\n'})
        seed_provider(self.dir, "codex-official", {}, agent="codex",
                      settings={"auth": {}, "config": ""})
        A.op_switch("codex", "official")
        self.assertIn("proxy -a codex disable", " ".join(self.cli.calls[0].args))

    def test_switch_to_current_is_idempotent_no_cli(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        A.op_switch("claude", "deepseek")
        self.assertEqual(self.cli.calls, [])

    def test_switch_to_empty_config_row_uses_pty_path(self):
        # Empty-config rows (official/direct placeholders) prompt upstream —
        # the adapter answers them under a pty via `script -qec` + "y".
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "claude-official", {})
        self.cli.stdout_for = None
        A.op_switch("claude", "claude-official")
        call = self.cli.calls[0]
        self.assertEqual(call.args[0], "script")
        self.assertIn("provider switch claude-official", call.args[2])
        self.assertEqual(call.stdin_text, "y\ny\n")

    def test_switch_official_pseudo_target_maps_to_agent_row(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "claude-official", {})
        A.op_switch("claude", "official")
        self.assertIn("provider switch claude-official", self.cli.calls[0].args[2])

    def test_switch_injection_guard_rejects_bad_ids(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "bad; rm -rf /", {})
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_switch("claude", "bad; rm -rf /")
        self.assertEqual(ctx.exception.code, A.ERR_BAD_REQUEST)
        self.assertEqual(self.cli.calls, [])

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

    def _install_sql_cli(self):
        dir_path = self.dir

        def sql_cli(args, stdin_text, secrets):
            argv = list(args)
            try:
                if "add" in argv:
                    body = json.loads(stdin_text)
                    pid = argv[argv.index("--id") + 1]
                    conn = sqlite3.connect(dir_path / "cc-switch.db", timeout=15)
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "INSERT INTO providers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, argv[argv.index("-a") + 1], pid,
                         json.dumps(body), "https://x", "custom", 1, 0, "",
                         None, None, "{}", 1, 0),
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

    def test_fetch_models_parses_lines_and_label_pairs(self):
        seed_provider(self.dir, "deepseek", {"ANTHROPIC_BASE_URL": "https://x"})
        self.cli.stub_stdout(
            "Fetching models for 'DeepSeek'...\n"
            "Endpoint: https://api.deepseek.com/anthropic\n\n"
            "- deepseek-chat\n"
            "deepseek-reasoner\n"
            "  default: deepseek-v4-flash[1m]\n"
        )
        result = A.op_fetch_models("claude", "deepseek")
        self.assertTrue(result["available"])
        self.assertEqual(result["models"],
                         ["deepseek-chat", "deepseek-reasoner",
                          "deepseek-v4-flash[1m]"])
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
        result = A.op_fetch_models("claude", "deepseek")
        self.assertFalse(result["available"])
        self.assertEqual(result["models"], [])
        self.assertIn("401", result["message"])

    def test_fetch_models_unknown_provider_is_adapter_error(self):
        with self.assertRaises(A.AdapterError) as ctx:
            A.op_fetch_models("claude", "ghost")
        self.assertEqual(ctx.exception.code, A.ERR_NOT_FOUND)

    def test_fetch_models_main_envelope_shape(self):
        seed_provider(self.dir, "deepseek", {"ANTHROPIC_BASE_URL": "https://x"})
        self.cli.stub_stdout("deepseek-chat\ndeepseek-reasoner\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = A.main(["fetch-models", "--agent", "claude", "--id", "deepseek"])
        self.assertEqual(code, 0)
        envelope = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(envelope["ok"])
        self.assertTrue(envelope["fetch_models"]["available"])
        self.assertEqual(envelope["fetch_models"]["models"][0], "deepseek-chat")


if __name__ == "__main__":
    unittest.main()
