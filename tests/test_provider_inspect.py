"""Unit tests for the container-side aisc-provider-inspect (S0.4).

Imports the inspector as a module and exercises the claude/codex detection
logic against a temp config layout + a real cc-switch SQLite DB. No Docker.
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

_WRAPPER = Path(__file__).resolve().parents[1] / "container" / "aisc-provider-inspect"
_loader = importlib.machinery.SourceFileLoader("aisc_provider_inspect", str(_WRAPPER))
_spec = importlib.util.spec_from_loader("aisc_provider_inspect", _loader)
inspector = importlib.util.module_from_spec(_spec)
_loader.exec_module(inspector)


def _make_db(cc_dir, rows):
    """Create cc-switch.db; rows = [(id, app_type, name, is_current, settings_config_dict)]."""
    db = os.path.join(cc_dir, "cc-switch.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT, "
        "settings_config TEXT, is_current INTEGER)"
    )
    for pid, app, name, cur, sc in rows:
        con.execute(
            "INSERT INTO providers VALUES (?,?,?,?,?)",
            (pid, app, name, json.dumps(sc), 1 if cur else 0),
        )
    con.commit()
    con.close()
    return db


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


class _Layout:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="aisc-prov-")
        self.claude = os.path.join(self.root, ".claude")
        self.codex = os.path.join(self.root, ".codex")
        self.cc = os.path.join(self.root, ".cc-switch")
        for d in (self.claude, self.codex, self.cc):
            os.makedirs(d)

    def ctx(self):
        return {
            "claude_config_dir": self.claude,
            "codex_config_dir": self.codex,
            "cc_switch_config_dir": self.cc,
        }


class TestClaude(unittest.TestCase):
    def setUp(self):
        self.lay = _Layout()
        self.addCleanup(shutil.rmtree, self.lay.root, True)

    def test_fresh_default_proxy_not_configured(self):
        _make_db(self.lay.cc, [("default", "claude", "default", True, {"statusLine": {}})])
        _write_json(os.path.join(self.lay.claude, "settings.json"), {
            "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:15721",
                    "ANTHROPIC_AUTH_TOKEN": "PROXY_MANAGED"}})
        out = inspector.inspect("claude", self.lay.ctx())
        assert out == {"provider_id": "default", "provider_name": "default",
                       "route_mode": "cc-switch-proxy", "auth_status": "not_configured"}

    def test_deepseek_with_key_is_configured_and_secret_free(self):
        _make_db(self.lay.cc, [
            ("default", "claude", "default", False, {"statusLine": {}}),
            ("deepseek", "claude", "DeepSeek", True, {
                "env": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/v1",
                        "ANTHROPIC_API_KEY": "sk-real-secret"}}),
        ])
        _write_json(os.path.join(self.lay.claude, "settings.json"),
                    {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:15721"}})
        out = inspector.inspect("claude", self.lay.ctx())
        assert out["provider_id"] == "deepseek"
        assert out["route_mode"] == "cc-switch-proxy"
        assert out["auth_status"] == "configured"
        assert "sk-real-secret" not in json.dumps(out)  # secret never emitted

    def test_official_no_auth_is_login_required(self):
        _make_db(self.lay.cc, [("claude-official", "claude", "Claude Official", True, {"env": {}})])
        _write_json(os.path.join(self.lay.claude, "settings.json"),
                    {"env": {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}})
        out = inspector.inspect("claude", self.lay.ctx())
        assert out["route_mode"] == "official-direct"
        assert out["auth_status"] == "login_required"

    def test_official_oauth_is_configured(self):
        _make_db(self.lay.cc, [("claude-official", "claude", "Claude Official", True, {"env": {}})])
        _write_json(os.path.join(self.lay.claude, "settings.json"), {"env": {}})
        with open(os.path.join(self.lay.claude, ".credentials.json"), "w") as f:
            f.write("{}")
        out = inspector.inspect("claude", self.lay.ctx())
        assert out["route_mode"] == "official-direct"
        assert out["auth_status"] == "configured"

    def test_no_current_row_falls_back_to_anthropic_official(self):
        _make_db(self.lay.cc, [("deepseek", "claude", "DeepSeek", False,
                                {"env": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/v1"}})])
        _write_json(os.path.join(self.lay.claude, "settings.json"),
                    {"env": {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}})
        out = inspector.inspect("claude", self.lay.ctx())
        assert out["provider_id"] == "anthropic-official"
        assert out["route_mode"] == "official-direct"

    def test_proxy_managed_token_does_not_count_as_configured(self):
        _make_db(self.lay.cc, [("default", "claude", "default", True, {"env": {}})])
        _write_json(os.path.join(self.lay.claude, "settings.json"),
                    {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:15721",
                             "ANTHROPIC_AUTH_TOKEN": "PROXY_MANAGED"}})
        out = inspector.inspect("claude", self.lay.ctx())
        assert out["auth_status"] == "not_configured"

    def test_malformed_env_does_not_crash(self):
        # A hand-edited settings.json with env as a non-dict must not raise;
        # the inspector degrades to a valid (unknown/empty) status.
        _make_db(self.lay.cc, [("default", "claude", "default", True, {"env": {}})])
        _write_json(os.path.join(self.lay.claude, "settings.json"),
                    {"env": ["not a dict"]})
        out = inspector.inspect("claude", self.lay.ctx())
        assert "route_mode" in out and "auth_status" in out


class TestCodex(unittest.TestCase):
    def setUp(self):
        self.lay = _Layout()
        self.addCleanup(shutil.rmtree, self.lay.root, True)

    _DEEPSEEK_TOML = (
        'model_provider = "deepseek"\n'
        "[model_providers.deepseek]\n"
        'name = "deepseek"\n'
        'base_url = "https://api.deepseek.com/v1"\n'
    )

    def test_fresh_official_no_auth_is_login_required(self):
        _make_db(self.lay.cc, [("codex-official", "codex", "OpenAI Official", True,
                                {"auth": {}, "config": ""})])
        out = inspector.inspect("codex", self.lay.ctx())
        assert out == {"provider_id": "codex-official", "provider_name": "OpenAI Official",
                       "route_mode": "official-direct", "auth_status": "login_required"}

    def test_deepseek_with_api_key_is_configured_and_secret_free(self):
        toml = self._DEEPSEEK_TOML + 'api_key = "sk-real-secret"\n'
        _make_db(self.lay.cc, [
            ("codex-official", "codex", "OpenAI Official", False, {"auth": {}, "config": ""}),
            ("deepseek", "codex", "DeepSeek", True, {"config": toml}),
        ])
        out = inspector.inspect("codex", self.lay.ctx())
        assert out["provider_id"] == "deepseek"
        assert out["route_mode"] == "cc-switch-proxy"
        assert out["auth_status"] == "configured"
        assert "sk-real-secret" not in json.dumps(out)

    def test_official_oauth_is_configured(self):
        _make_db(self.lay.cc, [("codex-official", "codex", "OpenAI Official", True,
                                {"auth": {}, "config": ""})])
        with open(os.path.join(self.lay.codex, "auth.json"), "w") as f:
            f.write("{}")
        out = inspector.inspect("codex", self.lay.ctx())
        assert out["route_mode"] == "official-direct"
        assert out["auth_status"] == "configured"

    def test_no_current_row_falls_back_to_codex_official(self):
        _make_db(self.lay.cc, [("deepseek", "codex", "DeepSeek", False,
                                {"config": self._DEEPSEEK_TOML})])
        out = inspector.inspect("codex", self.lay.ctx())
        assert out["provider_id"] == "codex-official"
        assert out["route_mode"] == "official-direct"

    def test_model_provider_selector_does_not_use_inactive_key(self):
        # Active = deepseek (no key); inactive kimi has a key. The inspector must
        # use the active provider's config, not scan all and pick kimi's key.
        toml = (
            'model_provider = "deepseek"\n'
            "[model_providers.deepseek]\n"
            'name = "deepseek"\n'
            'base_url = "https://api.deepseek.com/v1"\n'
            "[model_providers.kimi]\n"
            'name = "kimi"\n'
            'base_url = "https://api.moonshot.cn/v1"\n'
            'api_key = "sk-kimi"\n'
        )
        _make_db(self.lay.cc, [("multi", "codex", "Multi", True, {"config": toml})])
        out = inspector.inspect("codex", self.lay.ctx())
        assert out["auth_status"] == "not_configured"  # active deepseek has no key
        assert out["route_mode"] == "cc-switch-proxy"
        assert "sk-kimi" not in json.dumps(out)

    def test_empty_auth_value_does_not_count_as_configured(self):
        _make_db(self.lay.cc, [("codex-official", "codex", "OpenAI Official", True,
                                {"auth": {"access_token": ""}, "config": ""})])
        out = inspector.inspect("codex", self.lay.ctx())
        assert out["auth_status"] == "login_required"

    def test_invalid_agent_fails(self):
        _make_db(self.lay.cc, [])
        with self.assertRaises(SystemExit):
            inspector.inspect("gemini", self.lay.ctx())


if __name__ == "__main__":
    unittest.main()
