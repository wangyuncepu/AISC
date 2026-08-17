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
        "claude_env": env,
        "_env_history": history,
        "_retired_env_keys": [],
        "description": (
            "DeepSeek V4 (official Anthropic-compatible endpoint; "
            "pro[1m] main + flash for haiku/subagent per official docs)"
        ),
    }


def build_preset_providers(fixture_path: Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    fixture = load_deepseek_fixture(fixture_path)
    return [
        deepseek_provider_from_fixture(fixture),
        {
            "id": "volcengine-ark",
            "name": "Volcengine Ark",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "model": "",
            "description": "Volcengine Ark inference service; configure an endpoint ID",
        },
        {
            "id": "zhipu",
            "name": "Zhipu GLM",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "anthropic_base_url": "https://open.bigmodel.cn/api/anthropic",
            "model": "glm-5.2",
            "description": "Zhipu GLM-5.2 flagship model service",
        },
        {
            "id": "kimi",
            "name": "Kimi",
            "base_url": "https://api.moonshot.cn/v1",
            "anthropic_base_url": "https://api.moonshot.cn/anthropic",
            "model": "kimi-k3",
            "description": "Moonshot Kimi K3 model service",
        },
    ]


PRESET_PROVIDERS = build_preset_providers()

SUPPORTED_AGENTS = ("claude", "codex")
MARKER_TEMPLATE = ".aisc-preset-providers-{agent}.sha256"
PRESET_FORMAT_VERSION = 4
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
            return {"env": dict(provider["claude_env"])}
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
        return {"env": env}

    if agent == "codex":
        provider_id = provider["id"]
        lines = [
            f"model_provider = {_toml_string(provider_id)}",
        ]
        if provider["model"]:
            lines.append(f"model = {_toml_string(provider['model'])}")
        lines.extend(
            [
                'model_reasoning_effort = "high"',
                "",
                f"[model_providers.{provider_id}]",
                f"name = {_toml_string(provider_id)}",
                f"base_url = {_toml_string(provider['base_url'])}",
                # Third-party OpenAI-compatible providers implement Chat
                # Completions, not OpenAI's proprietary Responses API.
                'wire_api = "chat"',
                "requires_openai_auth = true",
            ]
        )
        # api_key is the one user-owned field that must survive a preset
        # refresh; it is only re-injected when refreshing an existing provider.
        if api_key:
            lines.append(f"api_key = {_toml_string(api_key)}")
        lines.append("")
        return {"config": "\n".join(lines)}

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
    """Pull the user's api_key out of an existing codex settings_config TOML."""
    config_text = _parse_json_settings(existing_raw).get("config", "")
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
            merged_env = {
                k: v for k, v in existing_env.items()
                if k not in _CLAUDE_PRESET_ENV_KEYS
            }
            merged_env.update(_settings_config(agent, provider)["env"])
        result: dict[str, Any] = {"env": merged_env}
    elif agent == "codex":
        api_key = _extract_codex_api_key(existing_raw)
        result = _settings_config(agent, provider, api_key=api_key)
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
            row[0]: row[1]
            for row in conn.execute(
                "SELECT id, settings_config FROM providers WHERE app_type = ?",
                (agent,),
            )
        }
        now = int(time.time() * 1000)

        for sort_index, provider in enumerate(PRESET_PROVIDERS):
            provider_id = provider["id"]
            settings = json.dumps(
                _merged_settings(agent, provider, existing.get(provider_id)),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if provider_id in existing:
                conn.execute(
                    """
                    UPDATE providers
                    SET name = ?, settings_config = ?, website_url = ?,
                        notes = ?, sort_index = ?
                    WHERE id = ? AND app_type = ?
                    """,
                    (
                        provider["name"],
                        settings,
                        provider["base_url"],
                        provider["description"],
                        sort_index,
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
                        "{}",
                        0,
                        0,
                    ),
                )
                print(f"Added provider: {provider_id} ({provider['name']})", file=log)
                added += 1

        removed = _remove_retired_providers(conn, agent, existing, log)

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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preconfigure cc-switch providers without API keys"
    )
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--agent", choices=SUPPORTED_AGENTS, default="claude")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--mode", default="auto")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.config_dir.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
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
