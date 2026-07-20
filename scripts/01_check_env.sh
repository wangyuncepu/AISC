#!/usr/bin/env bash
# scripts/01_check_env.sh — 环境检测：docker 已安装且 daemon 运行中
set -uo pipefail

echo "🔍 [1/4] 环境检测..."

# docker 命令存在？
if ! command -v docker >/dev/null 2>&1; then
  echo "❌ 未检测到 docker。请先安装 Docker：https://www.docker.com/"
  exit 1
fi

# daemon 运行中？
if ! docker info >/dev/null 2>&1; then
  echo "❌ Docker daemon 未运行。请启动 Docker Desktop（Windows/macOS）或 docker 服务（Linux）。"
  exit 1
fi

echo "✅ Docker 已就绪。"
exit 0
