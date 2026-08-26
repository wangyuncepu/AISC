#!/usr/bin/env bash
# AISC portable uninstall — removes the installed aisc binary and bundle
#
# Usage:
#   ./uninstall.sh                        # also cleans AISC Docker resources
#   ./uninstall.sh --keep-docker-resources # keep containers + image
#
# Removes:
#   - AISC Docker containers and the workstation image (via the bundled
#     CLI's centralized lifecycle service; default, needs Docker running)
#   - The install directory (aisc + aisc-bundle/ from install.sh)
#   - The symlink from $XDG_BIN_HOME
#
# Does NOT remove:
#   - User configuration (e.g. ~/.aisc, container volumes)
#   - Workspace directories or persistent toolchains

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

KEEP_DOCKER=false
for arg in "$@"; do
    case "$arg" in
        --keep-docker-resources) KEEP_DOCKER=true ;;
        *) die "Unknown option: $arg (expected --keep-docker-resources)" ;;
    esac
done

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

# 1.5 Docker companion cleanup (docker-resource-lifecycle D): default ON,
# --keep-docker-resources opts out. Runs the bundled CLI BEFORE the
# install dir is removed; best-effort, never blocks the uninstall.
if [ "$KEEP_DOCKER" = false ] && [ -x "${INSTALL_DIR}/${EXE_NAME}" ]; then
    info "Cleaning AISC Docker resources (containers + image)..."
    set +e
    "${INSTALL_DIR}/${EXE_NAME}" maintenance docker-cleanup         --context uninstall --format json
    rc=$?
    set -e
    if [ "$rc" -eq 3 ]; then
        warn "Docker unreachable - AISC containers/image kept."
    elif [ "$rc" -ne 0 ]; then
        warn "Partial cleanup failures (exit $rc) - see output above."
    else
        info "AISC Docker resources cleaned."
    fi
elif [ "$KEEP_DOCKER" = true ]; then
    info "Keeping Docker resources (--keep-docker-resources)."
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
    info "  - User configuration: ~/.aisc and the data root"
    info "  - Workspace directories and persistent toolchains"
    info ""
    info "If you also used the Scheme A (uv) installation, run:"
    info "  uv tool uninstall aisc"
else
    info "No AISC installation found — nothing to uninstall."
fi
