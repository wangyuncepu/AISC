"""P3 热切换实施（2026-09-12）：模型映射 shim + adapter 挂钩。

Hermetic: 纯函数矩阵 + 临时 sqlite + 真实 HTTP 回环（假上游断言重写与
SSE 透传）+ adapter 挂钩的 live 文件端口双向切换。
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIM_PATH = ROOT / "container" / "aisc-model-shim"
ADAPTER_PATH = ROOT / "container" / "aisc-cc-provider"


def _load(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


S = _load("aisc_model_shim", SHIM_PATH)
A = _load("aisc_cc_provider_shim_tests", ADAPTER_PATH)


def rows(*specs) -> list[dict]:
    """specs: (id, current, role_env, model)."""
    return [
        {"id": i, "name": i, "is_current": c, "role_env": r or {}, "model": m or ""}
        for i, c, r, m in specs
    ]


class MappingMatrixTests(unittest.TestCase):
    def test_claude_role_rewrite(self) -> None:
        tables = S.build_tables(rows(
            ("zhipu", True, {
                "ANTHROPIC_MODEL": "glm-4.6",
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-4.6",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-4.6-air",
            }, ""),
            ("deepseek", False, {
                "ANTHROPIC_MODEL": "deepseek-v4-flash[1m]",
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro",
            }, ""),
        ), "claude")
        # foreign primary → current primary slot
        self.assertEqual(
            S.resolve_model("deepseek-v4-flash[1m]", tables), "glm-4.6")
        # foreign opus slot → current opus slot
        self.assertEqual(S.resolve_model("deepseek-v4-pro", tables), "glm-4.6")
        # foreign sonnet slot present in current → its name
        tables2 = S.build_tables(rows(
            ("zhipu", True, {"ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-4.6-air"}, ""),
            ("deepseek", False, {"ANTHROPIC_DEFAULT_SONNET_MODEL": "ds-sonnet"}, ""),
        ), "claude")
        self.assertEqual(S.resolve_model("ds-sonnet", tables2), "glm-4.6-air")

    def test_passthrough_cases(self) -> None:
        tables = S.build_tables(rows(
            ("zhipu", True, {"ANTHROPIC_MODEL": "glm-4.6"}, ""),
            ("deepseek", False, {"ANTHROPIC_MODEL": "deepseek-v4-flash[1m]"}, ""),
        ), "claude")
        self.assertIsNone(S.resolve_model("glm-4.6", tables))  # current name
        self.assertIsNone(S.resolve_model("my-custom-model", tables))  # unmapped
        self.assertIsNone(S.resolve_model("", tables))

    def test_role_missing_in_current(self) -> None:
        tables = S.build_tables(rows(
            ("zhipu", True, {"ANTHROPIC_MODEL": "glm-4.6"}, ""),  # no sonnet slot
            ("deepseek", False, {"ANTHROPIC_DEFAULT_SONNET_MODEL": "ds-sonnet"}, ""),
        ), "claude")
        self.assertIsNone(S.resolve_model("ds-sonnet", tables))

    def test_codex_primary_only(self) -> None:
        tables = S.build_tables(rows(
            ("kimi", True, {}, "kimi-k3"),
            ("deepseek", False, {}, "deepseek-chat"),
        ), "codex")
        self.assertEqual(S.resolve_model("deepseek-chat", tables), "kimi-k3")
        self.assertIsNone(S.resolve_model("kimi-k3", tables))

    def test_no_current_row_is_inert(self) -> None:
        tables = S.build_tables(rows(("a", False, {"ANTHROPIC_MODEL": "x"}, "")), "claude")
        self.assertIsNone(S.resolve_model("x", tables))


class DbParsingTests(unittest.TestCase):
    def test_rows_from_db_claude_and_codex(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "cc-switch.db"
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE providers (id TEXT, name TEXT, settings_config TEXT,"
                " is_current INTEGER, sort_index INTEGER, app_type TEXT)")
            conn.execute(
                "INSERT INTO providers VALUES ('z','z',?,1,0,'claude')",
                (json.dumps({"env": {"ANTHROPIC_MODEL": "glm-4.6",
                                     "ANTHROPIC_AUTH_TOKEN": "sk-secret"}}),))
            conn.execute(
                "INSERT INTO providers VALUES ('d','d',?,0,1,'claude')",
                (json.dumps({"env": {"ANTHROPIC_MODEL": "deepseek-v4-flash[1m]"}}),))
            conn.execute(
                "INSERT INTO providers VALUES ('k','k',?,1,0,'codex')",
                (json.dumps({"config": 'model_provider = "k"\nmodel = "kimi-k3"\n'}),))
            conn.commit()
            conn.close()

            import os
            old = os.environ.get("CC_SWITCH_CONFIG_DIR")
            os.environ["CC_SWITCH_CONFIG_DIR"] = td
            try:
                claude = S._rows_from_db("claude")
                self.assertEqual(len(claude), 2)
                self.assertTrue(claude[0]["is_current"])
                self.assertEqual(claude[1]["role_env"]["ANTHROPIC_MODEL"],
                                 "deepseek-v4-flash[1m]")
                codex = S._rows_from_db("codex")
                self.assertEqual(codex[0]["model"], "kimi-k3")
                # end-to-end through tables_for
                t = S.build_tables(claude, "claude")
                self.assertEqual(
                    S.resolve_model("deepseek-v4-flash[1m]", t), "glm-4.6")
            finally:
                if old is None:
                    os.environ.pop("CC_SWITCH_CONFIG_DIR", None)
                else:
                    os.environ["CC_SWITCH_CONFIG_DIR"] = old


class HttpRoundTripTests(unittest.TestCase):
    """A fake upstream captures the (rewritten?) body and streams SSE back."""

    @classmethod
    def setUpClass(cls) -> None:
        seen: dict[str, str] = {}

        class Up(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                seen["body"] = self.rfile.read(n).decode()
                payload = (b'data: {"delta":1}\n\n' * 3)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                for i in range(3):
                    self.wfile.write(b'data: {"delta":1}\n\n')
                    self.wfile.flush()

            def log_message(self, *a) -> None:
                pass

        cls.up = ThreadingHTTPServer(("127.0.0.1", 0), Up)
        cls.seen = seen
        threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        up_port = cls.up.server_address[1]

        handler = type("H", (S.ShimHandler,), {
            "agent": "claude",
            "upstream": f"http://127.0.0.1:{up_port}",
        })
        cls.shim = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.shim.serve_forever, daemon=True).start()
        cls.shim_port = cls.shim.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.up.shutdown()
        cls.shim.shutdown()

    def test_rewrite_and_stream(self) -> None:
        # Prime the tables cache with a mapping decision.
        S._CACHE.update({
            "tables": S.build_tables(rows(
                ("zhipu", True, {"ANTHROPIC_MODEL": "glm-4.6"}, ""),
                ("deepseek", False, {"ANTHROPIC_MODEL": "deepseek-v4-flash[1m]"}, ""),
            ), "claude"),
            "at": __import__("time").monotonic(),
            "agent": "claude",
        })
        body = json.dumps({"model": "deepseek-v4-flash[1m]",
                           "messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.shim_port}/v1/messages", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        resp = urllib.request.urlopen(req, timeout=10)
        self.assertEqual(resp.status, 200)
        streamed = resp.read().decode()
        self.assertEqual(streamed.count('data: {"delta":1}'), 3)  # SSE intact
        sent = json.loads(self.seen["body"])
        self.assertEqual(sent["model"], "glm-4.6")  # rewritten
        self.assertEqual(sent["messages"][0]["content"], "hi")  # rest intact


class AdapterWiringTests(unittest.TestCase):
    def test_point_stub_bidirectional(self) -> None:
        import os
        with tempfile.TemporaryDirectory() as td:
            settings = Path(td) / "settings.json"
            settings.write_text(json.dumps(
                {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:15701/api"}},
                ensure_ascii=False), encoding="utf-8")
            old_c = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = td
            try:
                # shim alive → stub points at the SHIM port 15721 (it owns the historical port)
                with mock.patch.object(A, "_tcp_listening", return_value=True):
                    A._point_stub_at_shim("claude")
                url = json.loads(settings.read_text())["env"]["ANTHROPIC_BASE_URL"]
                self.assertIn(":15721", url)
                # shim dead → restored to the direct proxy port
                with mock.patch.object(A, "_tcp_listening", return_value=False):
                    A._point_stub_at_shim("claude")
                url = json.loads(settings.read_text())["env"]["ANTHROPIC_BASE_URL"]
                self.assertIn(":15701", url)  # restored to the direct port
                # direct provider URLs are untouched
                settings.write_text(json.dumps(
                    {"env": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/x"}}),
                    encoding="utf-8")
                with mock.patch.object(A, "_tcp_listening", return_value=True):
                    A._point_stub_at_shim("claude")
                url = json.loads(settings.read_text())["env"]["ANTHROPIC_BASE_URL"]
                self.assertEqual(url, "https://api.deepseek.com/x")
            finally:
                if old_c is None:
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = old_c

    def test_codex_toml_port_swap(self) -> None:
        import os
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.toml"
            cfg.write_text(
                'model_provider = "k"\n'
                '[model_providers.k]\n'
                'base_url = "http://127.0.0.1:15702/v1"\n',
                encoding="utf-8")
            old = os.environ.get("CODEX_CONFIG_DIR")
            os.environ["CODEX_CONFIG_DIR"] = td
            try:
                with mock.patch.object(A, "_tcp_listening", return_value=True):
                    A._point_stub_at_shim("codex")
                self.assertIn("127.0.0.1:15722", cfg.read_text())
            finally:
                if old is None:
                    os.environ.pop("CODEX_CONFIG_DIR", None)
                else:
                    os.environ["CODEX_CONFIG_DIR"] = old


if __name__ == "__main__":
    unittest.main()
