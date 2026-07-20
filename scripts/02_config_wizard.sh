#!/usr/bin/env bash
# scripts/02_config_wizard.sh — 代理配置向导（TUI）→ .claude/mihomo/config.yaml + state(PROXY_ENABLED)
# 宿主只下载/拷贝用户原始配置；TUN 块由容器 entrypoint 注入。格式由容器内自动识别/转换。
# 代理为可选项：失败/跳过 → PROXY_ENABLED=0 回退直连（非阻断，匹配旧行为）。
set -uo pipefail
source "$(dirname "$0")/_state.sh"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MIHOMO_DIR="$PROJECT_ROOT/.claude/mihomo"
CFG="$MIHOMO_DIR/config.yaml"

echo "🌐 [2/4] 代理网络配置（容器内访问 Anthropic API 等国际网络）"
read -r -p "是否需要配置代理网络? [y/N]: " pc
case "$pc" in
  y|Y) ;;
  *) echo "⏭️  跳过代理，容器直连网络。"; state_set PROXY_ENABLED 0; exit 0 ;;
esac

echo "  1) 本地文件 — 输入本地配置文件绝对路径"
echo "  2) 网络链接 — 输入订阅链接 / 配置直链 URL"
read -r -p "选择 [1/2，默认 2]: " mode
mode="${mode:-2}"

mkdir -p "$MIHOMO_DIR"
ok=0
if [ "$mode" = "1" ]; then
  read -r -p "本地配置文件绝对路径: " src
  if [ ! -f "$src" ]; then
    echo "❌ 文件不存在: $src"
  else
    cp -f "$src" "$CFG"; ok=1
  fi
else
  read -r -p "配置 URL: " url
  if [ -z "$url" ]; then
    echo "❌ URL 为空"
  else
    echo "⬇️  下载配置..."
    if curl -fsSL "$url" -o "$CFG"; then ok=1; else echo "❌ 下载失败: $url"; rm -f "$CFG"; fi
  fi
fi

# 基本校验：非空即可。格式（yaml/base64订阅/URI直链/JSON）由容器内自动识别/转换。
if [ "$ok" = "1" ] && [ ! -s "$CFG" ]; then
  echo "❌ 配置内容为空。"; ok=0; rm -f "$CFG"
fi

if [ "$ok" = "1" ]; then
  echo "✅ 代理配置已就绪: $CFG（格式由容器内自动识别/转换）"
  state_set PROXY_ENABLED 1
else
  echo "⚠️  代理配置未完成，将以直连启动。"
  state_set PROXY_ENABLED 0
fi
exit 0
