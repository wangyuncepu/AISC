#!/usr/bin/env bash
set -euo pipefail

# 保存原始工作目录（在 cd 之前，用作默认 workspace）
ORIGINAL_PWD="$(pwd)"

cd "$(dirname "$0")"
export ORIGINAL_PWD
exec ./start.sh "$@"
