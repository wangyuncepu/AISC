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
- Windows 推荐使用 **Windows Terminal / Warp / Termius**，不推荐传统 CMD（中文与 emoji 可能乱码）

### 方式一：导入预构建镜像

```bash
docker load -i super-claude-v1.1.3.tar
```

### 方式二：从源码构建

```bash
# 标准构建
docker build -t super-claude:latest .

# 国内网络指定基础镜像源
docker build \
  --build-arg NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim \
  -t super-claude:latest .
```

> 首次启动时运行 `cs <后端>` 配置 Key，之后自动记住无需重复输入。

### Windows 使用

#### 一键启动

双击：

```text
一键启动_AI工作站.bat
```

#### 手动启动（PowerShell / Windows Terminal）

```powershell
docker run -it --rm -v "${PWD}:/app" super-claude:latest
```

#### CMD

```bat
docker run -it --rm -v "%cd%:/app" super-claude:latest
```

> CMD 即使执行了 `chcp 65001`，也可能因为字体或 emoji 渲染出现乱码。推荐 Windows Terminal。

### Linux 使用

#### 一键启动

```bash
chmod +x ./启动_AI工作站.sh
./启动_AI工作站.sh
```

#### 手动启动

```bash
docker run -it --rm -v "$(pwd):/app" super-claude:latest
```

### macOS 使用

#### 一键启动

```bash
chmod +x ./启动_AI工作站.command ./启动_AI工作站.sh
./启动_AI工作站.command
```

也可以在 Finder 中双击 `启动_AI工作站.command`。

#### 手动启动

```bash
docker run -it --rm -v "$(pwd):/app" super-claude:latest
```

### 启动模式

| 模式 | 命令 | 说明 |
|------|------|------|
| 交互式 Claude Code | `docker run -it --rm -v "$(pwd):/app" super-claude:latest` | 默认模式，进入 Claude Code |
| 容器 Bash | `docker run -it --rm -v "$(pwd):/app" super-claude:latest bash` | 调试、手动运行 `cs`、查看配置 |
| 切换后端并启动 | `docker run -it --rm -v "$(pwd):/app" super-claude:latest cs ark` | 写入 Ark 配置后自动进入 Claude Code |
| 单次运行 | `docker run -it --rm -v "$(pwd):/app" super-claude:latest claude -p "解释这个项目的架构"` | 执行一次任务后退出 |

### 单次运行示例

```bash
# 解释当前项目
docker run -it --rm -v "$(pwd):/app" super-claude:latest claude -p "解释这个项目的架构"

# 代码审查
docker run -it --rm -v "$(pwd):/app" super-claude:latest claude -p "阅读 README.md 并指出可以改进的地方"

# 先切换后端，再执行单次任务
docker run -it --rm -v "$(pwd):/app" super-claude:latest bash -lc "cs deepseek && claude -p '总结这个仓库的用途'"
```

### 容器残留清理

正常退出 Claude Code 或 Bash 时，`--rm` 会自动删除容器。若直接关闭 Terminal，容器可能残留。

#### Linux / macOS / Git Bash

```bash
docker ps -a --filter "ancestor=super-claude:latest"
docker rm -f $(docker ps -aq --filter "ancestor=super-claude:latest")
```

#### Windows PowerShell

```powershell
docker ps -a --filter "ancestor=super-claude:latest"
docker ps -aq --filter "ancestor=super-claude:latest" | ForEach-Object { docker rm -f $_ }
```

### 启动流程

```
docker run -it --rm -v "$(pwd):/app" super-claude:latest
        │
        ├── entrypoint.sh ──→ .claude/ 注入 + 权限修复 + 读取当前后端
        │                     （优先读取 /app/.claude/settings.json）
        │
        ├── 已配置后端 ──→ 注入 env → claude-wrapper → claude-real
        │
        └── 未配置后端 ──→ 提示运行 cs <后端> → 进入 bash
                │
                └── bash 内运行 cs ark / cs deepseek
                        └── 写入 /app/.claude/settings.json 和 /app/.claude/api-keys
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
| **全局配置** | `claude.json`（claude-hud + document-skills 插件）+ `CLAUDE.md`（默认 karpathy-flow + Caveman） |
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
├── global-claude.md                    # 镜像内全局 CLAUDE.md 模板
├── 一键启动_AI工作站.bat              # Windows 一键启动
├── 启动_AI工作站.sh                  # Linux 一键启动
├── 启动_AI工作站.command             # macOS 一键启动
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


## 许可证

MIT
