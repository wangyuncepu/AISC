#!/bin/bash
# 开启遇到错误即退出的严格模式
set -e

# 运行期 UTF-8 兜底：即便镜像未注入 locale 也保证中文不乱码 (no.5)
export LANG=C.UTF-8 LC_ALL=C.UTF-8

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
# cs 将 settings 持久化到 /app/.claude/（宿主机卷），此处统一读取
SETTINGS_FILE="/app/.claude/settings.json"
KEY_STORE="/app/.claude/api-keys"

# 首次运行：cs 尚未写入，使用容器内的空默认配置作为 fallback
if [ ! -f "$SETTINGS_FILE" ]; then
    SETTINGS_FILE="${HOME}/.claude/settings.json"
fi
if [ ! -f "$KEY_STORE" ]; then
    KEY_STORE="${HOME}/.claude/api-keys"
fi

if [ -f "$SETTINGS_FILE" ]; then
    MODEL=$(node -e "try{process.stdout.write(require('$SETTINGS_FILE').env?.ANTHROPIC_MODEL||'')}catch(e){}" 2>/dev/null)
    BASE_URL=$(node -e "try{process.stdout.write(require('$SETTINGS_FILE').env?.ANTHROPIC_BASE_URL||'')}catch(e){}" 2>/dev/null)
    AUTH=$(node -e "try{const e=require('$SETTINGS_FILE').env;process.stdout.write(e.ANTHROPIC_API_KEY||e.ANTHROPIC_AUTH_TOKEN?'yes':'no')}catch(e){process.stdout.write('no')}" 2>/dev/null)

    # 将 settings.json 的 env 块真正注入当前 shell，供 claude 进程继承。
    # 空值必须 unset，避免 ANTHROPIC_API_KEY="" 覆盖 ANTHROPIC_AUTH_TOKEN。
    eval "$(SETTINGS_FILE="$SETTINGS_FILE" node - <<'NODE'
const fs = require('fs');
const cfg = JSON.parse(fs.readFileSync(process.env.SETTINGS_FILE, 'utf8'));
const env = cfg.env || {};
function q(v) {
  return "'" + String(v).replace(/'/g, "'\\''") + "'";
}
for (const [k, v] of Object.entries(env)) {
  if (v) console.log(`export ${k}=${q(v)}`);
  else console.log(`unset ${k}`);
}
NODE
)"
else
    MODEL=""
    BASE_URL=""
    AUTH="no"
fi

echo "🌐 当前大模型后端: ${MODEL:-未配置}"
if [ -n "$BASE_URL" ]; then
    echo "🔗 自定义 API 节点: $BASE_URL"
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
# 5. 未配置拦截：无后端时阻止直接进 Claude，引导用户先配置
# ==========================================
if [ "$1" = "claude" ] && [ "$AUTH" = "no" ] && [ -z "$MODEL" ]; then
    echo ""
    if [ -f "$KEY_STORE" ] && grep -q '.=' "$KEY_STORE" 2>/dev/null; then
        echo "💡 已检测到保存的 Key，请运行 cs <后端> 完成配置："
        echo "   cs deepseek    cs ark    cs 1y    cs duo-cc    cs cc"
    else
        echo "💡 请先运行 cs <后端> 配置 Key，再启动 Claude："
        echo "   cs deepseek    ← DeepSeek V4"
        echo "   cs ark         ← Ark GLM-5.2"
        echo "   cs 1y          ← 1yuanapi"
        echo "   cs duo-cc      ← duo-cc"
        echo "   cs cc          ← Anthropic 官方"
    fi
    echo ""
    exec bash
fi

# ==========================================
# 6. 执行控制权移交 (极其关键)
# ==========================================
# 使用 exec 是 Docker 入口脚本的最佳实践！
# 它会让 claude 进程直接替换掉当前的 bash 进程成为 PID 1。
# 这样在终端里按下 Ctrl+C 才能被 Claude 正确捕获并打断任务，否则终端会卡死。
exec "$@"
