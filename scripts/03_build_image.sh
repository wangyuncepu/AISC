#!/usr/bin/env bash
# scripts/03_build_image.sh — 镜像检测 + 构建菜单 → state(IMAGE, DO_RUN)
#   DO_RUN=1 运行(默认) / 0 构建后选"不运行" → 04 跳过 docker run
set -uo pipefail
source "$(dirname "$0")/_state.sh"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="$(state_get IMAGE)"
[ -z "$IMAGE" ] && IMAGE="super-claude:latest"

echo "📦 [3/4] 镜像构建..."

build_image() {
  if [ ! -f "$PROJECT_ROOT/Dockerfile" ]; then
    echo "❌ 未找到 Dockerfile: $PROJECT_ROOT/Dockerfile"
    exit 1
  fi
  local cache_flag="" mirror_arg="USE_CN_MIRROR=1"
  local node_arg="NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim"
  read -r -p "构建是否使用缓存? [Y/n]（n=--no-cache 全新构建）: " uc
  case "$uc" in n|N) cache_flag="--no-cache" ;; esac
  read -r -p "是否使用国内镜像源(基础镜像daocloud/apt清华/npm淘宝)? [Y/n]: " um
  case "$um" in n|N) mirror_arg="USE_CN_MIRROR=0"; node_arg="NODE_IMAGE=node:20-slim" ;; esac
  echo "📦 正在构建镜像: $IMAGE  ${cache_flag:+(无缓存) }(${mirror_arg}) ..."
  if ! docker build $cache_flag --build-arg "$mirror_arg" --build-arg "$node_arg" -t "$IMAGE" "$PROJECT_ROOT"; then
    echo "❌ 构建失败。"
    exit 1
  fi
  echo "✅ 构建完成: $IMAGE"
  echo
  read -r -p "构建成功，是否立即运行容器? [Y/n]（n=退出）: " rb
  case "$rb" in
    n|N) state_set DO_RUN 0; echo "👋 已退出，未启动容器。" ;;
  esac
}

image_exists() { docker image inspect "$IMAGE" >/dev/null 2>&1; }

if image_exists; then
  echo "⚠️  已存在同名镜像: $IMAGE"
  echo "   [1] 直接运行现有镜像（默认）"
  echo "   [2] 删除旧镜像并重新构建（避免悬空 <none> 镜像）"
  echo "   [3] 用新镜像名构建运行（保留旧镜像）"
  read -r -p "请选择 [1/2/3，默认 1]: " choice
  case "${choice:-1}" in
    2) echo "🗑️  删除旧镜像 $IMAGE ..."; docker rmi -f "$IMAGE" 2>/dev/null || true; build_image ;;
    3) read -r -p "输入新镜像名 (如 super-claude:v2): " NEWIMG
       [ -n "$NEWIMG" ] && IMAGE="$NEWIMG"
       build_image ;;
    *) echo "▶️  使用现有镜像。" ;;
  esac
else
  echo "🔍 未找到镜像 $IMAGE，开始构建..."
  build_image
fi

state_set IMAGE "$IMAGE"
exit 0
