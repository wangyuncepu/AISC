#!/bin/bash
# 开启遇到错误即退出的严格模式
set -e

# 定义常量路径
PROJECT_CLAUDE_DIR="/app/.claude"
TEMPLATE_CLAUDE_DIR="/template/.claude"

echo -e "\n🚀 [Super Claude] 工作站初始化中..."

# ==========================================
# 1. 智能技能注入逻辑 (防覆盖机制)
# ==========================================
# 检查模板目录是否存在内容
if [ -d "$TEMPLATE_CLAUDE_DIR" ] && [ "$(ls -A $TEMPLATE_CLAUDE_DIR)" ]; then
    # 检查用户的项目目录下是否已经有 .claude 文件夹
    if [ ! -d "$PROJECT_CLAUDE_DIR" ]; then
        echo "📦 检测到项目首次运行，正在注入全局技能库 (Skills) 和预设配置..."
        # 递归拷贝所有模板文件到宿主机挂载的项目目录
        cp -r "$TEMPLATE_CLAUDE_DIR" "$PROJECT_CLAUDE_DIR"
        echo "✅ 技能库注入成功！"
    else
        echo "🔍 检测到当前项目已有 .claude 配置，跳过注入 (保护您的自定义修改)。"
    fi
else
    echo "⚠️ 未找到预设技能模板，跳过注入步骤。"
fi

# ==========================================
# 2. 权限修复机制 (解决 Linux/WSL 下的文件 Root 锁死问题)
# ==========================================
# 由于 Docker 内部默认是 root 运行，cp 过去的文件归属也是 root。
# 这里通过自动获取挂载目录当前的属主，把新文件的权限交还给你！
if [ -d "$PROJECT_CLAUDE_DIR" ]; then
    HOST_UID=$(stat -c "%u" /app)
    HOST_GID=$(stat -c "%g" /app)
    # 如果发现宿主机目录不是 root，就把 .claude 的归属权还给宿主机用户
    if [ "$HOST_UID" != "0" ]; then
        chown -R $HOST_UID:$HOST_GID "$PROJECT_CLAUDE_DIR"
    fi
fi

# ==========================================
# 3. 环境变量与网络状态展示
# ==========================================
SETTINGS_FILE="${HOME}/.claude/settings.json"
if [ -f "$SETTINGS_FILE" ]; then
    MODEL=$(node -e "try{process.stdout.write(require('$SETTINGS_FILE').env?.ANTHROPIC_MODEL||'')}catch(e){}" 2>/dev/null)
    BASE_URL=$(node -e "try{process.stdout.write(require('$SETTINGS_FILE').env?.ANTHROPIC_BASE_URL||'')}catch(e){}" 2>/dev/null)
    echo "🌐 当前大模型后端: ${MODEL:-未配置}"
    if [ -n "$BASE_URL" ]; then
        echo "🔗 自定义 API 节点: $BASE_URL"
    fi
else
    echo "🌐 当前大模型后端: 未配置（运行 cs <后端> 进行切换）"
fi
echo -e "----------------------------------------\n"

# ==========================================
# 4. 智能引导：支持 cs 直连切换
# ==========================================
# 如果用户用 Docker 命令行传入 cs，表示切换后自动重启 Claude
if [ "$1" = "cs" ]; then
    shift
    SC_RESTART=1 exec /usr/local/bin/cs "$@"
fi

# ==========================================
# 5. 执行控制权移交 (极其关键)
# ==========================================
# 使用 exec 是 Docker 入口脚本的最佳实践！
# 它会让 claude 进程直接替换掉当前的 bash 进程成为 PID 1。
# 这样在终端里按下 Ctrl+C 才能被 Claude 正确捕获并打断任务，否则终端会卡死。
exec "$@"
