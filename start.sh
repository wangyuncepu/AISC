#!/usr/bin/env bash
# Super Claude AI 工作站入口（薄壳）—— 按序调用 scripts/ 流水线模块
# 模块：01_check_env → 02_config_wizard → 03_build_image → 04_launcher
# 用法：start.sh [--workspace PATH]
#   --workspace PATH  指定要挂载为容器 root 家目录 /root 的工作目录
#                     默认：当前工作目录
set -uo pipefail

# 保存原始工作目录（在任何 cd 之前）
AISC_WORKSPACE="${ORIGINAL_PWD:-$(pwd)}"

# 解析 --workspace 参数
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      AISC_WORKSPACE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: start.sh [--workspace PATH]" >&2
      exit 1
      ;;
  esac
done

# 验证 workspace 目录
if [[ ! -d "$AISC_WORKSPACE" ]]; then
  echo "❌ Workspace directory does not exist: $AISC_WORKSPACE" >&2
  exit 1
fi
if [[ ! -r "$AISC_WORKSPACE" ]]; then
  echo "❌ Workspace directory is not readable: $AISC_WORKSPACE" >&2
  exit 1
fi
export AISC_WORKSPACE

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$SCRIPT_DIR/scripts/run.sh"
