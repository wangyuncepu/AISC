#!/usr/bin/env bash
set -euo pipefail

IMAGE="super-claude:latest"

echo
echo "🚀 Super Claude AI 工作站"
echo "   v1.1.3 · cs 一键切换"
echo
echo "📦 正在启动容器..."
echo "💡 容器内可用 cs ark / cs deepseek / cs show 切换模型后端"
echo

docker run -it --rm -v "$(pwd):/app" "$IMAGE"
