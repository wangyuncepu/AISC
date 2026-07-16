#!/usr/bin/env bash
# ai_brief/run.sh - 薄包装，绕 DrvFs 无 exec 位（宿主 Windows 挂载点 bin 脚本无 x 位）。
# 用法：bash run.sh [--date YYYY-MM-DD] [--days N] [--top N] [--ai] [--save] [--no-cache] [--source tldr|rundown|both] [--strict]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/brief.py" "$@"
