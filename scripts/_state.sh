#!/usr/bin/env bash
# scripts/_state.sh — 启动器流水线状态文件助手（模块间解耦传参）
# 用法：source "$(dirname "$0")/_state.sh"
#   state_init            建 .deploy 并清空 state.env
#   state_set KEY VAL     追加/更新（值须为简单串：无空格/特殊字符；路径不入状态）
#   state_get KEY         输出值（无则空）
# 状态文件：$PROJECT_ROOT/.deploy/state.env  (KEY=value, ASCII, LF)
#   只存简单值：IMAGE / PROXY_ENABLED / CONTAINER_NAME。路径由各模块从自身位置推导。
_STATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.deploy"
STATE_FILE="$_STATE_DIR/state.env"

state_init() {
  mkdir -p "$_STATE_DIR"
  : > "$STATE_FILE"
}

state_set() {
  local key="$1" val="$2"
  mkdir -p "$_STATE_DIR"
  local tmp="$STATE_FILE.tmp"
  # 移除旧的同名行，再追加新值（避免 sed 特殊字符问题）
  grep -v "^${key}=" "$STATE_FILE" 2>/dev/null > "$tmp" || true
  printf '%s=%s\n' "$key" "$val" >> "$tmp"
  mv "$tmp" "$STATE_FILE"
}

state_get() {
  local key="$1"
  grep "^${key}=" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2- | tr -d '\r'
}
