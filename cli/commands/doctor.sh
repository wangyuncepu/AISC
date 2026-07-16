#!/usr/bin/env bash
# cli/commands/doctor.sh — AISC 环境诊断工具
# 检查 Docker、Git、文件权限等核心依赖，输出 PASS/FAIL/WARN。
# 用法: ./start.sh doctor  或直接  bash cli/commands/doctor.sh
set -euo pipefail

# ── 颜色定义 ──────────────────────────────────────────────
C_RESET='\033[0m'
C_GREEN='\033[0;32m'
C_RED='\033[0;31m'
C_YELLOW='\033[0;33m'

# 终端不支持颜色时关闭
if [[ -t 1 ]] && command -v tput &>/dev/null && [[ $(tput colors 2>/dev/null || echo 0) -lt 8 ]]; then
  C_RESET='' C_GREEN='' C_RED='' C_YELLOW=''
elif [[ ! -t 1 ]]; then
  C_RESET='' C_GREEN='' C_RED='' C_YELLOW=''
fi

PASS="[${C_GREEN}✓${C_RESET}]"
FAIL="[${C_RED}✗${C_RESET}]"
WARN="[${C_YELLOW}!${C_RESET}]"

# ── 状态计数器 ────────────────────────────────────────────
PASSED=0
WARNINGS=0
FAILURES=0

# ── 辅助函数 ──────────────────────────────────────────────
_passed() { echo -e "  $PASS $1"; (( ++PASSED )); }
_failed() { echo -e "  $FAIL $1"; (( ++FAILURES )); }
_warn()   { echo -e "  $WARN $1"; (( ++WARNINGS )); }

# ── 确定 AISC_ROOT ────────────────────────────────────────
# 优先使用环境变量，否则从脚本自身位置推导（cli/commands/ → 上两级）
if [[ -n "${AISC_ROOT:-}" ]]; then
  AISC_ROOT="$(cd "$AISC_ROOT" && pwd)"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  AISC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi

echo
echo "  AISC Doctor — 环境诊断"
echo "  项目根: $AISC_ROOT"
echo

# ── 1. Docker CLI 已安装并可访问 ───────────────────────────
if command -v docker &>/dev/null; then
  _passed "Docker CLI 已安装 ($(docker --version 2>/dev/null | head -1))"
else
  _failed "Docker CLI 未安装或不在 PATH 中"
fi

# ── 2. Docker 守护进程正在运行 ──────────────────────────────
# docker info 是快速的本地守护进程检查，不涉及网络/registry
if command -v docker &>/dev/null; then
  if docker info &>/dev/null; then
    _passed "Docker 守护进程运行中"
  else
    _failed "Docker 守护进程未运行或无响应"
  fi
else
  _failed "Docker 守护进程 — 跳过（CLI 不可用）"
fi

# ── 3. 当前用户可以运行 Docker 命令 ─────────────────────────
if command -v docker &>/dev/null; then
  if docker ps &>/dev/null; then
    _passed "当前用户可以执行 Docker 命令"
  else
    _warn "当前用户可能无权运行 Docker（可尝试 sudo 或加入 docker 组）"
  fi
else
  _failed "用户 Docker 权限 — 跳过（CLI 不可用）"
fi

# ── 4. Docker Compose 可用 ─────────────────────────────────
# 优先检测 docker compose（插件），再试 docker-compose（v1 独立二进制）
COMPOSE_CMD=""
if docker compose version &>/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE_CMD="docker-compose"
fi

if [[ -n "$COMPOSE_CMD" ]]; then
  _passed "Docker Compose 可用 ($COMPOSE_CMD)"
else
  _warn "Docker Compose 不可用（docker compose 插件 或 docker-compose 均未找到）"
fi

# ── 5. Git 可用 ────────────────────────────────────────────
if command -v git &>/dev/null; then
  _passed "Git 已安装 ($(git --version 2>/dev/null | head -1))"
else
  _warn "Git 未安装或不在 PATH 中"
fi

# ── 6. 工作目录可访问且可写 ─────────────────────────────────
if [[ -d "$AISC_ROOT" ]]; then
  if [[ -w "$AISC_ROOT" ]]; then
    _passed "项目目录可访问且可写"
  else
    _warn "项目目录可访问但不可写"
  fi
else
  _failed "项目目录不可访问: $AISC_ROOT"
fi

# ── 7. AISC 项目根已找到 ───────────────────────────────────
if [[ -f "$AISC_ROOT/image/Dockerfile" ]]; then
  _passed "AISC 项目根已找到 (image/Dockerfile)"
else
  _failed "未找到 image/Dockerfile — 可能不是 AISC 项目根目录"
fi

# ── 8. image/Dockerfile 存在且可读 ─────────────────────────
DOCKERFILE="$AISC_ROOT/image/Dockerfile"
if [[ -f "$DOCKERFILE" ]]; then
  if [[ -r "$DOCKERFILE" ]]; then
    _passed "image/Dockerfile 存在且可读"
  else
    _failed "image/Dockerfile 存在但不可读"
  fi
else
  _failed "image/Dockerfile 不存在"
fi

# ── 9. ai_brief/brief.py Python 语法有效 ────────────────────
BRIEF_PY="$AISC_ROOT/ai_brief/brief.py"
if [[ -f "$BRIEF_PY" ]]; then
  if command -v python3 &>/dev/null; then
    if python3 -m py_compile "$BRIEF_PY" 2>/dev/null; then
      _passed "ai_brief/brief.py Python 语法有效"
    else
      _warn "ai_brief/brief.py Python 语法检查失败"
    fi
    # 清理 __pycache__
    rm -rf "${BRIEF_PY%/*}/__pycache__" 2>/dev/null || true
  else
    _warn "python3 不可用，跳过 ai_brief/brief.py 语法检查"
  fi
else
  _warn "ai_brief/brief.py 不存在，跳过语法检查"
fi

# ── 10. macOS: start.command 可执行 ─────────────────────────
if [[ "$(uname -s)" == "Darwin" ]]; then
  START_CMD="$AISC_ROOT/start.command"
  if [[ -f "$START_CMD" ]]; then
    if [[ -x "$START_CMD" ]]; then
      _passed "start.command 可执行"
    else
      _warn "start.command 不可执行 (运行: chmod +x start.command)"
    fi
  else
    _warn "start.command 不存在"
  fi
fi

# ── 11. start.sh 可执行 ────────────────────────────────────
START_SH="$AISC_ROOT/start.sh"
if [[ -f "$START_SH" ]]; then
  if [[ -x "$START_SH" ]]; then
    _passed "start.sh 可执行"
  else
    _warn "start.sh 不可执行 (运行: chmod +x start.sh)"
  fi
else
  _failed "start.sh 不存在"
fi

# ── 汇总 ───────────────────────────────────────────────────
echo
if (( FAILURES > 0 )); then
  echo -e "  ${C_RED}${PASSED} 通过, ${WARNINGS} 警告, ${FAILURES} 失败${C_RESET}"
else
  echo -e "  ${C_GREEN}${PASSED} 通过, ${WARNINGS} 警告, ${FAILURES} 失败${C_RESET}"
fi
echo

# 有任何失败则退出码为 1
if (( FAILURES > 0 )); then
  exit 1
else
  exit 0
fi
