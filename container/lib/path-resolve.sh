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

# ensure_writable DIR... — mkdir -p + sudo chown AISC
ensure_writable() {
  local d
  for d in "$@"; do
    mkdir -p "$d"
    sudo chown -R AISC:AISC "$d" 2>/dev/null || true
  done
}
