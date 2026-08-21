#!/usr/bin/env python3
"""Preconfigure cc-switch providers without storing API keys.

Stage 8c (CS-03/CS-04, D8-06/D8-11): the DeepSeek preset is driven by the
official-docs fixture (``deepseek-official-facts.json`` next to this module)
— nothing about models, endpoints or the ``[1m]`` suffix is hardcoded here.
Refresh is ownership-aware: preset-written values are upgraded, values the
USER set on top of the preset survive every refresh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, TextIO

FIXTURE_PATH = Path(__file__).parent / "deepseek-official-facts.json"
FIXTURE_SCHEMA = "aisc.deepseek-official-facts/v1"
# Env keys the official Claude Code integration page defines; the fixture
# must carry every one of them (the AUTH_TOKEN is user-owned and never
# written by the preset — the preset env template simply omits it).
_REQUIRED_FIXTURE_ENV_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_EFFORT_LEVEL",
)
# The user's token env key — preset-owned env never includes it.
USER_ONLY_ENV_KEYS = frozenset({"ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"})

# Retest round 2 (2026-08-21): upstream's claude switch REPLACES settings.json
# with the provider row's settings_config wholesale (live-probed) — an
# env-only row wipes the user's statusLine/enabledPlugins. Every claude
# settings_config this module (or the adapter) builds therefore carries the
# image's non-env base template. In the image it ships next to this module;
# in the repo/tests it is container/claude-settings.json one level up.
CLAUDE_SETTINGS_BASE_CANDIDATES = (
    Path(__file__).parent / "aisc-claude-settings-base.json",
    Path(__file__).parent.parent / "claude-settings.json",
)


def load_claude_settings_base() -> dict[str, Any]:
    """Non-env base template for claude settings_config (env never included).

    Unreadable/missing candidates → {} — rows degrade to env-only (the
    historical shape), never a startup failure.
    """
    for path in CLAUDE_SETTINGS_BASE_CANDIDATES:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k != "env"}
    return {}


def load_deepseek_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    """Strictly validate the official-docs fixture (fail closed)."""
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"DeepSeek fixture unreadable at {path}: {exc}") from exc
    if fixture.get("schema") != FIXTURE_SCHEMA:
        raise RuntimeError(
            f"DeepSeek fixture schema {fixture.get('schema')!r} != {FIXTURE_SCHEMA!r}"
        )
    env = fixture.get("claude_code_official_env")
    if not isinstance(env, dict):
        raise RuntimeError("DeepSeek fixture is missing claude_code_official_env")
    missing = [k for k in _REQUIRED_FIXTURE_ENV_KEYS if k not in env]
    if missing:
        raise RuntimeError(f"DeepSeek fixture env is missing keys: {', '.join(missing)}")
    models = fixture.get("models", {}).get("official_ids")
    if not isinstance(models, list) or not models:
        raise RuntimeError("DeepSeek fixture is missing models.official_ids")
    if not fixture.get("base_url_anthropic"):
        raise RuntimeError("DeepSeek fixture is missing base_url_anthropic")
    return fixture


def deepseek_provider_from_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    """Build the DeepSeek preset entry from the official fixture.

    ``claude_env`` is the FULL official environment set minus the user-owned
    token keys — the preset writes exactly these and owns exactly these.
    ``_env_history`` lists every value earlier AISC presets (or cc-switch's
    MODEL fan-out) historically wrote, so a refresh can tell "old preset
    value → upgrade" apart from "user override → keep" (CS-04).
    """
    env = dict(fixture["claude_code_official_env"])
    for key in USER_ONLY_ENV_KEYS:
        env.pop(key, None)
    # Historical preset-written values for the model keys: the deprecated
    # official ids, the bare v4 name, and the [1m] forms. The role-model
    # keys also carry these because cc-switch's `provider add` fans
    # ANTHROPIC_MODEL out to the three DEFAULT_* keys verbatim.
    model_history = [
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-pro",
        "deepseek-v4-pro[1m]",
        "deepseek-v4-flash",
        "deepseek-v4-flash[1m]",
    ]
    history: dict[str, list[str]] = {
        "ANTHROPIC_BASE_URL": [
            "https://api.deepseek.com",
            "https://api.deepseek.com/v1",
            "https://api.deepseek.com/anthropic",
        ],
        "ANTHROPIC_MODEL": list(model_history),
        "ANTHROPIC_DEFAULT_OPUS_MODEL": list(model_history),
        "ANTHROPIC_DEFAULT_SONNET_MODEL": list(model_history),
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": list(model_history),
        "CLAUDE_CODE_SUBAGENT_MODEL": list(model_history),
        # First revision shipping this key: nothing historical wrote it.
        "CLAUDE_CODE_EFFORT_LEVEL": [],
    }
    official_ids = list(fixture["models"]["official_ids"])
    return {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": fixture.get("base_url_openai", "https://api.deepseek.com"),
        "anthropic_base_url": fixture["base_url_anthropic"],
        # Codex side keeps the official pro id (fixture-verified).
        "model": "deepseek-v4-pro" if "deepseek-v4-pro" in official_ids else official_ids[-1],
        # Codex 模型目录（codex-adapt 修复轮 2026-08-20）：cc-switch 的
        # `modelCatalog.models` 数据源——切换 codex 供应商时上游生成
        # models 目录文件并向 ~/.codex/config.toml 注入 `model_catalog_json`，
        # codex /model 随之显示本目录而非官方内置列表；目录条目的
        # contextWindow 同时取代 codex 的 fallback 元数据（消「Model
        # metadata not found」）。数值 fixture 冻结（context_length=1M）。
        "model_catalog": _codex_model_catalog(official_ids, fixture),
        # 用户实测工作形状（2026-08-20）：DeepSeek 走 Anthropic Messages——
        # store base_url=/anthropic + wire_api=responses，切换时 cc-switch
        # 本地路由接管 live 并按 meta.apiFormat=anthropic 做 Responses→
        # Anthropic 转换（preset 刷新写入该 meta，见 add_preset_providers）。
        "codex_api_format": "anthropic",
        "claude_env": env,
        "_env_history": history,
        "_retired_env_keys": [],
        "description": (
            "DeepSeek V4 (official Anthropic-compatible endpoint; "
            "pro[1m] main + flash for haiku/subagent per official docs)"
        ),
    }


def _context_window_from_length(raw: Any) -> int:
    """Fixture `context_length` ("1M"/"384K"/"131072") → tokens."""
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw or "").strip().upper()
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    if text and text[-1] in multipliers:
        try:
            return int(float(text[:-1]) * multipliers[text[-1]])
        except ValueError:
            return 0
    try:
        return int(text)
    except ValueError:
        return 0


def _codex_model_catalog(official_ids: list[str], fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """Catalog rows for cc-switch `modelCatalog.models` (codex side).

    Order = /model 列表优先级（cc-switch priority = 1000 + index）：主推
    pro 在前。contextWindow 取 fixture 的 context_length（"1M"→1_000_000，
    与用户实测工作配置的 mapping 行一致）；缺省 128k。
    """
    context_window = _context_window_from_length(
        fixture.get("models", {}).get("context_length")
    ) or 128_000
    preferred = ["deepseek-v4-pro", "deepseek-v4-flash"]
    ordered = [m for m in preferred if m in official_ids]
    ordered += [m for m in official_ids if m not in ordered]
    return [{"model": m, "contextWindow": context_window} for m in ordered]


def build_preset_providers(fixture_path: Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    fixture = load_deepseek_fixture(fixture_path)
    return [
        deepseek_provider_from_fixture(fixture),
        {
            "id": "volcengine-ark",
            "name": "Volcengine Ark",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "model": "",
            # IDEA-5 (5c): historical preset-written MODEL values — the
            # ownership-merge discriminator (in-list → upgrade on refresh;
            # anything else is a user override and survives). Empty: this
            # preset never wrote a model.
            "_model_history": [],
            "description": "Volcengine Ark inference service; configure an endpoint ID",
        },
        {
            "id": "zhipu",
            "name": "Zhipu GLM",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "anthropic_base_url": "https://open.bigmodel.cn/api/anthropic",
            "model": "glm-5.2",
            "_model_history": ["glm-5.2"],
            "description": "Zhipu GLM-5.2 flagship model service",
        },
        {
            "id": "kimi",
            "name": "Kimi",
            "base_url": "https://api.moonshot.cn/v1",
            "anthropic_base_url": "https://api.moonshot.cn/anthropic",
            "model": "kimi-k3",
            "_model_history": ["kimi-k3"],
            "description": "Moonshot Kimi K3 model service",
        },
    ]


PRESET_PROVIDERS = build_preset_providers()

SUPPORTED_AGENTS = ("claude", "codex")
MARKER_TEMPLATE = ".aisc-preset-providers-{agent}.sha256"
PRESET_FORMAT_VERSION = 5
# Preset provider ids removed from PRESET_PROVIDERS, mapped to a fingerprint
# that identifies the old preset's settings_config. On refresh an id is deleted
# only if its stored config still carries the fingerprint, so a user who
# repurposed the id with their own config is left alone. codex-claude pointed
# at the non-resolvable api.codex.so and is gone.
RETIRED_PROVIDER_IDS = {"codex-claude": "codex.so"}
REQUIRED_PROVIDER_COLUMNS = {
    "id",
    "app_type",
    "name",
    "settings_config",
    "website_url",
    "category",
    "created_at",
    "sort_index",
    "notes",
    "icon",
    "icon_color",
    "meta",
    "is_current",
    "in_failover_queue",
}


def marker_path(config_dir: Path, agent: str) -> Path:
    if agent not in SUPPORTED_AGENTS:
        raise ValueError(f"unsupported agent: {agent}")
    return config_dir / MARKER_TEMPLATE.format(agent=agent)


def preset_revision(agent: str) -> str:
    """Return a revision derived only from the provider payload and schema."""
    payload = {
        "format": PRESET_FORMAT_VERSION,
        "agent": agent,
        "providers": PRESET_PROVIDERS,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _toml_string(value: str) -> str:
    """Encode a string using JSON's TOML-compatible quoted-string syntax."""
    return json.dumps(value, ensure_ascii=True)


def _settings_config(
    agent: str, provider: dict[str, Any], *, api_key: str = ""
) -> dict[str, Any]:
    if agent == "claude":
        # Fixture-driven providers (Stage 8c) carry the full official env set.
        if "claude_env" in provider:
            return {"env": dict(provider["claude_env"]), **load_claude_settings_base()}
        # Third-party providers expose a separate Anthropic-compatible endpoint
        # (e.g. /anthropic) distinct from their OpenAI base_url. Prefer it when
        # present so Claude Code speaks the Messages API to the right URL.
        base_url = provider.get("anthropic_base_url") or provider["base_url"]
        env = {"ANTHROPIC_BASE_URL": base_url}
        # A provider may expose a Claude-specific model name (e.g. DeepSeek's
        # docs recommend deepseek-v4-pro[1m] for Claude Code) distinct from the
        # OpenAI model used by codex; prefer it when present.
        claude_model = provider.get("anthropic_model") or provider["model"]
        if claude_model:
            env["ANTHROPIC_MODEL"] = claude_model
        return {"env": env, **load_claude_settings_base()}

    if agent == "codex":
        provider_id = provider["id"]
        lines = [
            f"model_provider = {_toml_string(provider_id)}",
        ]
        if provider["model"]:
            lines.append(f"model = {_toml_string(provider['model'])}")
        # codex-adapt: with a catalog the active entry's window wins; this
        # top-level key is the no-catalog fallback (official codex config
        # key — keeps token accounting sane even if the catalog file goes
        # away), taken from the first catalog row.
        catalog_rows = provider.get("model_catalog") or []
        if catalog_rows and catalog_rows[0].get("contextWindow"):
            lines.append(
                f"model_context_window = {int(catalog_rows[0]['contextWindow'])}"
            )
        lines.extend(
            [
                'model_reasoning_effort = "high"',
                "",
                f"[model_providers.{provider_id}]",
                f"name = {_toml_string(provider_id)}",
                # 用户实测工作形状：codex 始终对本地路由说 Responses；路由按
                # meta.apiFormat（anthropic/chat）改写上游协议。DeepSeek 走
                # Anthropic Messages 端点（fixture anthropic_base_url）。
                f"base_url = {_toml_string(provider.get('anthropic_base_url') or provider['base_url'])}",
                'wire_api = "responses"',
                "requires_openai_auth = true",
            ]
        )
        # api_key is the one user-owned field that must survive a preset
        # refresh; it is only re-injected when refreshing an existing provider.
        if api_key:
            lines.append(f"api_key = {_toml_string(api_key)}")
        lines.append("")
        # Upstream `provider switch` refuses a codex settings_config without
        # an "auth" object ("Codex 供应商配置缺少 'auth' 字段"); its own
        # official rows seed {"auth":{},"config":""}. The user's key rides
        # auth.OPENAI_API_KEY — the channel live ~/.codex/auth.json is
        # written from on switch, and the one the local proxy worker
        # captures at enable time (live-probed 2026-08-21: the router
        # neither reads the TOML api_key line nor passes the client bearer
        # through) — mirrored into the TOML line for legacy rows/masks.
        auth = {"OPENAI_API_KEY": api_key} if api_key else {}
        settings: dict[str, Any] = {"auth": auth, "config": "\n".join(lines)}
        # codex-adapt 修复轮: providers carrying a model catalog get it into
        # settings — cc-switch then generates the models file + injects
        # `model_catalog_json` on switch (see _codex_model_catalog).
        catalog = provider.get("model_catalog")
        if isinstance(catalog, list) and catalog:
            settings["modelCatalog"] = {"models": catalog}
        return settings

    raise ValueError(f"unsupported agent: {agent}")


# Env keys the legacy (non-fixture) claude presets own; refresh overwrites
# these but leaves any other env var (notably the user's token keys) alone.
_CLAUDE_PRESET_ENV_KEYS = frozenset({"ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"})


def _parse_json_settings(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _merged_claude_env(
    provider: dict[str, Any], existing_env: dict[str, Any]
) -> dict[str, str]:
    """Ownership-aware claude env refresh (Stage 8c, CS-04).

    For each preset-owned key:
    - absent, or still carrying a value the PRESET (or cc-switch's MODEL
      fan-out) historically wrote → upgrade to the new official value;
    - carrying anything else → the USER changed it; keep their value.
    Keys outside the owned set are user-owned and always kept; keys retired
    from the preset are dropped.
    """
    owned: dict[str, str] = dict(provider["claude_env"])
    history: dict[str, list[str]] = provider.get("_env_history", {})
    retired: set[str] = set(provider.get("_retired_env_keys", []))

    merged = {
        k: v
        for k, v in existing_env.items()
        if k not in owned and k not in retired
    }
    for key, new_value in owned.items():
        existing_value = existing_env.get(key)
        if (
            existing_value is not None
            and existing_value != new_value
            and existing_value not in history.get(key, [])
        ):
            merged[key] = existing_value  # user override wins (D8-07)
        else:
            merged[key] = new_value
    return merged


def _extract_codex_api_key(existing_raw: str | None) -> str:
    """Pull the user's api_key out of an existing codex settings_config.

    auth.OPENAI_API_KEY is the live channel (synced to ~/.codex/auth.json);
    the model_providers.<id>.api_key TOML line is the legacy mirror kept
    for rows written before the auth channel existed.
    """
    existing = _parse_json_settings(existing_raw)
    auth = existing.get("auth")
    if isinstance(auth, dict) and auth.get("OPENAI_API_KEY"):
        return str(auth["OPENAI_API_KEY"])
    config_text = existing.get("config", "")
    if not isinstance(config_text, str) or not config_text:
        return ""
    try:
        toml = tomllib.loads(config_text)
    except Exception:
        return ""
    providers = toml.get("model_providers")
    if not isinstance(providers, dict):
        return ""
    for entry in providers.values():
        if isinstance(entry, dict) and entry.get("api_key"):
            return str(entry["api_key"])
    return ""


def _merged_settings(
    agent: str,
    provider: dict[str, Any],
    existing_raw: str | None,
) -> dict[str, Any]:
    """Build fresh settings for a provider, preserving user-owned fields.

    On a fresh install (existing_raw is None) this is just the preset config.
    On refresh it overlays the new preset-managed fields (base_url, model,
    wire_api, ...) while keeping the user's API key and any non-preset keys
    (e.g. codex OAuth auth mirror) carried on the existing settings_config.
    """
    if existing_raw is None:
        return _settings_config(agent, provider)

    existing = _parse_json_settings(existing_raw)

    if agent == "claude":
        existing_env = existing.get("env")
        existing_env = existing_env if isinstance(existing_env, dict) else {}
        if "claude_env" in provider:
            merged_env = _merged_claude_env(provider, existing_env)
        else:
            # IDEA-5 (5c): ANTHROPIC_MODEL rides the same ownership merge as
            # the claude_env presets — a user mapping override survives
            # refresh, while an absent/historical preset value upgrades.
            # BASE_URL keeps its legacy semantics (preset resets it).
            preset_env = _settings_config(agent, provider)["env"]
            preset_model = preset_env.get("ANTHROPIC_MODEL")
            synth = {
                "claude_env": ({"ANTHROPIC_MODEL": preset_model}
                               if preset_model is not None else {}),
                "_env_history": {
                    "ANTHROPIC_MODEL": list(provider.get("_model_history") or []),
                },
            }
            strip = {"ANTHROPIC_BASE_URL"}
            if preset_model is not None:
                strip.add("ANTHROPIC_MODEL")
            merged_env = {
                k: v for k, v in existing_env.items() if k not in strip
            }
            merged_env.update(_merged_claude_env(synth, existing_env))
            merged_env.update(
                {k: v for k, v in preset_env.items() if k != "ANTHROPIC_MODEL"}
            )
        result: dict[str, Any] = {"env": merged_env}
        # Seed-style base ownership (retest round 2): base keys are added
        # only when the stored row doesn't carry them — a row the user
        # customized in the TUI keeps its own statusLine/enabledPlugins on
        # every refresh; the tail loop below carries any other existing
        # keys forward untouched.
        for key, value in load_claude_settings_base().items():
            if key not in existing:
                result[key] = value
    elif agent == "codex":
        api_key = _extract_codex_api_key(existing_raw)
        result = _settings_config(agent, provider, api_key=api_key)
        # Preserve a non-empty existing auth object (e.g. the codex OAuth
        # mirror) — only absent/empty auth gets the fresh {} placeholder.
        # A key recovered from the row must ride along even here, or a
        # refresh would silently drop it back to placeholder-401.
        if isinstance(existing.get("auth"), dict) and existing["auth"]:
            result["auth"] = dict(existing["auth"])
            if api_key and not result["auth"].get("OPENAI_API_KEY"):
                result["auth"]["OPENAI_API_KEY"] = api_key
    else:
        raise ValueError(f"unsupported agent: {agent}")

    # Preserve any top-level keys the preset doesn't own (e.g. codex "auth").
    for key, value in existing.items():
        if key not in result:
            result[key] = value
    return result


def _validate_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(providers)")}
    missing = REQUIRED_PROVIDER_COLUMNS - columns
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise RuntimeError(
            "cc-switch providers schema is incompatible; "
            f"missing columns: {missing_text}"
        )


def preset_required(config_dir: Path, agent: str, revision: str) -> tuple[bool, str]:
    """Check whether this agent's preset revision has been applied."""
    marker = marker_path(config_dir, agent)
    if not marker.is_file():
        return True, "first initialization"

    try:
        existing_revision = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return True, "marker is unreadable"

    if existing_revision != revision:
        return True, "preset revision changed"
    return False, "current"


def _remove_retired_providers(
    conn: sqlite3.Connection,
    agent: str,
    existing: dict[str, str | None],
    log: TextIO,
) -> int:
    """Delete retired preset ids that still look like the old preset."""
    count = 0
    for retired_id, fingerprint in RETIRED_PROVIDER_IDS.items():
        if retired_id not in existing:
            continue
        if fingerprint not in (existing.get(retired_id) or ""):
            # The id exists but no longer matches the old preset shape; the
            # user likely repurposed it, so leave it alone.
            print(
                f"Retired id {retired_id} looks repurposed; keeping",
                file=log,
            )
            continue
        conn.execute(
            "DELETE FROM providers WHERE id = ? AND app_type = ?",
            (retired_id, agent),
        )
        print(f"Removed retired provider: {retired_id}", file=log)
        count += 1
    return count


def add_preset_providers(
    config_dir: Path,
    agent: str,
    revision: str,
    log: TextIO,
) -> tuple[int, int, int]:
    """Add or refresh presets in one transaction and update the agent marker.

    Existing preset providers are refreshed in place: preset-managed fields
    (name, settings_config, website_url, notes, sort_index) are overwritten
    with current values while user-owned fields (API key, is_current,
    in_failover_queue) are preserved. Retired preset ids are removed.
    Returns (added, refreshed, removed) counts.
    """
    db_path = config_dir / "cc-switch.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"cc-switch database does not exist: {db_path}")

    conn = sqlite3.connect(db_path, timeout=10)
    added = 0
    refreshed = 0
    removed = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        _validate_schema(conn)
        existing = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT id, settings_config, meta FROM providers WHERE app_type = ?",
                (agent,),
            )
        }
        now = int(time.time() * 1000)

        def _merged_meta(provider: dict[str, Any], raw_meta: str | None) -> str:
            """codex-adapt: presets declare the upstream wire format
            (``codex_api_format`` → cc-switch ``meta.apiFormat`` — the local
            router's translation selector). Ownership: the key is only set
            when ABSENT; a user/TUI-written meta (e.g. their mapping-page
            saves) always wins, other meta keys are preserved verbatim."""
            declared = provider.get("codex_api_format")
            meta: dict[str, Any] = {}
            if raw_meta:
                try:
                    parsed = json.loads(raw_meta)
                    if isinstance(parsed, dict):
                        meta = parsed
                except json.JSONDecodeError:
                    meta = {}
            if declared and "apiFormat" not in meta:
                meta["apiFormat"] = declared
            return json.dumps(meta, ensure_ascii=False, separators=(",", ":"))

        for sort_index, provider in enumerate(PRESET_PROVIDERS):
            provider_id = provider["id"]
            settings = json.dumps(
                _merged_settings(agent, provider, existing.get(provider_id, ("", None))[0]),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if provider_id in existing:
                conn.execute(
                    """
                    UPDATE providers
                    SET name = ?, settings_config = ?, website_url = ?,
                        notes = ?, sort_index = ?, meta = ?
                    WHERE id = ? AND app_type = ?
                    """,
                    (
                        provider["name"],
                        settings,
                        provider["base_url"],
                        provider["description"],
                        sort_index,
                        _merged_meta(provider, existing[provider_id][1]),
                        provider_id,
                        agent,
                    ),
                )
                print(
                    f"Refreshed provider: {provider_id} ({provider['name']})",
                    file=log,
                )
                refreshed += 1
            else:
                conn.execute(
                    """
                    INSERT INTO providers (
                        id, app_type, name, settings_config, website_url,
                        category, created_at, sort_index, notes, icon,
                        icon_color, meta, is_current, in_failover_queue
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        provider_id,
                        agent,
                        provider["name"],
                        settings,
                        provider["base_url"],
                        "custom",
                        now,
                        sort_index,
                        provider["description"],
                        None,
                        None,
                        _merged_meta(provider, None),
                        0,
                        0,
                    ),
                )
                print(f"Added provider: {provider_id} ({provider['name']})", file=log)
                added += 1

        removed = _remove_retired_providers(
            conn, agent, {k: v[0] for k, v in existing.items()}, log
        )

        expected = {provider["id"] for provider in PRESET_PROVIDERS}
        persisted = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM providers WHERE app_type = ?",
                (agent,),
            )
        }
        missing = expected - persisted
        if missing:
            raise RuntimeError(
                "provider insertion did not persist: " + ", ".join(sorted(missing))
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    marker = marker_path(config_dir, agent)
    temp_marker = marker.with_name(f"{marker.name}.tmp")
    temp_marker.write_text(f"{revision}\n", encoding="utf-8")
    temp_marker.replace(marker)
    return added, refreshed, removed


# ---------------------------------------------------------------------------
# Post-init reconcile (retest round 2, 2026-08-21): the provider-page choice
# owns BOTH agents' local proxy routes. Container start re-asserts the
# invariant so volumes created by older images (claude route force-enabled
# while sitting on the imported "default" row) self-heal.
# ---------------------------------------------------------------------------

OFFICIAL_ROW_IDS = {"claude": "claude-official", "codex": "codex-official"}


def _claude_row_real(settings: dict[str, Any]) -> bool:
    env = settings.get("env")
    return isinstance(env, dict) and bool(env.get("ANTHROPIC_BASE_URL"))


def _codex_row_real(settings: dict[str, Any]) -> bool:
    text = settings.get("config")
    if not isinstance(text, str) or not text:
        return False
    try:
        toml = tomllib.loads(text)
    except Exception:
        return False
    providers = toml.get("model_providers")
    if isinstance(providers, dict):
        for entry in providers.values():
            if isinstance(entry, dict) and entry.get("base_url"):
                return True
    return False


def _is_pristine_default_import(agent: str, pid: str, settings: dict[str, Any]) -> bool:
    """cc-switch's first-init import row ("default") before any user input:
    a settings.json snapshot with NO env (no endpoint, no token). Any env the
    user added means the row was repurposed — never touch it."""
    if agent != "claude" or pid != "default":
        return False
    env = settings.get("env")
    if not isinstance(env, dict):
        return True
    return not any(env.values())


def reconcile_runtime_state(
    config_dir: Path, log: TextIO, runner=subprocess.run
) -> list[str]:
    """Re-assert the proxy/default invariants at container start.

    1. Official rows exist for both agents (the cancel-proxy targets) —
       created when missing; claude-official gets the settings base keys
       while it is still cc-switch's bare seed shape (the claude switch
       replaces settings.json wholesale, so even the official row must
       carry the statusLine/plugin base).
    2. A PRISTINE imported "default" row is deleted; when it was current,
       current re-points to claude-official (user decision 2026-08-21 —
       "claude 出现 default 配置" was the confusing symptom). A row the
       user configured is never touched.
    3. Per agent: proxy route ON iff the current provider row is a real
       third-party endpoint. enable/disable are idempotent (live-probed
       2026-08-21), so unconditional calls converge legacy states.

    Best-effort by contract: a failing cc-switch call logs and continues;
    returns the actions taken (entrypoint echo + tests).
    """
    actions: list[str] = []
    db_path = config_dir / "cc-switch.db"
    if not db_path.is_file():
        return actions
    conn = sqlite3.connect(db_path, timeout=15)
    try:
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("BEGIN IMMEDIATE")
        current: dict[str, tuple[str, dict[str, Any]]] = {}
        for agent in SUPPORTED_AGENTS:
            row = conn.execute(
                "SELECT id, settings_config FROM providers "
                "WHERE app_type = ? AND is_current = 1 LIMIT 1",
                (agent,),
            ).fetchone()
            if row is not None:
                current[agent] = (str(row[0]), _parse_json_settings(row[1]))

        now = int(time.time() * 1000)
        for agent in SUPPORTED_AGENTS:
            official_id = OFFICIAL_ROW_IDS[agent]
            existing = conn.execute(
                "SELECT settings_config FROM providers "
                "WHERE id = ? AND app_type = ?",
                (official_id, agent),
            ).fetchone()
            if existing is None:
                settings = (
                    {"env": {}, **load_claude_settings_base()}
                    if agent == "claude"
                    else {"auth": {}, "config": ""}
                )
                next_sort = conn.execute(
                    "SELECT COALESCE(MAX(sort_index), -1) + 1 FROM providers "
                    "WHERE app_type = ?",
                    (agent,),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO providers ("
                    "id, app_type, name, settings_config, website_url, "
                    "category, created_at, sort_index, notes, icon, "
                    "icon_color, meta, is_current, in_failover_queue"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        official_id, agent,
                        "Claude Official" if agent == "claude" else "OpenAI Official",
                        json.dumps(settings, ensure_ascii=False,
                                   separators=(",", ":")),
                        "", "custom", now, next_sort, "", None, None,
                        "{}", 0, 0,
                    ),
                )
                if agent not in current:
                    # No current row at all — the fresh official row is the
                    # only candidate (env-less → proxy stays off).
                    current[agent] = (official_id, settings)
                actions.append(f"created {agent} official row")
                print(f"Created missing official row: {official_id}", file=log)
            elif agent == "claude":
                settings = _parse_json_settings(existing[0])
                if set(settings.keys()) <= {"env"}:
                    settings = {"env": settings.get("env") or {},
                                **load_claude_settings_base()}
                    conn.execute(
                        "UPDATE providers SET settings_config = ? "
                        "WHERE id = ? AND app_type = ?",
                        (json.dumps(settings, ensure_ascii=False,
                                    separators=(",", ":")),
                         official_id, agent),
                    )
                    if current.get(agent, ("", {}))[0] == official_id:
                        current[agent] = (official_id, settings)
                    actions.append("seeded claude-official settings base")
                    print("Seeded settings base into claude-official", file=log)

        claude_row = current.get("claude")
        if claude_row is not None and _is_pristine_default_import(
            "claude", claude_row[0], claude_row[1]
        ):
            conn.execute(
                "UPDATE providers SET is_current = 0 WHERE app_type = 'claude'"
            )
            conn.execute(
                "UPDATE providers SET is_current = 1 "
                "WHERE id = ? AND app_type = 'claude'",
                (OFFICIAL_ROW_IDS["claude"],),
            )
            conn.execute(
                "DELETE FROM providers WHERE id = 'default' AND app_type = 'claude'"
            )
            current["claude"] = (OFFICIAL_ROW_IDS["claude"], {})
            actions.append("removed imported claude 'default' row "
                           "(current -> claude-official)")
            print("Removed pristine 'default' import; current -> claude-official",
                  file=log)
        else:
            # Leftover sweep: a pristine non-current 'default' import (the
            # user already switched away) is deleted too — the TUI clutter
            # was the complaint. Repurposed rows survive, as above.
            for pid, raw in conn.execute(
                "SELECT id, settings_config FROM providers "
                "WHERE app_type = 'claude'"
            ).fetchall():
                if _is_pristine_default_import(
                    "claude", str(pid), _parse_json_settings(raw)
                ):
                    conn.execute(
                        "DELETE FROM providers "
                        "WHERE id = ? AND app_type = 'claude'",
                        (str(pid),),
                    )
                    actions.append("removed leftover claude 'default' row")
                    print("Removed leftover pristine 'default' import", file=log)
        conn.commit()
    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        print(f"Reconcile DB step failed (continuing to proxy calls): {exc}",
              file=log)
    finally:
        conn.close()

    real_check = {"claude": _claude_row_real, "codex": _codex_row_real}
    for agent in SUPPORTED_AGENTS:
        row = current.get(agent)
        real = row is not None and real_check[agent](row[1])
        verb = "enable" if real else "disable"
        try:
            completed = runner(
                ["cc-switch", "proxy", "-a", agent, verb],
                capture_output=True, text=True, timeout=30,
            )
        except Exception as exc:  # timeout / spawn failure — best-effort
            print(f"proxy {verb} {agent} could not run: {exc}", file=log)
            continue
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:200]
            print(f"proxy {verb} {agent} failed (exit "
                  f"{completed.returncode}): {detail}", file=log)
            continue
        actions.append(f"proxy {agent} {verb}d")
        print(f"Proxy route {agent}: {verb}d", file=log)
    return actions


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preconfigure cc-switch providers without API keys"
    )
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--agent", choices=SUPPORTED_AGENTS, default="claude")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--mode", default="auto")
    parser.add_argument(
        "--reconcile", action="store_true",
        help="post-init invariant pass only (official rows, pristine default "
             "import, proxy on/off per current provider); no preset refresh",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.config_dir.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)

    if args.reconcile:
        with args.log.open("a", encoding="utf-8") as log:
            try:
                actions = reconcile_runtime_state(args.config_dir, log)
            except Exception as exc:  # never fail container start
                print(f"Runtime state reconcile failed: {exc}", file=log)
                return 1
            print("reconciled" if actions else "current")
            for action in actions:
                print(f"  - {action}", file=log)
            return 0

    revision = preset_revision(args.agent)

    mode = args.mode.lower()
    with args.log.open("a", encoding="utf-8") as log:
        if mode not in {"auto", "always", "off"}:
            print(f"Unknown AISC_PRESET_PROVIDERS={args.mode!r}; using auto", file=log)
            mode = "auto"

        if mode == "off":
            print("off")
            return 0

        try:
            required, reason = preset_required(args.config_dir, args.agent, revision)
            if mode == "always":
                required, reason = True, "forced by AISC_PRESET_PROVIDERS=always"

            if not required:
                print("current")
                return 0

            print(f"Preconfiguring {args.agent} providers: {reason}", file=log)
            added, refreshed, removed = add_preset_providers(
                config_dir=args.config_dir,
                agent=args.agent,
                revision=revision,
                log=log,
            )
            if added:
                status = "added"
            elif refreshed or removed:
                status = "refreshed"
            else:
                status = "current"
            print(status)
            print(
                f"Added {added}, refreshed {refreshed}, removed {removed} "
                f"preset providers",
                file=log,
            )
            return 0
        except Exception as exc:
            print(f"Provider preconfiguration failed: {exc}", file=log)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
