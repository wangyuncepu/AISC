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
  echo
  read -r -p "构建成功，是否立即运行容器? [Y/n]（n=退出）: " rb
  case "$rb" in
    n|N) echo "👋 已退出。" ; exit 0 ;;
  esac
}

image_exists() { docker image inspect "$IMAGE" >/dev/null 2>&1; }

# ── 代理网络配置（容器内建 Mihomo TUN）──
#   宿主只下载/拷贝用户原始配置到 .claude/mihomo/config.yaml；TUN 块由容器 entrypoint 注入。
#   选“需要代理”→ docker run 追加 NET_ADMIN + /dev/net/tun + 配置只读挂载。
PROXY_ENABLED=0
configure_proxy() {
  local mihomo_dir="$SCRIPT_DIR/.claude/mihomo"
  local cfg="$mihomo_dir/config.yaml"

  echo "🌐 代理网络配置（容器内访问 Anthropic API 等国际网络）"
  read -r -p "是否需要配置代理网络? [y/N]: " pc
  case "$pc" in
    y|Y) ;;
    *) echo "⏭️  跳过代理，容器直连网络。"; return 0 ;;
  esac

  echo "  1) 本地文件 — 输入本地 config.yaml 绝对路径"
  echo "  2) 网络链接 — 输入订阅链接 / 配置直链 URL"
  read -r -p "选择 [1/2，默认 2]: " mode
  mode="${mode:-2}"

  mkdir -p "$mihomo_dir"
  if [ "$mode" = "1" ]; then
    read -r -p "本地 config.yaml 绝对路径: " src
    if [ ! -f "$src" ]; then
      echo "❌ 文件不存在: $src"
      return 1
    fi
    cp -f "$src" "$cfg"
  else
    read -r -p "配置 URL: " url
    [ -n "$url" ] || { echo "❌ URL 为空"; return 1; }
    echo "⬇️  下载配置..."
    if ! curl -fsSL "$url" -o "$cfg"; then
      echo "❌ 下载失败: $url"
      rm -f "$cfg"; return 1
    fi
  fi

  # 基本校验：非空即可。格式（yaml / base64 订阅 / URI 直链 / JSON）由容器内自动识别与转换。
  if [ ! -s "$cfg" ]; then
    echo "❌ 下载内容为空。"
    rm -f "$cfg"; return 1
  fi
  echo "✅ 代理配置已就绪: $cfg（格式由容器内自动识别/转换）"
  PROXY_ENABLED=1
  return 0
}

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

# ── 代理网络引导（容器内建 Mihomo TUN）──
configure_proxy || { echo "⚠️  代理配置未完成，将以直连启动。"; PROXY_ENABLED=0; }

# 仅清理已退出的旧工作站容器（不影响正在运行的，支持多开并行）
docker ps -aq -f "name=super-claude-station" -f "status=exited" 2>/dev/null | xargs -r docker rm >/dev/null 2>&1 || true

# 拼接 docker run 参数；启用代理时追加 NET_ADMIN + /dev/net/tun + 配置只读挂载
RUN_ARGS=(-it --rm -e TERM=xterm-256color --name "$NAME" -v "$(pwd):/home/AISC/app")
if [ "$PROXY_ENABLED" = "1" ]; then
  RUN_ARGS+=(--cap-add=NET_ADMIN --device /dev/net/tun \
    -v "$SCRIPT_DIR/.claude/mihomo/config.yaml:/etc/mihomo/config.yaml:ro")
  echo "🛡️  已启用容器内 TUN 透明代理（NET_ADMIN + /dev/net/tun）"
fi

docker run "${RUN_ARGS[@]}" "$IMAGE"
