#!/bin/bash
# env_inject SETTINGS_FILE
# 从 settings.json 读取 env 块并注入 shell 的共享函数。
# 依赖: node（需要 fs）
env_inject() {
  local sf="$1"
  [ -f "$sf" ] || return 0
  eval "$(SETTINGS_FILE="$sf" node - <<'NODE'
const fs = require('fs');
const cfg = JSON.parse(fs.readFileSync(process.env.SETTINGS_FILE, 'utf8'));
const env = cfg.env || {};
for (const [k, v] of Object.entries(env)) {
  if (v) {
    const q = "'" + String(v).replace(/'/g, "'\\''") + "'";
    console.log('export ' + k + '=' + q);
  } else {
    console.log('unset ' + k);
  }
}
NODE
  )"
}
