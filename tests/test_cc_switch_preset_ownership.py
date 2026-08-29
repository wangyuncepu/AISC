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
        # v7 (S8g): codex upstream format flips to openai_responses +
        # codesome joins — existing volumes must refresh, so the format
        # version is part of the revision hash.
        self.assertEqual(H.PRESET_FORMAT_VERSION, 7)
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
        # S8g (2026-08-29): codex presets speak Responses DIRECTLY to the
        # OpenAI-side base (official guides/responses_api) — no translation.
        self.assertIn("auth", settings)
        self.assertIn('base_url = "https://api.deepseek.com"', settings["config"])
        self.assertNotIn("/anthropic", settings["config"])
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


class S8gUpstreamFormatTests(unittest.TestCase):
    """S8g (user ruling + live-verified 2026-08-29): every codex preset
    upstream is the OpenAI Responses API (meta.apiFormat=openai_responses);
    codex rows point at the OpenAI-side base. codesome joins the presets."""

    def test_every_preset_declares_openai_responses(self):
        for provider in H.PRESET_PROVIDERS:
            self.assertEqual(
                provider.get("codex_api_format"),
                "openai_responses",
                f"{provider['id']} must declare openai_responses",
            )

    def test_codex_rows_use_the_openai_side_base(self):
        for provider in H.PRESET_PROVIDERS:
            config = H._settings_config("codex", provider)["config"]
            self.assertIn(f'base_url = "{provider["base_url"]}"', config)

    def test_anthropic_format_still_routes_to_the_anthropic_base(self):
        # Legacy translation branch: a provider declaring anthropic keeps
        # pointing codex at anthropic_base_url (the router converts).
        legacy = {
            "id": "legacy", "base_url": "https://x.example",
            "anthropic_base_url": "https://x.example/anthropic",
            "model": "m", "codex_api_format": "anthropic",
        }
        config = H._settings_config("codex", legacy)["config"]
        self.assertIn('base_url = "https://x.example/anthropic"', config)

    def test_codesome_preset_shape(self):
        codesome = next(p for p in H.PRESET_PROVIDERS if p["id"] == "codesome")
        self.assertEqual(codesome["base_url"], "https://v5.codesome.cn/openai")
        self.assertEqual(codesome["anthropic_base_url"], "https://v5.codesome.cn/api")
        # Claude row: env-based, Anthropic side URL, no token written.
        claude = H._settings_config("claude", codesome)
        self.assertEqual(
            claude["env"]["ANTHROPIC_BASE_URL"], "https://v5.codesome.cn/api"
        )
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", claude["env"])

    def test_preset_revision_bumped_for_the_format_migration(self):
        # Existing volumes must refresh: v7 (format flip + codesome).
        self.assertEqual(H.PRESET_FORMAT_VERSION, 7)


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
            # deepseek existed (refreshed); the other four were added
            # (S8g: codesome joined the preset set).
            self.assertEqual((added, refreshed, removed), (4, 1, 0))

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


class ClaudeSettingsBaseTests(unittest.TestCase):
    """Retest round 2 (2026-08-21): upstream's claude switch replaces
    settings.json with the row's settings_config WHOLESALE — preset rows must
    carry the non-env base (statusLine/enabledPlugins/...) or the user's
    setup is wiped on the first switch."""

    def test_base_loads_the_repo_template(self):
        base = H.load_claude_settings_base()
        self.assertIn("statusLine", base)
        self.assertIn("enabledPlugins", base)
        self.assertIn("extraKnownMarketplaces", base)
        self.assertNotIn("env", base)

    def test_fresh_claude_settings_carry_base(self):
        settings = H._settings_config("claude", deepseek())
        self.assertIn("statusLine", settings)
        self.assertIn("enabledPlugins", settings)
        self.assertTrue(settings["env"]["ANTHROPIC_BASE_URL"])

    def test_custom_preset_path_carries_base_too(self):
        kimi = next(p for p in H.PRESET_PROVIDERS if p["id"] == "kimi")
        settings = H._settings_config("claude", kimi)
        self.assertIn("statusLine", settings)

    def test_refresh_seeds_base_only_when_absent(self):
        custom_statusline = {"type": "command", "command": "user-custom"}
        raw = json.dumps({
            "env": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "sk-user"},
            "statusLine": custom_statusline,
        })
        merged = H._merged_settings("claude", deepseek(), raw)
        # The user's own statusLine survives every refresh…
        self.assertEqual(merged["statusLine"], custom_statusline)
        # …while base keys the row lacks are seeded.
        self.assertIn("enabledPlugins", merged)

    def test_refresh_upgrades_env_only_rows(self):
        raw = json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": "sk-user"}})
        merged = H._merged_settings("claude", deepseek(), raw)
        self.assertIn("statusLine", merged)
        self.assertIn("enabledPlugins", merged)


class ReconcileTests(unittest.TestCase):
    """Post-init invariant (retest round 2): proxy on ⟺ the current
    provider is a real third-party endpoint; a PRISTINE imported 'default'
    row is removed with current re-pointed to the named official row."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_dir = Path(self.tmp.name)
        db = sqlite3.connect(self.config_dir / "cc-switch.db")
        db.execute(
            "CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT, "
            "settings_config TEXT, website_url TEXT, category TEXT, "
            "created_at INTEGER, sort_index INTEGER, notes TEXT, icon TEXT, "
            "icon_color TEXT, meta TEXT, is_current INTEGER, "
            "in_failover_queue INTEGER)"
        )
        db.commit()
        db.close()
        self.runner_calls: list[list[str]] = []

    def _seed(self, pid: str, agent: str, settings: dict, *, current=False,
              name=None):
        db = sqlite3.connect(self.config_dir / "cc-switch.db")
        db.execute(
            "INSERT INTO providers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, agent, name or pid, json.dumps(settings),
             "", "custom", 1, 0, "", None, None, "{}",
             1 if current else 0, 0),
        )
        db.commit()
        db.close()

    def _rows(self, agent: str) -> dict:
        db = sqlite3.connect(self.config_dir / "cc-switch.db")
        try:
            return {
                row[0]: (row[1], json.loads(row[2]))
                for row in db.execute(
                    "SELECT id, is_current, settings_config FROM providers "
                    "WHERE app_type = ?", (agent,))
            }
        finally:
            db.close()

    def _reconcile(self, rc=0):
        import subprocess as _sp

        def fake_runner(argv, **_kwargs):
            self.runner_calls.append(list(argv))
            return _sp.CompletedProcess(argv, rc, stdout="", stderr="boom"
                                        if rc else "")

        log_path = self.config_dir / "reconcile.log"
        with log_path.open("w", encoding="utf-8") as log_io:
            return H.reconcile_runtime_state(self.config_dir, log_io,
                                             runner=fake_runner)

    def test_pristine_default_removed_and_routes_disabled(self):
        # The legacy volume shape: claude sitting on cc-switch's imported
        # 'default' snapshot with the route force-enabled by the old
        # entrypoint; codex already on its official placeholder.
        self._seed("default", "claude",
                   {"statusLine": {"type": "command", "command": "x"}},
                   current=True, name="default")
        self._seed("claude-official", "claude", {"env": {}})
        self._seed("deepseek", "claude", {
            "env": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "sk-user"}})
        self._seed("codex-official", "codex", {"auth": {}, "config": ""},
                   current=True)
        actions = self._reconcile()

        rows = self._rows("claude")
        self.assertNotIn("default", rows)                       # artifact gone
        self.assertEqual(rows["claude-official"][0], 1)         # re-pointed
        self.assertIn("statusLine", rows["claude-official"][1])  # base seeded
        self.assertEqual(rows["deepseek"][0], 0)                # untouched
        # Invariant: both current rows are non-real → both routes off.
        self.assertEqual(
            self.runner_calls,
            [["cc-switch", "proxy", "-a", "claude", "disable"],
             ["cc-switch", "proxy", "-a", "codex", "disable"]])
        self.assertTrue(any("default" in a for a in actions))

    def test_real_current_provider_enables_route(self):
        self._seed("claude-official", "claude", {"env": {}}, current=True)
        self._seed("deepseek", "claude", {
            "env": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic"}},
            current=False)
        self._seed("codex-official", "codex", {"auth": {}, "config": ""})
        self._seed("deepseek", "codex", {
            "auth": {}, "config": 'model_provider = "deepseek"\n'
                                  "[model_providers.deepseek]\n"
                                  'base_url = "https://api.deepseek.com"\n'},
            current=True)
        self._reconcile()
        self.assertEqual(
            self.runner_calls,
            [["cc-switch", "proxy", "-a", "claude", "disable"],   # official row
             ["cc-switch", "proxy", "-a", "codex", "enable"],     # real row
             ["cc-switch", "proxy", "-a", "codex", "show"]])      # route verify

    def test_repurposed_default_is_kept(self):
        self._seed("default", "claude", {
            "env": {"ANTHROPIC_BASE_URL": "https://my-proxy.example.com",
                    "ANTHROPIC_AUTH_TOKEN": "sk-mine"}}, current=True)
        self._seed("claude-official", "claude", {"env": {}})
        self._seed("codex-official", "codex", {"auth": {}, "config": ""},
                   current=True)
        self._reconcile()
        rows = self._rows("claude")
        self.assertIn("default", rows)                    # user's row survives
        self.assertEqual(rows["default"][0], 1)           # …and stays current
        self.assertEqual(rows["claude-official"][0], 0)
        self.assertIn(["cc-switch", "proxy", "-a", "claude", "enable"],
                      self.runner_calls)                  # real row → route on

    def test_missing_official_rows_are_created(self):
        self._seed("deepseek", "claude", {
            "env": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic"}},
            current=True)
        self._seed("deepseek", "codex", {
            "auth": {}, "config": 'model_provider = "d"\n'
                                  "[model_providers.d]\n"
                                  'base_url = "https://x"\n'},
            current=True)
        self._reconcile()
        rows = self._rows("claude")
        self.assertIn("claude-official", rows)
        self.assertIn("statusLine", rows["claude-official"][1])
        self.assertEqual(rows["claude-official"][0], 0)   # current untouched
        self.assertIn("codex-official", self._rows("codex"))
        self.assertEqual(
            self.runner_calls,
            [["cc-switch", "proxy", "-a", "claude", "enable"],
             ["cc-switch", "proxy", "-a", "claude", "show"],
             ["cc-switch", "proxy", "-a", "codex", "enable"],
             ["cc-switch", "proxy", "-a", "codex", "show"]])

    def test_second_run_is_steady(self):
        self._seed("claude-official", "claude", {"env": {}}, current=True)
        self._seed("codex-official", "codex", {"auth": {}, "config": ""},
                   current=True)
        self._reconcile()
        self._reconcile()
        rows = self._rows("claude")
        self.assertEqual(list(rows), ["claude-official"])
        self.assertEqual(rows["claude-official"][0], 1)

    def test_runner_failure_never_raises(self):
        self._seed("claude-official", "claude", {"env": {}}, current=True)
        self._seed("codex-official", "codex", {"auth": {}, "config": ""},
                   current=True)
        actions = self._reconcile(rc=1)
        self.assertFalse(any(a.startswith("proxy") for a in actions))
        # The DB steps still committed.
        self.assertIn("statusLine", self._rows("claude")["claude-official"][1])

    def test_enable_verifies_route_and_recovers_via_daemon_restart(self):
        # Manual round 3 (2026-08-21): enable can silently no-op with a
        # stale/dead daemon — the reconcile verifies the port listens and
        # recovers (daemon stop→start→re-enable), never failing boot.
        import socket as _socket
        import subprocess as _sp

        sock = _socket.socket()
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
        sock.close()

        self._seed("claude-official", "claude", {"env": {}}, current=True)
        self._seed("deepseek", "codex", {
            "auth": {}, "config": 'model_provider = "d"\n'
                                  "[model_providers.d]\n"
                                  'base_url = "https://x"\n'},
            current=True)

        listener: list = []
        calls: list[list[str]] = []

        def fake_runner(argv, **_kwargs):
            calls.append(list(argv))
            joined = " ".join(argv)
            stdout = ""
            if "show" in argv:
                stdout = f"- Codex: enabled, configured {closed_port}\n"
            if "enable" in joined and len(calls) > 3 and not listener:
                # the recovery re-enable → bring the route up for real
                server = _socket.socket()
                server.bind(("127.0.0.1", closed_port))
                server.listen(4)
                listener.append(server)
            return _sp.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        self.addCleanup(lambda: listener and listener[0].close())
        log_path = self.config_dir / "reconcile.log"
        with log_path.open("w", encoding="utf-8") as log_io:
            actions = H.reconcile_runtime_state(self.config_dir, log_io,
                                                runner=fake_runner)
        joined = [" ".join(c) for c in calls]
        self.assertTrue(any("daemon" in a and "stop" in a for a in joined))
        self.assertTrue(any("daemon" in a and "start" in a for a in joined))
        self.assertTrue(any("recovered codex route" in a for a in actions))


if __name__ == "__main__":
    unittest.main()
