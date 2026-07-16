#!/usr/bin/env bash
# scripts/_state.sh — 启动器流水线状态文件助手（模块间解耦传参）
# 用法：source "$(dirname "$0")/_state.sh"
#   state_init            建 .aisc 并清空 state.env（同时写入 .deploy 向后兼容）
#   state_set KEY VAL     追加/更新（值须为简单串：无空格/特殊字符；路径不入状态）
#   state_get KEY         输出值（无则空）
# 状态文件（新）：$AISC_HOME/state.env  主位置
# 状态文件（旧）：$AISC_ROOT/.deploy/state.env  向后兼容（已弃用）
#   只存简单值：IMAGE / PROXY_ENABLED / CONTAINER_NAME。路径由各模块从自身位置推导。
AISC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AISC_HOME="${AISC_ROOT}/.aisc"
_STATE_DIR="$AISC_HOME"
STATE_FILE="$_STATE_DIR/state.env"
_LEGACY_STATE_DIR="${AISC_ROOT}/.deploy"
_LEGACY_STATE_FILE="${_LEGACY_STATE_DIR}/state.env"
_STATE_HEADER="# AISC launcher state — do not edit manually"

state_init() {
  mkdir -p "$_STATE_DIR"
  printf '%s\n\n' "$_STATE_HEADER" > "$STATE_FILE"
  # Backward compat: also initialize legacy state file
  mkdir -p "$_LEGACY_STATE_DIR"
  printf '%s\n\n' "$_STATE_HEADER" > "$_LEGACY_STATE_FILE"
}

state_set() {
  local key="$1" val="$2"

  _write_one() {
    local file="$1"
    local dir
    dir="$(dirname "$file")"
    mkdir -p "$dir"
    local tmp="$file.tmp"
    # Write header
    printf '%s\n\n' "$_STATE_HEADER" > "$tmp"
    # Copy all existing non-header, non-matching-key lines
    grep -v "^#" "$file" 2>/dev/null | grep -v "^${key}=" >> "$tmp" || true
    # Append the new value
    printf '%s=%s\n' "$key" "$val" >> "$tmp"
    mv "$tmp" "$file"
  }

  _write_one "$STATE_FILE"
  _write_one "$_LEGACY_STATE_FILE"
}

state_get() {
  local key="$1"
  # Read from new location first
  if [[ -f "$STATE_FILE" ]]; then
    local val
    val="$(grep "^${key}=" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2- | tr -d '\r')"
    if [[ -n "$val" ]]; then
      echo "$val"
      return
    fi
  fi
  # Fall back to legacy location
  grep "^${key}=" "$_LEGACY_STATE_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2- | tr -d '\r'
}
