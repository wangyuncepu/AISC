#!/usr/bin/env bash
# cli/lib/state.sh — KEY=value 状态文件读写
# 用法：source "$(dirname "$0")/state.sh"
#   state_init            创建 .aisc/ 并清空 state.env
#   state_set KEY VAL     设置值（追加/更新）
#   state_get KEY         读取值（无则空）
# 状态文件：$AISC_ROOT/.aisc/state.env（纯 shell source 兼容）

_STATE_ROOT="${AISC_ROOT:-$(pwd)}"
_STATE_DIR="$_STATE_ROOT/.aisc"
STATE_FILE="$_STATE_DIR/state.env"

state_init() {
  mkdir -p "$_STATE_DIR"
  : > "$STATE_FILE"
}

state_set() {
  local key="$1" val="$2"
  mkdir -p "$_STATE_DIR"
  local tmp="$STATE_FILE.tmp"
  grep -v "^${key}=" "$STATE_FILE" 2>/dev/null > "$tmp" || true
  printf '%s=%s\n' "$key" "$val" >> "$tmp"
  mv "$tmp" "$STATE_FILE"
}

state_get() {
  local key="$1"
  grep "^${key}=" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2- | tr -d '\r'
}
