#!/usr/bin/env bash
# 启动 LiteLLM 反向代理：交互式输入上游 base_url + api_key，起 :4000。
# Claude Code 流量 -> localhost:4000/v1/messages -> 协议转换 -> openai/gpt-4o
#
# 运行：bash start_proxy.sh   （DrvFs 无 exec 位，需用 bash 显式调用）
# 非交互：预设 OPENAI_API_BASE / OPENAI_API_KEY 环境变量即可跳过提示。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_CONFIG="$HERE/.config.runtime.yaml"

echo "🔧 配置 LiteLLM 上游（OpenAI 兼容渠道）"
echo "   外部模型名: claude-3-7-sonnet-20250219（Claude Code 强校验）"
echo "   后端模型:   openai/gpt-4o"
echo

# 优先环境变量，否则交互输入
API_BASE="${OPENAI_API_BASE:-}"
API_KEY="${OPENAI_API_KEY:-}"
[ -z "$API_BASE" ] && read -r -p "API Base URL（留空=OpenAI 官方 api.openai.com）: " API_BASE
[ -z "$API_KEY" ] && { read -r -s -p "API Key: " API_KEY; echo; }
[ -z "$API_KEY" ] && { echo "❌ API Key 不能为空"; exit 1; }

# 生成运行时配置（不覆盖原 config.yaml；含 key 故不入 git）
BASE_LINE=""
[ -n "$API_BASE" ] && BASE_LINE="      api_base: $API_BASE"
cat > "$RUNTIME_CONFIG" <<EOF
# 运行时生成（start_proxy.sh），含 API Key，勿提交 git
model_list:
  - model_name: claude-3-7-sonnet-20250219
    litellm_params:
      model: openai/gpt-4o
      api_key: "$API_KEY"
$BASE_LINE
litellm_settings:
  telemetry: False
EOF

echo "✅ 配置已生成: $RUNTIME_CONFIG"
echo "🚀 启动 LiteLLM Proxy (:4000)..."
echo

# 宿主(Python3.14+DrvFs)：有 run_proxy.py+.venv -> 走它绕 uvloop 不兼容。
# 容器(Python3.11, litellm 在 PATH)：直接 litellm。
if [ -f "$HERE/run_proxy.py" ] && [ -x "$HERE/.venv/bin/python" ]; then
  exec "$HERE/.venv/bin/python" "$HERE/run_proxy.py" --config "$RUNTIME_CONFIG" --port 4000
else
  exec litellm --config "$RUNTIME_CONFIG" --port 4000
fi
