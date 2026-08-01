# Version pins: see config/versions.env for all dependency versions
# Override via: docker build --build-arg MIHOMO_VERSION=v1.20.0 ...
# NODE_IMAGE_DIGEST is documented in config/versions.env but not consumed by FROM:
# pin the digest in NODE_IMAGE itself, e.g. node:20-slim@sha256:...

# 使用官方轻量级 Node 镜像；国内网络可通过 --build-arg NODE_IMAGE=... 替换拉取源
# USE_CN_MIRROR=1 时自动使用国内镜像加速（docker.1ms.run）
ARG USE_CN_MIRROR=1
ARG NODE_IMAGE=node:20-slim
FROM ${NODE_IMAGE}

# 是否使用国内镜像源（apt 清华 / npm 淘宝）。1=用（默认），0=用官方源。
# 启动脚本会按交互选择传入 --build-arg USE_CN_MIRROR=0/1
ARG USE_CN_MIRROR=1

# ==========================================
# 容器内建 Mihomo (Clash Meta) TUN 透明代理核心
#   - MIHOMO_VERSION: pin 版本（可 --build-arg 覆盖）；asset = mihomo-linux-<arch>-<ver>.gz
#   - GH_PROXY: GitHub release 加速前缀。留空=直连；USE_CN_MIRROR=1 时自动用 ghproxy（可显式覆盖）
# ==========================================
ARG MIHOMO_VERSION=v1.19.27
ARG GH_PROXY=

# cc-switch-cli 版本（Claude/Codex provider 与 skills 的统一管理工具）
ARG CC_SWITCH_VERSION=v5.9.0

# Claude Code npm 版本（@anthropic-ai/claude-code）
ARG CLAUDE_CODE_VERSION=latest  # TODO: pin to specific version

# Codex CLI npm 版本（@openai/codex）
ARG CODEX_VERSION=latest  # TODO: pin to specific version

# Geodata 发布版本（MetaCubeX/meta-rules-dat release tag）
ARG GEODATA_VERSION=latest  # TODO: pin to dated release tag

# ==========================================
# 1. 网络环境优化：按 USE_CN_MIRROR 决定 apt 源
# ==========================================
RUN if [ "$USE_CN_MIRROR" = "1" ]; then \
        sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list 2>/dev/null || true ; \
        echo "apt: 清华镜像" ; \
    else echo "apt: 官方源" ; fi

# 安装必要的系统工具：
#   git/curl/tmux      — Claude Code 常用底层依赖
#   iptables/iproute2  — Mihomo TUN auto-route 操纵 iptables 与路由表所必需
#   ca-certificates    — mihomo/geodata 经 https 下载所需
RUN apt-get update && apt-get install -y git curl tmux iptables iproute2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ==========================================
# 运行身份
#   容器始终以 root 运行，规避 Windows → WSL2 → Docker bind mount 中文件
#   显示为 root:root 时的读写错误。IS_SANDBOX 告知 AI CLI 当前处于隔离容器。
# ==========================================
ENV IS_SANDBOX=1
USER root

# ==========================================
# 1b/1c. Mihomo + geodata —— 容器内建 TUN 透明代理核心
#   优先用构建上下文 downloads/ 里预放的本地文件（离线/网络差时，由 stage-mihomo.sh 下载）；
#   否则多镜像轮询下载（ghfast.top 实测稳）+ 强制 --http1.1（绕开 curl/GitHub CDN 的 HTTP/2 流异常）
#   + 短 connect-timeout 快失败 + 直连兜底。
#   mihomo → /usr/local/bin/mihomo（root:root 755），geodata → /opt/aisc/mihomo。
#   注意：mihomo 是 ELF 二进制，绝不能 sed 处理（同 claude-real 教训）。
# ==========================================
COPY container/downloads/ /tmp/dl/
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in amd64) mih_arch=amd64;; arm64|aarch64) mih_arch=arm64;; *) mih_arch=amd64;; esac; \
    # 1) 优先本地预置
    if ls /tmp/dl/mihomo-linux-${mih_arch}-*.gz >/dev/null 2>&1; then \
        echo "📦 使用本地预置 mihomo: $(ls /tmp/dl/mihomo-linux-${mih_arch}-*.gz)"; \
        cp /tmp/dl/mihomo-linux-${mih_arch}-*.gz /tmp/mihomo.gz; \
        rm -f /tmp/dl/mihomo-linux-${mih_arch}-*.gz; \
    else \
        base="https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/mihomo-linux-${mih_arch}-${MIHOMO_VERSION}.gz"; \
        if [ -n "${GH_PROXY:-}" ]; then mirrors="${GH_PROXY}"; \
        elif [ "$USE_CN_MIRROR" = "1" ]; then mirrors="https://ghfast.top/ https://gh-proxy.com/ https://github.moeyy.xyz/ https://ghproxy.net/ https://mirror.ghproxy.com/"; \
        else mirrors=""; fi; \
        ok=0; \
        for m in $mirrors ""; do \
            u="${m}${base}"; echo "⬇️  mihomo try: $u"; \
            if curl -fSL --http1.1 --retry 2 --retry-delay 1 --retry-all-errors \
                    --connect-timeout 8 --max-time 120 "$u" -o /tmp/mihomo.gz; then ok=1; break; fi; \
        done; \
        [ "$ok" = "1" ] || { echo "❌ mihomo 下载失败（可运行 bash stage-mihomo.sh 预下载到 downloads/ 后重建，或 --build-arg GH_PROXY=<镜像前缀>）"; exit 1; }; \
    fi; \
    gunzip -f /tmp/mihomo.gz; \
    mv /tmp/mihomo /usr/local/bin/mihomo; \
    chmod +x /usr/local/bin/mihomo; \
    /usr/local/bin/mihomo -v

RUN set -eux; \
    mkdir -p /opt/aisc/mihomo; \
    if [ -n "${GH_PROXY:-}" ]; then mirrors="${GH_PROXY}"; \
    elif [ "$USE_CN_MIRROR" = "1" ]; then mirrors="https://ghfast.top/ https://gh-proxy.com/ https://github.moeyy.xyz/ https://ghproxy.net/ https://mirror.ghproxy.com/"; \
    else mirrors=""; fi; \
    for f in geoip.metadb geosite.dat country.mmdb; do \
        if [ -f /tmp/dl/$f ]; then \
            echo "📦 使用本地预置 geodata: $f"; cp /tmp/dl/$f /opt/aisc/mihomo/$f; rm -f /tmp/dl/$f; \
        else \
            url="https://github.com/MetaCubeX/meta-rules-dat/releases/download/${GEODATA_VERSION}/$f"; \
            ok=0; \
            for m in $mirrors ""; do \
                u="${m}${url}"; \
                if curl -fSL --http1.1 --retry 2 --retry-delay 1 --retry-all-errors \
                        --connect-timeout 8 --max-time 120 "$u" -o "/opt/aisc/mihomo/$f"; then ok=1; break; fi; \
            done; \
            [ "$ok" = "1" ] || echo "⚠️  geodata $f 下载失败（mihomo 仍可启动，GEO 规则可能受限）"; \
        fi; \
    done; \
    rm -rf /tmp/dl

# ==========================================
# 容器内 UTF-8 locale：解决 ls / 中文文件名八进制转义乱码 (no.5)
# debian-slim/glibc 内置 C.UTF-8，无需 locale-gen
# ==========================================
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# 替换 NPM 源（按 USE_CN_MIRROR）并全局安装 Claude Code 和 Codex CLI
# --no-cache + 版本校验：防止镜像源返回损坏 tarball 导致装出的二进制 segfault
RUN if [ "$USE_CN_MIRROR" = "1" ]; then \
        npm config set registry https://registry.npmmirror.com/ ; echo "npm: 淘宝镜像" ; \
    else echo "npm: 官方源" ; fi \
    && npm install -g --no-cache @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && npm install -g --no-cache @openai/codex@${CODEX_VERSION} \
    && claude --version \
    && codex --version

# ==========================================
# Claude/Codex 出厂目录：/opt/aisc/factory（不会被 /root bind mount 遮蔽）
#   - 让 Claude CLI 自己生成原生结构（projects/todos/statsig/plugins/shell-snapshots…）
#   - 再叠加我们的全局 skills + CLAUDE.md + claude.json
#   - 项目模式整目录拷贝到 /root/app/.claude（宿主工作区）
# ==========================================
# 跳过首次启动联网 onboarding（绕过 api.anthropic.com 检查）。
# 新版 CLI 核心状态在 .claude.json（非 config.json）；缺失会报
# "Claude configuration file not found"。先写入完整 onboarding 状态，
# 再跑一次 CLI 让它补全 machineID / userID / migrationVersion 等运行字段。
RUN mkdir -p /opt/aisc/factory/.claude \
    && echo '{'                                           >  /opt/aisc/factory/.claude/.claude.json \
    && echo '  "hasCompletedOnboarding": true,'           >> /opt/aisc/factory/.claude/.claude.json \
    && echo '  "acceptedTos": true,'                      >> /opt/aisc/factory/.claude/.claude.json \
    && echo '  "autoUpdates": false,'                     >> /opt/aisc/factory/.claude/.claude.json \
    && echo '  "installMethod": "npm",'                   >> /opt/aisc/factory/.claude/.claude.json \
    && echo '  "firstStartTime": "2025-01-01T00:00:00Z"'  >> /opt/aisc/factory/.claude/.claude.json \
    && echo '}'                                           >> /opt/aisc/factory/.claude/.claude.json \
    && echo '{ "hasCompletedOnboarding": true }'          >  /opt/aisc/factory/.claude/config.json

# 触发 CLI 初始化：补全 .claude.json 运行字段并生成原生目录（projects/sessions/backups…）
RUN CLAUDE_CONFIG_DIR=/opt/aisc/factory/.claude claude -p "init" >/dev/null 2>&1 || true \
    && CLAUDE_CONFIG_DIR=/opt/aisc/factory/.claude claude --version >/dev/null 2>&1 || true

# 初始化 Codex 全局出厂目录。codex --version 不会生成 CODEX_HOME，
# 因此显式创建可复制的原生目录骨架与合法空配置。
RUN mkdir -p /opt/aisc/factory/.codex/skills \
             /opt/aisc/factory/.codex/rules \
             /opt/aisc/factory/.codex/sessions \
             /opt/aisc/factory/.codex/shell_snapshots \
             /opt/aisc/factory/.codex/tmp \
    && : > /opt/aisc/factory/.codex/config.toml

# 创建技能目录与项目挂载点
RUN mkdir -p /opt/aisc/factory/.claude/skills

# 1. 注入全局 CLAUDE.md
COPY container/global-claude.md /opt/aisc/factory/.claude/CLAUDE.md

# 2. 注入插件机制技能套件（离线可用）：
#    caveman（默认激活）/ claude-hud / document-skills / superpowers / skill-creator
#    由 stage-skills.sh 预暂存到 _bundle/plugins（含 cache + marketplaces + 注册表）
COPY container/_bundle/plugins/ /opt/aisc/factory/.claude/plugins/

# 2b. entrypoint 会把插件 bundle 中的构建期绝对路径改为当前运行作用域。

# 3. 注入扁平技能（来源 _bundle/skills）：gstack（仅文档，6 子技能）
COPY container/_bundle/skills/ /opt/aisc/factory/.claude/skills/

# Codex 使用同一套 SKILL.md 格式；预置到镜像的完整 .codex，项目模式整目录复制。
COPY container/_bundle/skills/ /opt/aisc/factory/.codex/skills/
COPY container/global-claude.md /opt/aisc/factory/.codex/AGENTS.md
RUN sed -i -e 's/Super Claude/Super Codex/' \
           -e 's/Claude Code/Codex/g' /opt/aisc/factory/.codex/AGENTS.md \
    && find /opt/aisc/factory/.codex/skills /opt/aisc/factory/.codex/AGENTS.md /opt/aisc/factory/.codex/config.toml \
        -type f 2>/dev/null | sort | xargs sha1sum 2>/dev/null | sha1sum | cut -d' ' -f1 \
        > /opt/aisc/factory/.codex/.factory-version

# 3c. 解引用 .claude 内所有符号链接 → 真文件
#     Windows 绑定挂载(grpcfuse)不支持创建 symlink，cp -r 会失败导致项目复制残缺。
#     在镜像内把 symlink 替换为内容，使 cp -r 在任何宿主上都成功。
RUN find /opt/aisc/factory/.claude -type l | while read -r l; do \
        t="$(readlink -f "$l")"; \
        if [ -e "$t" ]; then cp -f --remove-destination "$t" "$l"; fi; \
    done

# 3b. gstack 6 个技能的斜杠命令（/plan-ceo-review 等，包装对应 skill）
COPY container/commands/ /opt/aisc/factory/.claude/commands/

# 5. CLI settings.json：启用 5 个插件 + marketplace 来源 + claude-hud 状态栏(statusLine)
#    statusLine 用 node 跑 claude-hud 的 dist/index.js（容器无 bun）
COPY container/claude-settings.json /opt/aisc/factory/.claude/settings.json

# 6. skill-creator 在 host 未预装，从本地 marketplace 离线安装（写入 installed_plugins.json）
RUN CLAUDE_CONFIG_DIR=/opt/aisc/factory/.claude claude plugin install skill-creator@claude-plugins-official 2>&1 | tail -1 || true

# 7. 默认 settings.local.json 放入 CLI 原生目录（随 .claude 一并复制到项目）
RUN echo '{ "enableAllProjectMcpServers": true }' > /opt/aisc/factory/.claude/settings.local.json

# 8. 出厂版本戳（内容哈希）：项目模式据此检测镜像是否更新
#    仅哈希出厂内容（skills/plugins/commands/CLAUDE.md/settings*），排除 .claude.json
#    （含每次构建随机的 machineID，会无谓变动）
RUN find /opt/aisc/factory/.claude/skills /opt/aisc/factory/.claude/plugins /opt/aisc/factory/.claude/commands \
        /opt/aisc/factory/.claude/CLAUDE.md /opt/aisc/factory/.claude/settings.json /opt/aisc/factory/.claude/settings.local.json \
        -type f 2>/dev/null | sort | xargs sha1sum 2>/dev/null | sha1sum | cut -d' ' -f1 \
        > /opt/aisc/factory/.claude/.factory-version \
    && echo "factory-version: $(cat /opt/aisc/factory/.claude/.factory-version)"

# 共享库脚本（entrypoint / claude-wrapper 复用 env 注入与路径/权限逻辑）
COPY container/lib/ /usr/local/bin/lib/
RUN chmod +x /usr/local/bin/lib/*.sh

# 拷贝并赋予 entrypoint 脚本执行权限
COPY container/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Mihomo 配置构建器：原始订阅 → mihomo 配置（格式自动转换 yaml/base64订阅/URI直链/JSON
#   + 强制注入 TUN/DNS）。entrypoint 调用，Node 运行，无外部依赖。
COPY container/mihomo-build-config.js /usr/local/bin/mihomo-build-config.js

# Claude 包装器：每次启动前从 settings.json 注入 env，并默认追加
# --dangerously-skip-permissions（跳过权限确认，容器内自动流）。
# IS_SANDBOX=1 标记当前 root 进程运行在隔离容器内。
RUN mv /usr/local/bin/claude /usr/local/bin/claude-real
COPY container/claude-wrapper /usr/local/bin/claude
RUN chmod +x /usr/local/bin/claude

# Codex 包装器：类似 Claude，从配置注入环境变量
RUN mv /usr/local/bin/codex /usr/local/bin/codex-real
COPY container/codex-wrapper /usr/local/bin/codex
RUN chmod +x /usr/local/bin/codex

# 防御：若构建上下文来自 Windows（CRLF），脚本 shebang 会变成 "#!/bin/bash\r"，
# 导致 "cannot execute: required file not found"。统一剥离 CR，确保镜像内脚本可执行。
# 注意：只处理文本脚本，绝不能 sed claude-real/codex-real —— 那些是原生 ELF 二进制，
# sed -i 会破坏其结构导致运行时 segfault。
RUN sed -i 's/\r$//' \
        /usr/local/bin/entrypoint.sh \
        /usr/local/bin/claude \
        /usr/local/bin/codex \
        /usr/local/bin/mihomo-build-config.js \
        /usr/local/bin/lib/env-inject.sh \
        /usr/local/bin/lib/writable.sh \
        /usr/local/bin/cc-switch 2>/dev/null || true

# ==========================================
# Python 运行时：python3 + pip + venv + python-is-python3
#   Claude Code 可直接用 python/pip。放靠后，避免使前面 npm/claude 重型层缓存失效。
#   Debian 12 PEP 668 限制系统 pip install → 建默认 venv并挂 PATH 头。
# ==========================================
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv python-is-python3 \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录；宿主工作区挂载到 /root/app。
WORKDIR /root/app

# git 系统配置：core.autocrlf=input（/root 会被宿主工作区挂载覆盖）
#   commit 时 CRLF→LF（仓库永远干净 LF），checkout 不转（保持仓库原样）。
#   跨平台(Win 宿主 + Linux 容器)场景避免 CRLF 噪音进历史；.gitattributes 优先于此。
RUN git config --system core.autocrlf input

# 默认 Python venv（root 可写，pip install 不受 PEP 668 限制）
#   python/pip → venv（PATH 优先）；pip install 直达，无需 --break-system-packages。
#   venv 在镜像内（--rm 容器每次重启重置为出厂；如需持久化包，加 requirements.txt + 启动安装）。
RUN python3 -m venv /opt/aisc/venv \
    && /opt/aisc/venv/bin/python -m pip install --upgrade pip --quiet
ENV PATH="/opt/aisc/venv/bin:${PATH}"

# ==========================================
# cc-switch-cli（Rust 二进制）：Claude/Codex provider 与 skills 的唯一管理工具
#   以 root 写入 /usr/local/bin。
#   复用 mihomo 的 GH_PROXY 多镜像 fallback；musl 静态版兼容 glibc/musl。
# ==========================================
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in amd64) cs_arch=x64;; arm64|aarch64) cs_arch=arm64;; *) cs_arch=x64;; esac; \
    base="https://github.com/saladday/cc-switch-cli/releases/download/${CC_SWITCH_VERSION}/cc-switch-cli-linux-${cs_arch}-musl.tar.gz"; \
    if [ -n "${GH_PROXY:-}" ]; then mirrors="${GH_PROXY}"; \
    elif [ "$USE_CN_MIRROR" = "1" ]; then mirrors="https://ghfast.top/ https://gh-proxy.com/ https://github.moeyy.xyz/ https://ghproxy.net/"; \
    else mirrors=""; fi; \
    ok=0; \
    for m in $mirrors ""; do \
        u="${m}${base}"; echo "⬇️  cc-switch try: $u"; \
        if curl -fSL --http1.1 --retry 2 --retry-delay 1 --retry-all-errors \
                --connect-timeout 8 --max-time 120 "$u" -o /tmp/ccs.tar.gz; then ok=1; break; fi; \
    done; \
    [ "$ok" = "1" ] || { echo "❌ cc-switch 下载失败（可 --build-arg GH_PROXY=<镜像前缀> 重试）"; exit 1; }; \
    tar -xzf /tmp/ccs.tar.gz -C /tmp; \
    mv /tmp/cc-switch /usr/local/bin/cc-switch-real; \
    chmod +x /usr/local/bin/cc-switch-real; \
    rm -f /tmp/ccs.tar.gz; \
    /usr/local/bin/cc-switch-real --version

COPY container/cc-switch-wrapper /usr/local/bin/cc-switch
RUN sed -i 's/\r$//' /usr/local/bin/cc-switch \
    && chmod +x /usr/local/bin/cc-switch

COPY container/cc_switch_skills.py /usr/local/bin/lib/cc_switch_skills.py
COPY container/lib/cc_switch_preset_providers.py /usr/local/bin/lib/cc_switch_preset_providers.py

# cc-switch 离线 skills：元技能说明 + 已暂存插件中的实际 skill 内容。
COPY container/cc-switch-skills/ /opt/aisc/skills/
RUN set -eux; \
    caveman_src="$(find /opt/aisc/factory/.claude/plugins/cache/caveman -type d -path '*/skills/caveman' | head -1)"; \
    document_src="$(find /opt/aisc/factory/.claude/plugins/cache/anthropic-agent-skills/document-skills -mindepth 1 -maxdepth 1 -type d | head -1)"; \
    superpowers_src="$(find /opt/aisc/factory/.claude/plugins/cache/claude-plugins-official/superpowers -mindepth 1 -maxdepth 1 -type d | head -1)"; \
    test -f "$caveman_src/SKILL.md"; \
    test -d "$document_src/skills"; \
    test -d "$superpowers_src/skills"; \
    mkdir -p /opt/aisc/skills/caveman /opt/aisc/skills/document-skills/skills /opt/aisc/skills/superpowers/skills; \
    cp -a "$caveman_src/." /opt/aisc/skills/caveman/; \
    cp -a "$document_src/skills/." /opt/aisc/skills/document-skills/skills/; \
    cp -a "$superpowers_src/skills/." /opt/aisc/skills/superpowers/skills/; \
    (cd /opt/aisc/skills && \
        find . -type f -print0 | sort -z | xargs -0 sha256sum | \
        sha256sum | awk '{print $1}') > /tmp/aisc-skills.sha256; \
    mv /tmp/aisc-skills.sha256 /opt/aisc/skills/.aisc-bundle.sha256
# 设置入口点
ENTRYPOINT ["entrypoint.sh"]

# 默认执行指令
CMD ["claude"]
