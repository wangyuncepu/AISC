#!/usr/bin/env bash
# Regression test: ensure_writable() — sudo fallback, path quoting, call ordering
# Uses fake sudo & mkdir to validate behaviour without real root access.
set -euo pipefail

TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT

PASSED=0
FAILED=0
pass() { echo "  PASS: $1"; PASSED=$((PASSED+1)); }
fail() { echo "  FAIL: $1"; FAILED=$((FAILED+1)); }

FAKE_BIN="$TEST_ROOT/bin"
mkdir -p "$FAKE_BIN"
TRACE="$TEST_ROOT/trace"
FAIL_MARKER="$TEST_ROOT/fail-mkdir"

# ---- fake sudo: logs invocations, delegates mkdir to real /bin/mkdir,
#      chown to fake chown (PATH), other commands to real sudo ----
cat > "$FAKE_BIN/sudo" << 'END_FAKE_SUDO'
#!/bin/bash
echo "sudo $*" >> "${TRACE_FILE:?}"
cmd="$1"
shift
case "$cmd" in
  mkdir) exec /bin/mkdir "$@" ;;
  chown) exec chown "$@" ;;
  *)     /usr/bin/sudo "$cmd" "$@" 2>/dev/null || true ;;
esac
END_FAKE_SUDO
chmod +x "$FAKE_BIN/sudo"

# ---- fake chown: logs invocations, always succeeds (no real AISC user on test host) ----
cat > "$FAKE_BIN/chown" << 'END_FAKE_CHOWN'
#!/bin/bash
echo "chown $*" >> "${TRACE_FILE:?}"
exit 0
END_FAKE_CHOWN
chmod +x "$FAKE_BIN/chown"

# ---- fake mkdir: logs invocations, can be told to fail via marker file ----
cat > "$FAKE_BIN/mkdir" << 'END_FAKE_MKDIR'
#!/bin/bash
echo "mkdir $*" >> "${TRACE_FILE:?}"
if [ -f "${FAIL_MARKER:?}" ]; then
  exit 1
fi
exec /bin/mkdir "$@"
END_FAKE_MKDIR
chmod +x "$FAKE_BIN/mkdir"

export PATH="$FAKE_BIN:$PATH"
export TRACE_FILE="$TRACE"
export FAIL_MARKER="$FAIL_MARKER"
export TEST_ROOT="$TEST_ROOT"

# Source the library under test
LIB="$(cd "$(dirname "$0")/../.." && pwd)/container/lib/path-resolve.sh"
if [ ! -f "$LIB" ]; then
  echo "FATAL: cannot find $LIB" >&2
  exit 2
fi
source "$LIB"

echo "=== Test: ensure_writable regression ==="
echo "Library: $LIB"
echo ""

# -----------------------------------------------------------------------
# Test 1: empty path must be rejected
# -----------------------------------------------------------------------
echo "[Test 1] Empty path validation"
if ensure_writable "" 2>/dev/null; then
  fail "empty path should return nonzero"
else
  pass "empty path rejected"
fi

# -----------------------------------------------------------------------
# Test 2: normal creation — directory is created and writable
# -----------------------------------------------------------------------
echo "[Test 2] Normal directory creation"
rm -f "$TRACE"
NORM_DIR="$TEST_ROOT/normal-dir"
if ensure_writable "$NORM_DIR"; then
  if [ -d "$NORM_DIR" ] && [ -w "$NORM_DIR" ]; then
    pass "directory created and writable"
  else
    fail "directory not created/writable after ensure_writable"
  fi
else
  fail "ensure_writable returned nonzero for normal case"
fi

# -----------------------------------------------------------------------
# Test 3: path with spaces — quoted correctly through the pipeline
# -----------------------------------------------------------------------
echo "[Test 3] Path with spaces"
rm -f "$TRACE"
SPACE_DIR="$TEST_ROOT/my test dir"
if ensure_writable "$SPACE_DIR"; then
  pass "path with spaces created successfully"
  # Verify trace shows the path with spaces was passed intact (plain or sudo mkdir)
  if grep -q "mkdir.*my test dir" "$TRACE"; then
    pass "mkdir received path with spaces intact (quoted)"
  else
    fail "mkdir trace missing space path (quoting issue)"
  fi
else
  fail "path with spaces: ensure_writable failed"
fi

# -----------------------------------------------------------------------
# Test 4: sudo mkdir fallback when plain mkdir fails
# -----------------------------------------------------------------------
echo "[Test 4] Plain mkdir failure → sudo mkdir fallback"
rm -f "$TRACE"
touch "$FAIL_MARKER"          # force fake mkdir to exit 1
FAIL_DIR="$TEST_ROOT/fallback-dir"
if ensure_writable "$FAIL_DIR" 2>/dev/null; then
  pass "fallback to sudo mkdir succeeded"
else
  fail "fallback to sudo mkdir should have succeeded"
fi
rm -f "$FAIL_MARKER"
# Trace must show a sudo mkdir call for this directory
if grep -q "sudo mkdir.*fallback-dir" "$TRACE"; then
  pass "sudo mkdir fallback trace confirmed"
else
  fail "sudo mkdir fallback not found in trace"
fi

# -----------------------------------------------------------------------
# Test 5: call ordering — mkdir invoked before chown
# -----------------------------------------------------------------------
echo "[Test 5] Call ordering: mkdir before chown"
rm -f "$TRACE"
ORDER_DIR="$TEST_ROOT/order-dir"
ensure_writable "$ORDER_DIR"
# Look for any mkdir trace (plain or sudo) and chown trace
MKDIR_LINE=$(grep -n "mkdir.*order-dir" "$TRACE" | head -1 | cut -d: -f1 || echo "0")
CHOWN_LINE=$(grep -n "chown.*order-dir" "$TRACE" | head -1 | cut -d: -f1 || echo "0")
if [ "$MKDIR_LINE" -gt 0 ] && [ "$CHOWN_LINE" -gt 0 ] 2>/dev/null; then
  if [ "$MKDIR_LINE" -lt "$CHOWN_LINE" ] 2>/dev/null; then
    pass "mkdir before chown (lines $MKDIR_LINE < $CHOWN_LINE)"
  else
    fail "ordering: mkdir line=$MKDIR_LINE, chown line=$CHOWN_LINE (expected mkdir first)"
  fi
else
  fail "could not locate mkdir/chown trace lines (mkdir=$MKDIR_LINE, chown=$CHOWN_LINE)"
fi

# -----------------------------------------------------------------------
# Test 6: sudo chown uses AISC:AISC
# -----------------------------------------------------------------------
echo "[Test 6] sudo chown targets AISC:AISC"
if grep -q "sudo chown -R AISC:AISC" "$TRACE"; then
  pass "sudo chown -R AISC:AISC invoked"
else
  fail "sudo chown -R AISC:AISC not found in trace"
fi

# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------
echo ""
echo "=== Results: $PASSED passed, $FAILED failed ==="
if [ "$FAILED" -gt 0 ]; then
  exit 1
fi
exit 0
