#!/usr/bin/env bash
# Build the AISC CLI as a Tauri sidecar binary (Linux / macOS).
#
# Produces dist/<name>-<target-triple> (Tauri externalBin convention).
# Requires: python3 with PyInstaller (pip install -e '.[dev]' or uv).

set -euo pipefail
cd "$(dirname "$0")/.."

TARGET_TRIPLE="${TARGET_TRIPLE:-}"
if [ -z "$TARGET_TRIPLE" ]; then
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64)  TARGET_TRIPLE="x86_64-unknown-linux-gnu" ;;
    Linux-aarch64) TARGET_TRIPLE="aarch64-unknown-linux-gnu" ;;
    Darwin-arm64)  TARGET_TRIPLE="aarch64-apple-darwin" ;;
    Darwin-x86_64) TARGET_TRIPLE="x86_64-apple-darwin" ;;
    *) echo "unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
  esac
fi

echo "== building aisc sidecar ($TARGET_TRIPLE) =="
python3 -m PyInstaller --noconfirm --clean packaging/aisc.spec

mkdir -p dist
mv dist/aisc "dist/aisc-${TARGET_TRIPLE}"
echo "== artifact: dist/aisc-${TARGET_TRIPLE} =="
"dist/aisc-${TARGET_TRIPLE}" version --format json | head -c 400
echo
