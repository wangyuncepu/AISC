#!/usr/bin/env bash
# stage-skills-cleanup.sh — 供 stage-skills.sh 调用的破坏性清理辅助函数
# 仅限 _bundle/plugins/ 和 _bundle/skills/gstack 目录下的安全清理。
# 绝不触碰其他 skills 目录（由 aisc skill 导入的目录）。
# 本脚本可被测试独立调用（需提供 DST 变量）。

: "${DST:?DST must be set to container/_bundle path}"

for _clean_target in "$DST/plugins" "$DST/skills/gstack"; do
    [ -d "$_clean_target" ] || continue
    find "$_clean_target" -name '.git' -prune -exec rm -rf {} + 2>/dev/null || true
    find "$_clean_target" -name '.in_use' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    find "$_clean_target" -name '.gitignore' -delete 2>/dev/null || true
done
