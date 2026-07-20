#!/usr/bin/env bash
# cli/lib/workspace.sh — workspace 路径解析
# 用法：source "$(dirname "$0")/workspace.sh"
#   resolve_workspace [--workspace PATH]
# 优先级：--workspace > $AISC_ROOT > $(pwd)
# 验证目录存在且可读，输出解析后的绝对路径

resolve_workspace() {
  local ws=""

  # 解析 --workspace 参数
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --workspace)
        ws="$2"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done

  # 确定 workspace 路径
  if [[ -n "$ws" ]]; then
    ws="$(realpath "$ws" 2>/dev/null || echo "$ws")"
  elif [[ -n "${AISC_ROOT:-}" ]]; then
    ws="$AISC_ROOT"
  else
    ws="$(pwd)"
  fi

  # 验证目录存在且可读
  if [[ ! -d "$ws" ]]; then
    echo "Error: workspace '$ws' does not exist or is not a directory" >&2
    return 1
  fi
  if [[ ! -r "$ws" ]]; then
    echo "Error: workspace '$ws' is not readable" >&2
    return 1
  fi

  echo "$ws"
}
