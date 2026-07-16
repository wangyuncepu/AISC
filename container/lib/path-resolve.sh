#!/bin/bash
# resolve_cc_config_dir — 按优先级输出 CC_CONFIG_DIR
resolve_cc_config_dir() {
  if [ -n "${CC_CONFIG_DIR:-}" ]; then
    echo "$CC_CONFIG_DIR"
  elif [ -d /home/AISC/app ]; then
    echo "/home/AISC/app/.cc-config"
  elif [ -f "./.cc-config/api-keys" ]; then
    echo "$(pwd)/.cc-config"
  else
    echo "${HOME}/.cc-config"
  fi
}

# resolve_key_store — 输出 api-keys 路径
resolve_key_store() {
  echo "$(resolve_cc_config_dir)/api-keys"
}

# _probe_writable DIR — test writability via real file ops (create/write/rename/delete)
# Best-effort cleanup on all paths. No [ -w ] — real I/O is the only reliable signal.
_probe_writable() {
  local d="$1"
  local stamp="${RANDOM}${RANDOM}_$$"
  local p="${d}/.aisc_wr_probe_${stamp}"
  local p2="${d}/.aisc_wr_probe_${stamp}_r"
  # create
  : > "$p" 2>/dev/null || return 1
  # write
  printf 'x' > "$p" 2>/dev/null || { rm -f -- "$p" 2>/dev/null; return 1; }
  # rename
  mv -- "$p" "$p2" 2>/dev/null || { rm -f -- "$p" "$p2" 2>/dev/null; return 1; }
  # delete — must verify rm actually succeeded
  if ! rm -f -- "$p2" 2>/dev/null; then
    rm -f -- "$p" "$p2" 2>/dev/null
    return 1
  fi
  return 0
}

# ensure_writable DIR... — mkdir + real-I/O probe with non-recursive best-effort repair
# Does NOT use [ -w ]; probes with actual create/write/rename/delete.
# On first probe success skips sudo/chown/chmod entirely (no unnecessary privilege ops).
# On failure applies best-effort non-recursive sudo chown + sudo chmod, then re-probes.
# Final failure prints diagnostics (id / stat / possible root causes) without leaking content.
ensure_writable() {
  local d
  for d in "$@"; do
    [ -n "$d" ] || { echo "ensure_writable: empty path" >&2; return 1; }

    # --- mkdir: plain → sudo fallback ---
    if ! mkdir -p -- "$d" 2>/dev/null; then
      if ! sudo mkdir -p -- "$d" 2>/dev/null; then
        echo "ensure_writable: cannot create directory '$d'" >&2
        return 1
      fi
    fi

    # --- First probe: real I/O ---
    if _probe_writable "$d"; then
      continue
    fi

    # --- Probe failed: best-effort non-recursive repair (no -R) ---
    sudo chown "$(id -u):$(id -g)" -- "$d" 2>/dev/null || true
    sudo chmod u+rwx -- "$d"               2>/dev/null || true

    # --- Second probe ---
    if _probe_writable "$d"; then
      continue
    fi

    # --- Final failure: clear diagnostics ---
    echo "ensure_writable: '$d' is not writable after repair attempts" >&2
    echo "  current user: $(id 2>/dev/null || echo 'unknown')" >&2
    if command -v stat >/dev/null 2>&1; then
      echo "  dir  stat: $(stat -c 'perm=%a owner=%U:%G' -- "$d" 2>/dev/null || echo 'unavailable')" >&2
      echo "  parent stat: $(stat -c 'perm=%a owner=%U:%G' -- "$(dirname -- "$d")" 2>/dev/null || echo 'unavailable')" >&2
    fi
    echo "  possible causes: read-only bind mount / CIFS / NFS / rootless / user namespace" >&2
    return 1
  done
}
