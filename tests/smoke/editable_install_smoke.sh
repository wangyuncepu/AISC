#!/usr/bin/env bash
# Editable install smoke test — installs aisc as editable from the repo
# into a fully-isolated temporary environment, then runs key commands
# from outside the repo to verify end-to-end functionality.
#
# Design:
#   - When uv is available: sets UV_TOOL_DIR + UV_TOOL_BIN_DIR inside TMPDIR.
#     Uses ``uv tool install --editable`` and calls ``$UV_TOOL_BIN_DIR/aisc``.
#     No global side effects; deleting TMPDIR deletes everything.
#   - When uv is absent: falls back to pip editable install in a temp venv.
#   - Runs commands from a temp directory (outside the repo).
#   - Does NOT require Docker; uses --dry-run / --format json for build.
#   - All side effects confined to TMPDIR; trap cleanup on exit.
#
# Usage:
#   bash tests/smoke/editable_install_smoke.sh
#
# Environment variables:
#   AISC_SMOKE_SKIP_UV=1   Skip uv path, force pip fallback.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO_PATH="$ROOT"

echo "=== AISC Editable Install Smoke Test ==="
echo "  Repo: $REPO_PATH"
echo ""

# ------------------------------------------------------------------
# Determine tool: uv (tool install --editable) or pip (venv + pip install -e)
# ------------------------------------------------------------------

USE_UV=false
if [ "${AISC_SMOKE_SKIP_UV:-0}" = "1" ]; then
    echo "[tool] AISC_SMOKE_SKIP_UV=1 — forcing pip fallback"
elif command -v uv &>/dev/null; then
    UV_VERSION=$(uv --version 2>&1 || echo "unknown")
    echo "[tool] uv found: $UV_VERSION"
    USE_UV=true
else
    echo "[tool] uv not found — using pip + venv fallback"
fi

# ------------------------------------------------------------------
# Temp workspace — ALL side effects confined here
# ------------------------------------------------------------------
TMPDIR=$(mktemp -d -t aisc-editable-smoke-XXXXXX)
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

WORKDIR="$TMPDIR/work"
mkdir -p "$WORKDIR"

# ------------------------------------------------------------------
# Isolated uv directories (only created/used when USE_UV=true)
# ------------------------------------------------------------------
if $USE_UV; then
    UV_TOOL_DIR="$TMPDIR/uv-tools"
    UV_TOOL_BIN_DIR="$TMPDIR/uv-bin"
    mkdir -p "$UV_TOOL_DIR" "$UV_TOOL_BIN_DIR"
    export UV_TOOL_DIR UV_TOOL_BIN_DIR
    echo "[uv] UV_TOOL_DIR=$UV_TOOL_DIR"
    echo "[uv] UV_TOOL_BIN_DIR=$UV_TOOL_BIN_DIR"
fi

# ------------------------------------------------------------------
# Helper: verify a command succeeds and stdout contains a pattern.
# Arguments: label cwd grep_pattern cmd [args...]
# Uses array expansion (no eval) — safe with paths containing spaces.
# ------------------------------------------------------------------
check_cmd() {
    local label="$1"
    local cwd="$2"
    local grep_pattern="$3"
    shift 3

    echo -n "  [$label] "
    if ( cd "$cwd" && "$@" >"$TMPDIR/stdout" 2>"$TMPDIR/stderr" ); then
        if [ -n "$grep_pattern" ] && ! grep -q "$grep_pattern" "$TMPDIR/stdout"; then
            echo "FAIL (output missing '$grep_pattern')"
            echo "    stdout: $(head -3 "$TMPDIR/stdout")"
            return 1
        fi
        echo "PASS"
        return 0
    else
        echo "FAIL (exit=$?)"
        echo "    stderr: $(head -3 "$TMPDIR/stderr")"
        return 1
    fi
}

PASS_COUNT=0
FAIL_COUNT=0

count_pass() { PASS_COUNT=$((PASS_COUNT + 1)); }
count_fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); }

# ------------------------------------------------------------------
# Install
# ------------------------------------------------------------------
if $USE_UV; then
    # --- uv path: tool install --editable into isolated env ---
    echo "[1/4] uv tool install --editable (isolated)"
    uv tool install --editable "$REPO_PATH" 2>&1 | tail -5
    echo "       installed into $UV_TOOL_BIN_DIR"

    AISC_BIN="$UV_TOOL_BIN_DIR/aisc"
    if [ ! -x "$AISC_BIN" ]; then
        echo "FAIL: aisc binary not found at $AISC_BIN"
        ls -la "$UV_TOOL_BIN_DIR/" 2>/dev/null || true
        exit 1
    fi
else
    # --- pip path: create venv, pip install -e ---
    echo "[1/4] pip install -e . (into temp venv)"
    python3 -m venv "$TMPDIR/venv" > /dev/null 2>&1
    "$TMPDIR/venv/bin/python3" -m pip install -e "$REPO_PATH" > /dev/null 2>&1
    echo "       installed"
    AISC_BIN="$TMPDIR/venv/bin/aisc"
fi

echo "  aisc bin: $AISC_BIN"
echo ""

# ------------------------------------------------------------------
# Test 1: aisc version (outside repo)
# ------------------------------------------------------------------
echo "[2/4] Testing aisc version (outside repo)..."
if check_cmd "version text"       "$WORKDIR" "AISC CLI version"   "$AISC_BIN" version;                                    then count_pass; else count_fail; fi
if check_cmd "version json"       "$WORKDIR" '"cli_version"'       "$AISC_BIN" version --format json;                     then count_pass; else count_fail; fi
if check_cmd "version with root"  "$WORKDIR" "AISC CLI version"   "$AISC_BIN" --aisc-root "$REPO_PATH" version;           then count_pass; else count_fail; fi

# ------------------------------------------------------------------
# Test 2: aisc build --dry-run (outside repo; no Docker needed)
# ------------------------------------------------------------------
echo "[3/4] Testing aisc build --dry-run (outside repo, no Docker)..."
if check_cmd "build dry-run"      "$WORKDIR" "dry-run"             "$AISC_BIN" --aisc-root "$REPO_PATH" build --dry-run;  then count_pass; else count_fail; fi

# ------------------------------------------------------------------
# Test 3: aisc provider list --format json (outside repo)
# ------------------------------------------------------------------
echo "[4/4] Testing aisc provider list --format json (outside repo)..."

(
    cd "$WORKDIR"
    "$AISC_BIN" --aisc-root "$REPO_PATH" provider list --format json
) >"$TMPDIR/provider_stdout" 2>"$TMPDIR/provider_stderr"
PROVIDER_EXIT=$?

if [ "$PROVIDER_EXIT" -eq 0 ]; then
    if python3 -c "
import json
data = json.load(open('$TMPDIR/provider_stdout'))
meta = data.get('meta', {})
assert meta.get('command') == 'provider', 'Wrong or missing meta.command'
assert meta.get('exit_code') == 0, 'Non-zero exit_code'
assert 'data' in data, 'Missing data key'
assert 'providers' in data['data'], 'Missing providers key'
providers = data['data']['providers']
assert len(providers) >= 1, 'No providers found'
assert all('id' in p for p in providers), 'Missing id in some providers'
print(f'Provider count: {len(providers)}')
print('JSON structure valid')
"; then
        echo "  [provider list json] PASS (provider count verified)"
        count_pass
    else
        echo "  [provider list json] FAIL (JSON structure invalid)"
        count_fail
    fi
else
    echo "  [provider list json] FAIL (command exit=$PROVIDER_EXIT)"
    echo "    stderr: $(head -3 "$TMPDIR/provider_stderr")"
    count_fail
fi

echo ""
echo "=== Results: $PASS_COUNT passed, $FAIL_COUNT failed ==="

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "SMOKE FAILED"
    exit 1
fi

echo "SMOKE PASSED"
exit 0
