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

    def __call__(self, args, stdin_text, secrets):
        call = FakeCall(list(args), stdin_text)
        self.calls.append(call)
        for marker, message in self.fail_on.items():
            if marker in " ".join(args):
                return subprocess.CompletedProcess(args, 1, stdout="", stderr=message)
        return subprocess.CompletedProcess(args, 0, stdout="✓ ok (API Key: sk-leak)", stderr="")

    def argv(self) -> list[list[str]]:
        return [c.args for c in self.calls]


class AdapterTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        create_db(self.dir)
        self._env = {"CC_SWITCH_CONFIG_DIR": str(self.dir)}
        self._patcher = mock.patch.dict("os.environ", self._env, clear=False)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.cli = RecordingCli()
        self._orig_cli = A.run_cli
        A.run_cli = self.cli
        self.addCleanup(setattr, A, "run_cli", self._orig_cli)


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
        kinds = []
        for call in self.cli.calls:
            if "delete" in call.args:
                kinds.append("delete")
            elif "add" in call.args:
                kinds.append("add")
            elif "switch" in call.args:
                kinds.append("switch")
        self.assertEqual(kinds, ["delete", "add"])  # no switch dance needed
        sent = json.loads(self.cli.calls[1].stdin_text)
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
        self.assertEqual(kinds, [
            ("switch", "zhipu"),
            ("delete", "deepseek"),
            ("add", "deepseek"),
            ("switch", "deepseek"),
        ])
        # The re-add carries the FULL preserved settings (incl. old token).
        sent = json.loads(self.cli.calls[2].stdin_text)
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


class DeleteTests(AdapterTestCase):
    def test_delete_current_switches_away_first(self):
        seed_provider(self.dir, "deepseek", CLAUDE_ENV, is_current=True)
        seed_provider(self.dir, "zhipu", {"ANTHROPIC_BASE_URL": "https://z"})
        A.op_delete("claude", "deepseek")
        self.assertEqual(
            ["switch" if "switch" in c.args else "delete" for c in self.cli.calls],
            ["switch", "delete"],
        )

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


if __name__ == "__main__":
    unittest.main()
