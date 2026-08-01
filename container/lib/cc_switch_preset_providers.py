#!/usr/bin/env python3
"""为 cc-switch 预配置常见 AI 供应商的 provider（不包含 API Key）。

仅在首次初始化或明确指定时添加；已存在的 provider 不会覆盖。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from typing import TextIO

# 预设 provider 配置（不包含 API Key）
PRESET_PROVIDERS = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "description": "DeepSeek 高性价比 AI 模型服务",
    },
    {
        "id": "codex-claude",
        "name": "Codex Claude",
        "base_url": "https://api.codex.so/v1",
        "model": "claude-opus-5",
        "description": "通过 Codex 订阅访问 Claude 官方模型",
    },
    {
        "id": "volcengine-ark",
        "name": "火山引擎 Ark",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "",  # 需要用户指定 endpoint ID
        "description": "火山引擎 Ark 模型推理服务（需在控制台创建推理接入点）",
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "description": "智谱 AI GLM 系列大语言模型",
    },
    {
        "id": "kimi",
        "name": "Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-128k",
        "description": "月之暗面 Kimi 长文本 AI 模型",
    },
]

MARKER_FILE = ".aisc-preset-providers.sha256"


def _get_existing_providers(db_path: Path, agent: str) -> set[str]:
    """获取已存在的 provider ID 列表。"""
    if not db_path.is_file():
        return set()

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", timeout=10, uri=True)
        try:
            cursor = conn.execute(
                "SELECT id FROM providers WHERE agent = ?",
                (agent,),
            )
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()
    except sqlite3.Error:
        return set()


def _add_provider(
    db_path: Path,
    agent: str,
    provider_id: str,
    name: str,
    base_url: str,
    model: str,
    description: str,
    log: TextIO,
) -> bool:
    """添加单个 provider 到数据库。"""
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            now = int(time.time())
            conn.execute(
                """
                INSERT OR IGNORE INTO providers (
                    id, agent, name, base_url, model, description,
                    api_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider_id,
                    agent,
                    name,
                    base_url,
                    model,
                    description,
                    "",  # API Key 为空，需用户后续配置
                    now,
                    now,
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"添加 provider {provider_id} 失败: {exc}", file=log)
        return False


def preset_required(config_dir: Path, revision: str) -> tuple[bool, str]:
    """检查是否需要添加预设 provider。"""
    marker = config_dir / MARKER_FILE
    if not marker.is_file():
        return True, "首次初始化"

    try:
        existing_revision = marker.read_text(encoding="utf-8").strip()
        if existing_revision != revision:
            return True, f"版本变更 ({existing_revision} -> {revision})"
    except OSError:
        return True, "标记文件不可读"

    return False, "已预配置"


def add_preset_providers(
    config_dir: Path,
    agent: str,
    revision: str,
    log: TextIO,
) -> int:
    """添加预设 provider 到 cc-switch 数据库。

    Returns:
        添加的 provider 数量
    """
    db_path = config_dir / "cc-switch.db"
    if not db_path.is_file():
        print("cc-switch.db 不存在，跳过预配置", file=log)
        return 0

    existing = _get_existing_providers(db_path, agent)
    added = 0

    for provider in PRESET_PROVIDERS:
        provider_id = provider["id"]
        if provider_id in existing:
            print(f"Provider {provider_id} 已存在，跳过", file=log)
            continue

        if _add_provider(
            db_path=db_path,
            agent=agent,
            provider_id=provider_id,
            name=provider["name"],
            base_url=provider["base_url"],
            model=provider["model"],
            description=provider["description"],
            log=log,
        ):
            print(f"✓ 添加 provider: {provider_id} ({provider['name']})", file=log)
            added += 1
        else:
            print(f"✗ 添加 provider 失败: {provider_id}", file=log)

    # 写入标记文件
    if added > 0:
        marker = config_dir / MARKER_FILE
        temp_marker = config_dir / f"{MARKER_FILE}.tmp"
        temp_marker.write_text(f"{revision}\n", encoding="utf-8")
        temp_marker.replace(marker)

    return added


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="预配置 cc-switch provider（不包含 API Key）"
    )
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--agent", type=str, default="claude")
    parser.add_argument("--revision", type=str, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--mode", default="auto")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.config_dir.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)

    mode = args.mode.lower()
    with args.log.open("a", encoding="utf-8") as log:
        if mode not in {"auto", "always", "off"}:
            print(
                f"未知模式 AISC_PRESET_PROVIDERS={args.mode!r}，使用 auto",
                file=log,
            )
            mode = "auto"

        if mode == "off":
            print("off")
            return 0

        try:
            required, reason = preset_required(args.config_dir, args.revision)
            if mode == "always":
                required, reason = True, "强制预配置 (AISC_PRESET_PROVIDERS=always)"

            if not required:
                print("current")
                return 0

            print(f"预配置 provider: {reason}", file=log)
            added = add_preset_providers(
                config_dir=args.config_dir,
                agent=args.agent,
                revision=args.revision,
                log=log,
            )

            if added > 0:
                print("added", file=sys.stdout)
                print(f"已添加 {added} 个预设 provider", file=log)
            else:
                print("current", file=sys.stdout)
                print("所有预设 provider 均已存在", file=log)

            return 0

        except Exception as exc:
            print(f"预配置失败: {exc}", file=log)
            import traceback
            traceback.print_exc(file=log)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
