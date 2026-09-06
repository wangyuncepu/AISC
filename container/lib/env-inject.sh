#!/bin/bash
# env_inject SETTINGS_FILE
# 从 settings.json 读取 env 块并注入 shell 的共享函数。
# 依赖: node（需要 fs）
#
# PERF P3b (D-13): mtime 缓存——cc-switch 每次切换都会重写 settings.json
# （mtime 前进），缓存比它新即意味着解析结果仍有效；此前每次 agent
# 启动都 spawn 一个 node 只为解析同一个文件。缓存命中路径零外部进程
# （[ file -nt file ] 是 bash 内建）。缓存文件不比 settings 新（或首次）
# 才跑 node，产物同时落缓存。
env_inject() {
  local sf="$1"
  [ -f "$sf" ] || return 0
  local cache="/tmp/aisc-env-inject${sf//\//_}.sh"
  if [ -f "$cache" ] && [ "$cache" -nt "$sf" ]; then
    source "$cache" 2>/dev/null && return 0
  fi
  local exports
  exports="$(SETTINGS_FILE="$sf" node - <<'NODE'
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
  [ -n "$exports" ] || return 0
  printf '%s\n' "$exports" > "$cache" 2>/dev/null || true
  eval "$exports"
}
