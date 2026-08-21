"""Stage 8c (CS-03/CS-04, D8-06/D8-11): fixture-driven DeepSeek preset and
ownership-aware refresh.

The preset must generate the official Claude Code env set VERBATIM from
``container/lib/deepseek-official-facts.json`` (never a hardcoded copy), never
write the user's token keys, upgrade every historically-preset-written value
on refresh, and preserve genuine user overrides.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "container" / "lib" / "deepseek-official-facts.json"

_spec = importlib.util.spec_from_file_location(
    "aisc_cc_switch_preset_8c", ROOT / "container" / "lib" / "cc_switch_preset_providers.py"
)
assert _spec and _spec.loader
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)

FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def deepseek() -> dict:
    """A deep copy — tests mutate provider entries (e.g. _retired_env_keys)
    and must never pollute the shared module-level list."""
    return json.loads(json.dumps(
        next(p for p in H.PRESET_PROVIDERS if p["id"] == "deepseek")
    ))


class FixtureDrivenPresetTests(unittest.TestCase):
    def test_claude_env_is_the_official_set_minus_user_token_keys(self):
        env = H._settings_config("claude", deepseek())["env"]
        official = dict(FIXTURE["claude_code_official_env"])
        expected = {k: v for k, v in official.items() if k not in H.USER_ONLY_ENV_KEYS}
        self.assertEqual(env, expected)

    def test_1m_suffix_rules_match_the_fixture(self):
        env = H._settings_config("claude", deepseek())["env"]
        suffix = FIXTURE["one_million_context_suffix"]
        for key in suffix["applies_to"]:
            self.assertIn("[1m]", env[key], f"{key} must carry [1m]")
        for key in suffix["not_applicable_to"]:
            self.assertNotIn("[1m]", env[key], f"{key} must NOT carry [1m]")

    def test_official_model_ids_and_endpoint(self):
        env = H._settings_config("claude", deepseek())["env"]
        official_ids = FIXTURE["models"]["official_ids"]
        for key in (
            "ANTHROPIC_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
        ):
            base = env[key].removesuffix("[1m]")
            self.assertIn(base, official_ids)
        for key in ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
            self.assertIn(env[key], official_ids)
            self.assertEqual(env[key], "deepseek-v4-flash")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], FIXTURE["base_url_anthropic"])
        self.assertEqual(env["CLAUDE_CODE_EFFORT_LEVEL"], "max")

    def test_deprecated_ids_never_generated(self):
        # A-CS03: the deprecated deepseek-chat/reasoner defaults must never
        # come back, and the bare pro name must not appear without [1m] on
        # the [1m]-carrying keys.
        env = H._settings_config("claude", deepseek())["env"]
        for key, value in env.items():
            self.assertNotIn("deepseek-chat", value)
            self.assertNotIn("deepseek-reasoner", value)
        self.assertNotEqual(env["ANTHROPIC_MODEL"], "deepseek-v4-pro")
        self.assertNotEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "deepseek-v4-pro")

    def test_fresh_install_writes_no_token_keys(self):
        env = H._settings_config("claude", deepseek())["env"]
        for key in H.USER_ONLY_ENV_KEYS:
            self.assertNotIn(key, env)

    def test_preset_format_bumped_and_revision_is_fixture_sensitive(self):
        self.assertEqual(H.PRESET_FORMAT_VERSION, 5)
        base_revision = H.preset_revision("claude")
        # A mutated fixture must yield a different revision (refresh triggers).
        mutated = json.loads(json.dumps(deepseek()))
        mutated["claude_env"]["ANTHROPIC_MODEL"] = "deepseek-v4-flash"
        payload = {
            "format": H.PRESET_FORMAT_VERSION,
            "agent": "claude",
            "providers": [mutated] + [p for p in H.PRESET_PROVIDERS if p["id"] != "deepseek"],
        }
        import hashlib

        other = hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertNotEqual(base_revision, other)

    def test_codex_settings_carry_auth_field(self):
        # Upstream `provider switch` refuses codex rows without an "auth"
        # object (IDEA-4 manual test on the real container).
        for provider in H.PRESET_PROVIDERS:
            settings = H._settings_config("codex", provider)
            self.assertIn("auth", settings)
            self.assertIsInstance(settings["auth"], dict)

    def test_codex_api_key_rides_auth_channel(self):
        # 2026-08-21 live probe: the local proxy worker serves the token it
        # captures from live ~/.codex/auth.json at enable time — which is
        # written from settings auth on switch. The key must live THERE,
        # with the TOML api_key line as a legacy mirror.
        settings = H._settings_config("codex", deepseek(), api_key="sk-x-1234")
        self.assertEqual(settings["auth"], {"OPENAI_API_KEY": "sk-x-1234"})
        self.assertIn('api_key = "sk-x-1234"', settings["config"])
        self.assertEqual(H._settings_config("codex", deepseek())["auth"], {})

    def test_codex_refresh_recovers_key_from_auth_channel(self):
        # Rows written by upstream's own TUI carry the key in auth only —
        # extraction is auth-first so a refresh never drops it back to the
        # placeholder-401 shape.
        existing = json.dumps({
            "auth": {"OPENAI_API_KEY": "sk-auth-chan-1"},
            "config": ('model_provider = "deepseek"\n'
                       '[model_providers.deepseek]\n'
                       'base_url = "https://api.deepseek.com/anthropic"\n'),
        })
        merged = H._merged_settings("codex", deepseek(), existing)
        self.assertEqual(merged["auth"].get("OPENAI_API_KEY"), "sk-auth-chan-1")

    def test_codex_refresh_keeps_key_alongside_oauth_mirror(self):
        existing = json.dumps({
            "auth": {"tokens": {"id_token": "tok"}},
            "config": ('model_provider = "deepseek"\n'
                       '[model_providers.deepseek]\nbase_url = "x"\n'
                       'api_key = "sk-toml-9"\n'),
        })
        merged = H._merged_settings("codex", deepseek(), existing)
        self.assertEqual(merged["auth"]["tokens"], {"id_token": "tok"})
        self.assertEqual(merged["auth"]["OPENAI_API_KEY"], "sk-toml-9")

    def test_codex_refresh_upgrades_legacy_toml_key_into_auth(self):
        existing = json.dumps({
            "auth": {},
            "config": ('model_provider = "deepseek"\n'
                       '[model_providers.deepseek]\nbase_url = "x"\n'
                       'api_key = "sk-old-2"\n'),
        })
        merged = H._merged_settings("codex", deepseek(), existing)
        self.assertEqual(merged["auth"].get("OPENAI_API_KEY"), "sk-old-2")

    def test_bad_fixture_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"schema": "nope"}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                H.load_deepseek_fixture(bad)
            bad.write_text(
                json.dumps({**FIXTURE, "claude_code_official_env": {"ANTHROPIC_BASE_URL": "x"}}),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                H.load_deepseek_fixture(bad)


def legacy(pid: str) -> dict:
    """Deep copy of a legacy (non-claude_env) preset row."""
    return json.loads(json.dumps(
        next(p for p in H.PRESET_PROVIDERS if p["id"] == pid)
    ))


class CodexModelCatalogTests(unittest.TestCase):
    """codex-adapt 修复轮（2026-08-20）：codex settings 携带 cc-switch
    `modelCatalog.models` —— 上游切换时生成模型目录文件并注入
    `model_catalog_json`，codex /model 随之显示供应商模型列表（并取代
    fallback 元数据，消「Model metadata not found」）。"""

    def test_deepseek_codex_settings_carry_model_catalog(self):
        settings = H._settings_config("codex", deepseek())
        catalog = settings.get("modelCatalog", {}).get("models", [])
        self.assertEqual(
            [row["model"] for row in catalog],
            ["deepseek-v4-pro", "deepseek-v4-flash"],  # 主推 pro 在前
        )
        # contextWindow：fixture "1M" → 1_000_000（与用户实测 mapping 行一致）
        self.assertEqual(catalog[0]["contextWindow"], 1_000_000)
        self.assertEqual(catalog[1]["contextWindow"], 1_000_000)
        # 既有形态 + 用户实测工作形状：anthropic 端点 + responses（本地路由接管）
        self.assertIn("auth", settings)
        self.assertIn('base_url = "https://api.deepseek.com/anthropic"', settings["config"])
        self.assertIn('wire_api = "responses"', settings["config"])
        self.assertIn("model_context_window = 1000000", settings["config"])

    def test_providers_without_catalog_omit_the_key(self):
        legacy = {"id": "x", "base_url": "https://x", "model": "m"}
        settings = H._settings_config("codex", legacy)
        self.assertNotIn("modelCatalog", settings)

    def test_context_window_parsing(self):
        f = lambda v: H._context_window_from_length(v)
        self.assertEqual(f("1M"), 1_000_000)
        self.assertEqual(f("384K"), 384_000)
        self.assertEqual(f("131072"), 131072)
        self.assertEqual(f(""), 0)
        self.assertEqual(f("garbage"), 0)


class LegacyModelOwnershipTests(unittest.TestCase):
    """IDEA-5 (5c): legacy presets (zhipu/kimi/volcengine) give
    ANTHROPIC_MODEL the same ownership merge — user mapping overrides
    survive refresh; historical/absent values upgrade; BASE_URL keeps its
    legacy reset semantics."""

    def _merge(self, pid: str, existing_env: dict) -> dict:
        raw = json.dumps({"env": existing_env})
        return H._merged_settings("claude", legacy(pid), raw)["env"]

    def test_zhipu_user_model_override_survives(self):
        merged = self._merge("zhipu", {
            "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
            "ANTHROPIC_MODEL": "glm-5.2",          # historical preset value
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-5.2-air",  # user-added role slot
        })
        # The preset default upgrades (in history).
        self.assertEqual(merged["ANTHROPIC_MODEL"], "glm-5.2")
        # User-added role keys outside the owned set survive untouched.
        self.assertEqual(merged["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "glm-5.2-air")

    def test_zhipu_mapping_override_survives_refresh(self):
        merged = self._merge("zhipu", {
            "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
            "ANTHROPIC_MODEL": "my-custom-glm",    # user override (not history)
        })
        self.assertEqual(merged["ANTHROPIC_MODEL"], "my-custom-glm")

    def test_zhipu_model_upgrades_when_preset_default_changes(self):
        provider = legacy("zhipu")
        provider["model"] = "glm-6.0"              # a future official default
        raw = json.dumps({"env": {
            "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
            "ANTHROPIC_MODEL": "glm-5.2",          # old default (in history)
        }})
        merged = H._merged_settings("claude", provider, raw)["env"]
        self.assertEqual(merged["ANTHROPIC_MODEL"], "glm-6.0")

    def test_volcengine_user_model_survives_and_base_url_resets(self):
        merged = self._merge("volcengine-ark", {
            "ANTHROPIC_BASE_URL": "https://user-endpoint.example",
            "ANTHROPIC_MODEL": "ep-user-endpoint",  # user-set (preset has none)
        })
        # No preset model → the user's MODEL is never owned, never dropped.
        self.assertEqual(merged["ANTHROPIC_MODEL"], "ep-user-endpoint")
        # BASE_URL keeps the legacy semantics: preset resets it.
        self.assertEqual(merged["ANTHROPIC_BASE_URL"],
                         "https://ark.cn-beijing.volces.com/api/v3")


class OwnershipRefreshTests(unittest.TestCase):
    def _merge(self, existing_env: dict) -> dict:
        raw = json.dumps({"env": existing_env})
        return H._merged_settings("claude", deepseek(), raw)["env"]

    def test_user_override_survives_refresh(self):
        merged = self._merge({
            "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "sk-user",
            "ANTHROPIC_MODEL": "my-own-model",          # user override
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "also-mine",  # user override
            "CLAUDE_CODE_EFFORT_LEVEL": "low",           # key new in this rev
        })
        self.assertEqual(merged["ANTHROPIC_MODEL"], "my-own-model")
        self.assertEqual(merged["ANTHROPIC_DEFAULT_SONNET_MODEL"], "also-mine")
        # EFFORT_LEVEL has empty history → any existing value is the user's.
        self.assertEqual(merged["CLAUDE_CODE_EFFORT_LEVEL"], "low")
        # Untouched keys keep upgrading to the official set.
        self.assertEqual(merged["ANTHROPIC_DEFAULT_OPUS_MODEL"], "deepseek-v4-pro[1m]")
        self.assertEqual(merged["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "deepseek-v4-flash")
        # The user's token is never touched.
        self.assertEqual(merged["ANTHROPIC_AUTH_TOKEN"], "sk-user")

    def test_legacy_preset_values_are_upgraded(self):
        merged = self._merge({
            "ANTHROPIC_BASE_URL": "https://api.deepseek.com/v1",   # legacy URL
            "ANTHROPIC_MODEL": "deepseek-chat",                     # deprecated
            "ANTHROPIC_AUTH_TOKEN": "sk-user",
        })
        self.assertEqual(merged["ANTHROPIC_BASE_URL"], "https://api.deepseek.com/anthropic")
        self.assertEqual(merged["ANTHROPIC_MODEL"], "deepseek-v4-pro[1m]")

    def test_fanout_artifact_values_are_upgraded(self):
        # cc-switch `provider add` fans ANTHROPIC_MODEL out to the DEFAULT_*
        # keys — those artifact values must upgrade, not stick.
        merged = self._merge({
            "ANTHROPIC_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-pro",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-pro",
        })
        self.assertEqual(merged["ANTHROPIC_MODEL"], "deepseek-v4-pro[1m]")
        self.assertEqual(merged["ANTHROPIC_DEFAULT_OPUS_MODEL"], "deepseek-v4-pro[1m]")
        self.assertEqual(merged["ANTHROPIC_DEFAULT_SONNET_MODEL"], "deepseek-v4-pro[1m]")
        self.assertEqual(merged["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "deepseek-v4-flash")

    def test_user_added_env_keys_survive(self):
        merged = self._merge({
            "ANTHROPIC_SMALL_FAST_MODEL": "my-fast",
            "HTTP_PROXY": "http://127.0.0.1:7890",
        })
        self.assertEqual(merged["ANTHROPIC_SMALL_FAST_MODEL"], "my-fast")
        self.assertEqual(merged["HTTP_PROXY"], "http://127.0.0.1:7890")

    def test_retired_preset_keys_dropped(self):
        provider = deepseek()
        provider["_retired_env_keys"] = ["ANTHROPIC_SMALL_FAST_MODEL"]
        raw = json.dumps({"env": {"ANTHROPIC_SMALL_FAST_MODEL": "stale"}})
        merged = H._merged_settings("claude", provider, raw)["env"]
        self.assertNotIn("ANTHROPIC_SMALL_FAST_MODEL", merged)

    def test_end_to_end_db_refresh_preserves_user_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            db = sqlite3.connect(config_dir / "cc-switch.db")
            db.execute(
                "CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT, "
                "settings_config TEXT, website_url TEXT, category TEXT, "
                "created_at INTEGER, sort_index INTEGER, notes TEXT, icon TEXT, "
                "icon_color TEXT, meta TEXT, is_current INTEGER, "
                "in_failover_queue INTEGER)"
            )
            old = json.dumps({"env": {
                "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                "ANTHROPIC_MODEL": "deepseek-v4-pro[1m]",
                "ANTHROPIC_AUTH_TOKEN": "sk-live-user-key",
            }})
            db.execute(
                "INSERT INTO providers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("deepseek", "claude", "DeepSeek", old, "https://api.deepseek.com",
                 "custom", 1, 0, "", None, None, "{}", 1, 0),
            )
            db.commit()
            db.close()

            log = config_dir / "preset.log"
            with log.open("w", encoding="utf-8") as log_io:
                added, refreshed, removed = H.add_preset_providers(
                    config_dir, "claude", H.preset_revision("claude"), log_io
                )
            # deepseek existed (refreshed); the other three were added.
            self.assertEqual((added, refreshed, removed), (3, 1, 0))

            db = sqlite3.connect(config_dir / "cc-switch.db")
            raw = db.execute(
                "SELECT settings_config FROM providers WHERE id='deepseek'"
            ).fetchone()[0]
            db.close()
            env = json.loads(raw)["env"]
            # Upgraded to the full official set…
            self.assertEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "deepseek-v4-pro[1m]")
            self.assertEqual(env["CLAUDE_CODE_EFFORT_LEVEL"], "max")
            # …while the user's key and current-selection state survive.
            self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-live-user-key")
            check = sqlite3.connect(config_dir / "cc-switch.db")
            try:
                is_current = check.execute(
                    "SELECT is_current FROM providers WHERE id='deepseek'"
                ).fetchone()[0]
            finally:
                check.close()
            self.assertEqual(is_current, 1)


if __name__ == "__main__":
    unittest.main()
