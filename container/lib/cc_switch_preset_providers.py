#!/usr/bin/env python3
"""Preconfigure cc-switch providers without storing API keys."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, TextIO


PRESET_PROVIDERS = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "description": "DeepSeek high-value AI model service",
    },
    {
        "id": "codex-claude",
        "name": "Codex Claude",
        "base_url": "https://api.codex.so/v1",
        "model": "claude-opus-5",
        "description": "Access Claude models through a Codex subscription",
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
        "model": "glm-4-plus",
        "description": "Zhipu AI GLM model service",
    },
    {
        "id": "kimi",
        "name": "Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-128k",
        "description": "Moonshot Kimi long-context model service",
    },
]

SUPPORTED_AGENTS = ("claude", "codex")
MARKER_TEMPLATE = ".aisc-preset-providers-{agent}.sha256"
PRESET_FORMAT_VERSION = 2
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


def _settings_config(agent: str, provider: dict[str, str]) -> dict[str, Any]:
    if agent == "claude":
        env = {"ANTHROPIC_BASE_URL": provider["base_url"]}
        if provider["model"]:
            env["ANTHROPIC_MODEL"] = provider["model"]
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
                "disable_response_storage = true",
                "",
                f"[model_providers.{provider_id}]",
                f"name = {_toml_string(provider_id)}",
                f"base_url = {_toml_string(provider['base_url'])}",
                'wire_api = "responses"',
                "requires_openai_auth = true",
                "",
            ]
        )
        return {"config": "\n".join(lines)}

    raise ValueError(f"unsupported agent: {agent}")


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


def add_preset_providers(
    config_dir: Path,
    agent: str,
    revision: str,
    log: TextIO,
) -> int:
    """Add missing presets in one transaction and update the agent marker."""
    db_path = config_dir / "cc-switch.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"cc-switch database does not exist: {db_path}")

    conn = sqlite3.connect(db_path, timeout=10)
    added = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        _validate_schema(conn)
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM providers WHERE app_type = ?",
                (agent,),
            )
        }
        now = int(time.time() * 1000)

        for sort_index, provider in enumerate(PRESET_PROVIDERS):
            provider_id = provider["id"]
            if provider_id in existing:
                print(f"Provider {provider_id} already exists; skipping", file=log)
                continue

            settings = json.dumps(
                _settings_config(agent, provider),
                ensure_ascii=False,
                separators=(",", ":"),
            )
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
    return added


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
            added = add_preset_providers(
                config_dir=args.config_dir,
                agent=args.agent,
                revision=revision,
                log=log,
            )
            print("added" if added else "current")
            print(f"Added {added} preset providers", file=log)
            return 0
        except Exception as exc:
            print(f"Provider preconfiguration failed: {exc}", file=log)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
