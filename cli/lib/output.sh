#!/usr/bin/env bash
# cli/lib/output.sh — 统一彩色输出
# 用法：source "$(dirname "$0")/output.sh"
#   info "消息"   蓝色
#   ok "消息"     绿色
#   warn "消息"   黄色
#   fail "消息"   红色
# 通过 AISC_COLOR=0 可禁用颜色输出

if [[ "${AISC_COLOR:-1}" == "0" ]]; then
  _C_RESET=""
  _C_BLUE=""
  _C_GREEN=""
  _C_YELLOW=""
  _C_RED=""
else
  _C_RESET='\033[0m'
  _C_BLUE='\033[0;34m'
  _C_GREEN='\033[0;32m'
  _C_YELLOW='\033[0;33m'
  _C_RED='\033[0;31m'
fi

info() { printf "${_C_BLUE}[info]${_C_RESET} %s\n" "$*"; }
ok()   { printf "${_C_GREEN}[ok]${_C_RESET}   %s\n" "$*"; }
warn() { printf "${_C_YELLOW}[warn]${_C_RESET}  %s\n" "$*"; }
fail() { printf "${_C_RED}[fail]${_C_RESET}  %s\n" "$*"; }
