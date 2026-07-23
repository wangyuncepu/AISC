#!/bin/bash
# 开启遇到错误即退出的严格模式
set -e

# 运行期 UTF-8 兜底：即便镜像未注入 locale 也保证中文不乱码 (no.5)
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export IS_SANDBOX="${IS_SANDBOX:-1}"

# 终端能力兜底：Windows(cmd/docker) 下容器 TERM 常缺失，导致 Claude Code
# 判定终端不支持而隐藏 statusLine(claude-hud HUD)。强制设为支持 VT 的值。
export TERM="${TERM:-xterm-256color}"
[ "$TERM" = "dumb" ] && export TERM=xterm-256color

# ==========================================
# 共享库：env 注入 + 路径/权限辅助（消除 entrypoint/claude-wrapper 重复代码）
# ==========================================
source /usr/local/bin/lib/env-inject.sh
source /usr/local/bin/lib/writable.sh

# ==========================================
# 路径模型（全程以 root 运行，宿主工作区挂载为 /root/app）
#   .claude = Claude CLI 原生完整目录（skills/plugins/projects/todos/statsig…，软件本体）
#             出厂模板在 /opt/aisc/factory；项目模式复制到 /root/app/.claude
#             临时模式复制到 /tmp/aisc-home/.claude
#   .codex  = Codex CLI 配置目录（类似 .claude 结构）
#             项目模式使用 /root/app/.codex；临时模式使用 /tmp/aisc-home/.codex
#   .cc-switch = cc-switch 运行时目录（数据库、设置、备份及 skills SSOT）
#             项目模式放 /root/app/.cc-switch；临时模式放 /tmp/aisc-home/.cc-switch
# ==========================================
FACTORY_HOME="/opt/aisc/factory"
FACTORY_CLAUDE_DIR="$FACTORY_HOME/.claude"
FACTORY_CODEX_DIR="$FACTORY_HOME/.codex"
TEMP_HOME="/tmp/aisc-home"
TEMP_CLAUDE_DIR="$TEMP_HOME/.claude"
TEMP_CODEX_DIR="$TEMP_HOME/.codex"
PROJECT_CLAUDE_DIR="/root/app/.claude"
PROJECT_CODEX_DIR="/root/app/.codex"

echo -e "\n🚀 [AISC] AI 工作站初始化中..."

# ==========================================
# 1. 选择 CLI 作用域：临时 / 项目
#    临时(temporary) = 用镜像内置配置，容器退出即重置，改动不保留
#    项目(project)   = 项目独立配置，持久到宿主机卷，跨 run 保留
#    - 优先环境变量 CLI_SCOPE=global|project（global 即临时；无交互，适合脚本）
#    - 兼容旧环境变量 CLAUDE_SCOPE
#    - 否则交互终端弹菜单
#    - 非交互且无变量 → 默认 project
# ==========================================
SCOPE="${CLI_SCOPE:-${CLAUDE_SCOPE:-}}"

if [ -z "$SCOPE" ]; then
    if [ -t 0 ]; then
        echo ""
        echo "请选择 AI CLI 作用域（Claude + Codex）："
        echo "  1) 临时 temporary — 使用镜像内置配置，容器退出即重置、改动不保留"
        echo "  2) 项目 project   — 当前项目独立配置，持久到宿主机，从镜像完整复制"
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
# 2. 按作用域确定 CLI 配置目录
# ==========================================
if [ "$SCOPE" = "global" ] || [ "$SCOPE" = "temp" ] || [ "$SCOPE" = "temporary" ]; then
    CLAUDE_CONFIG_DIR="$TEMP_CLAUDE_DIR"
    CODEX_CONFIG_DIR="$TEMP_CODEX_DIR"
    CC_SWITCH_CONFIG_DIR="$TEMP_HOME/.cc-switch"
    mkdir -p "$CLAUDE_CONFIG_DIR" "$CODEX_CONFIG_DIR"
    cp -rL "$FACTORY_CLAUDE_DIR/." "$CLAUDE_CONFIG_DIR/"
    cp -rL "$FACTORY_CODEX_DIR/." "$CODEX_CONFIG_DIR/"
    echo "🧪 作用域: 临时 (temporary) → Claude: $CLAUDE_CONFIG_DIR, Codex: $CODEX_CONFIG_DIR （容器退出即重置）"
else
    CLAUDE_CONFIG_DIR="$PROJECT_CLAUDE_DIR"
    CODEX_CONFIG_DIR="$PROJECT_CODEX_DIR"
    CC_SWITCH_CONFIG_DIR="/root/app/.cc-switch"
    echo "📁 作用域: 项目 (project) → Claude: $CLAUDE_CONFIG_DIR, Codex: $CODEX_CONFIG_DIR"

    # 项目 .claude 初始化（保持原有逻辑）
    NEED_COPY=0
    if [ "${FORCE_COPY_CLAUDE:-0}" = "1" ]; then
        NEED_COPY=1
        echo "🔄 FORCE_COPY_CLAUDE=1，强制重新复制 .claude..."
    elif [ ! -d "$PROJECT_CLAUDE_DIR" ]; then
        NEED_COPY=1
        echo "📦 当前项目首次运行，正在从镜像复制完整 .claude（含技能库与 CLI 状态）..."
    elif [ ! -d "$PROJECT_CLAUDE_DIR/skills" ] || [ ! -d "$PROJECT_CLAUDE_DIR/plugins" ]; then
        NEED_COPY=1
        echo "⚠️  检测到项目 .claude 残缺（缺 skills/plugins），正在从镜像补全复制..."
    elif [ -z "$(ls -A "$PROJECT_CLAUDE_DIR/skills" 2>/dev/null)" ] || [ -z "$(ls -A "$PROJECT_CLAUDE_DIR/plugins" 2>/dev/null)" ]; then
        NEED_COPY=1
        echo "⚠️  检测到项目 .claude skills/plugins 为空，正在从镜像补全复制..."
    fi

    if [ "$NEED_COPY" = 1 ]; then
        mkdir -p "$PROJECT_CLAUDE_DIR"
        if ! cp -rL "$FACTORY_CLAUDE_DIR/." "$PROJECT_CLAUDE_DIR/" 2>&1; then
            echo "❌ 复制 .claude 失败，请检查权限和磁盘空间" >&2
            exit 1
        fi

        # 验证关键目录存在且非空
        if [ ! -d "$PROJECT_CLAUDE_DIR/skills" ] || [ ! -d "$PROJECT_CLAUDE_DIR/plugins" ]; then
            echo "❌ 复制后 skills/plugins 目录仍然不存在" >&2
            exit 1
        fi
        if [ -z "$(ls -A "$PROJECT_CLAUDE_DIR/skills" 2>/dev/null)" ] || [ -z "$(ls -A "$PROJECT_CLAUDE_DIR/plugins" 2>/dev/null)" ]; then
            echo "❌ 复制后 skills/plugins 目录为空" >&2
            exit 1
        fi

        echo "✅ 项目 .claude 已就绪。"
    else
        echo "🔍 检测到当前项目已有完整 .claude，跳过复制 (保护您的自定义修改)。"
    fi

    # 检测镜像出厂配置更新
    FV_IMG="$FACTORY_CLAUDE_DIR/.factory-version"
    FV_PRJ="$PROJECT_CLAUDE_DIR/.factory-version"
    if [ -f "$FV_IMG" ] && [ "$(cat "$FV_IMG" 2>/dev/null)" != "$(cat "$FV_PRJ" 2>/dev/null)" ]; then
        echo "⚠️  镜像出厂配置已更新（skills/插件/命令等）。"
        echo "    可删除旧出厂副本后重启容器，或使用 cc-switch skills sync 同步 skills。"
    fi

    # 项目 .codex 初始化：从镜像内置完整出厂目录复制（类似 .claude 逻辑）
    NEED_COPY_CODEX=0
    if [ ! -d "$PROJECT_CODEX_DIR" ]; then
        NEED_COPY_CODEX=1
        echo "📦 首次运行，正在从镜像复制 Codex 配置..."
    elif [ -z "$(ls -A "$PROJECT_CODEX_DIR" 2>/dev/null)" ]; then
        NEED_COPY_CODEX=1
        echo "⚠️  项目 .codex 为空，正在从镜像补全..."
    fi

    if [ "$NEED_COPY_CODEX" = 1 ]; then
        mkdir -p "$PROJECT_CODEX_DIR"
        if [ ! -f "$FACTORY_CODEX_DIR/config.toml" ] || [ ! -d "$FACTORY_CODEX_DIR/skills" ]; then
            echo "❌ 镜像内置 .codex 不完整（缺 config.toml 或 skills），请重新构建镜像。" >&2
            exit 1
        fi
        if ! cp -rL "$FACTORY_CODEX_DIR/." "$PROJECT_CODEX_DIR/" 2>&1; then
            echo "❌ 复制 .codex 失败，请检查权限和磁盘空间。" >&2
            exit 1
        fi
        echo "✅ 项目 .codex 已就绪。"
    else
        echo "🔍 检测到当前项目已有 .codex 配置，跳过复制 (保护您的自定义修改)。"
    fi
fi

# 插件 bundle 的注册表包含构建期绝对路径；统一修正到当前作用域（幂等）。
for j in installed_plugins.json known_marketplaces.json; do
    f="$CLAUDE_CONFIG_DIR/plugins/$j"
    [ -f "$f" ] && sed -i \
        -e "s#${FACTORY_CLAUDE_DIR}#${CLAUDE_CONFIG_DIR}#g" \
        -e "s#/root/.claude#${CLAUDE_CONFIG_DIR}#g" \
        "$f" 2>/dev/null || true
done

export CLAUDE_CONFIG_DIR
export CODEX_CONFIG_DIR
export CODEX_HOME="$CODEX_CONFIG_DIR"
export CC_SWITCH_CONFIG_DIR

# cc-switch 与 CLI 配置目录确保可写。
ensure_writable "$CC_SWITCH_CONFIG_DIR"

# CLI 配置目录同理：确认实际可写。
ensure_writable "$CLAUDE_CONFIG_DIR"
ensure_writable "$CODEX_CONFIG_DIR"

# 确保 settings.json 存在且可解析
# 注意：settings.json 可能没有 env 字段（如镜像内置的 claude-settings.json），
# 这是正常的，不应该覆盖。只有在文件不存在或 JSON 格式错误时才需要修复。
SETTINGS_FILE="$CLAUDE_CONFIG_DIR/settings.json"
if [ ! -f "$SETTINGS_FILE" ]; then
    echo "📝 初始化 settings.json..."
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    printf '{\n  "env": {}\n}\n' > "$SETTINGS_FILE"
    chmod 644 "$SETTINGS_FILE"
elif ! python3 -c "import json; json.load(open('$SETTINGS_FILE'))" 2>/dev/null; then
    echo "⚠️  修复损坏的 settings.json（JSON 格式错误）..."
    printf '{\n  "env": {}\n}\n' > "$SETTINGS_FILE"
    chmod 644 "$SETTINGS_FILE"
fi

# Tighten sensitive dirs to 700 (owner-only), non-recursive, best-effort.
# If the underlying fs rejects chmod (bind/CIFS/NFS) but the dir remains writable,
# emit a security warning and continue — do NOT fail startup over a chmod.
# Also detects CIFS "fake success": chmod returns 0 but mode unchanged.
for _d in "$CC_SWITCH_CONFIG_DIR"; do
  if chmod 700 -- "$_d" 2>/dev/null; then
    # chmod reported success — verify it actually took effect (CIFS may silently ignore)
    if command -v stat >/dev/null 2>&1; then
      _mode=$(stat -c '%a' -- "$_d" 2>/dev/null || echo '')
      if [ -n "$_mode" ] && [ "$_mode" != "700" ]; then
        echo "⚠️  安全警告: chmod 700 '$_d' 报告成功但实际 mode=${_mode}（CIFS/绑定挂载可能静默忽略），目录仍可写，继续启动。" >&2
      fi
    fi
  else
    if _probe_writable "$_d"; then
      echo "⚠️  安全警告: 无法收紧 '$_d' 权限为 700（可能绑定挂载限制），目录仍可写，继续启动。" >&2
    fi
  fi
done

# 后续 exec 的 bash/CLI 会继承以上导出变量；不改写宿主工作区中的 /root/.bashrc。

# ==========================================
# 3. 环境变量与网络状态展示
#    env 块读 CLAUDE_CONFIG_DIR/settings.json（Claude CLI 原生文件）
# ==========================================
SETTINGS_FILE="$CLAUDE_CONFIG_DIR/settings.json"

if [ -f "$SETTINGS_FILE" ]; then
    MODEL=$(node -e "try{process.stdout.write(require('$SETTINGS_FILE').env?.ANTHROPIC_MODEL||'')}catch(e){}" 2>/dev/null)
    BASE_URL=$(node -e "try{process.stdout.write(require('$SETTINGS_FILE').env?.ANTHROPIC_BASE_URL||'')}catch(e){}" 2>/dev/null)
    AUTH=$(node -e "try{const e=require('$SETTINGS_FILE').env;process.stdout.write(e.ANTHROPIC_API_KEY||e.ANTHROPIC_AUTH_TOKEN?'yes':'no')}catch(e){process.stdout.write('no')}" 2>/dev/null)

    # 将 settings.json 的 env 块真正注入当前 shell，供 claude 进程继承。
    # 空值必须 unset，避免 ANTHROPIC_API_KEY="" 覆盖 ANTHROPIC_AUTH_TOKEN。
    env_inject "$SETTINGS_FILE"
else
    MODEL=""
    BASE_URL=""
    AUTH="no"
fi

# ==========================================
# 3.1. 启动 cc-switch 默认后台服务
#   使用 cc-switch 自带的 detach 模式，避免 shell 后台任务与 proxy enable
#   同时争抢 pidfile/socket。必须确认 daemon 可达并初始化 Codex provider
#   后再启用应用路由。
# ==========================================
CC_SWITCH_DAEMON_LOG="/tmp/cc-switch-daemon.log"
CC_SWITCH_CODEX_INIT_LOG="/tmp/cc-switch-codex-init.log"
CC_SWITCH_SKILLS_LOG="/tmp/cc-switch-skills-init.log"
if command -v cc-switch >/dev/null 2>&1; then
    CC_SWITCH_DAEMON_READY=0
    if cc-switch daemon start --detach >"$CC_SWITCH_DAEMON_LOG" 2>&1; then
        # Windows bind mount 上首次初始化 SQLite 可能较慢，最多等待 10 秒。
        for _attempt in $(seq 1 40); do
            _daemon_status="$(cc-switch daemon status 2>&1 || true)"
            case "$_daemon_status" in
                "cc-switch daemon"*)
                    CC_SWITCH_DAEMON_READY=1
                    break
                    ;;
            esac
            sleep 0.25
        done
    fi

    if [ "$CC_SWITCH_DAEMON_READY" = "1" ]; then
        echo "✅ cc-switch 后台服务已就绪（配置: $CC_SWITCH_CONFIG_DIR）"

        # 全新数据库会预置 codex-official，但不会自动选为当前 provider，
        # 此时直接启用 Codex 路由会被 cc-switch 拒绝。
        # 优先导入用户现有的 config.toml；仍无当前 provider 时才使用内置项。
        if ! cc-switch -a codex provider current >/dev/null 2>&1; then
            if [ -s "$CODEX_CONFIG_DIR/config.toml" ]; then
                cc-switch -a codex provider import-live \
                    >>"$CC_SWITCH_CODEX_INIT_LOG" 2>&1 || true
            fi
            if ! cc-switch -a codex provider current >/dev/null 2>&1; then
                if cc-switch -a codex provider switch codex-official \
                    >>"$CC_SWITCH_CODEX_INIT_LOG" 2>&1; then
                    echo "✅ cc-switch 已初始化 Codex provider: codex-official"
                else
                    echo "⚠️  cc-switch Codex provider 初始化失败；日志: $CC_SWITCH_CODEX_INIT_LOG" >&2
                fi
            fi
        fi

        # cc-switch 的 skills 路径以 HOME 为根：项目态同步到挂载的 /root，
        # 临时态同步到 /tmp/aisc-home，不污染宿主工作区。
        if [ "$SCOPE" = "global" ] || [ "$SCOPE" = "temp" ] || [ "$SCOPE" = "temporary" ]; then
            CC_SWITCH_SKILLS_HOME="$TEMP_HOME"
        else
            CC_SWITCH_SKILLS_HOME="/root/app"
        fi
        # 默认仅在首次安装、内置内容变化或已启用目标缺失时同步。
        # always 可强制同步，off 可完全跳过；现有启停状态由 cc-switch 管理。
        if CC_SWITCH_SKILLS_RESULT="$(
            HOME="$CC_SWITCH_SKILLS_HOME" python3 /usr/local/bin/lib/cc_switch_skills.py \
                --config-dir "$CC_SWITCH_CONFIG_DIR" \
                --skills-home "$CC_SWITCH_SKILLS_HOME" \
                --bundle-dir /opt/aisc/skills \
                --log "$CC_SWITCH_SKILLS_LOG" \
                --mode "${AISC_SKILLS_SYNC:-auto}"
        )"; then
            case "$CC_SWITCH_SKILLS_RESULT" in
                synced)
                    echo "✅ cc-switch 已安装 caveman、document-skills、grill-me、superpowers（Claude + Codex）"
                    ;;
                current)
                    echo "ℹ️  cc-switch 内置 skills 已是最新，跳过同步。"
                    ;;
                off)
                    echo "ℹ️  AISC_SKILLS_SYNC=off，已跳过 cc-switch 内置 skills 同步。"
                    ;;
                declined)
                    echo "ℹ️  文件锁不可用且宿主 Skills 已存在，已按默认选择保留现有内容并跳过同步。"
                    ;;
            esac
        else
            echo "⚠️  cc-switch skills 离线安装失败；日志: $CC_SWITCH_SKILLS_LOG" >&2
        fi

        cc-switch proxy -a claude enable >/dev/null 2>&1 || true
        if cc-switch -a codex provider current >/dev/null 2>&1; then
            cc-switch proxy -a codex enable >/dev/null 2>&1 || true
        else
            echo "⚠️  未找到可用的 Codex provider，已跳过 Codex 路由启用" >&2
        fi
    else
        echo "⚠️  cc-switch 后台服务启动失败；启动日志: $CC_SWITCH_DAEMON_LOG" >&2
        [ ! -s "$CC_SWITCH_DAEMON_LOG" ] || sed -n '1,20p' "$CC_SWITCH_DAEMON_LOG" >&2
        echo "    详细日志: $(cc-switch daemon logs 2>/dev/null || echo '/root/.local/state/cc-switch/cc-switchd.log')" >&2
    fi
fi

# ==========================================
# 3.5 容器内 Mihomo TUN 透明代理（若挂载了配置 /etc/mihomo/config.yaml）
#    - 宿主侧启动器仅下载/拷贝用户原始配置/订阅（ro 挂载），由 mihomo-build-config.js 处理：
#      读 ro 源 → 识别格式(yaml/base64订阅/URI直链/JSON) 非yaml自动转最小Clash配置
#      → 剥离已有 tun:/dns: 顶层块 → 追加规范 tun:（+ 缺失时补 dns:）→ 写可写副本
#      → mihomo -f 副本
#    - mihomo 建 TUN 设备 + auto-route iptables 需 CAP_NET_ADMIN → 以 root 后台启动
#      （容器需 --cap-add=NET_ADMIN --device /dev/net/tun）
#    - 启动后再 exec claude：TUN 已接管容器全部出站，API 请求经代理
# ==========================================
if [ -f /etc/mihomo/config.yaml ]; then
    echo "🚀 正在内建 TUN 透明代理网络..."
    MIHOMO_DATA_DIR="/tmp/aisc-mihomo"
    MIHOMO_CFG="$MIHOMO_DATA_DIR/config.yaml"
    mkdir -p "$MIHOMO_DATA_DIR"
    cp -n /opt/aisc/mihomo/* "$MIHOMO_DATA_DIR/" 2>/dev/null || true

    # 原始订阅 → mihomo 配置（格式自动转换 + TUN/DNS 强制注入）到可写副本。
    # 支持 yaml / base64 订阅 / URI 直链 / JSON(SIP008)；失败仅告警不阻断，便于进 bash 排障。
    if node /usr/local/bin/mihomo-build-config.js /etc/mihomo/config.yaml "$MIHOMO_CFG"; then
        # 后台启动 mihomo（root）
        bash -c "mihomo -d '$MIHOMO_DATA_DIR' -f '$MIHOMO_CFG' > '$MIHOMO_DATA_DIR/mihomo.log' 2>&1" &
        # 等待 TUN 接管路由 + url-test 初选节点（节点多时需几秒）
        sleep 4
        # 健康探测：经代理能否到达 api.anthropic.com（不带 -f：401/404 等任何 HTTP 响应都算可达，只看连接是否成功）
        if curl -sS --max-time 10 -o /dev/null https://api.anthropic.com 2>/dev/null; then
            echo "✅ Mihomo TUN 已就绪，代理连通: api.anthropic.com 可达"
        else
            # curl 失败：区分 mihomo 进程是否存活，给出更准确的排障提示
            if pgrep -f 'mihomo -d' >/dev/null 2>&1; then
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
        if command -v python3 >/dev/null 2>&1 && [ -d /opt/aisc/apps/ai-brief ]; then
            if [ -n "$BASE_URL" ] && [ "$AUTH" = "yes" ]; then
                echo "📰 AI 简讯后台抓取中（日志: /tmp/ai-brief.log，容器启动后 cat /tmp/ai-brief.log 查看）"
                (
                    python3 /opt/aisc/apps/ai-brief/brief.py --ai --top 5 \
                        > /tmp/ai-brief.log 2>&1
                    printf '--- DONE (%s) ---\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> /tmp/ai-brief.log
                ) &
            else
                echo "📰 简讯跳过（当前 cc-switch provider 未配置 API 凭据）"
            fi
        fi
        ;;
    foreground)
        # 阻塞同步模式（会延长启动时间，仅调试/手动触发用）
        if command -v python3 >/dev/null 2>&1 && [ -d /opt/aisc/apps/ai-brief ]; then
            if [ -n "$BASE_URL" ] && [ "$AUTH" = "yes" ]; then
                BRIEF_EXIT=0
                BRIEF="$(timeout 50 python3 /opt/aisc/apps/ai-brief/brief.py --ai --top 5 2>/tmp/ai-brief.log)" || BRIEF_EXIT=$?
                if [ -n "$BRIEF" ]; then
                    echo "📰 今日 AI 简讯："
                    echo "$BRIEF"
                    echo "----------------------------------------"
                elif [ "$BRIEF_EXIT" = "124" ]; then
                    echo "📰 简讯加载超时（50s），已跳过（容器内可手跑：python3 /opt/aisc/apps/ai-brief/brief.py）"
                    echo "----------------------------------------"
                else
                    echo "📰 简讯加载失败，已跳过（容器内可手跑：python3 /opt/aisc/apps/ai-brief/brief.py）"
                    echo "----------------------------------------"
                fi
            else
                echo "📰 简讯跳过（当前 cc-switch provider 未配置 API 凭据）"
            fi
        fi
        ;;
    *)
        # off / 空 / 任何其他值 — 默认不运行，静默零阻塞
        ;;
esac

# ==========================================
# 4. 智能引导：CLI 选择
# ==========================================
# 支持直接启动 codex
if [ "$1" = "codex" ]; then
    exec codex "$@"
fi

# ==========================================
# 5. 启动方式菜单：bash / claude / codex / cc-switch
#    仅在交互终端、且以默认 claude 启动时弹出
#    无 provider 配置时不拦截 —— CLI 使用各自官方默认端点
# ==========================================
if [ "$1" = "claude" ] && [ -t 0 ]; then
    if [ "$AUTH" = "no" ] && [ -z "$MODEL" ]; then
        echo "ℹ️  当前未配置自定义 provider，将使用 CLI 官方默认端点（可运行 cc-switch 配置）。"
    fi
    echo ""
    echo "请选择启动方式："
    echo "  1) bash   进入命令行（可手动配置后再启动 AI CLI，默认）"
    echo "  2) claude 直接启动 Claude Code"
    echo "  3) codex  直接启动 OpenAI Codex"
    echo "  4) cc-switch 打开 Provider、路由与 Skills 管理界面"
    echo ""
    read -r -p "输入 1、2、3 或 4 [默认 1]: " launch
    case "$launch" in
        2) ;;  # 继续往下启动 claude
        3) echo "▶️  启动 Codex..."; exec codex ;;
        4) echo "▶️  启动 cc-switch 管理界面..."; exec cc-switch ;;
        *) echo "▶️  进入 bash。"; exec bash ;;
    esac
fi

# ==========================================
# 6. 执行控制权移交 (极其关键)
# ==========================================
# 使用 exec 是 Docker 入口脚本的最佳实践！
# 它会让 claude 进程直接替换掉当前的 bash 进程成为 PID 1。
# 这样在终端里按下 Ctrl+C 才能被 Claude 正确捕获并打断任务，否则终端会卡死。
exec "$@"
