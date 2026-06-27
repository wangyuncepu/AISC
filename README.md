# Super Claude

开箱即用的 [Claude Code](https://claude.ai/code) Docker 容器——预装 20+ 技能库、**5 大模型后端**、`cs` 一键切换，**100% 纯终端 CLI**。

## 核心亮点

- 🔄 **5 大模型后端** — `cs cc` / `cs deepseek` / `cs ark` / `cs 1y` / `cs duo-cc`，一键切换
- 🔐 **Key 安全存储** — API Key 存于 `~/.claude/api-keys`（chmod 600），脚本不包含机密
- ⚡ **轻量离线** — 预装 Claude Code + 全套国内镜像源，导出 tar 后可在无外网环境部署
- 🧠 **20+ 预装技能** — 代码审查、Bug 排查、TDD、Karpathy 编码规范等

## 快速开始

### 前置条件

- 已安装 [Docker](https://www.docker.com/)
- 拥有至少一个后端的 API Key

### 方式一：导入预构建镜像

```bash
docker load -i super-claude-v1.tar
```

### 方式二：从源码构建

```bash
# 标准构建
docker build -t super-claude:v1 .

# 国内网络指定基础镜像源
docker build \
  --build-arg NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim \
  -t super-claude:v1 .
```

> 首次启动时运行 `cs <后端>` 配置 Key，之后自动记住无需重复输入。

### 启动

```bash
# 直接启动 Claude Code（首次需先运行 cs 配置后端）
docker run -it --rm -v "$(pwd):/app" super-claude:v1

# 先进入终端
docker run -it --rm -v "$(pwd):/app" super-claude:v1 bash

# 切换后端后自动启动 Claude Code
docker run -it --rm -v "$(pwd):/app" super-claude:v1 cs ark
```

Windows 用户也可双击 `一键启动_AI工作站.bat`。

### 启动流程

```
docker run ... super-claude:v1
        │
        ├── entrypoint.sh ──→ .claude/ 注入 + 权限修复 + 显示当前后端
        │                     （从 ~/.claude/settings.json 读取）
        │
        └── 默认执行 claude ──→ Claude Code 启动
                │
                └── 需要切换后端时：cs <cc|deepseek|ark|1y|duo-cc|show>
                        └── 修改 ~/.claude/settings.json 的 env 配置
                            └── SC_RESTART=1 时自动重启 Claude Code
```

---

## `cs` 模型切换

容器内 `cs` 与 `claude-switch` 指向同一脚本。Key 保存在 `~/.claude/api-keys`，后端配置写入 `~/.claude/settings.json`。

首次运行某后端时会提示输入 Key，之后自动记住。

```bash
cs show       # 查看当前后端
cs cc         # Anthropic 官方  →  claude-opus-4-8
cs deepseek   # DeepSeek 官方  →  deepseek-v4-pro[1m]
cs ark        # 火山 Ark       →  glm-5.2[1m]
cs 1y         # 1yuanapi       →  claude-sonnet-4-8[1m]
cs duo-cc     # duo-cc         →  claude-sonnet-4-8[1m]
```

### 平台详情

| 命令 | 平台 | 默认模型 | 端点 |
|------|------|----------|------|
| `cs cc` | Anthropic 官方 | `claude-opus-4-8` | 官方默认 |
| `cs deepseek` | DeepSeek | `deepseek-v4-pro[1m]` | `api.deepseek.com/anthropic` |
| `cs ark` | 火山 Ark | `glm-5.2[1m]` | `ark.cn-beijing.volces.com/api/coding` |
| `cs 1y` | 1yuanapi | `claude-sonnet-4-8[1m]` | `1yuanapi.com` |
| `cs duo-cc` | duo-cc | `claude-sonnet-4-8[1m]` | `api.duou.cc` |

> 💡 Key 保存后，通过 Docker 命令直接调用 `cs`（如 `docker run ... cs ark`），切换后会自动重启 Claude Code。

---

## 容器包含

| 层级 | 内容 |
|------|------|
| **基础镜像** | 默认 `node:20-slim`，可通过 `--build-arg NODE_IMAGE=...` 替换拉取源 |
| **网络优化** | 清华 apt 镜像 + 淘宝 NPM 镜像（免 VPN） |
| **运行时** | Claude Code 全局安装 |
| **默认后端** | 空配置启动，首次运行 `cs <后端>` 时输入 Key 即可 |
| **切换工具** | `cs` / `claude-switch` 模型后端切换器 |
| **鉴权机制** | Anthropic 官方用 `ANTHROPIC_API_KEY`，第三方平台用 `ANTHROPIC_AUTH_TOKEN` |
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

## 项目结构

```
.
├── Dockerfile
├── entrypoint.sh                       # 入口：技能注入 + 权限修复 + cs 直连
├── claude-switch                       # 切换脚本 → /usr/local/bin/cs、claude-switch
├── 一键启动_AI工作站.bat              # Windows 一键启动
├── README.md
├── devlog.md                           # 开发日志
├── skills/                             # 全局技能 → /root/.claude/skills/
│   ├── claude.json
│   ├── karpathy-flow/
│   └── ... (20+ 技能)
├── .claude/                            # 项目模板 → /app/.claude/
│   └── settings.local.json
└── todo/
    └── todo.md
```

## 使用场景

- **日常开发** — 挂载项目目录，获得全副武装的 AI 编程助手
- **CI/CD 审查** — `docker run ... claude -p "/review"` 在流水线中审查 PR
- **一次性任务** — `docker run --rm ... claude -p "排查 src/auth.ts 中的 Bug"`
- **离线部署** — 导出 tar 后 `docker load` 即可在无外网环境使用

## 构建与导出

```bash
# 构建
docker build \
  --build-arg NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim \
  -t super-claude:v1 .

# 导出
docker save -o super-claude-v1.tar super-claude:v1
docker save super-claude:v1 | gzip > super-claude-v1.tar.gz   # 压缩版

# 导入
docker load -i super-claude-v1.tar
gunzip -c super-claude-v1.tar.gz | docker load                # 解压导入
```

## 许可证

MIT
