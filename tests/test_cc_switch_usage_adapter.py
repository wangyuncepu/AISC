"""IDEA-2 2c: the in-container adapter ``usage`` op.

Hermetic: temp cc-switch.db seeded with ``providers`` + ``proxy_request_logs``
rows (both epoch-seconds and epoch-milliseconds variants for the unit
sniff); table-missing and empty-table degradation must stay ``ok=true``.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "container" / "aisc-cc-provider"

_loader = SourceFileLoader("aisc_cc_usage_adapter", str(ADAPTER_PATH))
_spec = importlib.util.spec_from_loader("aisc_cc_usage_adapter", _loader)
assert _spec and _spec.loader
A = importlib.util.module_from_spec(_spec)
_loader.exec_module(A)

NOW_S = 1787100000  # fixed epoch-seconds anchor
NOW_MS = NOW_S * 1000

_LOGS_DDL = """
CREATE TABLE proxy_request_logs (
    request_id TEXT PRIMARY KEY, provider_id TEXT NOT NULL, app_type TEXT NOT NULL,
    model TEXT NOT NULL, request_model TEXT, pricing_model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    input_token_semantics INTEGER NOT NULL DEFAULT 0,
    input_cost_usd TEXT NOT NULL DEFAULT '0', output_cost_usd TEXT NOT NULL DEFAULT '0',
    cache_read_cost_usd TEXT NOT NULL DEFAULT '0',
    cache_creation_cost_usd TEXT NOT NULL DEFAULT '0',
    total_cost_usd TEXT NOT NULL DEFAULT '0', latency_ms INTEGER NOT NULL,
    first_token_ms INTEGER, duration_ms INTEGER, status_code INTEGER NOT NULL,
    error_message TEXT, session_id TEXT, provider_type TEXT,
    is_streaming INTEGER NOT NULL DEFAULT 0, cost_multiplier TEXT NOT NULL DEFAULT '1.0',
    created_at INTEGER NOT NULL, data_source TEXT NOT NULL DEFAULT 'proxy'
)
"""

_PROVIDERS_DDL = """
CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT,
    settings_config TEXT, is_current INTEGER, sort_index INTEGER)
"""


def _make_db(dir_path: Path, *, with_logs: bool = True, with_providers: bool = True):
    conn = sqlite3.connect(dir_path / "cc-switch.db")
    if with_providers:
        conn.execute(_PROVIDERS_DDL)
        conn.execute(
            "INSERT INTO providers (id, app_type, name, settings_config, "
            "is_current, sort_index) VALUES ('deepseek', 'claude', 'DeepSeek', "
            "'{}', 1, 0)")
        conn.execute(
            "INSERT INTO providers (id, app_type, name, settings_config, "
            "is_current, sort_index) VALUES ('kimi', 'codex', 'Kimi', "
            "'{}', 0, 0)")
    if with_logs:
        conn.execute(_LOGS_DDL)
    return conn


def _insert_log(conn, *, rid, pid, app, model, created, status=200,
                tok_in=100, tok_out=50, cache_r=10, cache_w=5, cost="0.01"):
    conn.execute(
        "INSERT INTO proxy_request_logs (request_id, provider_id, app_type, model, "
        "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, "
        "total_cost_usd, latency_ms, status_code, created_at, data_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 120, ?, ?, 'proxy')",
        (rid, pid, app, model, tok_in, tok_out, cache_r, cache_w, cost, status,
         created),
    )


def _run_main(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = A.main(argv)
    return code, json.loads(buf.getvalue().strip().splitlines()[-1])


class UsageOpTests(unittest.TestCase):
    def _env(self, dir_path: Path):
        return {"CC_SWITCH_CONFIG_DIR": str(dir_path)}

    def test_aggregates_per_provider_with_name_join_and_cutoff(self):
        with tempfile.TemporaryDirectory() as td:
            dp = Path(td)
            conn = _make_db(dp)
            # Three rows inside the window (one failing), one ancient row.
            _insert_log(conn, rid="r1", pid="deepseek", app="claude",
                        model="deepseek-chat", created=NOW_S - 100)
            _insert_log(conn, rid="r2", pid="deepseek", app="claude",
                        model="deepseek-chat", created=NOW_S - 50, status=500)
            _insert_log(conn, rid="r3", pid="kimi", app="codex",
                        model="kimi-k2", created=NOW_S - 10, cost="2.5")
            _insert_log(conn, rid="r0", pid="deepseek", app="claude",
                        model="deepseek-chat", created=NOW_S - 90 * 86400)
            conn.commit()
            conn.close()

            with mock.patch.dict("os.environ", self._env(dp)):
                code, envelope = _run_main(["usage", "--since", str(NOW_S - 86400)])
            self.assertEqual(code, 0)
            self.assertTrue(envelope["ok"])
            usage = envelope["usage"]
            self.assertTrue(usage["available"])
            self.assertEqual(usage["unit"], "s")
            by_key = {(p["app"], p["provider_id"]): p for p in usage["providers"]}
            ds = by_key[("claude", "deepseek")]
            self.assertEqual(ds["provider_name"], "DeepSeek")
            self.assertEqual(ds["requests"], 2)
            self.assertEqual(ds["success"], 1)
            self.assertEqual(ds["failed"], 1)
            # tokens_total = (in+out+cache_read+cache_creation) summed over rows
            self.assertEqual(ds["tokens_total"], 2 * (100 + 50 + 10 + 5))
            self.assertAlmostEqual(ds["cost_estimate"], 0.02, places=6)
            km = by_key[("codex", "kimi")]
            self.assertEqual(km["requests"], 1)
            self.assertEqual(km["cost_estimate"], 2.5)
            models = {(m["app"], m["model"]): m for m in usage["models"]}
            self.assertEqual(models[("claude", "deepseek-chat")]["tokens_in"], 200)

    def test_millisecond_epochs_are_sniffed(self):
        with tempfile.TemporaryDirectory() as td:
            dp = Path(td)
            conn = _make_db(dp)
            _insert_log(conn, rid="m1", pid="deepseek", app="claude",
                        model="m", created=NOW_MS - 1000)
            _insert_log(conn, rid="m2", pid="deepseek", app="claude",
                        model="m", created=NOW_MS - 40 * 86400 * 1000)
            conn.commit()
            conn.close()
            with mock.patch.dict("os.environ", self._env(dp)):
                code, envelope = _run_main(["usage", "--since", str(NOW_S - 86400)])
            self.assertEqual(code, 0)
            usage = envelope["usage"]
            self.assertEqual(usage["unit"], "ms")
            self.assertEqual(usage["providers"][0]["requests"], 1)

    def test_missing_table_degrades_to_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            dp = Path(td)
            conn = _make_db(dp, with_logs=False)
            conn.commit()
            conn.close()
            with mock.patch.dict("os.environ", self._env(dp)):
                code, envelope = _run_main(["usage", "--since", "0"])
            self.assertEqual(code, 0)
            self.assertTrue(envelope["ok"])
            self.assertFalse(envelope["usage"]["available"])
            self.assertEqual(envelope["usage"]["providers"], [])

    def test_empty_table_is_available_with_no_rows(self):
        with tempfile.TemporaryDirectory() as td:
            dp = Path(td)
            conn = _make_db(dp)
            conn.commit()
            conn.close()
            with mock.patch.dict("os.environ", self._env(dp)):
                code, envelope = _run_main(["usage", "--since", "0"])
            self.assertEqual(code, 0)
            self.assertTrue(envelope["usage"]["available"])
            self.assertEqual(envelope["usage"]["providers"], [])

    def test_missing_db_file_degrades_to_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict("os.environ",
                                 {"CC_SWITCH_CONFIG_DIR": td}):
                code, envelope = _run_main(["usage", "--since", "0"])
            self.assertEqual(code, 0)
            self.assertFalse(envelope["usage"]["available"])

    def test_unknown_provider_id_falls_back_to_id_as_name(self):
        with tempfile.TemporaryDirectory() as td:
            dp = Path(td)
            conn = _make_db(dp)
            _insert_log(conn, rid="x1", pid="ghost", app="claude",
                        model="m", created=NOW_S - 5)
            conn.commit()
            conn.close()
            with mock.patch.dict("os.environ", self._env(dp)):
                code, envelope = _run_main(["usage", "--since", "0"])
            self.assertEqual(code, 0)
            row = envelope["usage"]["providers"][0]
            self.assertEqual(row["provider_name"], "ghost")

    def test_other_ops_still_require_agent(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict("os.environ",
                                 {"CC_SWITCH_CONFIG_DIR": td}):
                code, envelope = _run_main(["list"])
            self.assertEqual(code, 2)
            self.assertFalse(envelope["ok"])
            self.assertIn("--agent", envelope["error"]["message"])


if __name__ == "__main__":
    unittest.main()
