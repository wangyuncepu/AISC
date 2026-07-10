#!/usr/bin/env bash
# 引导流量到本地 LiteLLM 代理并启动 Claude Code 客户端。
set -euo pipefail

export ANTHROPIC_BASE_URL="http://localhost:4000"
export ANTHROPIC_API_KEY="placeholder_key"

cat <<'EOF'
   ____ _               _         _                 _     _
  / ___(_)_ __ ___  ___| |_   _  | | ___   __ _  __| | __| |
 | |   | | '__/ _ \/ __| | | | | |/ _ \ / _` |/ _` |/ _` |
 | |___| | | |  __/ (__| | |_| | | (_) | (_| | (_| | (_| |
  \____|_|_|  \___|\___|_|\__, | |\___/ \__,_|\__,_|\__,_|
                          |___/ |_|
EOF
echo ">> 演示已准备就绪，即将启动本地 Claude 客户端..."
echo ">> ANTHROPIC_BASE_URL = $ANTHROPIC_BASE_URL"
echo ">> ANTHROPIC_API_KEY  = $ANTHROPIC_API_KEY  (代理 master_key 校验由 LiteLLM 处理)"
echo ">> 真实后端：openai/gpt-4o（经 LiteLLM 协议转换）"
echo

exec claude
