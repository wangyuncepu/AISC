#!/usr/bin/env bash
# Packaging smoke test — builds wheel from a temp copy, installs in a
# temp venv, verifies both console entry point and python -m aisc work
# without PYTHONPATH.  Does NOT pollute the repository.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
echo "=== AISC Packaging Smoke Test ==="
echo ""

TMPDIR=$(mktemp -d -t aisc-packaging-XXXXXX)
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

# ------------------------------------------------------------------
# 1. Copy source tree to temp directory (exclude .git, build/, dist/,
#    .venv/, __pycache__, *.egg-info)
# ------------------------------------------------------------------
echo "[1/6] Copying source tree..."
SRCCOPY="$TMPDIR/src"
mkdir -p "$SRCCOPY"
# Copy everything except VCS/build artifacts
( cd "$ROOT" && find . -maxdepth 1 -mindepth 1 \
    ! -name '.git' \
    ! -name 'build' \
    ! -name 'dist' \
    ! -name '.venv' \
    ! -name '__pycache__' \
    ! -name '*.egg-info' \
    ! -name '*.pyc' \
    -print0 | xargs -0 -I{} cp -a {} "$SRCCOPY/" )
echo "  Copied to $SRCCOPY"

# ------------------------------------------------------------------
# 2. Build wheel from temp copy
# ------------------------------------------------------------------
echo "[2/6] Building wheel..."
python3 -m pip wheel --no-deps -w "$TMPDIR/wheelhouse" "$SRCCOPY" > /dev/null 2>&1
WHEEL=$(ls "$TMPDIR/wheelhouse"/aisc-*.whl | head -1)
echo "  Wheel: $(basename "$WHEEL")"

# ------------------------------------------------------------------
# 3. Check PEP440 metadata version (exact match)
# ------------------------------------------------------------------
echo "[3/6] Checking distribution metadata version..."
python3 -m venv "$TMPDIR/metavenv" > /dev/null 2>&1
"$TMPDIR/metavenv/bin/python3" -m pip install --no-deps "$WHEEL" > /dev/null 2>&1
DIST_VERSION=$("$TMPDIR/metavenv/bin/python3" -c \
    "import importlib.metadata; print(importlib.metadata.version('aisc'))")
echo "  Distribution version: $DIST_VERSION"
# Read expected version from VERSION file and convert to PEP440
EXPECTED_VERSION=$(cat "$SRCCOPY/VERSION" | tr -d '\n' | sed 's/-dev/.dev0/')
if [ "$DIST_VERSION" = "$EXPECTED_VERSION" ]; then
    echo "  PASS: exact PEP440 match ($EXPECTED_VERSION)"
else
    echo "  FAIL: expected $EXPECTED_VERSION, got $DIST_VERSION"
    exit 1
fi

# ------------------------------------------------------------------
# 4. Clean venv install
# ------------------------------------------------------------------
echo "[4/6] Installing wheel into fresh venv..."
python3 -m venv "$TMPDIR/testvenv" > /dev/null 2>&1
"$TMPDIR/testvenv/bin/python3" -m pip install --no-deps "$WHEEL" > /dev/null 2>&1
echo "  Installed."

# ------------------------------------------------------------------
# 5. Test console script entry point
# ------------------------------------------------------------------
echo "[5/6] Testing 'aisc' console script..."
AISC_BIN="$TMPDIR/testvenv/bin/aisc"
if [ ! -x "$AISC_BIN" ]; then
    echo "  FAIL: aisc script not found at $AISC_BIN"
    exit 1
fi
# text mode
if "$AISC_BIN" version 2>&1 | grep -q "AISC CLI version"; then
    echo "  PASS: aisc version (text)"
else
    echo "  FAIL: aisc version text output unexpected"
    exit 1
fi
# JSON mode
if "$AISC_BIN" version --format json 2>/dev/null | python3 -m json.tool > /dev/null 2>&1; then
    echo "  PASS: aisc version --format json"
else
    echo "  FAIL: aisc version --format json not valid JSON"
    exit 1
fi

# ------------------------------------------------------------------
# 6. Test python -m aisc
# ------------------------------------------------------------------
echo "[6/6] Testing 'python -m aisc'..."
if "$TMPDIR/testvenv/bin/python3" -m aisc version --format json 2>/dev/null \
    | python3 -m json.tool > /dev/null 2>&1; then
    echo "  PASS: python -m aisc version --format json"
else
    echo "  FAIL: python -m aisc not valid JSON"
    exit 1
fi
if "$TMPDIR/testvenv/bin/python3" -m aisc --format=json version 2>/dev/null \
    | python3 -m json.tool > /dev/null 2>&1; then
    echo "  PASS: python -m aisc --format=json version"
else
    echo "  FAIL: python -m aisc --format=json not valid JSON"
    exit 1
fi

echo ""
echo "=== PASSED ==="
echo "All packaging smoke tests passed."
exit 0
