#!/usr/bin/env bash
# 启动 LiteLLM 反向代理：监听 4000 端口，按 config.yaml 做模型映射。
# Claude Code 流量 -> localhost:4000/v1/messages -> 协议转换 -> openai/gpt-4o
#
# 运行：bash start_proxy.sh   （DrvFs 无 exec 位，需用 bash 显式调用）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 宿主(Python3.14+DrvFs)：有 run_proxy.py+.venv -> 走它绕 uvloop 不兼容。
# 容器(Python3.11, litellm 在 PATH)：直接 litellm。
if [ -f "$HERE/run_proxy.py" ] && [ -x "$HERE/.venv/bin/python" ]; then
  exec "$HERE/.venv/bin/python" "$HERE/run_proxy.py" --config "$HERE/config.yaml" --port 4000
else
  exec litellm --config "$HERE/config.yaml" --port 4000
fi
