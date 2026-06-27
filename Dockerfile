# 使用官方轻量级 Node 镜像
FROM node:20-slim

# ==========================================
# 1. 网络环境优化：注入国内镜像源 (告别 VPN 依赖)
# ==========================================
# 替换 Debian 软件源为清华镜像（防止 apt-get 卡死）
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list || true

# 安装必要的系统工具 (git 和 curl 是 Claude Code 常用的底层依赖)
RUN apt-get update && apt-get install -y git curl sudo tmux \
    && rm -rf /var/lib/apt/lists/*

# 替换 NPM 源为淘宝镜像，并全局安装 Claude Code
RUN npm config set registry https://registry.npmmirror.com/ \
    && npm install -g @anthropic-ai/claude-code

# ==========================================
# 跳过 Claude Code 首次启动的联网验证（解决国内无 VPN 报错）
# ==========================================
# Claude Code 启动时会强制连接 api.anthropic.com 做 onboarding 检查
# 这个检查无视 ANTHROPIC_BASE_URL。手动写 config.json 告诉它"已完成引导"
RUN mkdir -p /root/.claude \
    && echo '{'                                           >  /root/.claude/config.json \
    && echo '  "hasCompletedOnboarding": true,'           >> /root/.claude/config.json \
    && echo '  "acceptedTos": true,'                      >> /root/.claude/config.json \
    && echo '  "autoUpdates": false,'                     >> /root/.claude/config.json \
    && echo '  "installMethod": "npm",'                   >> /root/.claude/config.json \
    && echo '  "firstStartTime": "2025-01-01T00:00:00Z"'  >> /root/.claude/config.json \
    && echo '}'                                           >> /root/.claude/config.json


# ==========================================
# 🚀 注入 DeepSeek 专属环境变量 (公开安全配置)
# ==========================================
ENV ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
ENV ANTHROPIC_MODEL="deepseek-v4-pro[1m]"
ENV ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro[1m]"
ENV ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-pro[1m]"
ENV ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-flash"
ENV CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-flash"
ENV CLAUDE_CODE_EFFORT_LEVEL="max"


# 创建全局配置与技能目录
RUN mkdir -p /root/.claude/skills

# 1. 注入全局系统配置 (你提取的 claude.json)
COPY skills/claude.json /root/.claude/claude.json

# 2. 注入全局技能库 (gstack, superpowers, review 等)
COPY skills/ /root/.claude/skills/
# 因为你的 claude.json 放在 skills 目录里一起拷进去了，我们在 skills 目录下将其删掉保持整洁
RUN rm -f /root/.claude/skills/claude.json

# 3. 准备局部项目模板 — 不再依赖宿主机的 .claude/ 目录
#    直接在镜像内生成默认 settings.local.json，彻底告别 COPY 报错
RUN mkdir -p /template/.claude /app \
    && echo '{ "enableAllProjectMcpServers": true }' > /template/.claude/settings.local.json

# 拷贝并赋予 entrypoint 脚本执行权限
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 注入模型切换 CLI 工具
COPY claude-switch /usr/local/bin/claude-switch
RUN chmod +x /usr/local/bin/claude-switch

# ==========================================
# Claude 包装器：无 Key 时自动引导到 claude-switch
# ==========================================
# 将原版 claude 重命名为 claude-real，用包装脚本替换
# 检查两种鉴权方式：ANTHROPIC_API_KEY（Anthropic 官方）或 ANTHROPIC_AUTH_TOKEN（第三方）
RUN mv /usr/local/bin/claude /usr/local/bin/claude-real
RUN echo '#!/bin/bash'                    >  /usr/local/bin/claude \
 && echo 'if [ -z "$ANTHROPIC_API_KEY" ] && [ -z "$ANTHROPIC_AUTH_TOKEN" ]; then' >> /usr/local/bin/claude \
 && echo '    echo "⚠️  尚未配置 API Key，自动启动模型后端切换器..."' >> /usr/local/bin/claude \
 && echo '    exec claude-switch "$@"'    >> /usr/local/bin/claude \
 && echo 'else'                           >> /usr/local/bin/claude \
 && echo '    exec claude-real "$@"'      >> /usr/local/bin/claude \
 && echo 'fi'                             >> /usr/local/bin/claude \
 && chmod +x /usr/local/bin/claude

# 设置工作目录，后续用户的代码将挂载到这里
WORKDIR /app

# 设置入口点
ENTRYPOINT ["entrypoint.sh"]

# 默认执行指令
CMD ["claude"]