#!/usr/bin/env bash
# Install/uninstall smoke test — validates install.sh and uninstall.sh
# on a fake archive, verifying layout, symlink, repeated install,
# and that uninstall does not delete external user configuration.
#
# Requires: bash, tar
# Does NOT require: Docker, Python, a real aisc binary

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SCRIPT="$ROOT/packaging/install.sh"
UNINSTALL_SCRIPT="$ROOT/packaging/uninstall.sh"

if [ ! -f "$INSTALL_SCRIPT" ]; then
    echo "FATAL: install.sh not found at $INSTALL_SCRIPT" >&2
    exit 2
fi
if [ ! -f "$UNINSTALL_SCRIPT" ]; then
    echo "FATAL: uninstall.sh not found at $UNINSTALL_SCRIPT" >&2
    exit 2
fi

PASSED=0
FAILED=0
pass() { echo "  PASS: $1"; PASSED=$((PASSED+1)); }
fail() { echo "  FAIL: $1"; FAILED=$((FAILED+1)); }

# Create a temp workspace for this test
TEST_WORKSPACE=$(mktemp -d -t aisc-install-smoke-XXXXXX)
cleanup() { rm -rf "$TEST_WORKSPACE"; }
trap cleanup EXIT

export HOME="$TEST_WORKSPACE/home"

# Override XDG paths so we don't touch the real user's system
export XDG_DATA_HOME="$TEST_WORKSPACE/data"
export XDG_BIN_HOME="$TEST_WORKSPACE/bin"
export PATH="${XDG_BIN_HOME}:${PATH}"

mkdir -p "$HOME"
mkdir -p "$XDG_DATA_HOME"
mkdir -p "$XDG_BIN_HOME"

echo "=== AISC Install Smoke Test ==="
echo "Install script: $INSTALL_SCRIPT"
echo "Uninstall script: $UNINSTALL_SCRIPT"
echo "Workspace: $TEST_WORKSPACE"
echo ""

# =========================================================================
# Setup: Create a fake archive directory
# =========================================================================

echo "[Setup] Creating fake AISC source tree..."

FAKE_SOURCE="$TEST_WORKSPACE/source"
ARCHIVE_DIR="$FAKE_SOURCE/AISC-9.9.9-test-linux-x86_64"
mkdir -p "$ARCHIVE_DIR"

# Create a fake aisc executable (it just echoes version and exits with code 0)
cat > "$ARCHIVE_DIR/aisc" << 'FAKE_EXE'
#!/usr/bin/env bash
# Fake aisc binary for testing install/uninstall
if [ "${1:-}" = "version" ]; then
    echo "AISC CLI version 9.9.9-test"
elif [ "${1:-}" = "doctor" ]; then
    echo "AISC doctor: OK"
elif [ "${1:-}" = "--help" ]; then
    echo "Usage: aisc [command]"
else
    echo "aisc fake binary"
fi
exit 0
FAKE_EXE
chmod 755 "$ARCHIVE_DIR/aisc"

# Create a minimal aisc-bundle with required files
BUNDLE_DIR="$ARCHIVE_DIR/aisc-bundle"
mkdir -p "$BUNDLE_DIR"
echo "9.9.9-test" > "$BUNDLE_DIR/VERSION"

# container/Dockerfile
mkdir -p "$BUNDLE_DIR/container"
cat > "$BUNDLE_DIR/container/Dockerfile" << 'DOCKERFILE'
FROM node:20-slim
RUN echo hello
DOCKERFILE

# config/versions.env
mkdir -p "$BUNDLE_DIR/config"
cat > "$BUNDLE_DIR/config/versions.env" << 'VERSIONS_ENV'
AISC_VERSION=9.9.9-test
VERSIONS_ENV

# Other bundle files
echo "# README" > "$BUNDLE_DIR/README.md"
echo "MIT" > "$BUNDLE_DIR/LICENSE"
echo "node_modules/" > "$BUNDLE_DIR/.dockerignore"

echo "  Fake source created: $ARCHIVE_DIR"
echo ""

# =========================================================================
# Test 1: install from directory source (direct layout)
# =========================================================================

echo "[Test 1] Install from directory source (direct layout)"

# Create a direct-layout source (aisc + aisc-bundle/ in one dir)
DIRECT_SRC="$TEST_WORKSPACE/direct-src"
mkdir -p "$DIRECT_SRC"
cp "$ARCHIVE_DIR/aisc" "$DIRECT_SRC/aisc"
chmod 755 "$DIRECT_SRC/aisc"
cp -r "$ARCHIVE_DIR/aisc-bundle" "$DIRECT_SRC/aisc-bundle"

INSTALL_DIR="$XDG_DATA_HOME/aisc"
BIN_LINK="$XDG_BIN_HOME/aisc"

# Clean any previous
rm -rf "$INSTALL_DIR" "$BIN_LINK" 2>/dev/null || true

if bash "$INSTALL_SCRIPT" "$DIRECT_SRC" > "$TEST_WORKSPACE/install1.log" 2>&1; then
    pass "install script exited 0"
else
    fail "install script failed — see install1.log"
    cat "$TEST_WORKSPACE/install1.log"
fi

# Check install directory exists
if [ -d "$INSTALL_DIR" ]; then
    pass "install directory created: $INSTALL_DIR"
else
    fail "install directory not found: $INSTALL_DIR"
fi

# Check executable exists
if [ -x "$INSTALL_DIR/aisc" ]; then
    pass "aisc executable exists and is executable"
else
    fail "aisc executable not found or not executable"
fi

# Check bundle exists with required files
if [ -d "$INSTALL_DIR/aisc-bundle" ]; then
    pass "aisc-bundle/ directory exists"
else
    fail "aisc-bundle/ directory not found"
fi

if [ -f "$INSTALL_DIR/aisc-bundle/VERSION" ]; then
    pass "bundle/VERSION exists"
else
    fail "bundle/VERSION not found"
fi

if [ -f "$INSTALL_DIR/aisc-bundle/container/Dockerfile" ]; then
    pass "bundle/container/Dockerfile exists"
else
    fail "bundle/container/Dockerfile not found"
fi

if [ -f "$INSTALL_DIR/aisc-bundle/config/versions.env" ]; then
    pass "bundle/config/versions.env exists"
else
    fail "bundle/config/versions.env not found"
fi

# Check symlink
if [ -L "$BIN_LINK" ]; then
    pass "symlink exists: $BIN_LINK"
    TARGET=$(readlink "$BIN_LINK" 2>/dev/null || true)
    echo "    symlink target: $TARGET"
else
    fail "symlink not found: $BIN_LINK"
fi

# Check symlink resolves to executable
if [ -x "$BIN_LINK" ]; then
    pass "symlink resolves to executable"
else
    fail "symlink does not resolve to executable"
fi

# Check the fake binary works through the symlink
if "$BIN_LINK" version 2>/dev/null | grep -q "9.9.9-test"; then
    pass "aisc via symlink outputs expected version"
else
    fail "aisc via symlink does not output expected version"
fi

echo ""

# =========================================================================
# Test 2: Repeated install (overwrite)
# =========================================================================

echo "[Test 2] Repeated install (overwrite)"

# Create a marker in the old install
OLD_MARKER="installed-$(date +%s)"
echo "$OLD_MARKER" > "$INSTALL_DIR/.smoke-marker"

# Re-install from the same source
if bash "$INSTALL_SCRIPT" "$DIRECT_SRC" > "$TEST_WORKSPACE/install2.log" 2>&1; then
    pass "repeated install script exited 0"
else
    fail "repeated install script failed — see install2.log"
    cat "$TEST_WORKSPACE/install2.log"
fi

# Old marker should be gone (clean replacement)
if [ ! -f "$INSTALL_DIR/.smoke-marker" ]; then
    pass "old install was cleanly replaced (marker gone)"
else
    fail "old marker file still present — install may not have replaced"
fi

# Installation should still be valid
if [ -x "$INSTALL_DIR/aisc" ] && [ -d "$INSTALL_DIR/aisc-bundle" ]; then
    pass "repeated install: layout still valid"
else
    fail "repeated install: layout broken"
fi

echo ""

# =========================================================================
# Test 3: Install from tar.gz archive
# =========================================================================

echo "[Test 3] Install from .tar.gz archive"

# Create a tar.gz from the fake source
TAR_FILE="$TEST_WORKSPACE/AISC-9.9.9-test-linux-x86_64.tar.gz"
( cd "$FAKE_SOURCE" && tar -czf "$TAR_FILE" "AISC-9.9.9-test-linux-x86_64" )

# Clean previous install
rm -rf "$INSTALL_DIR" "$BIN_LINK" 2>/dev/null || true

if bash "$INSTALL_SCRIPT" "$TAR_FILE" > "$TEST_WORKSPACE/install3.log" 2>&1; then
    pass "install from tar.gz script exited 0"
else
    fail "install from tar.gz failed — see install3.log"
    cat "$TEST_WORKSPACE/install3.log"
fi

if [ -d "$INSTALL_DIR" ] && [ -x "$INSTALL_DIR/aisc" ] && [ -d "$INSTALL_DIR/aisc-bundle" ]; then
    pass "install from tar.gz: layout valid"
else
    fail "install from tar.gz: layout broken"
fi

if [ -L "$BIN_LINK" ] && [ -x "$BIN_LINK" ]; then
    pass "install from tar.gz: symlink valid"
else
    fail "install from tar.gz: symlink broken"
fi

echo ""

# =========================================================================
# Test 4: Install with spaces in path
# =========================================================================

echo "[Test 4] Install with spaces in path"

SPACE_SRC="$TEST_WORKSPACE/my test dir/src"
mkdir -p "$SPACE_SRC"
cp "$ARCHIVE_DIR/aisc" "$SPACE_SRC/aisc"
chmod 755 "$SPACE_SRC/aisc"
cp -r "$ARCHIVE_DIR/aisc-bundle" "$SPACE_SRC/aisc-bundle"

rm -rf "$INSTALL_DIR" "$BIN_LINK" 2>/dev/null || true

if bash "$INSTALL_SCRIPT" "$SPACE_SRC" > "$TEST_WORKSPACE/install4.log" 2>&1; then
    pass "install with spaces in path: script exited 0"
else
    fail "install with spaces in path: script failed — see install4.log"
    cat "$TEST_WORKSPACE/install4.log"
fi

if [ -d "$INSTALL_DIR" ] && [ -x "$INSTALL_DIR/aisc" ] && [ -d "$INSTALL_DIR/aisc-bundle" ]; then
    pass "install with spaces in path: layout valid"
else
    fail "install with spaces in path: layout broken"
fi

echo ""

# =========================================================================
# Test 5: Uninstall does not delete external user config
# =========================================================================

echo "[Test 5] Uninstall preserves external user config"

# Create mock user config directories
MOCK_CONFIG="$HOME/.aisc"
mkdir -p "$MOCK_CONFIG"
echo "important-config" > "$MOCK_CONFIG/config.yaml"

MOCK_WORKSPACE="$HOME/workspace"
mkdir -p "$MOCK_WORKSPACE"
echo "project-data" > "$MOCK_WORKSPACE/project.txt"

MOCK_CC="$HOME/.cc-config"
mkdir -p "$MOCK_CC"
echo "cc-data" > "$MOCK_CC/settings.json"

# Ensure install exists
if [ ! -d "$INSTALL_DIR" ]; then
    bash "$INSTALL_SCRIPT" "$DIRECT_SRC" > /dev/null 2>&1 || true
fi

if bash "$UNINSTALL_SCRIPT" > "$TEST_WORKSPACE/uninstall.log" 2>&1; then
    pass "uninstall script exited 0"
else
    fail "uninstall script failed — see uninstall.log"
    cat "$TEST_WORKSPACE/uninstall.log"
fi

# Install directory should be gone
if [ ! -d "$INSTALL_DIR" ] && [ ! -L "$INSTALL_DIR" ]; then
    pass "install directory removed"
else
    fail "install directory still exists"
fi

# Symlink should be gone
if [ ! -L "$BIN_LINK" ] && [ ! -f "$BIN_LINK" ]; then
    pass "symlink removed"
else
    fail "symlink still exists"
fi

# User config should be preserved
if [ -f "$MOCK_CONFIG/config.yaml" ]; then
    pass "user config (~/.aisc) preserved"
else
    fail "user config (~/.aisc) was deleted!"
fi

if [ -f "$MOCK_WORKSPACE/project.txt" ]; then
    pass "user workspace preserved"
else
    fail "user workspace was deleted!"
fi

if [ -f "$MOCK_CC/settings.json" ]; then
    pass "user .cc-config preserved"
else
    fail "user .cc-config was deleted!"
fi

echo ""

# =========================================================================
# Test 6: Uninstall when nothing is installed (no-op)
# =========================================================================

echo "[Test 6] Uninstall when nothing is installed"

if bash "$UNINSTALL_SCRIPT" > "$TEST_WORKSPACE/uninstall2.log" 2>&1; then
    pass "uninstall when nothing installed: script exited 0"
else
    fail "uninstall when nothing installed: script failed — see uninstall2.log"
    cat "$TEST_WORKSPACE/uninstall2.log"
fi

echo ""

# =========================================================================
# Test 7: install.sh validates SOURCE parameter
# =========================================================================

echo "[Test 7] install.sh validates SOURCE parameter"

if ! bash "$INSTALL_SCRIPT" "" > /dev/null 2>&1; then
    pass "empty SOURCE rejected"
else
    fail "empty SOURCE should be rejected"
fi

if ! bash "$INSTALL_SCRIPT" "/nonexistent/path/12345" > /dev/null 2>&1; then
    pass "nonexistent SOURCE rejected"
else
    fail "nonexistent SOURCE should be rejected"
fi

echo ""

# =========================================================================
# Test 8: No leftover aisc-install-* temp dirs after tar.gz install
# =========================================================================

echo "[Test 8] No leftover aisc-install-* temp dirs after tar.gz install"

# Use a controlled TMPDIR so we can inspect for leftovers
CONTROLLED_TMP="$TEST_WORKSPACE/controlled-tmp"
mkdir -p "$CONTROLLED_TMP"
export TMPDIR="$CONTROLLED_TMP"

# Ensure no pre-existing aisc-install-* dirs
find "$CONTROLLED_TMP" -maxdepth 1 -name 'aisc-install-*' -exec rm -rf {} + 2>/dev/null || true

# Clean previous install
rm -rf "$INSTALL_DIR" "$BIN_LINK" 2>/dev/null || true

# Run tar.gz install
if TMPDIR="$CONTROLLED_TMP" bash "$INSTALL_SCRIPT" "$TAR_FILE" > "$TEST_WORKSPACE/install8.log" 2>&1; then
    pass "tar.gz install (controlled TMPDIR) exited 0"
else
    fail "tar.gz install (controlled TMPDIR) failed — see install8.log"
    cat "$TEST_WORKSPACE/install8.log"
fi

# Check for leftover aisc-install-* directories
LEFTOVERS=$(find "$CONTROLLED_TMP" -maxdepth 1 -name 'aisc-install-*' 2>/dev/null)
if [ -z "$LEFTOVERS" ]; then
    pass "no leftover aisc-install-* temp dirs in TMPDIR"
else
    fail "leftover temp dirs found: $LEFTOVERS"
fi

echo ""

# =========================================================================
# Test 9: Unset XDG_BIN_HOME does not crash uninstall
# =========================================================================

echo "[Test 9] Unset XDG_BIN_HOME does not crash uninstall"

# Install so there's something to uninstall
rm -rf "$INSTALL_DIR" "$BIN_LINK" 2>/dev/null || true
bash "$INSTALL_SCRIPT" "$DIRECT_SRC" > /dev/null 2>&1 || true

# Run uninstall with XDG_BIN_HOME explicitly unset
# (the test workspace already has XDG_BIN_HOME exported, so unset it)
if unset XDG_BIN_HOME && bash "$UNINSTALL_SCRIPT" > "$TEST_WORKSPACE/uninstall9.log" 2>&1; then
    pass "uninstall with unset XDG_BIN_HOME: exited 0"
else
    fail "uninstall with unset XDG_BIN_HOME: crashed — see uninstall9.log"
    cat "$TEST_WORKSPACE/uninstall9.log"
fi

# Bin directory (default ~/.local/bin) should be removed if empty
# Don't assert on removal — just that we survived
if [ ! -d "$INSTALL_DIR" ] && [ ! -L "$INSTALL_DIR" ]; then
    pass "uninstall with unset XDG_BIN_HOME: install dir removed"
else
    fail "uninstall with unset XDG_BIN_HOME: install dir still exists"
fi

echo ""

# =========================================================================
# Summary
# =========================================================================

echo "=== Results: $PASSED passed, $FAILED failed ==="
if [ "$FAILED" -gt 0 ]; then
    echo ""
    echo "Logs available in: $TEST_WORKSPACE"
    exit 1
fi
echo "All install smoke tests passed."
exit 0
