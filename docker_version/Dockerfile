# 使用轻量级的 Node.js 20 镜像作为基础环境
FROM node:20-slim

# 安装运行过程中可能需要的底层依赖 (如 git, curl 等)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 全局安装最新版的 Claude Code
RUN npm install -g @anthropic-ai/claude-code


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

# 3. 准备局部项目模板 (包含 settings.local.json 和局部的 caveman)
RUN mkdir -p /template/.claude
COPY .claude/ /template/.claude/

# 拷贝并赋予 entrypoint 脚本执行权限
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 设置工作目录，后续用户的代码将挂载到这里
WORKDIR /app

# 设置入口点
ENTRYPOINT ["entrypoint.sh"]

# 默认执行指令
CMD ["claude"]