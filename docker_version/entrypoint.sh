#!/bin/sh
set -e

# 目标挂载目录（用户当前的项目代码）
PROJECT_CLAUDE_DIR="/app/.claude"

# 如果用户项目目录下没有 .claude 文件夹，或者没有 settings.local.json，则自动注入
if [ ! -d "$PROJECT_CLAUDE_DIR" ] || [ ! -f "$PROJECT_CLAUDE_DIR/settings.local.json" ]; then
    echo "💡 [Super-Claude] 正在为当前项目初始化本地配置与插件..."
    mkdir -p "$PROJECT_CLAUDE_DIR"
    cp -r /template/.claude/* "$PROJECT_CLAUDE_DIR/" 2>/dev/null || true
fi

# 执行传给 docker 的命令（默认是 claude）
exec "$@"