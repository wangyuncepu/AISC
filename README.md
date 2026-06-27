# Super Claude

开箱即用的 [Claude Code](https://claude.ai/code) Docker 容器——预装精选技能库、**5 大模型后端**、密钥持久化，**100% 纯终端 CLI**。挂载任意代码库即可获得全副武装的 Claude Code 会话。

## 核心亮点

- 🔄 **5 大模型后端** — Anthropic 官方 / DeepSeek / 硅基流动 / OpenRouter / 智谱 Z.AI，15+ 模型可选
- 🔑 **密钥持久化** — API Key 保存至 `.claude_keys`（chmod 600），容器重启不丢失
- 🛡️ **自动引导** — 未配置 Key 时无论怎么启动都自动进 `claude-switch`，杜绝裸奔报错
- 🧠 **20+ 预装技能** — 代码审查、Bug 排查、TDD、Karpathy 编码规范等开箱即用

## 快速开始

### 前置条件

- 已安装 [Docker](https://www.docker.com/)
- 拥有至少一个后端的 API Key

### 三步启动

```bash
# 1. 构建
docker build -t super-claude:v1 .

# 2. 启动（二选一）
docker run -it --rm -v "$(pwd):/app" super-claude:v1          # 直接启动，自动进菜单
docker run -it --rm -v "$(pwd):/app" super-claude:v1 bash     # 先进入终端，手动操作

# 3. 选后端 + 配 Key → 自动进入 Claude
```

Windows 用户可直接双击 `一键启动_AI工作站.bat`。

> 💡 `claude` 命令已被包装：无论从 CMD 启动还是 bash 内手动敲，**只要没有 API Key 就会自动弹出菜单引导配置**。配置过的 Key 缓存到 `.claude_keys`，下次自动加载。

### 首次启动全流程

```
docker run ... super-claude:v1
        │
        ├── entrypoint.sh ──→ .claude/ 注入 + 权限修复 + 环境展示
        │
        ├── claude 包装器检测到无 API Key
        │       └──→ claude-switch 菜单
        │               ├── 选平台 (1-5)
        │               ├── 选模型（硅基流动/OpenRouter/智谱 支持子菜单）
        │               ├── 首次输入 Key → 持久化到 .claude_keys
        │               └── exec claude ← 进入对话
        │
        └── 下次启动：Key 已缓存，选完后端直接进 Claude
```

---

## claude-switch 平台与模型

### 主菜单

```
╔══════════════════════════════════════════╗
║      🔄 Claude 模型后端切换器           ║
╠══════════════════════════════════════════╣
║  1) Anthropic 官方                      ║
║     模型: claude-opus-4-8              ║
║                                          ║
║  2) DeepSeek 官方                       ║
║     模型: deepseek-v4-pro[1m]           ║
║                                          ║
║  3) 硅基流动 · 国产模型                 ║
║  4) OpenRouter · 全球路由               ║
║  5) 智谱 Z.AI · GLM 系列               ║
╚══════════════════════════════════════════╝
```

### 平台详情

| # | 平台 | 默认模型 | 端点 | 鉴权方式 | 子菜单 |
|---|------|----------|------|----------|--------|
| 1 | Anthropic 官方 | `claude-opus-4-8` | 官方默认 | `API_KEY` | — |
| 2 | DeepSeek 官方 | `deepseek-v4-pro[1m]` | `api.deepseek.com/anthropic` | `AUTH_TOKEN` | — |
| 3 | 硅基流动 | `Pro/deepseek-ai/DeepSeek-V4-Pro` | `api.siliconflow.cn/v1/anthropic` | `AUTH_TOKEN` | 5 款模型 |
| 4 | OpenRouter | `anthropic/claude-opus-4-8` | `openrouter.ai/api` | `AUTH_TOKEN` | 6 款模型 |
| 5 | 智谱 Z.AI | `glm-4.6` | `api.z.ai/api/anthropic` | `AUTH_TOKEN` | 3 款模型 |

### 子菜单模型

| 平台 | 可选模型 |
|------|----------|
| **硅基流动** | DeepSeek-V4-Pro ⭐ / GLM-5.2 / Nex-N2-Pro / MiniMax M3 / Qwen3.6-35B |
| **OpenRouter** | Claude Opus 4.8 ⭐ / Claude Sonnet 4.6 / DeepSeek V3.2 / GLM-5.2 / Qwen3 Coder Plus / Kimi K2.7 Code |
| **智谱 Z.AI** | GLM-4.6 ⭐ / GLM-4.5 / GLM-4.5-Air |

### 密钥管理

每个平台的 API Key **独立存储**，互不干扰。切换后端无需重新输入 Key。

```bash
grep -o '^[^=]*' /app/.claude_keys   # 查看已保存的平台
vim /app/.claude_keys                 # 手动编辑
```

---

## 容器包含

| 层级 | 内容 |
|------|------|
| **基础镜像** | `node:20-slim` + git + curl + sudo + tmux |
| **网络优化** | 清华 apt 镜像 + 淘宝 NPM 镜像（免 VPN） |
| **运行时** | Claude Code 全局安装 + `claude` 包装器（自动引导） |
| **CLI 工具** | `claude-switch` 模型后端切换器 + `claude` 包装器自动引导 |
| **鉴权机制** | Anthropic 官方用 `ANTHROPIC_API_KEY`，第三方平台用 `ANTHROPIC_AUTH_TOKEN`（避免 key 验证失败） |
| **全局配置** | `claude.json`（claude-hud + document-skills 插件） |
| **技能库** | 20+ 技能预装至 `/root/.claude/skills/` |
| **项目模板** | `settings.local.json`，首次挂载自动注入 |

## 内置技能

### 核心工作流
- **gstack** — 无头浏览器，QA 测试、网站验证、截图、部署检查
- **autoplan** — 全流程审查管线（CEO/工程/设计审查）
- **review** — 多维度代码审查（安全、性能、可维护性等）
- **investigate** — 系统性 Bug 排查与根因追溯

### 开发
- **karpathy-flow** — Andrej Karpathy 编码规范：先想后写、极简实现、精准修改、目标驱动
- **writing-plans** — 结构化实施方案 + 审查者提示词
- **subagent-driven-development** — 并行子代理开发
- **test-driven-development** — TDD 工作流 + 反模式检测
- **dispatching-parallel-agents** — 并行代理调度
- **verification-before-completion** — 提交前验证门禁

### 沟通
- **caveman** — 超压缩沟通模式（节省约 75% token）
- **brainstorming** — 结构化头脑风暴 + 可视化

### 运维
- **using-git-worktrees** — 隔离工作树
- **using-superpowers** — AI 工具参考指南
- **executing-plans** — 方案执行工作流
- **finishing-a-development-branch** — 分支收尾检查清单
- **receiving-code-review** — 处理代码审查

### 写作
- **writing-skills** — 技能编写指南 + Anthropic 最佳实践

---

## 环境变量

由 `claude-switch` 自动设置，也可手动覆盖：

| 变量 | 说明 |
|------|------|
| `ANTHROPIC_API_KEY` | Anthropic 官方 API 密钥（平台 1） |
| `ANTHROPIC_AUTH_TOKEN` | 第三方平台 API 密钥（平台 2-5） |
| `ANTHROPIC_BASE_URL` | API 端点 |
| `ANTHROPIC_MODEL` | 对话模型 |
| `CLAUDE_CODE_EFFORT_LEVEL` | 推理努力程度，默认 `max` |

> 💡 第三方平台必须用 `ANTHROPIC_AUTH_TOKEN` 传 Key，同时保持 `ANTHROPIC_API_KEY=""`。否则 Claude Code 会拿第三方 Key 去 Anthropic 官方验证，直接报错。

CI/CD 场景直接传 Key 跳过菜单：

```bash
# Anthropic 官方
docker run -it --rm \
  -e ANTHROPIC_API_KEY="sk-ant-xxx" \
  -v "$(pwd):/app" \
  super-claude:v1

# DeepSeek / 硅基流动 / OpenRouter / 智谱
docker run -it --rm \
  -e ANTHROPIC_AUTH_TOKEN="sk-xxx" \
  -e ANTHROPIC_API_KEY="" \
  -e ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic" \
  -v "$(pwd):/app" \
  super-claude:v1
```

---

## 项目结构

```
.
├── Dockerfile
├── entrypoint.sh                       # 入口：注入 .claude/ + 权限修复 + 自动引导
├── claude-switch                       # 模型后端切换器（5 平台 15+ 模型）
├── 一键启动_AI工作站.bat              # Windows 一键启动
├── devlog.md                           # 开发日志
├── README.md
├── skills/                             # 全局技能 → /root/.claude/skills/
│   ├── claude.json
│   ├── karpathy-flow/
│   └── ... (20+ 技能)
├── .claude/                            # 项目模板 → /app/.claude/
│   └── settings.local.json
├── .claude_keys                        # Key 持久化（chmod 600，运行时生成）
└── todo/
    └── todo.md
```

## 使用场景

- **日常开发** — 挂载项目目录，获得全副武装的 AI 编程助手
- **CI/CD 审查** — `docker run ... claude -p "/review"` 在流水线中审查 PR
- **一次性任务** — `docker run --rm ... claude -p "排查 src/auth.ts 中的 Bug"`
- **离线部署** — 预构建镜像包含全部依赖，运行时无需网络
- **多仓库切换** — 挂载不同项目，`.claude_keys` 随宿主机持久化

## 许可证

MIT
