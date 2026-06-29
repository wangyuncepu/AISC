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

echo "✂️  瘦身 marketplace（仅保留启用插件实际引用的源）..."
# anthropic-agent-skills：document-skills 源为 ./skills/{xlsx,docx,pptx,pdf}，其余技能删除
if [ -d "$DST/plugins/marketplaces/anthropic-agent-skills/skills" ]; then
    find "$DST/plugins/marketplaces/anthropic-agent-skills/skills" -mindepth 1 -maxdepth 1 -type d \
        ! -name 'xlsx' ! -name 'docx' ! -name 'pptx' ! -name 'pdf' -exec rm -rf {} +
fi
# claude-plugins-official：仅 skill-creator 需本地源（构建时离线 install），其余删除
if [ -d "$DST/plugins/marketplaces/claude-plugins-official/plugins" ]; then
    find "$DST/plugins/marketplaces/claude-plugins-official/plugins" -mindepth 1 -maxdepth 1 -type d \
        ! -name 'skill-creator' -exec rm -rf {} +
fi
rm -rf "$DST/plugins/marketplaces/claude-plugins-official/external_plugins"

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

echo "✂️  剪枝 cache 多余版本（每插件仅保留 installed_plugins.json 引用的版本）..."
IMG_HOME="$IMG_HOME" DST="$DST" node <<'NODE'
const fs = require('fs'), path = require('path');
const img = process.env.IMG_HOME, dst = process.env.DST;
const ip = JSON.parse(fs.readFileSync(`${dst}/plugins/installed_plugins.json`, 'utf8'));
// 收集每个 <marketplace>/<plugin> 需保留的版本目录名
const keep = {}; // key: "mp/plugin" -> Set(version)
for (const entries of Object.values(ip.plugins || {})) {
  for (const e of entries) {
    const p = (e.installPath || '').replace(img + '/plugins/cache/', '');
    const [mp, plugin, ver] = p.split('/');
    if (!mp || !plugin || !ver) continue;
    (keep[`${mp}/${plugin}`] ||= new Set()).add(ver);
  }
}
for (const [pp, vers] of Object.entries(keep)) {
  const dir = `${dst}/plugins/cache/${pp}`;
  if (!fs.existsSync(dir)) continue;
  for (const v of fs.readdirSync(dir)) {
    if (!vers.has(v)) { fs.rmSync(path.join(dir, v), { recursive: true, force: true }); console.log(`  剪除 ${pp}/${v}`); }
  }
}
NODE

echo "🌐 复制 gstack（仅文档，且只保留指定子技能）..."
# 只保留这些 gstack 子技能（docs-only：仅 *.md，无二进制）
GSTACK_SKILLS=(office-hours plan-ceo-review plan-eng-review plan-design-review autoplan plan-devex-review)
mkdir -p "$DST/skills/gstack"
# gstack 入口 SKILL.md（保留以使 gstack 作为技能可加载）
[ -f "$SRC/skills/gstack/SKILL.md" ] && cp "$SRC/skills/gstack/SKILL.md" "$DST/skills/gstack/SKILL.md"
for sk in "${GSTACK_SKILLS[@]}"; do
    [ -d "$SRC/skills/gstack/$sk" ] || { echo "  ⚠ 跳过缺失子技能: $sk"; continue; }
    rsync -a \
      --exclude='node_modules' --exclude='.git' \
      --include='*/' --include='*.md' --exclude='*' \
      "$SRC/skills/gstack/$sk/" "$DST/skills/gstack/$sk/"
done
find "$DST/skills/gstack" -type d -empty -delete 2>/dev/null || true

echo "🧩 折叠自定义扁平技能（custom-skills/）进 _bundle/skills/ ..."
# _bundle 每次重建，故自定义技能源置于 tracked 的 custom-skills/，构建期复制进来
CUSTOM_DIR="$(cd "$(dirname "$0")" && pwd)/custom-skills"
if [ -d "$CUSTOM_DIR" ]; then
    cp -r "$CUSTOM_DIR/." "$DST/skills/"
    echo "  已并入: $(ls "$CUSTOM_DIR")"
fi

echo "🧽 剥离嵌入 .git 与运行锁（避免污染外层仓库 / 减小体积）..."
find "$DST" -name '.git' -prune -exec rm -rf {} + 2>/dev/null || true
find "$DST" -name '.in_use' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "✅ 暂存完成。体积："
du -sh "$DST" "$DST/plugins/cache" "$DST/plugins/marketplaces" "$DST/skills/gstack" 2>/dev/null
echo ""
echo "下一步：docker build -t super-claude:latest ."
