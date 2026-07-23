#!/usr/bin/env bash
# Build macOS .pkg installer for AISC (arm64).
#
# Usage (macOS only):
#   bash build_pkg.sh <version> <onefile-path> <bundle-path> <output-dir>
#
# Example:
#   bash build_pkg.sh "2.0.4-dev" ./dist/aisc ./staging/aisc-bundle ./out
#
# Output:
#   AISC-2.0.4-dev-macos-arm64.pkg + .sha256
#
# Requirements: macOS with pkgbuild (included in Xcode CLT or full Xcode).
#
# Version handling:
#   - pkgbuild --version requires a dotted numeric version (e.g. "2.0.0").
#     Our VERSION may contain "-dev" / pre-release suffixes that pkgbuild
#     rejects.  We derive a "package version" (receipt_version) by extracting
#     the leading X.Y.Z core.  The output filename retains the full display
#     version for human readability.
#
# Layout:
#   /usr/local/lib/aisc/aisc           (onefile executable, 0755)
#   /usr/local/lib/aisc/aisc-bundle/   (bundle directory, recursive)
#   /usr/local/lib/aisc/uninstall.sh   (uninstaller, 0755)
#   /usr/local/bin/aisc -> ../lib/aisc/aisc  (relative symlink)

set -euo pipefail

die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
info() { printf '%s\n' "$*"; }

# ------------------------------------------------------------------
# Arguments
# ------------------------------------------------------------------
VERSION="${1:?Usage: $0 <version> <onefile> <bundle-dir> <output-dir>}"
ONEFILE="${2:?}"
BUNDLE_DIR="${3:?}"
OUTDIR="${4:?}"

# Basic input validation
[ -f "$ONEFILE"  ] || die "onefile not found: $ONEFILE"
[ -x "$ONEFILE"  ] || die "onefile is not executable: $ONEFILE"
[ -d "$BUNDLE_DIR" ] || die "bundle dir not found: $BUNDLE_DIR"

# Verify required bundle files
for required in VERSION container/Dockerfile config/versions.env; do
    [ -f "$BUNDLE_DIR/$required" ] || die "Missing required file in bundle: $required"
done

# Version normalisation for pkgbuild receipt
# pkgbuild --version requires a clean X.Y.Z; strip "-dev", "-alpha", etc.
receipt_version=$(echo "$VERSION" | sed -nE 's/^([0-9]+\.[0-9]+\.[0-9]+).*$/\1/p')
if [ -z "$receipt_version" ]; then
    die "Cannot extract X.Y.Z from VERSION='$VERSION'.  pkgbuild requires dotted numeric."
fi
info "Display version : $VERSION"
info "Package version : $receipt_version"

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
IDENTIFIER="com.aisc.cli"
PKG_NAME="AISC-${VERSION}-macos-arm64"
PKG_FILE="${PKG_NAME}.pkg"
TMPBASE="${TMPDIR:-/tmp}"
ROOT_DIR="$(mktemp -d "${TMPBASE}/aisc-pkg-root-XXXXXX")"
SCRIPTS_DIR="$(mktemp -d "${TMPBASE}/aisc-pkg-scripts-XXXXXX")"
CLEANUP_DONE=false
cleanup() {
    if [ "$CLEANUP_DONE" = false ]; then
        rm -rf "$ROOT_DIR" "$SCRIPTS_DIR"
        CLEANUP_DONE=true
    fi
}
trap cleanup EXIT

mkdir -p "$OUTDIR"

# ------------------------------------------------------------------
# Build payload root (relative to /)
# ------------------------------------------------------------------
info "Building payload root at $ROOT_DIR ..."

LIB_DIR="$ROOT_DIR/usr/local/lib/aisc"
BIN_DIR="$ROOT_DIR/usr/local/bin"

mkdir -p "$LIB_DIR" "$BIN_DIR"

# Copy onefile executable
cp "$ONEFILE" "$LIB_DIR/aisc"
chmod 0755 "$LIB_DIR/aisc"

# Copy entire bundle
cp -R "$BUNDLE_DIR" "$LIB_DIR/aisc-bundle"

# Create relative symlink: /usr/local/bin/aisc -> ../lib/aisc/aisc
# The symlink is embedded in the payload itself (BOM includes it).
ln -sf ../lib/aisc/aisc "$BIN_DIR/aisc"

# ------------------------------------------------------------------
# Uninstall script (also in payload)
# ------------------------------------------------------------------
cat > "$LIB_DIR/uninstall.sh" << 'UNINSTALL_EOF'
#!/usr/bin/env bash
# AISC macOS uninstaller — removes files installed by the .pkg.
# Must be run with sudo:  sudo /usr/local/lib/aisc/uninstall.sh
#
# Does NOT remove:
#   - $HOME/.aisc  (user config)
#   - Docker images / containers
#   - Workspace directories
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run with sudo." >&2
    echo "  sudo /usr/local/lib/aisc/uninstall.sh" >&2
    exit 1
fi

AISC_SYMLINK="/usr/local/bin/aisc"
AISC_LIB="/usr/local/lib/aisc"
IDENTIFIER="com.aisc.cli"

removed=false

# 1. Remove symlink — only if it points to our expected target
if [ -L "$AISC_SYMLINK" ]; then
    target="$(readlink "$AISC_SYMLINK" 2>/dev/null || true)"
    expected="../lib/aisc/aisc"
    if [ "$target" = "$expected" ]; then
        rm -f "$AISC_SYMLINK"
        echo "Removed symlink: $AISC_SYMLINK"
        removed=true
    else
        echo "WARNING: $AISC_SYMLINK is a symlink but points to '$target' (expected '$expected') — NOT removing." >&2
    fi
elif [ -f "$AISC_SYMLINK" ] || [ -e "$AISC_SYMLINK" ]; then
    echo "WARNING: $AISC_SYMLINK exists but is not a symlink created by AISC — NOT removing." >&2
fi

# 2. Remove /usr/local/lib/aisc and all contents
if [ -d "$AISC_LIB" ]; then
    rm -rf "$AISC_LIB"
    echo "Removed: $AISC_LIB"
    removed=true
fi

# 3. Forget the pkg receipt (best-effort)
if command -v pkgutil >/dev/null 2>&1; then
    pkgutil --forget "$IDENTIFIER" 2>/dev/null && \
        echo "Forgot package receipt: $IDENTIFIER" || \
        echo "WARNING: pkgutil --forget failed (receipt may not exist)" >&2
fi

echo ""
if [ "$removed" = true ]; then
    echo "AISC has been uninstalled."
    echo ""
    echo "The following were NOT removed:"
    echo "  - \$HOME/.aisc"
    echo "  - Docker images/containers"
else
    echo "AISC installation not found — nothing to uninstall."
fi
UNINSTALL_EOF
chmod 0755 "$LIB_DIR/uninstall.sh"

# ------------------------------------------------------------------
# Preinstall script (for upgrade cleanup)
# ------------------------------------------------------------------
# pkgbuild supports --scripts for preinstall/postinstall.
# On upgrade, old files not in new payload may linger.  We remove the
# old aisc and aisc-bundle before installing new versions so stale files
# don't accumulate.  We operate ONLY under $DSTROOT (the install root)
# to support alternate target volumes safely.
mkdir -p "$SCRIPTS_DIR"

cat > "$SCRIPTS_DIR/preinstall" << 'PREINSTALL_EOF'
#!/bin/bash
# preinstall: clean old aisc + aisc-bundle before new payload is laid down.
# $3 is the target mount point (e.g. "/" or a custom root for alternate installs).
set -euo pipefail
DSTROOT="${3:-/}"
LIB_DIR="${DSTROOT}/usr/local/lib/aisc"
BIN_LINK="${DSTROOT}/usr/local/bin/aisc"

if [ -f "${LIB_DIR}/aisc" ]; then
    rm -f "${LIB_DIR}/aisc"
fi
if [ -d "${LIB_DIR}/aisc-bundle" ]; then
    rm -rf "${LIB_DIR}/aisc-bundle"
fi
# Remove old symlink only if it's our expected relative target
if [ -L "${BIN_LINK}" ]; then
    target="$(readlink "${BIN_LINK}" 2>/dev/null || true)"
    if [ "$target" = "../lib/aisc/aisc" ]; then
        rm -f "${BIN_LINK}"
    fi
fi
exit 0
PREINSTALL_EOF
chmod 0755 "$SCRIPTS_DIR/preinstall"

# ------------------------------------------------------------------
# Build .pkg with pkgbuild
# ------------------------------------------------------------------
info "Building $PKG_FILE ..."

pkgbuild \
    --root "$ROOT_DIR" \
    --identifier "$IDENTIFIER" \
    --version "$receipt_version" \
    --scripts "$SCRIPTS_DIR" \
    --install-location "/" \
    "$OUTDIR/$PKG_FILE"

# ------------------------------------------------------------------
# SHA256 sidecar (macOS uses shasum -a 256)
# ------------------------------------------------------------------
if command -v shasum >/dev/null 2>&1; then
    SHASUM_CMD="shasum -a 256"
elif command -v sha256sum >/dev/null 2>&1; then
    SHASUM_CMD="sha256sum"
else
    die "Neither shasum nor sha256sum found"
fi

(cd "$OUTDIR" && $SHASUM_CMD "$PKG_FILE" > "${PKG_FILE}.sha256")

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
info ""
info "=== Package built ==="
info "  File:    $OUTDIR/$PKG_FILE"
info "  Size:    $(du -sh "$OUTDIR/$PKG_FILE" | cut -f1)"
info "  SHA256:  $(cat "$OUTDIR/${PKG_FILE}.sha256")"

cleanup
trap - EXIT
