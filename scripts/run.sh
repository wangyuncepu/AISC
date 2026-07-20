#!/usr/bin/env bash
# scripts/run.sh — Super Claude AI 工作站流水线编排
# 按序调用 01_check_env → 02_config_wizard → 03_build_image → 04_launcher
# 模块间用 .aisc/state.env (KEY=value) 解耦传参（.deploy/state.env 向后兼容）。任一模块非零退出即中止。
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_state.sh"

echo
echo "🚀 Super Claude AI 工作站"
echo "   cs 一键切换 · 插件/技能内置 · 容器内 TUN 代理"
echo

# 初始化状态（每次运行重生成）
state_init
state_set CONTAINER_NAME "super-claude-station-$$"
state_set IMAGE          "super-claude:latest"
state_set DO_RUN          1
state_set PROXY_ENABLED   0

# 流水线（各模块独立进程，互不污染；状态经文件传递）
bash "$SCRIPT_DIR/01_check_env.sh"    || { echo "❌ 环境检测未通过，已中止。"; exit 1; }
bash "$SCRIPT_DIR/02_config_wizard.sh" || { echo "❌ 配置向导未通过，已中止。"; exit 1; }
bash "$SCRIPT_DIR/03_build_image.sh"   || { echo "❌ 镜像构建未通过，已中止。"; exit 1; }
bash "$SCRIPT_DIR/04_launcher.sh"      || { echo "❌ 启动失败，已中止。"; exit 1; }
