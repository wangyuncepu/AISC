# Super Claude

开箱即用的 [Claude Code](https://claude.ai/code) Docker 容器——预装精选技能库、全局配置，一键注入项目。挂载任意代码库即可获得全副武装的 Claude Code 会话。

## 容器包含

| 层级 | 内容 |
|------|------|
| **基础镜像** | `node:20-slim` + git + curl |
| **运行时** | 全局安装 Claude Code (`@anthropic-ai/claude-code`) |
| **默认后端** | 预配置 DeepSeek Anthropic 兼容 API（`ANTHROPIC_BASE_URL`、模型映射、effort 等全部设好） |
| **全局配置** | `claude.json`，已启用 `claude-hud` 和 `document-skills` 插件 |
| **技能库** | 20+ 技能预装至 `/root/.claude/skills/` |
| **项目模板** | `.claude/settings.local.json` + 本地 `caveman` 技能，首次挂载时自动注入 |

## 内置技能

### 核心工作流
- **gstack** — 无头浏览器，用于 QA 测试、网站体验验证、截图、部署检查
- **autoplan** — 全流程审查管线（CEO/工程/设计审查），自动触发
- **review** — 多维度代码审查，覆盖安全、性能、可维护性等视角
- **investigate** — 系统性 Bug 排查与根因追溯

### 开发
- **writing-plans** — 结构化实施方案编写，附带审查者提示词
- **subagent-driven-development** — 基于任务简报和审查包的并行子代理开发
- **test-driven-development** — TDD 工作流，含反模式检测
- **dispatching-parallel-agents** — 并行代理调度模式
- **verification-before-completion** — 提交前验证门禁

### 沟通
- **caveman** — 超压缩沟通模式（节省约 75% token 消耗）
- **brainstorming** — 结构化头脑风暴，含可视化输出

### 运维
- **using-git-worktrees** — 隔离工作树工作流
- **using-superpowers** — Claude Code、Copilot、Gemini 等 AI 工具参考指南
- **executing-plans** — 方案执行工作流
- **finishing-a-development-branch** — 分支收尾检查清单
- **receiving-code-review** — 处理收到的代码审查

### 写作
- **writing-skills** — 技能编写指南，含 Anthropic 最佳实践

## 快速开始

### 前置条件

- 已安装 [Docker](https://www.docker.com/)
- 拥有 [DeepSeek API Key](https://platform.deepseek.com/)（默认后端为 DeepSeek；也可使用 Anthropic 官方 API Key 并覆盖环境变量）

### 构建镜像

```bash
docker build -t super-claude .
```

### 运行容器

将你的项目挂载到 `/app`，并传入 DeepSeek API Key：

```bash
docker run -it --rm \
  -e ANTHROPIC_API_KEY="$DEEPSEEK_API_KEY" \
  -v "$(pwd):/app" \
  super-claude
```

也可以直接跟一句指令：

```bash
docker run -it --rm \
  -e ANTHROPIC_API_KEY="$DEEPSEEK_API_KEY" \
  -v "$(pwd):/app" \
  super-claude claude -p "审查这个代码库"
```

### 首次运行发生了什么

入口脚本会检查你挂载的项目下是否存在 `.claude/` 目录及 `settings.local.json`。如果没有，则自动从模板注入（插件配置 + 本地 caveman 技能），开箱即用。

之后再以同一个项目运行时，项目的 `.claude/` 保持不变——你的本地设置不会被覆盖。

## 配置

### 默认后端：DeepSeek

容器已预配置为使用 **DeepSeek** 的 Anthropic 兼容 API 端点，无需额外设置即可直接使用 DeepSeek 模型。

如需切换回 Anthropic 官方 API，覆盖以下环境变量即可：

```bash
docker run -it --rm \
  -e ANTHROPIC_BASE_URL="" \
  -e ANTHROPIC_MODEL="" \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v "$(pwd):/app" \
  super-claude
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ANTHROPIC_API_KEY` | （空） | API 密钥。使用 DeepSeek 时需填入 DeepSeek API Key |
| `ANTHROPIC_BASE_URL` | `https://api.deepseek.com/anthropic` | API 端点地址 |
| `ANTHROPIC_MODEL` | `deepseek-v4-pro[1m]` | 默认对话模型 |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | `deepseek-v4-pro[1m]` | Opus 级别模型映射 |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | `deepseek-v4-pro[1m]` | Sonnet 级别模型映射 |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `deepseek-v4-flash` | Haiku 级别模型映射 |
| `CLAUDE_CODE_SUBAGENT_MODEL` | `deepseek-v4-flash` | 子代理使用的模型 |
| `CLAUDE_CODE_EFFORT_LEVEL` | `max` | 推理努力程度（max / high / medium / low） |

### 自定义技能集

构建前编辑 `skills/` 目录，增删技能即可。每个技能是一个包含 `SKILL.md` 的目录。

从 GitHub 仓库添加技能：

```bash
claude mcp add <技能名> --source <github-url>
```

然后将生成的技能目录复制到 `skills/` 下。

### 覆盖默认命令

```bash
# 运行指定技能
docker run -it --rm -e ANTHROPIC_API_TOKEN="$ANTHROPIC_API_KEY" -v "$(pwd):/app" super-claude claude -p "/review"

# 进入容器的交互式 Shell
docker run -it --rm -e ANTHROPIC_API_TOKEN="$ANTHROPIC_API_KEY" -v "$(pwd):/app" super-claude bash
```

## 项目结构

```
.
├── Dockerfile                  # 容器定义
├── entrypoint.sh               # 入口脚本：自动向挂载项目注入 .claude/
├── skills/                     # 全局技能（安装至 /root/.claude/skills/）
│   ├── claude.json             # 全局 Claude Code 配置
│   ├── gstack-core.md          # gstack 浏览器/QA 技能
│   ├── caveman/                # 超压缩沟通模式
│   ├── review/                 # 多维度代码审查
│   ├── autoplan/               # 自动审查管线
│   ├── investigate/            # Bug 排查
│   ├── brainstorming/          # 可视化头脑风暴
│   ├── writing-plans/          # 结构化实施方案
│   ├── writing-skills/         # 技能编写指南
│   ├── subagent-driven-development/
│   ├── dispatching-parallel-agents/
│   ├── test-driven-development/
│   ├── systematic-debugging/
│   ├── using-git-worktrees/
│   ├── using-superpowers/
│   ├── verification-before-completion/
│   ├── executing-plans/
│   ├── finishing-a-development-branch/
│   ├── receiving-code-review/
│   └── requesting-code-review/
├── .claude/                    # 项目模板（注入至 /app/.claude/）
│   ├── settings.local.json     # 插件配置
│   └── skills/caveman/         # 项目级 caveman 技能
└── skills-lock.json            # 技能来源锁定文件
```

## 使用场景

- **CI/CD 代码审查** — 在流水线中对每个 PR 运行 `/review`
- **团队统一环境** — 所有成员使用相同的技能和配置
- **一次性任务** — `docker run --rm super-claude claude -p "排查 src/auth.ts 中的 Bug"`
- **离线/私有化部署** — 预构建镜像包含所有依赖，运行时无需网络
- **多仓库工作** — 挂载不同项目而不污染它们的 git 状态

## 许可证

MIT
