# 使用官方轻量级 Node 镜像；国内网络可通过 --build-arg NODE_IMAGE=... 替换拉取源
ARG NODE_IMAGE=node:20-slim
FROM ${NODE_IMAGE}

# ==========================================
# 1. 网络环境优化：注入国内镜像源 (告别 VPN 依赖)
# ==========================================
# 替换 Debian 软件源为清华镜像（防止 apt-get 卡死）
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list || true

# 安装必要的系统工具 (git 和 curl 是 Claude Code 常用的底层依赖)
RUN apt-get update && apt-get install -y git curl sudo tmux \
    && rm -rf /var/lib/apt/lists/*

# ==========================================
# 容器内 UTF-8 locale：解决 ls / 中文文件名八进制转义乱码 (no.5)
# debian-slim/glibc 内置 C.UTF-8，无需 locale-gen
# ==========================================
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# 替换 NPM 源为淘宝镜像，并全局安装 Claude Code
# --no-cache + 版本校验：防止镜像源返回损坏 tarball 导致装出的二进制 segfault
RUN npm config set registry https://registry.npmmirror.com/ \
    && npm install -g --no-cache @anthropic-ai/claude-code \
    && claude --version

# ==========================================
# 全局 Claude CLI 目录：/root/.claude（CLI 原生完整目录）
#   - 让 Claude CLI 自己生成原生结构（projects/todos/statsig/plugins/shell-snapshots…）
#   - 再叠加我们的全局 skills + CLAUDE.md + claude.json
#   - 项目模式整目录拷贝到 /app/.claude（不改名）
#   - cs 运行配置（settings.json + api-keys）独立存放在 /app/.cc-config，不混进 .claude
# ==========================================
# 跳过首次启动联网 onboarding（绕过 api.anthropic.com 检查）。
# 新版 CLI 核心状态在 .claude.json（非 config.json）；缺失会报
# "Claude configuration file not found"。先写入完整 onboarding 状态，
# 再跑一次 CLI 让它补全 machineID / userID / migrationVersion 等运行字段。
RUN mkdir -p /root/.claude \
    && echo '{'                                           >  /root/.claude/.claude.json \
    && echo '  "hasCompletedOnboarding": true,'           >> /root/.claude/.claude.json \
    && echo '  "acceptedTos": true,'                      >> /root/.claude/.claude.json \
    && echo '  "autoUpdates": false,'                     >> /root/.claude/.claude.json \
    && echo '  "installMethod": "npm",'                   >> /root/.claude/.claude.json \
    && echo '  "firstStartTime": "2025-01-01T00:00:00Z"'  >> /root/.claude/.claude.json \
    && echo '}'                                           >> /root/.claude/.claude.json \
    && echo '{ "hasCompletedOnboarding": true }'          >  /root/.claude/config.json

# 触发 CLI 初始化：补全 .claude.json 运行字段并生成原生目录（projects/sessions/backups…）
RUN CLAUDE_CONFIG_DIR=/root/.claude claude -p "init" >/dev/null 2>&1 || true \
    && CLAUDE_CONFIG_DIR=/root/.claude claude --version >/dev/null 2>&1 || true

# 创建技能目录
RUN mkdir -p /root/.claude/skills /app

# 1. 注入全局 CLAUDE.md
COPY global-claude.md /root/.claude/CLAUDE.md

# 2. 注入插件机制技能套件（离线可用）：
#    caveman（默认激活）/ claude-hud / document-skills / superpowers / skill-creator
#    由 stage-skills.sh 预暂存到 _bundle/plugins（含 cache + marketplaces + 注册表）
COPY _bundle/plugins/ /root/.claude/plugins/

# 3. 注入扁平技能（来源 _bundle/skills）：gstack（仅文档，6 子技能）
COPY _bundle/skills/ /root/.claude/skills/

# 3b. gstack 6 个技能的斜杠命令（/plan-ceo-review 等，包装对应 skill）
COPY commands/ /root/.claude/commands/

# 5. CLI settings.json：启用 5 个插件 + marketplace 来源 + claude-hud 状态栏(statusLine)
#    statusLine 用 node 跑 claude-hud 的 dist/index.js（容器无 bun）
COPY claude-settings.json /root/.claude/settings.json

# 6. skill-creator 在 host 未预装，从本地 marketplace 离线安装（写入 installed_plugins.json）
RUN CLAUDE_CONFIG_DIR=/root/.claude claude plugin install skill-creator@claude-plugins-official 2>&1 | tail -1 || true

# 7. 默认 settings.local.json 放入 CLI 原生目录（随 .claude 一并复制到项目）
RUN echo '{ "enableAllProjectMcpServers": true }' > /root/.claude/settings.local.json

# 拷贝并赋予 entrypoint 脚本执行权限
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 注入模型切换 CLI 工具：使用根目录脚本作为 cs/claude-switch
COPY claude-switch /usr/local/bin/cs
RUN chmod +x /usr/local/bin/cs \
    && ln -sf /usr/local/bin/cs /usr/local/bin/claude-switch

# cs 运行配置（settings.json + api-keys）存于 .cc-config，独立于 CLI 的 .claude。
# 不在此预建 —— cs 首次运行时按 CLAUDE_CONFIG_DIR 同级的 .cc-config 目录自动创建。

# Claude 包装器：每次启动前从 settings.json 注入 env
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
        /usr/local/bin/claude 2>/dev/null || true

# 设置工作目录，后续用户的代码将挂载到这里
WORKDIR /app

# 设置入口点
ENTRYPOINT ["entrypoint.sh"]

# 默认执行指令
CMD ["claude"]