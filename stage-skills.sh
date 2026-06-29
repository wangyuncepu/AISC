#!/usr/bin/env bash
# stage-skills.sh —— 构建前从宿主机 ~/.claude 暂存所需插件与技能到 _bundle/
# Docker 构建上下文只能访问 AISC/ 目录，故插件缓存需先暂存进 _bundle（已 gitignore）。
#
# 暂存内容：
#   插件（plugin 机制，离线可用）：caveman / claude-hud / document-skills /
#                                  superpowers / skill-creator
#   扁平技能（仅文档）：gstack
set -euo pipefail

SRC="${HOME}/.claude"
DST="$(cd "$(dirname "$0")" && pwd)/_bundle"
IMG_HOME="/root/.claude"   # 镜像内目标路径，用于重写绝对路径

# 需要的 4 个 marketplace（skill-creator 由 claude-plugins-official 本地源解析）
MARKETS=(caveman claude-hud claude-plugins-official anthropic-agent-skills)

echo "🧹 清理旧 _bundle ..."
rm -rf "$DST"
mkdir -p "$DST/plugins/cache" "$DST/plugins/marketplaces" "$DST/skills"

echo "📦 复制插件 cache ..."
for mp in "${MARKETS[@]}"; do
    cp -r "$SRC/plugins/cache/$mp" "$DST/plugins/cache/$mp"
done

echo "📦 复制插件 marketplaces ..."
for mp in "${MARKETS[@]}"; do
    cp -r "$SRC/plugins/marketplaces/$mp" "$DST/plugins/marketplaces/$mp"
done

echo "📝 生成裁剪后的 known_marketplaces.json / installed_plugins.json（路径改写 → $IMG_HOME）..."
MARKETS_JSON="$(printf '%s\n' "${MARKETS[@]}" | node -e 'const ls=require("fs").readFileSync(0,"utf8").trim().split("\n");process.stdout.write(JSON.stringify(ls))')" \
SRC="$SRC" IMG_HOME="$IMG_HOME" DST="$DST" node <<'NODE'
const fs = require('fs');
const src = process.env.SRC, img = process.env.IMG_HOME, dst = process.env.DST;
const keep = new Set(JSON.parse(process.env.MARKETS_JSON));
const rewrite = (s) => JSON.parse(JSON.stringify(s).split(src).join(img));

// known_marketplaces.json：仅保留所需 marketplace
const km = JSON.parse(fs.readFileSync(`${src}/plugins/known_marketplaces.json`, 'utf8'));
const kmOut = {};
for (const [k, v] of Object.entries(km)) if (keep.has(k)) kmOut[k] = rewrite(v);
fs.writeFileSync(`${dst}/plugins/known_marketplaces.json`, JSON.stringify(kmOut, null, 2));

// installed_plugins.json：仅保留所需 marketplace 来源的插件
const ip = JSON.parse(fs.readFileSync(`${src}/plugins/installed_plugins.json`, 'utf8'));
const ipOut = { version: ip.version, plugins: {} };
for (const [name, entries] of Object.entries(ip.plugins || {})) {
  const mp = name.split('@')[1];
  if (!keep.has(mp)) continue;
  // 去重：同一插件可能有 user/project 多条 scope，仅保留 user（项目路径在镜像内无意义）
  let list = (entries || []).filter(e => e.scope === 'user');
  if (list.length === 0) list = [entries[0]];
  ipOut.plugins[name] = rewrite([list[0]]);
}
fs.writeFileSync(`${dst}/plugins/installed_plugins.json`, JSON.stringify(ipOut, null, 2));
console.log('  marketplaces:', Object.keys(kmOut).join(', '));
console.log('  plugins:', Object.keys(ipOut.plugins).join(', '));
NODE

echo "🌐 复制 gstack（仅 markdown 文档，无二进制）..."
# docs-only：仅保留目录结构与 *.md（SKILL.md 及其引用文档），剔除全部二进制/构建产物
rsync -a \
  --exclude='node_modules' --exclude='.git' --exclude='.gbrain' \
  --include='*/' --include='*.md' --exclude='*' \
  "$SRC/skills/gstack/" "$DST/skills/gstack/"
# 删除复制后残留的空目录
find "$DST/skills/gstack" -type d -empty -delete 2>/dev/null || true

echo "✅ 暂存完成。体积："
du -sh "$DST" "$DST/plugins/cache" "$DST/plugins/marketplaces" "$DST/skills/gstack" 2>/dev/null
echo ""
echo "下一步：docker build -t super-claude:latest ."
