#!/usr/bin/env bash
# Super Claude AI 工作站入口（薄壳）—— 按序调用 scripts/ 流水线模块
# 模块：01_check_env → 02_config_wizard → 03_build_image → 04_launcher
# 状态经 .deploy/state.env 解耦。详见 scripts/ 各模块。
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$SCRIPT_DIR/scripts/run.sh"
