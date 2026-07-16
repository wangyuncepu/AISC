#!/bin/bash
# 开启遇到错误即退出的严格模式
set -e

# 运行期 UTF-8 兜底：即便镜像未注入 locale 也保证中文不乱码 (no.5)
export LANG=C.UTF-8 LC_ALL=C.UTF-8

# 终端能力兜底：Windows(cmd/docker) 下容器 TERM 常缺失，导致 Claude Code
# 判定终端不支持而隐藏 statusLine(claude-hud HUD)。强制设为支持 VT 的值。
export TERM="${TERM:-xterm-256color}"
[ "$TERM" = "dumb" ] && export TERM=xterm-256color

# ==========================================
# 路径模型（全程非 root，用户 AISC，家目录 /home/AISC）
#   .claude   = Claude CLI 原生完整目录（skills/plugins/projects/todos/statsig…，软件本体）
#               临时模式用镜像内置 /home/AISC/.claude；项目模式整目录拷到 /home/AISC/app/.claude（不改名）
#   .cc-config = cs 运行时生成的特殊配置（settings.json + api-keys），独立于 .claude
#               固定放当前项目 /home/AISC/app/.cc-config（临时与项目模式都用它）
# ==========================================
GLOBAL_CLAUDE_DIR="/home/AISC/.claude"
PROJECT_CLAUDE_DIR="/home/AISC/app/.claude"
CC_CONFIG_DIR="/home/AISC/app/.cc-config"   # cs 配置目录，恒定项目内

echo -e "\n🚀 [Super Claude] 工作站初始化中..."

# ==========================================
# 1. 选择 .claude 作用域：临时 / 项目
#    临时(temporary) = 用镜像内置 /home/AISC/.claude，容器退出即重置，改动不保留
#    项目(project)   = /home/AISC/app/.claude，持久到宿主机卷，跨 run 保留
#    - 优先环境变量 CLAUDE_SCOPE=global|project（global 即临时；无交互，适合脚本）
#    - 否则交互终端弹菜单
#    - 非交互且无变量 → 默认 project
# ==========================================
SCOPE="${CLAUDE_SCOPE:-}"

if [ -z "$SCOPE" ]; then
    if [ -t 0 ]; then
        echo ""
        echo "请选择 Claude (.claude) 作用域："
        echo "  1) 临时 temporary — 使用镜像内置 .claude (${GLOBAL_CLAUDE_DIR})，容器退出即重置、改动不保留"
        echo "  2) 项目 project   — 当前项目独立 .claude (${PROJECT_CLAUDE_DIR})，持久到宿主机，从镜像完整复制"
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
if [ "$SCOPE" = "global" ] || [ "$SCOPE" = "temp" ] || [ "$SCOPE" = "temporary" ]; then
    CLAUDE_CONFIG_DIR="$GLOBAL_CLAUDE_DIR"
    echo "🧪 作用域: 临时 (temporary) → $CLAUDE_CONFIG_DIR （容器退出即重置）"
else
    CLAUDE_CONFIG_DIR="$PROJECT_CLAUDE_DIR"
    echo "📁 作用域: 项目 (project) → $CLAUDE_CONFIG_DIR"

    # 项目 .claude 不存在或残缺 → 从镜像内置 .claude 完整复制
    #   完整性判据：skills 与 plugins 同时存在。残缺多因旧版在 Windows 绑定挂载上
    #   cp 符号链接失败中断所致；此处自动修复。cp -rL 解引用符号链接，兼容 grpcfuse。
    NEED_COPY=0
    if [ ! -d "$PROJECT_CLAUDE_DIR" ]; then
        NEED_COPY=1
        echo "📦 当前项目首次运行，正在从镜像复制完整 .claude（含技能库与 CLI 状态）..."
    elif [ ! -d "$PROJECT_CLAUDE_DIR/skills" ] || [ ! -d "$PROJECT_CLAUDE_DIR/plugins" ]; then
        NEED_COPY=1
        echo "⚠️  检测到项目 .claude 残缺（缺 skills/plugins），正在从镜像补全复制..."
    fi
    if [ "$NEED_COPY" = 1 ]; then
        mkdir -p "$PROJECT_CLAUDE_DIR"
        cp -rL "$GLOBAL_CLAUDE_DIR/." "$PROJECT_CLAUDE_DIR/"
        echo "✅ 项目 .claude 已就绪。"
    else
        echo "🔍 检测到当前项目已有完整 .claude，跳过复制 (保护您的自定义修改)。"
    fi

    # 修正插件注册表绝对路径 → /home/AISC/app/.claude（幂等）。
    # 否则 installPath 仍指向镜像内路径，CLI 误判项目内插件副本为 orphan，
    # 可能在后续插件操作时删除其 dist → claude-hud(HUD) 等失效。
    # 兼容两类历史路径：当前镜像 /home/AISC/.claude，更早 root 镜像 /root/.claude
    # （后者 AISC 读不了 /root → 插件加载失败、skills 不出现）。
    for j in installed_plugins.json known_marketplaces.json; do
        f="$PROJECT_CLAUDE_DIR/plugins/$j"
        [ -f "$f" ] && sed -i -e "s#${GLOBAL_CLAUDE_DIR}#${PROJECT_CLAUDE_DIR}#g" \
                                -e "s#/root/.claude#${PROJECT_CLAUDE_DIR}#g" "$f" 2>/dev/null || true
    done

    # 检测镜像出厂配置是否比项目新 → 仅提示，由用户手动 cs upgrade
    FV_IMG="$GLOBAL_CLAUDE_DIR/.factory-version"
    FV_PRJ="$PROJECT_CLAUDE_DIR/.factory-version"
    if [ -f "$FV_IMG" ] && [ "$(cat "$FV_IMG" 2>/dev/null)" != "$(cat "$FV_PRJ" 2>/dev/null)" ]; then
        echo "⚠️  镜像出厂配置已更新（skills/插件/命令等）。"
        echo "    运行  cs upgrade  升级当前项目 .claude（保留你的后端配置与历史）。"
    fi
fi

export CLAUDE_CONFIG_DIR
export CC_CONFIG_DIR

# .cc-config（cs 配置）目录确保存在
mkdir -p "$CC_CONFIG_DIR"

# 旧镜像曾以 root 运行，绑定挂载把 root 所有权持久化到宿主；
# 新镜像 USER AISC 后 mkdir -p 见目录已存在则 no-op，不修所有权，
# 导致 AISC 读不了 root:600 的 api-keys → cs 切换静默失败。
# AISC 已在 sudoers (NOPASSWD)，此处直接 sudo chown 自愈，
# 不依赖外部 bat 的宿主侧 root pass。
sudo chown -R AISC:AISC "$CC_CONFIG_DIR" 2>/dev/null || true
# .claude 目录同理：挂载卷上文件可能属于宿主机用户（非 uid 1000），
# AISC 无写权限会导致 cs 写 settings.json 时报 EACCES。
if [ "$SCOPE" = "project" ]; then
    sudo chown -R AISC:AISC "$CLAUDE_CONFIG_DIR" 2>/dev/null || true
fi

# 让用户进入 bash 后再次运行 cs / claude 时仍能拿到同一作用域
# （非 root，只能写家目录 ~/.bashrc；不再写 /etc/profile.d）
if ! grep -q 'CC_CONFIG_DIR' "$HOME/.bashrc" 2>/dev/null; then
    {
        echo "export CLAUDE_CONFIG_DIR='$CLAUDE_CONFIG_DIR'"
        echo "export CC_CONFIG_DIR='$CC_CONFIG_DIR'"
    } >> "$HOME/.bashrc"
fi

# ==========================================
# 3. 环境变量与网络状态展示
#    env 块读 CLAUDE_CONFIG_DIR/settings.json（Claude CLI 原生文件，cs 写此处）
#    api-keys 密钥仍在 .cc-config
# ==========================================
SETTINGS_FILE="$CLAUDE_CONFIG_DIR/settings.json"
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
# 3.5 容器内 Mihomo TUN 透明代理（若挂载了配置 /etc/mihomo/config.yaml）
#    - 宿主侧启动器仅下载/拷贝用户原始配置/订阅（ro 挂载），由 mihomo-build-config.js 处理：
#      读 ro 源 → 识别格式(yaml/base64订阅/URI直链/JSON) 非yaml自动转最小Clash配置
#      → 剥离已有 tun:/dns: 顶层块 → 追加规范 tun:（+ 缺失时补 dns:）→ 写可写副本
#      → sudo mihomo -f 副本
#    - mihomo 建 TUN 设备 + auto-route iptables 需 CAP_NET_ADMIN → 以 root(sudo) 后台启动
#      （AISC 已在 sudoers NOPASSWD；容器需 --cap-add=NET_ADMIN --device /dev/net/tun）
#    - 启动后再 exec claude：TUN 已接管容器全部出站，API 请求经代理
# ==========================================
if [ -f /etc/mihomo/config.yaml ]; then
    echo "🚀 正在内建 TUN 透明代理网络..."
    MIHOMO_DATA_DIR="/home/AISC/.mihomo"
    MIHOMO_CFG="$MIHOMO_DATA_DIR/config.yaml"

    # 原始订阅 → mihomo 配置（格式自动转换 + TUN/DNS 强制注入）到可写副本。
    # 支持 yaml / base64 订阅 / URI 直链 / JSON(SIP008)；失败仅告警不阻断，便于进 bash 排障。
    if node /usr/local/bin/mihomo-build-config.js /etc/mihomo/config.yaml "$MIHOMO_CFG"; then
        # 后台启动 mihomo（root），日志写 AISC 可写目录
        sudo -b bash -c "mihomo -d '$MIHOMO_DATA_DIR' -f '$MIHOMO_CFG' > '$MIHOMO_DATA_DIR/mihomo.log' 2>&1"
        # 等待 TUN 接管路由 + url-test 初选节点（节点多时需几秒）
        sleep 4
        # 健康探测：经代理能否到达 api.anthropic.com（不带 -f：401/404 等任何 HTTP 响应都算可达，只看连接是否成功）
        if curl -sS --max-time 10 -o /dev/null https://api.anthropic.com 2>/dev/null; then
            echo "✅ Mihomo TUN 已就绪，代理连通: api.anthropic.com 可达"
        else
            # curl 失败：区分 mihomo 进程是否存活，给出更准确的排障提示
            if sudo pgrep -f 'mihomo -d' >/dev/null 2>&1; then
                echo "⚠️  mihomo 运行中但代理暂未通（可能仍在 url-test 初选节点，或节点异常）。可继续；若 claude 连不上请查 $MIHOMO_DATA_DIR/mihomo.log"
            else
                echo "❌ mihomo 进程已退出，请查日志: $MIHOMO_DATA_DIR/mihomo.log"
            fi
        fi
    else
        echo "❌ 代理配置构建失败，跳过 TUN。请检查订阅链接或配置格式（支持 yaml/base64订阅/URI直链/JSON）。"
    fi
    echo "----------------------------------------"
fi

# ==========================================
# 3.6 AI 每日简讯（opt-in，默认不运行）
#   AI_BRIEF_ON_START=background  → 后台抓取+LLM（日志 /tmp/ai-brief.log），不阻塞
#   AI_BRIEF_ON_START=foreground  → 阻塞同步运行（含 50s 超时，仅调试用）
#   AI_BRIEF_ON_START=off / 空    → 不运行（默认，零阻塞）
#   并发抓取 ~9-12s + LLM（reasoning 模型）~30s → 总预算 50s。
#   ~/.cache/ai-brief/ 持久化，跨容器复用。
# ==========================================
AI_BRIEF_ON_START="${AI_BRIEF_ON_START:-}"

case "${AI_BRIEF_ON_START,,}" in
    background)
        if command -v python3 >/dev/null 2>&1 && [ -d /home/AISC/ai_brief ]; then
            if [ -n "$BASE_URL" ] && [ "$AUTH" = "yes" ]; then
                echo "📰 AI 简讯后台抓取中（日志: /tmp/ai-brief.log，容器启动后 cat /tmp/ai-brief.log 查看）"
                (
                    python3 /home/AISC/ai_brief/brief.py --ai --top 5 \
                        > /tmp/ai-brief.log 2>&1
                    printf '--- DONE (%s) ---\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> /tmp/ai-brief.log
                ) &
            else
                echo "📰 简讯跳过（当前无 cs 后端配置，--ai 不可用）"
            fi
        fi
        ;;
    foreground)
        # 阻塞同步模式（会延长启动时间，仅调试/手动触发用）
        if command -v python3 >/dev/null 2>&1 && [ -d /home/AISC/ai_brief ]; then
            if [ -n "$BASE_URL" ] && [ "$AUTH" = "yes" ]; then
                BRIEF_EXIT=0
                BRIEF="$(timeout 50 python3 /home/AISC/ai_brief/brief.py --ai --top 5 2>/tmp/ai-brief.log)" || BRIEF_EXIT=$?
                if [ -n "$BRIEF" ]; then
                    echo "📰 今日 AI 简讯："
                    echo "$BRIEF"
                    echo "----------------------------------------"
                elif [ "$BRIEF_EXIT" = "124" ]; then
                    echo "📰 简讯加载超时（50s），已跳过（容器内可手跑：python3 /home/AISC/ai_brief/brief.py）"
                    echo "----------------------------------------"
                else
                    echo "📰 简讯加载失败，已跳过（容器内可手跑：python3 /home/AISC/ai_brief/brief.py）"
                    echo "----------------------------------------"
                fi
            else
                echo "📰 简讯跳过（当前无 cs 后端配置，--ai 不可用）"
            fi
        fi
        ;;
    *)
        # off / 空 / 任何其他值 — 默认不运行，静默零阻塞
        ;;
esac

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
