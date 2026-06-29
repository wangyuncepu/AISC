#!/usr/bin/env bash
set -euo pipefail

IMAGE="super-claude:latest"
NAME="super-claude-station"

echo
echo "🚀 Super Claude AI 工作站"
echo "   v1.1.3 · cs 一键切换"
echo
echo "📦 正在启动容器..."
echo "💡 容器内可用 cs ark / cs deepseek / cs show 切换模型后端"
echo

# 清理上次残留的同名容器，避免堆积 (no.3)
docker rm -f "$NAME" 2>/dev/null || true

docker run -it --rm --name "$NAME" -v "$(pwd):/app" "$IMAGE"
