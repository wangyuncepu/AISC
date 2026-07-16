#!/usr/bin/env bash
# scripts/04_launcher.sh — 读 state → docker run（按需加 NET_ADMIN/tun/挂载）
set -uo pipefail
source "$(dirname "$0")/_state.sh"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="$(state_get IMAGE)";    [ -z "$IMAGE" ] && IMAGE="super-claude:latest"
NAME="$(state_get CONTAINER_NAME)";  [ -z "$NAME" ] && NAME="super-claude-station-$$"
PROXY="$(state_get PROXY_ENABLED)"
DO_RUN="$(state_get DO_RUN)";  [ -z "$DO_RUN" ] && DO_RUN=1

if [ "$DO_RUN" = "0" ]; then
  echo "ℹ️  DO_RUN=0，未启动容器。"
  exit 0
fi

# 确定 workspace 挂载源：--workspace > AISC_WORKSPACE env > pwd
WORKSPACE="${AISC_WORKSPACE:-$(pwd)}"
if [[ ! -d "$WORKSPACE" ]]; then
  echo "❌ Workspace directory does not exist: $WORKSPACE" >&2
  exit 1
fi
if [[ ! -r "$WORKSPACE" ]]; then
  echo "❌ Workspace directory is not readable: $WORKSPACE" >&2
  exit 1
fi

echo "🚀 [4/4] 启动容器..."
echo "💡 容器内：cs ark / cs deepseek / cs show 切换模型后端"
echo "📂 Workspace: $WORKSPACE -> /home/AISC/app"
echo

# 仅清理已退出的旧工作站容器（保留运行中的，支持多开并行）
docker ps -aq -f "name=super-claude-station" -f "status=exited" 2>/dev/null | xargs -r docker rm >/dev/null 2>&1 || true

# 拼接 docker run 参数；启用代理时追加 NET_ADMIN + /dev/net/tun + 配置只读挂载
RUN_ARGS=(-it --rm -e TERM=xterm-256color --name "$NAME" -v "$WORKSPACE:/home/AISC/app")
if [ "$PROXY" = "1" ]; then
  RUN_ARGS+=(--cap-add=NET_ADMIN --device /dev/net/tun \
    -v "$PROJECT_ROOT/.claude/mihomo/config.yaml:/etc/mihomo/config.yaml:ro")
  echo "🛡️  已启用容器内 TUN 透明代理（NET_ADMIN + /dev/net/tun）"
fi

docker run "${RUN_ARGS[@]}" "$IMAGE"
