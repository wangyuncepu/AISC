#!/usr/bin/env bash
# Regression test: ensure_writable() — I/O probe, non-recursive repair, no [ -w ]
# Uses fake sudo/mkdir/chown/chmod to validate behaviour without real root.
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

# ---- Shared env between fakes and test ----
export TRACE_FILE="$TRACE"
export FAIL_MARKER="$FAIL_MARKER"

# ---- fake sudo: logs, delegates mkdir→real, chown/chmod→fakes ----
cat > "$FAKE_BIN/sudo" << 'END_FAKE_SUDO'
#!/bin/bash
echo "sudo $*" >> "${TRACE_FILE:?}"
cmd="$1"
shift
case "$cmd" in
  mkdir) exec /bin/mkdir "$@" ;;
  chown) exec chown "$@" ;;
  chmod) exec chmod "$@" ;;
  *)     /usr/bin/sudo "$cmd" "$@" 2>/dev/null || true ;;
esac
END_FAKE_SUDO
chmod +x "$FAKE_BIN/sudo"

# ---- fake chown: logs; exits 0 unless CHOWN_EXIT=1 ----
cat > "$FAKE_BIN/chown" << 'END_FAKE_CHOWN'
#!/bin/bash
echo "chown $*" >> "${TRACE_FILE:?}"
if [ "${CHOWN_EXIT:-0}" = "1" ]; then
  exit 1
fi
exit 0
END_FAKE_CHOWN
chmod +x "$FAKE_BIN/chown"

# ---- fake chmod: logs; exits 0 when CHMOD_NOOP=1, else delegates to real /bin/chmod ----
cat > "$FAKE_BIN/chmod" << 'END_FAKE_CHMOD'
#!/bin/bash
echo "chmod $*" >> "${TRACE_FILE:?}"
if [ "${CHMOD_NOOP:-0}" = "1" ]; then
  exit 0
fi
exec /bin/chmod "$@"
END_FAKE_CHMOD
chmod +x "$FAKE_BIN/chmod"

# ---- fake mkdir: logs; can be told to fail via marker file ----
cat > "$FAKE_BIN/mkdir" << 'END_FAKE_MKDIR'
#!/bin/bash
echo "mkdir $*" >> "${TRACE_FILE:?}"
if [ -f "${FAIL_MARKER:?}" ]; then
  exit 1
fi
exec /bin/mkdir "$@"
END_FAKE_MKDIR
chmod +x "$FAKE_BIN/mkdir"

# ---- fake rm: logs; fails on probe-pattern files when RM_FAIL_ON_PROBE=1,
#      else delegates to real /bin/rm (safe for test infrastructure) ----
cat > "$FAKE_BIN/rm" << 'END_FAKE_RM'
#!/bin/bash
echo "rm $*" >> "${TRACE_FILE:?}"
if [ "${RM_FAIL_ON_PROBE:-0}" = "1" ]; then
  for arg in "$@"; do
    case "$(basename -- "$arg" 2>/dev/null)" in
      .aisc_wr_probe_*) exit 1 ;;
    esac
  done
fi
exec /bin/rm "$@"
END_FAKE_RM
chmod +x "$FAKE_BIN/rm"

export PATH="$FAKE_BIN:$PATH"
export TEST_ROOT="$TEST_ROOT"

# Capture runtime uid/gid for assertions (ensure_writable now uses $(id -u):$(id -g))
TEST_UID="$(id -u)"
TEST_GID="$(id -g)"
EXPECT_CHOWN="${TEST_UID}:${TEST_GID}"

# Source library under test
LIB="$(cd "$(dirname "$0")/../.." && pwd)/container/lib/path-resolve.sh"
if [ ! -f "$LIB" ]; then
  echo "FATAL: cannot find $LIB" >&2
  exit 2
fi
source "$LIB"

echo "=== Test: ensure_writable regression (I/O probe) ==="
echo "Library: $LIB"
echo ""

# =========================================================================
# Test 1: Empty path rejected
# =========================================================================
echo "[Test 1] Empty path validation"
if ensure_writable "" 2>/dev/null; then
  fail "empty path should return nonzero"
else
  pass "empty path rejected"
fi

# =========================================================================
# Test 2: Path with spaces — quoted correctly through the pipeline
# =========================================================================
echo "[Test 2] Path with spaces"
rm -f "$TRACE"
SPACE_DIR="$TEST_ROOT/my test dir"
if ensure_writable "$SPACE_DIR"; then
  pass "path with spaces created successfully"
  if grep -q "mkdir.*my test dir" "$TRACE"; then
    pass "mkdir received path with spaces intact (quoted)"
  else
    fail "mkdir trace missing space path (quoting issue)"
  fi
else
  fail "path with spaces: ensure_writable failed"
fi

# =========================================================================
# Test 3: Already writable → no sudo repair (chown/chmod) invoked
# =========================================================================
echo "[Test 3] Already writable → no repair calls"
NORMAL_DIR="$TEST_ROOT/normal-skip-repair"
mkdir -p "$NORMAL_DIR"
rm -f "$TRACE"
unset CHOWN_EXIT CHMOD_NOOP
if ensure_writable "$NORMAL_DIR"; then
  if grep -qE '(chown|chmod)' "$TRACE"; then
    fail "chown/chmod invoked on already-writable dir (unnecessary repair)"
  else
    pass "no chown/chmod called when dir is already writable"
  fi
else
  fail "ensure_writable failed on writable dir"
fi
# Also verify no probe residue
if ls "$NORMAL_DIR"/.aisc_wr_probe_* >/dev/null 2>&1; then
  fail "probe files left behind in writable dir"
else
  pass "no residual probe files in writable dir"
fi

# =========================================================================
# Test 4: Permission error (0555) → non-recursive chown+chmod invoked,
#         probe fails, repair fixes, re-probe succeeds
# =========================================================================
echo "[Test 4] 0555 dir → non-recursive repair → success"
PERM_DIR="$TEST_ROOT/perm-dir"
mkdir -p "$PERM_DIR"
chmod 0555 "$PERM_DIR"                  # no write for owner
rm -f "$TRACE"
unset CHOWN_EXIT CHMOD_NOOP              # chown succeeds (fake), chmod delegates to real
if ensure_writable "$PERM_DIR" 2>/dev/null; then
  pass "ensure_writable succeeded after repair"
else
  fail "ensure_writable should have succeeded after chmod repair"
fi
# Trace assertions
if grep -q "sudo chown ${EXPECT_CHOWN}" "$TRACE"; then
  pass "sudo chown ${EXPECT_CHOWN} invoked"
else
  fail "sudo chown not found in trace"
fi
if grep -q "sudo chmod u+rwx" "$TRACE"; then
  pass "sudo chmod u+rwx invoked"
else
  fail "sudo chmod u+rwx not found in trace"
fi
# No residue
if ls "$PERM_DIR"/.aisc_wr_probe_* >/dev/null 2>&1; then
  fail "probe files left behind after repair"
else
  pass "no residual probe files after repair"
fi

# =========================================================================
# Test 5: chown succeeds, but fs still read-only (chmod no-op) → final failure
# =========================================================================
echo "[Test 5] chown ok + chmod no-op → still unwritable → failure"
CHOWN_FAIL_DIR="$TEST_ROOT/chown-ok-chmod-noop"
mkdir -p "$CHOWN_FAIL_DIR"
chmod 0555 "$CHOWN_FAIL_DIR"
rm -f "$TRACE"
export CHMOD_NOOP=1                     # chmod does nothing
unset CHOWN_EXIT                        # chown succeeds
if ensure_writable "$CHOWN_FAIL_DIR" 2>/tmp/ensure_stderr_5; then
  fail "should have failed when chmod cannot fix permissions"
else
  pass "ensure_writable correctly returned nonzero"
fi
# Must show diagnostic info
STDERR5="$(cat /tmp/ensure_stderr_5)"
if echo "$STDERR5" | grep -qi "not writable after repair\|read-only\|CIFS\|NFS\|rootless\|user namespace"; then
  pass "diagnostic message present for unwritable dir"
else
  fail "diagnostic message missing or insufficient: $STDERR5"
fi
unset CHMOD_NOOP

# =========================================================================
# Test 6: chown fails, chmod succeeds, re-probe succeeds → overall success
# =========================================================================
echo "[Test 6] chown fails + chmod fixes → success"
CHOWN_FAIL_DIR2="$TEST_ROOT/chown-fail-chmod-ok"
mkdir -p "$CHOWN_FAIL_DIR2"
chmod 0555 "$CHOWN_FAIL_DIR2"
rm -f "$TRACE"
export CHOWN_EXIT=1                      # chown fails
unset CHMOD_NOOP                         # chmod delegates to real /bin/chmod → fixes dir
if ensure_writable "$CHOWN_FAIL_DIR2" 2>/dev/null; then
  pass "ensure_writable succeeded despite chown failure (chmod fixed it)"
else
  fail "ensure_writable failed even though chmod should have fixed perms"
fi
if grep -q "sudo chown ${EXPECT_CHOWN}" "$TRACE"; then
  pass "chown was attempted (even though it failed)"
else
  fail "chown attempt not in trace"
fi
if grep -q "sudo chmod u+rwx" "$TRACE"; then
  pass "chmod was invoked"
else
  fail "chmod not found in trace"
fi
unset CHOWN_EXIT

# =========================================================================
# Test 7: No -R flag anywhere in chown/chmod invocations (non-recursive)
# =========================================================================
echo "[Test 7] No recursive (-R) chown or chmod"
# Accumulate all trace files from earlier tests, plus run a dedicated check
ALL_TRACE="$TEST_ROOT/all-trace"
cat "$TRACE" > "$ALL_TRACE" 2>/dev/null || true

# Run a fresh call to get a clean trace too
FRESH_DIR="$TEST_ROOT/fresh-norec"
mkdir -p "$FRESH_DIR"
chmod 0555 "$FRESH_DIR"
rm -f "$TRACE"
unset CHOWN_EXIT CHMOD_NOOP
ensure_writable "$FRESH_DIR" 2>/dev/null || true
cat "$TRACE" >> "$ALL_TRACE" 2>/dev/null || true

if grep -E '(chown|chmod).*-R' "$ALL_TRACE"; then
  fail "found -R flag in chown/chmod invocation (recursive not allowed)"
else
  pass "no -R flag in any chown/chmod invocation"
fi

# =========================================================================
# Test 8: sudo mkdir fallback when plain mkdir fails
# =========================================================================
echo "[Test 8] Plain mkdir failure → sudo mkdir fallback"
rm -f "$TRACE"
touch "$FAIL_MARKER"
FALLBACK_DIR="$TEST_ROOT/sudo-mkdir-fallback"
if ensure_writable "$FALLBACK_DIR" 2>/dev/null; then
  pass "sudo mkdir fallback succeeded"
else
  fail "sudo mkdir fallback should have succeeded"
fi
rm -f "$FAIL_MARKER"
if grep -q "sudo mkdir.*sudo-mkdir-fallback" "$TRACE"; then
  pass "sudo mkdir fallback trace confirmed"
else
  fail "sudo mkdir fallback not found in trace"
fi

# =========================================================================
# Test 9: Probe delete fails → ensure_writable must fail
#         Simulates a filesystem that allows create/write/rename but not delete.
# =========================================================================
echo "[Test 9] Delete failure in probe → ensure_writable fails"
DEL_FAIL_DIR="$TEST_ROOT/del-fail-dir"
mkdir -p "$DEL_FAIL_DIR"
rm -f "$TRACE"
export RM_FAIL_ON_PROBE=1
unset CHOWN_EXIT CHMOD_NOOP
if ensure_writable "$DEL_FAIL_DIR" 2>/dev/null; then
  fail "should have failed when probe delete fails"
else
  pass "ensure_writable correctly failed on delete failure"
fi
unset RM_FAIL_ON_PROBE

# =========================================================================
# Summary
# =========================================================================
echo ""
echo "=== Results: $PASSED passed, $FAILED failed ==="
if [ "$FAILED" -gt 0 ]; then
  exit 1
fi
exit 0
