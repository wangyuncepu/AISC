# 使用官方轻量级 Node 镜像；国内网络可通过 --build-arg NODE_IMAGE=... 替换拉取源
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

# ==========================================
# 1. 网络环境优化：按 USE_CN_MIRROR 决定 apt 源
# ==========================================
RUN if [ "$USE_CN_MIRROR" = "1" ]; then \
        sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list 2>/dev/null || true ; \
        echo "apt: 清华镜像" ; \
    else echo "apt: 官方源" ; fi

# 安装必要的系统工具：
#   git/curl/sudo/tmux — Claude Code 常用底层依赖
#   iptables/iproute2  — Mihomo TUN auto-route 操纵 iptables 与路由表所必需
#   ca-certificates    — mihomo/geodata 经 https 下载所需
RUN apt-get update && apt-get install -y git curl sudo tmux iptables iproute2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ==========================================
# 1b/1c. Mihomo + geodata —— 容器内建 TUN 透明代理核心
#   优先用构建上下文 downloads/ 里预放的本地文件（离线/网络差时，由 stage-mihomo.sh 下载）；
#   否则多镜像轮询下载（ghfast.top 实测稳）+ 强制 --http1.1（绕开 curl/GitHub CDN 的 HTTP/2 流异常）
#   + 短 connect-timeout 快失败 + 直连兜底。
#   放 root 阶段：mihomo → /usr/local/bin/mihomo（root:root 755），geodata → /home/AISC/.mihomo。
#   注意：mihomo 是 ELF 二进制，绝不能 sed 处理（同 claude-real 教训）。
# ==========================================
COPY downloads/ /tmp/dl/
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
    mkdir -p /home/AISC/.mihomo; \
    if [ -n "${GH_PROXY:-}" ]; then mirrors="${GH_PROXY}"; \
    elif [ "$USE_CN_MIRROR" = "1" ]; then mirrors="https://ghfast.top/ https://gh-proxy.com/ https://github.moeyy.xyz/ https://ghproxy.net/ https://mirror.ghproxy.com/"; \
    else mirrors=""; fi; \
    for f in geoip.metadb geosite.dat country.mmdb; do \
        if [ -f /tmp/dl/$f ]; then \
            echo "📦 使用本地预置 geodata: $f"; cp /tmp/dl/$f /home/AISC/.mihomo/$f; rm -f /tmp/dl/$f; \
        else \
            url="https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/$f"; \
            ok=0; \
            for m in $mirrors ""; do \
                u="${m}${url}"; \
                if curl -fSL --http1.1 --retry 2 --retry-delay 1 --retry-all-errors \
                        --connect-timeout 8 --max-time 120 "$u" -o "/home/AISC/.mihomo/$f"; then ok=1; break; fi; \
            done; \
            [ "$ok" = "1" ] || echo "⚠️  geodata $f 下载失败（mihomo 仍可启动，GEO 规则可能受限）"; \
        fi; \
    done; \
    rm -rf /tmp/dl

# ==========================================
# 创建非 root 运行用户 AISC（uid 1000）
#   原因：Claude Code 在 root 下拒绝 --dangerously-skip-permissions 模式。
#   全程以 AISC 身份构建与运行，家目录 /home/AISC 承载 .claude 与项目挂载 app/。
# ==========================================
RUN useradd -m -s /bin/bash AISC \
    && echo 'AISC:AISC' | chpasswd \
    && echo 'AISC ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/aisc \
    && chmod 440 /etc/sudoers.d/aisc

# ==========================================
# 容器内 UTF-8 locale：解决 ls / 中文文件名八进制转义乱码 (no.5)
# debian-slim/glibc 内置 C.UTF-8，无需 locale-gen
# ==========================================
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# 替换 NPM 源（按 USE_CN_MIRROR）并全局安装 Claude Code
# --no-cache + 版本校验：防止镜像源返回损坏 tarball 导致装出的二进制 segfault
RUN if [ "$USE_CN_MIRROR" = "1" ]; then \
        npm config set registry https://registry.npmmirror.com/ ; echo "npm: 淘宝镜像" ; \
    else echo "npm: 官方源" ; fi \
    && npm install -g --no-cache @anthropic-ai/claude-code \
    && claude --version

# ==========================================
# 全局 Claude CLI 目录：/home/AISC/.claude（CLI 原生完整目录）
#   - 让 Claude CLI 自己生成原生结构（projects/todos/statsig/plugins/shell-snapshots…）
#   - 再叠加我们的全局 skills + CLAUDE.md + claude.json
#   - 项目模式整目录拷贝到 /home/AISC/app/.claude（不改名）
#   - cs 运行配置（settings.json + api-keys）独立存放在 /home/AISC/app/.cc-config，不混进 .claude
# ==========================================
# 跳过首次启动联网 onboarding（绕过 api.anthropic.com 检查）。
# 新版 CLI 核心状态在 .claude.json（非 config.json）；缺失会报
# "Claude configuration file not found"。先写入完整 onboarding 状态，
# 再跑一次 CLI 让它补全 machineID / userID / migrationVersion 等运行字段。
RUN mkdir -p /home/AISC/.claude \
    && echo '{'                                           >  /home/AISC/.claude/.claude.json \
    && echo '  "hasCompletedOnboarding": true,'           >> /home/AISC/.claude/.claude.json \
    && echo '  "acceptedTos": true,'                      >> /home/AISC/.claude/.claude.json \
    && echo '  "autoUpdates": false,'                     >> /home/AISC/.claude/.claude.json \
    && echo '  "installMethod": "npm",'                   >> /home/AISC/.claude/.claude.json \
    && echo '  "firstStartTime": "2025-01-01T00:00:00Z"'  >> /home/AISC/.claude/.claude.json \
    && echo '}'                                           >> /home/AISC/.claude/.claude.json \
    && echo '{ "hasCompletedOnboarding": true }'          >  /home/AISC/.claude/config.json

# 触发 CLI 初始化：补全 .claude.json 运行字段并生成原生目录（projects/sessions/backups…）
RUN CLAUDE_CONFIG_DIR=/home/AISC/.claude claude -p "init" >/dev/null 2>&1 || true \
    && CLAUDE_CONFIG_DIR=/home/AISC/.claude claude --version >/dev/null 2>&1 || true

# 创建技能目录与项目挂载点
RUN mkdir -p /home/AISC/.claude/skills /home/AISC/app

# 1. 注入全局 CLAUDE.md
COPY global-claude.md /home/AISC/.claude/CLAUDE.md

# 2. 注入插件机制技能套件（离线可用）：
#    caveman（默认激活）/ claude-hud / document-skills / superpowers / skill-creator
#    由 stage-skills.sh 预暂存到 _bundle/plugins（含 cache + marketplaces + 注册表）
COPY _bundle/plugins/ /home/AISC/.claude/plugins/

# 3. 注入扁平技能（来源 _bundle/skills）：gstack（仅文档，6 子技能）
COPY _bundle/skills/ /home/AISC/.claude/skills/

# 3c. 解引用 .claude 内所有符号链接 → 真文件
#     Windows 绑定挂载(grpcfuse)不支持创建 symlink，cp -r 会失败导致项目复制残缺。
#     在镜像内把 symlink 替换为内容，使 cp -r 在任何宿主上都成功。
RUN find /home/AISC/.claude -type l | while read -r l; do \
        t="$(readlink -f "$l")"; \
        if [ -e "$t" ]; then cp -f --remove-destination "$t" "$l"; fi; \
    done

# 3b. gstack 6 个技能的斜杠命令（/plan-ceo-review 等，包装对应 skill）
COPY commands/ /home/AISC/.claude/commands/

# 5. CLI settings.json：启用 5 个插件 + marketplace 来源 + claude-hud 状态栏(statusLine)
#    statusLine 用 node 跑 claude-hud 的 dist/index.js（容器无 bun）
COPY claude-settings.json /home/AISC/.claude/settings.json

# 6. skill-creator 在 host 未预装，从本地 marketplace 离线安装（写入 installed_plugins.json）
RUN CLAUDE_CONFIG_DIR=/home/AISC/.claude claude plugin install skill-creator@claude-plugins-official 2>&1 | tail -1 || true

# 7. 默认 settings.local.json 放入 CLI 原生目录（随 .claude 一并复制到项目）
RUN echo '{ "enableAllProjectMcpServers": true }' > /home/AISC/.claude/settings.local.json

# 8. 出厂版本戳（内容哈希）：项目模式据此检测镜像是否更新，提示 cs upgrade
#    仅哈希出厂内容（skills/plugins/commands/CLAUDE.md/settings*），排除 .claude.json
#    （含每次构建随机的 machineID，会无谓变动）
RUN find /home/AISC/.claude/skills /home/AISC/.claude/plugins /home/AISC/.claude/commands \
        /home/AISC/.claude/CLAUDE.md /home/AISC/.claude/settings.json /home/AISC/.claude/settings.local.json \
        -type f 2>/dev/null | sort | xargs sha1sum 2>/dev/null | sha1sum | cut -d' ' -f1 \
        > /home/AISC/.claude/.factory-version \
    && echo "factory-version: $(cat /home/AISC/.claude/.factory-version)"

# 拷贝并赋予 entrypoint 脚本执行权限
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Mihomo 配置构建器：原始订阅 → mihomo 配置（格式自动转换 yaml/base64订阅/URI直链/JSON
#   + 强制注入 TUN/DNS）。entrypoint 调用，Node 运行，无外部依赖。
COPY mihomo-build-config.js /usr/local/bin/mihomo-build-config.js

# 注入模型切换 CLI 工具：使用根目录脚本作为 cs/claude-switch
COPY claude-switch /usr/local/bin/cs
RUN chmod +x /usr/local/bin/cs \
    && ln -sf /usr/local/bin/cs /usr/local/bin/claude-switch

# cs 运行配置（settings.json + api-keys）存于 .cc-config，独立于 CLI 的 .claude。
# 不在此预建 —— cs 首次运行时按 CLAUDE_CONFIG_DIR 同级的 .cc-config 目录自动创建。

# Claude 包装器：每次启动前从 settings.json 注入 env，并默认追加
# --dangerously-skip-permissions（跳过权限确认，容器内自动流；root 下 Claude
# 拒绝此 flag，故 USER AISC 是前提）。用户手动传入则不重复追加。
RUN mv /usr/local/bin/claude /usr/local/bin/claude-real
COPY claude-wrapper /usr/local/bin/claude
RUN chmod +x /usr/local/bin/claude

# 防御：若构建上下文来自 Windows（CRLF），脚本 shebang 会变成 "#!/bin/bash\r"，
# 导致 "cannot execute: required file not found"。统一剥离 CR，确保镜像内脚本可执行。
# 注意：只处理文本脚本，绝不能 sed claude-real —— 那是 244MB 原生 ELF 二进制，
# sed -i 会破坏其结构导致运行时 segfault。
RUN sed -i 's/\r$//' \
        /usr/local/bin/entrypoint.sh \
        /usr/local/bin/cs \
        /usr/local/bin/claude \
        /usr/local/bin/mihomo-build-config.js 2>/dev/null || true

# 设置工作目录，后续用户的代码将挂载到这里
WORKDIR /home/AISC/app

# 全部 /home/AISC 内容交还 AISC 用户（构建期以 root 写入，运行期以 AISC 运行）
RUN chown -R AISC:AISC /home/AISC

# 以非 root 用户运行：root 下 Claude Code 拒绝 --dangerously-skip-permissions
USER AISC

# git 全局配置：core.autocrlf=input
#   commit 时 CRLF→LF（仓库永远干净 LF），checkout 不转（保持仓库原样）。
#   跨平台(Win 宿主 + Linux 容器)场景避免 CRLF 噪音进历史；.gitattributes 优先于此。
RUN git config --global core.autocrlf input

# 设置入口点
ENTRYPOINT ["entrypoint.sh"]

# 默认执行指令
CMD ["claude"]