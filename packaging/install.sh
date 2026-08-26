#!/usr/bin/env bash
# AISC portable install — user-level installation without Python/uv
#
# Usage:
#   ./install.sh /path/to/AISC-2.0.4-dev-linux-x86_64.tar.gz
#   ./install.sh /path/to/extracted-archive/
#
# Installs the aisc executable and aisc-bundle/ into a user-local directory
# and creates a symlink in $XDG_BIN_HOME (default ~/.local/bin).
#
# Linux:    ${XDG_DATA_HOME:-$HOME/.local/share}/aisc
# macOS:    $HOME/Library/Application Support/AISC
# symlink:  ${XDG_BIN_HOME:-$HOME/.local/bin}/aisc
#
# Repeated installations use staged replacement (staging → rm old → mv).
# Executable and aisc-bundle/ must remain adjacent after install.
#
# This script does NOT:
#   - Create, upload, or publish GitHub Releases
#   - Sign, notarise, or auto-update
#   - Modify Docker, Python, or user workspaces

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
info() { printf '%s\n' "$*"; }

# Resolve a (possibly relative) path to an absolute path, handling macOS
# where /var is a symlink to /private/var.
resolve() {
    local p
    p="$1"
    # realpath --canonicalize-missing not universally available; use readlink -f
    if command -v realpath >/dev/null 2>&1; then
        realpath -- "$p"
    elif readlink -f / >/dev/null 2>&1; then
        readlink -f -- "$p"
    else
        # Fallback: cd to directory and use pwd
        local d b
        d="$(dirname -- "$p")"
        b="$(basename -- "$p")"
        if cd "$d" 2>/dev/null; then
            printf '%s/%s' "$(pwd -P 2>/dev/null || pwd)" "$b"
        else
            printf '%s' "$p"
        fi
    fi
}

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

info "Detected OS: ${OS}"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

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
# Argument parsing
# ---------------------------------------------------------------------------

SOURCE="${1:-}"

if [ -z "$SOURCE" ]; then
    die "Usage: $0 <source>"
    printf '\n'
    printf '  source   Path to a local AISC archive (.tar.gz) or an extracted\n'
    printf '           directory containing aisc + aisc-bundle/\n'
    exit 1
fi

SOURCE="$(resolve "$SOURCE")"

if [ ! -e "$SOURCE" ]; then
    die "Source not found: ${SOURCE}"
fi

# ---------------------------------------------------------------------------
# Locate aisc executable and aisc-bundle/ inside the source
# ---------------------------------------------------------------------------

find_in_source() {
    local src="$1"
    local exe bundle

    # If src is a directory: look directly, then one level down
    if [ -d "$src" ]; then
        exe=""
        bundle=""
        if [ -f "$src/$EXE_NAME" ]; then
            exe="$src/$EXE_NAME"
        fi
        if [ -d "$src/aisc-bundle" ]; then
            bundle="$src/aisc-bundle"
        fi
        if [ -n "$exe" ] && [ -n "$bundle" ]; then
            printf '%s\n' "$exe"
            printf '%s\n' "$bundle"
            return 0
        fi
        # Look one level down for AISC-*/ directories
        local inner
        inner=$(find "$src" -mindepth 1 -maxdepth 1 -type d -name 'AISC-*' 2>/dev/null | head -1)
        if [ -n "$inner" ]; then
            exe=""
            bundle=""
            if [ -f "$inner/$EXE_NAME" ]; then
                exe="$inner/$EXE_NAME"
            fi
            if [ -d "$inner/aisc-bundle" ]; then
                bundle="$inner/aisc-bundle"
            fi
            if [ -n "$exe" ] && [ -n "$bundle" ]; then
                printf '%s\n' "$exe"
                printf '%s\n' "$bundle"
                return 0
            fi
        fi
        return 1
    fi

    # If src is a .tar.gz or .tgz
    case "$src" in
        *.tar.gz|*.tgz) ;;
        *) return 1 ;;
    esac

    # Read tar table-of-contents to find executable and bundle without extracting
    local tar_bin
    tar_bin="$(command -v tar 2>/dev/null || true)"
    if [ -z "$tar_bin" ]; then
        die "tar not found — required to extract archive"
    fi

    local members
    members=$("$tar_bin" -tf "$src" 2>/dev/null) || die "Failed to read archive: ${src}"

    # Find the inner directory (AISC-*/) from file paths.
    # The tar may not contain standalone directory entries — extract the
    # common prefix from the first matching file path.
    local inner_dir
    inner_dir=$(printf '%s\n' "$members" | grep -Eo '^AISC-[^/]+/' | head -1 | sed 's|/$||')
    if [ -z "$inner_dir" ]; then
        die "No AISC-*/ top-level directory found in archive"
    fi

    # Check for executable and bundle entries
    local has_exe has_bundle
    has_exe=$(printf '%s\n' "$members" | grep -cE "^${inner_dir}/${EXE_NAME}$" || true)
    has_bundle=$(printf '%s\n' "$members" | grep -cE "^${inner_dir}/aisc-bundle/" || true)
    if [ "$has_exe" -eq 0 ]; then
        die "No ${EXE_NAME} found in archive under ${inner_dir}/"
    fi
    if [ "$has_bundle" -eq 0 ]; then
        die "No aisc-bundle/ found in archive under ${inner_dir}/"
    fi

    printf 'ARCHIVE:%s\n' "$inner_dir"
    return 0
}

# ---------------------------------------------------------------------------
# Verify required bundle files
# ---------------------------------------------------------------------------

verify_bundle() {
    local bundle_dir="$1"
    local errors=0

    check_file() {
        local f="$1"
        if [ ! -f "${bundle_dir}/${f}" ]; then
            warn "Missing required file: aisc-bundle/${f}"
            errors=$((errors + 1))
        fi
    }

    check_file "VERSION"
    check_file "container/Dockerfile"
    check_file "config/versions.env"

    if [ "$errors" -gt 0 ]; then
        die "Bundle verification failed: ${errors} missing required file(s)"
    fi

    local ver
    ver=$(head -1 "${bundle_dir}/VERSION" 2>/dev/null || echo "unknown")
    info "Bundle VERSION: ${ver}"
}

# ---------------------------------------------------------------------------
# Staged replacement install
# ---------------------------------------------------------------------------

do_install() {
    local exe_src="$1"
    local bundle_src="$2"

    # Verify the source executable is executable
    if [ ! -x "$exe_src" ]; then
        die "Source executable is not executable: ${exe_src}"
    fi

    # Verify bundle
    verify_bundle "$bundle_src"

    # Create bin directory
    mkdir -p "$BIN_DIR" 2>/dev/null || die "Cannot create bin directory: ${BIN_DIR}"

    # Check if bin directory is in PATH; warn if not
    if ! printf '%s' "${PATH:-}" | tr ':' '\n' | grep -qxF "$BIN_DIR"; then
        warn "${BIN_DIR} is not in your PATH"
        warn "Add this to your shell profile (e.g. ~/.bashrc):"
        warn "  export PATH=\"${BIN_DIR}:\$PATH\""
        warn "Or run: aisc --help   after re-opening your terminal"
    fi

    # Create a temporary staging directory next to the target
    local parent_dir
    parent_dir="$(dirname "$INSTALL_DIR")"
    mkdir -p "$parent_dir" 2>/dev/null || die "Cannot create parent directory: ${parent_dir}"

    local tmpdir
    tmpdir="$(mktemp -d "${INSTALL_DIR}.tmp-XXXXXX")" || die "Cannot create temporary directory"

    # Clean up temp on exit
    # shellcheck disable=SC2064
    trap 'rm -rf "$tmpdir"' EXIT

    # Copy executable into temp
    cp "$exe_src" "${tmpdir}/${EXE_NAME}" || die "Failed to copy executable to staging"
    chmod 755 "${tmpdir}/${EXE_NAME}" || die "Failed to set executable permission"

    # Copy bundle into temp
    cp -R "$bundle_src" "${tmpdir}/aisc-bundle" || die "Failed to copy bundle to staging"

    # Final verification of staged install
    if [ ! -x "${tmpdir}/${EXE_NAME}" ]; then
        die "Staged executable is not executable"
    fi
    verify_bundle "${tmpdir}/aisc-bundle"

    # docker-resource-lifecycle D: upgrade lifecycle. The STAGED (new)
    # sidecar runs BEFORE the old installation is replaced — the old aisc
    # may predate the maintenance commands. Capture the old default-image
    # id, then stop AISC containers (upgrade context keeps the tagged
    # image until the rebuild succeeds). Fresh installs skip entirely.
    local was_upgrade=false old_image_id=""
    if [ -x "${INSTALL_DIR}/${EXE_NAME}" ]; then
        was_upgrade=true
        info "Previous installation detected - running upgrade lifecycle..."
        old_image_id="$( "${tmpdir}/${EXE_NAME}" maintenance docker-scan             --context upgrade --format text 2>/dev/null             | awk '$1=="image" && ($2=="owned" || $2=="legacy_owned") &&                    $4=="super-claude:latest" {print $3; exit}' || true )"
        set +e
        "${tmpdir}/${EXE_NAME}" maintenance docker-cleanup             --context upgrade --format json
        rc=$?
        set -e
        if [ "$rc" -eq 3 ]; then
            warn "Docker unreachable - AISC containers left as-is."
        fi
    fi

    # Staged replacement: remove old install, move staging into place
    if [ -e "$INSTALL_DIR" ] || [ -L "$INSTALL_DIR" ]; then
        info "Removing previous installation at ${INSTALL_DIR} ..."
        rm -rf "$INSTALL_DIR" || die "Failed to remove previous installation"
    fi

    mv "$tmpdir" "$INSTALL_DIR" || die "Failed to move staging to ${INSTALL_DIR}"
    trap - EXIT  # temp dir was moved successfully

    # docker-resource-lifecycle D: no-cache rebuild with the old-ID
    # handoff. Best-effort: a failure leaves the image pending with the
    # manual command printed.
    if [ "$was_upgrade" = true ]; then
        info "Rebuilding workstation image (no cache; this can take minutes)..."
        set +e
        "${INSTALL_DIR}/${EXE_NAME}" maintenance docker-rebuild             --root "${INSTALL_DIR}/aisc-bundle"             --tag super-claude:latest --old-image-id "$old_image_id"             --format json
        rc=$?
        set -e
        if [ "$rc" -ne 0 ]; then
            warn "Image rebuild did not complete (exit $rc)."
            warn "Manual: aisc maintenance docker-rebuild --root ${INSTALL_DIR}/aisc-bundle --tag super-claude:latest"
        else
            info "Workstation image rebuilt."
        fi
    fi

    # Create symlink (or replace existing)
    local target="${INSTALL_DIR}/${EXE_NAME}"
    if [ -e "$BIN_LINK" ] || [ -L "$BIN_LINK" ]; then
        info "Removing previous symlink: ${BIN_LINK}"
        rm -f "$BIN_LINK" || warn "Failed to remove previous symlink"
    fi

    # Use relative symlink where possible
    if command -v realpath >/dev/null 2>&1; then
        ln -sf "$(realpath --relative-to="$BIN_DIR" "$target" 2>/dev/null || echo "$target")" "$BIN_LINK" || {
            warn "Relative symlink failed, falling back to absolute"
            ln -sf "$target" "$BIN_LINK" || die "Failed to create symlink"
        }
    else
        ln -sf "$target" "$BIN_LINK" || die "Failed to create symlink"
    fi

    # Verify the symlink works
    if [ ! -x "$BIN_LINK" ]; then
        warn "Symlink not executable — check file permissions"
    fi
}

# ---------------------------------------------------------------------------
# Handle tar.gz source (extract to temp)
# ---------------------------------------------------------------------------

install_from_archive() {
    local archive="$1"
    local inner_dir="$2"

    local extract_dir
    extract_dir="$(mktemp -d "${TMPDIR:-/tmp}/aisc-install-XXXXXX")" || die "Cannot create extraction directory"

    # Run extraction + install inside a subshell so that cleanup of
    # extract_dir always runs when this function returns, regardless of
    # do_install() manipulating its own EXIT trap or calling die().
    (
        set -euo pipefail
        info "Extracting ${archive} ..."
        tar -xzf "$archive" -C "$extract_dir" || exit 1

        local exe="${extract_dir}/${inner_dir}/${EXE_NAME}"
        local bundle="${extract_dir}/${inner_dir}/aisc-bundle"

        if [ ! -f "$exe" ]; then
            warn "Executable not found after extraction: ${exe}"
            exit 1
        fi
        if [ ! -d "$bundle" ]; then
            warn "Bundle not found after extraction: ${bundle}"
            exit 1
        fi

        chmod 755 "$exe" 2>/dev/null || true
        do_install "$exe" "$bundle"
    )
    local _rc=$?
    rm -rf "$extract_dir"
    return $_rc
}

# ---------------------------------------------------------------------------
# Handle directory source
# ---------------------------------------------------------------------------

install_from_directory() {
    local dir="$1"

    local exe bundle

    # Check direct layout first
    if [ -f "$dir/$EXE_NAME" ] && [ -d "$dir/aisc-bundle" ]; then
        exe="$dir/$EXE_NAME"
        bundle="$dir/aisc-bundle"
    else
        # Look one level down for AISC-*/ layout
        local inner
        inner=$(find "$dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)
        if [ -n "$inner" ] && [ -f "${inner}/${EXE_NAME}" ] && [ -d "${inner}/aisc-bundle" ]; then
            exe="${inner}/${EXE_NAME}"
            bundle="${inner}/aisc-bundle"
        else
            die "Cannot find ${EXE_NAME} + aisc-bundle/ in ${dir}"
        fi
    fi

    chmod 755 "$exe" 2>/dev/null || true
    do_install "$exe" "$bundle"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

FOUND=$(find_in_source "$SOURCE")

if [ -z "$FOUND" ]; then
    die "Could not locate ${EXE_NAME} + aisc-bundle/ in ${SOURCE}"
fi

# Restore EXIT trap (find_in_source may have inherited one but shouldn't set one)
trap - EXIT 2>/dev/null || true

# Check if source is an archive (find_in_source returns ARCHIVE: prefix)
case "$FOUND" in
    ARCHIVE:*)
        INNER_DIR="${FOUND#ARCHIVE:}"
        install_from_archive "$SOURCE" "$INNER_DIR"
        ;;
    *)
        # find_in_source returned two lines: exe path and bundle path
        SRC_EXE=$(printf '%s\n' "$FOUND" | head -1)
        SRC_BUNDLE=$(printf '%s\n' "$FOUND" | tail -1)
        do_install "$SRC_EXE" "$SRC_BUNDLE"
        ;;
esac

# Print summary
info ""
info "========================================="
info " AISC installed successfully!"
info "========================================="
info ""
info "  Install directory: ${INSTALL_DIR}"
info "  Symlink:           ${BIN_LINK}"
info ""

if ! printf '%s' "${PATH:-}" | tr ':' '\n' | grep -qxF "$BIN_DIR"; then
    info "  IMPORTANT: ${BIN_DIR} is not in your PATH."
    info "  Add the following to your shell profile and restart your terminal:"
    info ""
    info "    export PATH=\"${BIN_DIR}:\$PATH\""
    info ""
fi

info "  Verify installation:"
info "    aisc version"
info ""
info "  Uninstall:"
info "    ${0%/*}/uninstall.sh"
info ""
info "Source: ${SOURCE} can now be safely deleted."
