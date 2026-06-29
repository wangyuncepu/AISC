#!/usr/bin/env bash
set -euo pipefail

IMAGE="super-claude:latest"
# 容器名加唯一后缀（PID），避免多开（项目+临时并行）时同名容器互相挤掉
NAME="super-claude-station-$$"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"   # 构建上下文（AISC 目录，含 Dockerfile + _bundle）

echo
echo "🚀 Super Claude AI 工作站"
echo "   cs 一键切换 · 插件/技能内置"
echo

# ── 构建镜像（自包含：仓库已含 _bundle，无需联网/宿主机插件）──
build_image() {
  local cache_flag="" mirror_arg="USE_CN_MIRROR=1"
  # 国内镜像默认连基础镜像 node 也走 daocloud（绕开 docker.io 超时）
  local node_arg="NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim"

  read -r -p "构建是否使用缓存? [Y/n]（n=--no-cache 全新构建）: " uc
  case "$uc" in n|N) cache_flag="--no-cache" ;; esac

  read -r -p "是否使用国内镜像源(基础镜像daocloud/apt清华/npm淘宝)? [Y/n]: " um
  case "$um" in
    n|N) mirror_arg="USE_CN_MIRROR=0"; node_arg="NODE_IMAGE=node:20-slim" ;;
  esac

  echo "📦 正在构建镜像: $IMAGE  ${cache_flag:+(无缓存) }(${mirror_arg}) ..."
  docker build $cache_flag --build-arg "$mirror_arg" --build-arg "$node_arg" -t "$IMAGE" "$SCRIPT_DIR"
  echo "✅ 构建完成: $IMAGE"
}

image_exists() { docker image inspect "$IMAGE" >/dev/null 2>&1; }

if image_exists; then
  # ── 防止悬空镜像：同名镜像已存在，提示用户处理 ──
  echo "⚠️  已存在同名镜像: $IMAGE"
  echo "   [1] 直接运行现有镜像（默认）"
  echo "   [2] 删除旧镜像并重新构建（避免悬空 <none> 镜像）"
  echo "   [3] 用新镜像名构建运行（保留旧镜像）"
  read -r -p "请选择 [1/2/3，默认 1]: " choice
  case "${choice:-1}" in
    2)
      echo "🗑️  删除旧镜像 $IMAGE ..."
      docker rmi -f "$IMAGE" 2>/dev/null || true
      build_image
      ;;
    3)
      read -r -p "输入新镜像名 (如 super-claude:v2): " NEWIMG
      [ -n "$NEWIMG" ] && IMAGE="$NEWIMG"
      build_image
      ;;
    *)
      echo "▶️  使用现有镜像。"
      ;;
  esac
else
  echo "🔍 未找到镜像 $IMAGE，开始构建..."
  build_image
fi

echo
echo "📦 正在启动容器..."
echo "💡 容器内：cs ark / cs deepseek / cs show 切换模型后端"
echo

# 仅清理已退出的旧工作站容器（不影响正在运行的，支持多开并行）
docker ps -aq -f "name=super-claude-station" -f "status=exited" 2>/dev/null | xargs -r docker rm >/dev/null 2>&1 || true

docker run -it --rm -e TERM=xterm-256color --name "$NAME" -v "$(pwd):/app" "$IMAGE"
