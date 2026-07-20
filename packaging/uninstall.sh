#!/usr/bin/env bash
# AISC portable uninstall — removes the installed aisc binary and bundle
#
# Usage:
#   ./uninstall.sh
#
# Removes:
#   - The install directory (aisc + aisc-bundle/ from install.sh)
#   - The symlink from $XDG_BIN_HOME
#
# Does NOT remove:
#   - User configuration (e.g. ~/.aisc, container volumes)
#   - Docker images or containers
#   - Workspace directories

set -euo pipefail

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
info() { printf '%s\n' "$*"; }

# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------

detect_os() {
    case "$(uname -s)" in
        Linux)  echo "linux" ;;
        Darwin) echo "macos" ;;
        *)      die "Unsupported operating system: $(uname -s)" ;;
    esac
}

OS="$(detect_os)"
EXE_NAME="aisc"

get_install_dir() {
    if [ "$OS" = "linux" ]; then
        printf '%s' "${XDG_DATA_HOME:-$HOME/.local/share}/aisc"
    else
        printf '%s' "$HOME/Library/Application Support/AISC"
    fi
}

get_bin_dir() {
    printf '%s' "${XDG_BIN_HOME:-$HOME/.local/bin}"
}

INSTALL_DIR="$(get_install_dir)"
BIN_DIR="$(get_bin_dir)"
BIN_LINK="${BIN_DIR}/${EXE_NAME}"

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

removed_any=false

# 1. Remove symlink
if [ -L "$BIN_LINK" ]; then
    info "Removing symlink: ${BIN_LINK}"
    rm -f "$BIN_LINK" || warn "Failed to remove symlink"
    removed_any=true
elif [ -f "$BIN_LINK" ]; then
    # It exists but is a regular file, not a symlink. Check if it's our install.
    if [ -f "${INSTALL_DIR}/${EXE_NAME}" ]; then
        real_bin="$(readlink -f "$BIN_LINK" 2>/dev/null || true)"
        real_inst="$(readlink -f "${INSTALL_DIR}/${EXE_NAME}" 2>/dev/null || true)"
        if [ "$real_bin" = "$real_inst" ]; then
            info "Removing hard-linked or copied binary: ${BIN_LINK}"
            rm -f "$BIN_LINK" || warn "Failed to remove binary"
            removed_any=true
        fi
    fi
    if [ -f "$BIN_LINK" ]; then
        warn "Binary at ${BIN_LINK} is not a symlink and does not match our install — skipping"
    fi
else
    info "Symlink not found: ${BIN_LINK}"
fi

# 2. Remove install directory
if [ -d "$INSTALL_DIR" ]; then
    info "Removing install directory: ${INSTALL_DIR}"
    rm -rf "$INSTALL_DIR" || warn "Failed to remove install directory"
    removed_any=true
else
    info "Install directory not found: ${INSTALL_DIR}"
fi

# 3. Remove empty bin directory (only if we created it and it's empty)
if [ -d "$BIN_DIR" ] && [ -z "$(ls -A "$BIN_DIR" 2>/dev/null)" ]; then
    # Only remove if we own it and it's not a standard system directory
    if [ "$BIN_DIR" = "$HOME/.local/bin" ] || [ "$BIN_DIR" = "${XDG_BIN_HOME:-}" ]; then
        info "Removing empty bin directory: ${BIN_DIR}"
        rmdir "$BIN_DIR" 2>/dev/null || warn "Failed to remove empty bin directory (may not be empty after all)"
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

info ""
if [ "$removed_any" = true ]; then
    info "AISC has been uninstalled."
    info ""
    info "The following were NOT removed (preserve these manually if desired):"
    info "  - User configuration: ~/.aisc, ~/.cc-config"
    info "  - Docker images and containers (use 'docker' commands)"
    info "  - Workspace directories"
    info ""
    info "If you also used the Scheme A (uv) installation, run:"
    info "  uv tool uninstall aisc"
else
    info "No AISC installation found — nothing to uninstall."
fi
