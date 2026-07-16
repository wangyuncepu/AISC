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

# ensure_writable DIR... — mkdir -p with sudo fallback + sudo chown AISC
# Validates non-empty paths, falls back to sudo for creation, and fails clearly
# if the directory cannot be made writable for user AISC.
ensure_writable() {
  local d
  for d in "$@"; do
    # Validate non-empty path
    [ -n "$d" ] || { echo "ensure_writable: empty path" >&2; return 1; }

    # Try plain mkdir first, fall back to sudo
    if ! mkdir -p -- "$d" 2>/dev/null; then
      if ! sudo mkdir -p -- "$d" 2>/dev/null; then
        echo "ensure_writable: cannot create directory '$d'" >&2
        return 1
      fi
    fi

    # chown to AISC:AISC — do NOT silently swallow failure
    if ! sudo chown -R AISC:AISC -- "$d"; then
      echo "ensure_writable: cannot chown '$d' to AISC:AISC" >&2
      return 1
    fi

    # Verify the directory is actually writable by current user
    if ! [ -w "$d" ]; then
      echo "ensure_writable: '$d' is still not writable after chown" >&2
      return 1
    fi
  done
}
