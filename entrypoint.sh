#!/bin/bash
# 开启遇到错误即退出的严格模式
set -e

# 运行期 UTF-8 兜底：即便镜像未注入 locale 也保证中文不乱码 (no.5)
export LANG=C.UTF-8 LC_ALL=C.UTF-8

# ==========================================
# 路径模型
#   .claude   = Claude CLI 原生完整目录（skills/plugins/projects/todos/statsig…，软件本体）
#               全局 /root/.claude；项目模式整目录拷到 /app/.claude（不改名）
#   .cc-config = cs 运行时生成的特殊配置（settings.json + api-keys），独立于 .claude
#               固定放当前项目 /app/.cc-config（全局与项目模式都用它）
# ==========================================
GLOBAL_CLAUDE_DIR="/root/.claude"
PROJECT_CLAUDE_DIR="/app/.claude"
CC_CONFIG_DIR="/app/.cc-config"   # cs 配置目录，恒定项目内

echo -e "\n🚀 [Super Claude] 工作站初始化中..."

# ==========================================
# 1. 选择 .claude 作用域：全局 / 项目
#    - 优先环境变量 CLAUDE_SCOPE=global|project（无交互，适合脚本）
#    - 否则交互终端弹菜单
#    - 非交互且无变量 → 默认 project
# ==========================================
SCOPE="${CLAUDE_SCOPE:-}"

if [ -z "$SCOPE" ]; then
    if [ -t 0 ]; then
        echo ""
        echo "请选择 Claude (.claude) 作用域："
        echo "  1) 全局 global  — 使用镜像内置全局 .claude (${GLOBAL_CLAUDE_DIR})，不写入当前项目"
        echo "  2) 项目 project — 当前项目独立 .claude (${PROJECT_CLAUDE_DIR})，从全局完整复制"
        echo ""
        read -r -p "输入 1 或 2 [默认 2]: " choice
        case "$choice" in
            1) SCOPE="global" ;;
            *) SCOPE="project" ;;
        esac
    else
        SCOPE="project"
    fi
fi

# ==========================================
# 2. 按作用域确定 CLAUDE_CONFIG_DIR（CLI 原生目录）
# ==========================================
if [ "$SCOPE" = "global" ]; then
    CLAUDE_CONFIG_DIR="$GLOBAL_CLAUDE_DIR"
    echo "🌍 作用域: 全局 (global) → $CLAUDE_CONFIG_DIR"
else
    CLAUDE_CONFIG_DIR="$PROJECT_CLAUDE_DIR"
    echo "📁 作用域: 项目 (project) → $CLAUDE_CONFIG_DIR"

    # 项目 .claude 不存在 → 从全局完整复制（CLI 原生目录整体，含 skills/plugins/...）
    if [ ! -d "$PROJECT_CLAUDE_DIR" ]; then
        echo "📦 当前项目首次运行，正在从全局复制完整 .claude（含技能库与 CLI 状态）..."
        cp -r "$GLOBAL_CLAUDE_DIR" "$PROJECT_CLAUDE_DIR"
        echo "✅ 项目 .claude 初始化成功！"
    else
        echo "🔍 检测到当前项目已有 .claude，跳过复制 (保护您的自定义修改)。"
    fi
fi

export CLAUDE_CONFIG_DIR
export CC_CONFIG_DIR

# .cc-config（cs 配置）目录确保存在
mkdir -p "$CC_CONFIG_DIR"

# 权限修复：Docker 内 root 写入的文件交还宿主机用户（仅项目挂载卷需要）
HOST_UID=$(stat -c "%u" /app 2>/dev/null || echo 0)
HOST_GID=$(stat -c "%g" /app 2>/dev/null || echo 0)
if [ "$HOST_UID" != "0" ]; then
    [ -d "$PROJECT_CLAUDE_DIR" ] && chown -R "$HOST_UID:$HOST_GID" "$PROJECT_CLAUDE_DIR" 2>/dev/null || true
    chown -R "$HOST_UID:$HOST_GID" "$CC_CONFIG_DIR" 2>/dev/null || true
fi

# 让用户进入 bash 后再次运行 cs / claude 时仍能拿到同一作用域
{
    echo "export CLAUDE_CONFIG_DIR='$CLAUDE_CONFIG_DIR'"
    echo "export CC_CONFIG_DIR='$CC_CONFIG_DIR'"
} > /etc/profile.d/cc-scope.sh 2>/dev/null || true
if ! grep -q 'CC_CONFIG_DIR' /root/.bashrc 2>/dev/null; then
    {
        echo "export CLAUDE_CONFIG_DIR='$CLAUDE_CONFIG_DIR'"
        echo "export CC_CONFIG_DIR='$CC_CONFIG_DIR'"
    } >> /root/.bashrc
fi

# ==========================================
# 3. 环境变量与网络状态展示（读 .cc-config 的 settings.json）
# ==========================================
SETTINGS_FILE="$CC_CONFIG_DIR/settings.json"
KEY_STORE="$CC_CONFIG_DIR/api-keys"

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
# 5. 启动方式菜单：bash（可选）/ claude（默认）
#    仅在交互终端、且以默认 claude 启动时弹出
#    无任何 cs 配置时不再拦截 —— 空配置即走 cc 官方默认端点
# ==========================================
if [ "$1" = "claude" ] && [ -t 0 ]; then
    if [ "$AUTH" = "no" ] && [ -z "$MODEL" ]; then
        echo "ℹ️  当前无 cs 配置，将以 cc 官方默认启动（可在 bash 内用 cs 切换后端）。"
    fi
    echo ""
    echo "请选择启动方式："
    echo "  1) bash   进入命令行（可手动 cs 配置后再 claude）"
    echo "  2) claude 直接启动 Claude（默认）"
    echo ""
    read -r -p "输入 1 或 2 [默认 2]: " launch
    case "$launch" in
        1) echo "▶️  进入 bash。"; exec bash ;;
        *) ;;  # 继续往下启动 claude
    esac
fi

# ==========================================
# 6. 执行控制权移交 (极其关键)
# ==========================================
# 使用 exec 是 Docker 入口脚本的最佳实践！
# 它会让 claude 进程直接替换掉当前的 bash 进程成为 PID 1。
# 这样在终端里按下 Ctrl+C 才能被 Claude 正确捕获并打断任务，否则终端会卡死。
exec "$@"
