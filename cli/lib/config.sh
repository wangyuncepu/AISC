#!/usr/bin/env bash
# cli/lib/config.sh — 配置文件读写 (.aisc/config.env)
# 用法：source "$(dirname "$0")/config.sh"
#   config_read KEY      从 .aisc/config.env 读取值（无则空）
#   config_write KEY VAL 写入 .aisc/config.env
# 格式：每行 KEY=VALUE，纯 shell source 兼容

_CONFIG_ROOT="${AISC_ROOT:-$(pwd)}"
_CONFIG_DIR="$_CONFIG_ROOT/.aisc"
CONFIG_FILE="$_CONFIG_DIR/config.env"

config_read() {
  local key="$1"
  if [[ ! -f "$CONFIG_FILE" ]]; then
    return 0
  fi
  grep "^${key}=" "$CONFIG_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2- | tr -d '\r'
}

config_write() {
  local key="$1" val="$2"
  mkdir -p "$_CONFIG_DIR"
  local tmp="$CONFIG_FILE.tmp"
  grep -v "^${key}=" "$CONFIG_FILE" 2>/dev/null > "$tmp" || true
  printf '%s=%s\n' "$key" "$val" >> "$tmp"
  mv "$tmp" "$CONFIG_FILE"
}
