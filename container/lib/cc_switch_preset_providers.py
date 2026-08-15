#!/usr/bin/env python3
"""Preconfigure cc-switch providers without storing API keys."""

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


PRESET_PROVIDERS = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        # Per api-docs.deepseek.com (2026-08): the OpenAI-compatible base URL is
        # https://api.deepseek.com (the legacy /v1 alias also works); the
        # Anthropic-compatible endpoint is https://api.deepseek.com/anthropic.
        "base_url": "https://api.deepseek.com",
        "anthropic_base_url": "https://api.deepseek.com/anthropic",
        # Primary model for both the OpenAI and Anthropic endpoints.
        "model": "deepseek-v4-pro",
        # Claude Code's ANTHROPIC_MODEL per the docs (opus-equivalent; the
        # [1m] context variant is what the docs recommend for Claude Code).
        "anthropic_model": "deepseek-v4-pro[1m]",
        "description": "DeepSeek V4; deepseek-v4-pro primary (Claude Code opus-equivalent), "
                       "deepseek-v4-flash for fast/cheap reasoning",
    },
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

SUPPORTED_AGENTS = ("claude", "codex")
MARKER_TEMPLATE = ".aisc-preset-providers-{agent}.sha256"
PRESET_FORMAT_VERSION = 3
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
    agent: str, provider: dict[str, str], *, api_key: str = ""
) -> dict[str, Any]:
    if agent == "claude":
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


# Env keys the preset owns on the claude agent; refresh overwrites these but
# leaves any other env var (notably ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN)
# untouched so a user's stored key survives a preset update.
_CLAUDE_PRESET_ENV_KEYS = frozenset({"ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"})


def _parse_json_settings(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


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
    provider: dict[str, str],
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
