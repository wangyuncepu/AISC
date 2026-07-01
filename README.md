# Super Claude · v1.2.2

开箱即用的 [Claude Code](https://claude.ai/code) Docker 工作站 —— 插件化技能套件、**5 大模型后端一键切换**、**临时/项目双作用域**、**自包含离线构建**，100% 纯终端 CLI。

## 核心亮点

- 🔌 **插件化技能** — caveman（默认激活）/ claude-hud（状态栏 HUD）/ document-skills / superpowers / skill-creator + gstack，全部离线内置
- 🔄 **5 大模型后端** — `cs cc / deepseek / ark / 1y / duo-cc` 一键切换，**实时生效**
- 🧪 **临时 / 项目 双作用域** — 临时模式即用即弃，项目模式配置持久且隔离
- 🔐 **密钥隔离** — API Key 存于 `.cc-config/api-keys`（chmod 600），与 CLI 配置 `.claude` 分离，永不入 git
- 📦 **自包含构建** — 仓库内置 `_bundle`，`docker build` 不依赖宿主机 `~/.claude`、可离线
- ⬆️ **一键升级** — 镜像更新后 `cs upgrade` 合并出厂配置，保留你的后端选择与历史
- 🚀 **智能启动器** — 自动检测/构建镜像、防悬空镜像、可选缓存与国内镜像源、多开互不干扰
- ⚡ **默认跳过权限确认** — Claude 以 `--dangerously-skip-permissions` 启动，容器内自动流无需逐条确认
- 🛡️ **容器配置加固** — AISC 用户带密码 + 免密 sudo；entrypoint 自愈 `.cc-config` 所有权；git 全局 `autocrlf=input` 杜绝 CRLF 噪音
- 🔧 **构建稳健性** — 启动器 build 失败即退出、Dockerfile 缺失检查，不再假报成功

## 快速开始

### 前置

- 已安装 [Docker](https://www.docker.com/)（Windows 建议 Docker Desktop）
- Windows 推荐 **Windows Terminal**（cmd 旧窗口可能乱码且 HUD 不渲染）

### 一键启动（推荐）

| 平台 | 文件 |
|------|------|
| Windows | 双击 `一键启动_AI工作站.bat` |
| Linux | `./启动_AI工作站.sh` |
| macOS | 双击 `启动_AI工作站.command` |

启动器会：
1. 检测镜像是否存在 —— 不存在则**自动构建**（构建前询问：是否用缓存 / 是否用国内镜像源）
2. 镜像已存在 → 三选一：`[1]` 直接运行 `[2]` 删旧重建（防悬空 `<none>`）`[3]` 用新镜像名构建
3. 运行容器（交互菜单选作用域 + 启动方式）

### 手动构建 / 运行

#### 构建

```bash
# 默认构建（自包含，仓库已含 _bundle；国内镜像源默认开）
docker build -t super-claude:latest .

# 海外网络 —— 显式关闭国内镜像（apt / npm 走官方源）
docker build --build-arg USE_CN_MIRROR=0 -t super-claude:latest .

# 国内网络 + 基础镜像也走 daocloud（绕开 docker.io 拉取超时）
docker build \
  --build-arg NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim \
  -t super-claude:latest .

# 完全从头构建（禁用缓存）
docker build --no-cache -t super-claude:latest .
```

> **⚠️ `USE_CN_MIRROR` 默认 = `1`（国内源）**：apt → 清华、npm → 淘宝。海外用户需显式传 `--build-arg USE_CN_MIRROR=0` 走官方源。
>
> 仓库内置 `_bundle`（插件/技能，约 24M），构建不依赖宿主机 `~/.claude`。若需从你本机重新生成插件包，运行 `bash stage-skills.sh` 后再 build（一次性，普通用户无需）。

#### 运行

```bash
# Linux / macOS
docker run -it --rm -e TERM=xterm-256color -v "$(pwd):/home/AISC/app" super-claude:latest

# Windows PowerShell
docker run -it --rm -e TERM=xterm-256color -v "${PWD}:/home/AISC/app" super-claude:latest

# Windows CMD
docker run -it --rm -e TERM=xterm-256color -v "%cd%:/home/AISC/app" super-claude:latest
```

> **`TERM=xterm-256color` 必须设置**：Windows 下容器 TERM 常缺失，Claude Code 会判定终端不支持而隐藏 claude-hud（状态栏 HUD）。

#### 常用变体

```bash
# 跳过交互菜单，直接进入 claude（项目模式，持久化配置）
docker run -it --rm -e TERM=xterm-256color -e CLAUDE_SCOPE=project \
  -v "$(pwd):/home/AISC/app" super-claude:latest

# 临时模式（配置不持久，容器退出即重置）
docker run -it --rm -e TERM=xterm-256color -e CLAUDE_SCOPE=temp \
  -v "$(pwd):/home/AISC/app" super-claude:latest

# 直接进 bash（不启动 claude，可手动 cs 配置后再启动）
docker run -it --rm -e TERM=xterm-256color -v "$(pwd):/home/AISC/app" super-claude:latest bash

# 启动后一键切换后端（跳过菜单，cs 切换后自动重启 claude）
docker run -it --rm -e TERM=xterm-256color -v "$(pwd):/home/AISC/app" super-claude:latest cs deepseek

# 指定容器名（多开时加后缀区分，避免残留；--rm 正常退出自动清理）
docker run -it --rm --name sc-myproject -e TERM=xterm-256color \
  -v "$(pwd):/home/AISC/app" super-claude:latest
```

> 环境变量 `CLAUDE_SCOPE=project|temp` 可跳过交互作用域菜单，适合脚本/管道等非交互场景。

## 作用域：临时 vs 项目

启动时（交互终端）会询问：

```
请选择 Claude (.claude) 作用域：
  1) 临时 temporary — 使用镜像内置 .claude，容器退出即重置、改动不保留
  2) 项目 project   — 当前项目独立 .claude，持久到宿主机，从镜像完整复制
```

| | 临时 temporary | 项目 project（默认）|
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `/home/AISC/.claude`（镜像内置）| `/home/AISC/app/.claude`（挂载卷）|
| 持久化 | 容器退出即重置 | 持久到宿主机，跨 run 保留 |
| 适用 | 快速试用、一次性任务 | 长期项目、独立配置/历史 |
| 首次行为 | 直接用镜像 | 从镜像完整复制到 `/home/AISC/app/.claude` |

- 非交互（脚本/管道）默认 **项目**；可用环境变量 `CLAUDE_SCOPE=temp|project` 跳过菜单。
- 两模式的 `cs` 后端配置都写 `.cc-config`（恒在项目内），与 `.claude` 分离。

## `cs` 模型切换

容器内 `cs`（= `claude-switch`）。Key 存 `.cc-config/api-keys`，后端 env 写入 `.claude/settings.json`（Claude Code 原生读取 → **实时生效**，`!cs ds` 当场切换）。

```bash
cs show       # 查看当前后端与已存 Key
cs cc         # Anthropic 官方（可留空，清空所有配置走默认）
cs deepseek   # DeepSeek         → deepseek-v4-pro[1m]
cs ark        # 火山 Ark         → glm-5.2[1m]
cs 1y         # 1yuanapi         → claude-sonnet-4-8[1m]
cs duo-cc     # duo-cc           → claude-sonnet-4-8[1m]
cs upgrade    # 合并镜像出厂 .claude 到当前项目（保留后端配置/历史）
```

| 命令 | 平台 | 默认模型 | 端点 |
|------|------|----------|------|
| `cs cc` | Anthropic 官方 | （默认/留空）| 官方默认 |
| `cs deepseek` | DeepSeek | `deepseek-v4-pro[1m]` | `api.deepseek.com/anthropic` |
| `cs ark` | 火山 Ark | `glm-5.2[1m]` | `ark.cn-beijing.volces.com/api/coding` |
| `cs 1y` | 1yuanapi | `claude-sonnet-4-8[1m]` | `1yuanapi.com` |
| `cs duo-cc` | duo-cc | `claude-sonnet-4-8[1m]` | `api.duou.cc` |

> Key 首次输入后保存，之后自动记住。可 `docker run ... cs ark` 直接切换并重启 Claude。

## 内置技能（插件机制）

| 插件 | 作用 | 调用 |
|------|------|------|
| **caveman** | 超压缩沟通模式（**默认激活**，省约 75% token）| SessionStart 自动 + `/caveman` |
| **claude-hud** | 终端底部状态栏 HUD（模型/上下文/git/工具…）| statusLine 自动 |
| **superpowers** | 14 个工作流技能（TDD/调试/计划/审查…）| Skill 自动 |
| **document-skills** | 文档处理：docx / pdf / pptx / xlsx | Skill 自动 |
| **skill-creator** | 创建/优化/评测技能 | Skill 自动 |
| **gstack** | 计划评审 6 子技能 + 斜杠命令 | 见下 |

### gstack 斜杠命令

```
/plan-ceo-review     CEO 视角计划评审
/plan-eng-review     工程经理视角
/plan-design-review  设计视角（各维度 0-10 评分）
/plan-devex-review   开发者体验视角
/autoplan            自动流水线（CEO+设计+工程+DX 串跑）
/office-hours        YC Office Hours 拷问
```

## 升级流程

```
改 Dockerfile / 技能 → docker build（.factory-version 自动变）
        ↓
docker run（项目模式）→ 启动检测版本旧 → 提示「运行 cs upgrade」
        ↓
cs upgrade → 叠加更新出厂部分(skills/plugins/commands)，合并 settings(保留 env)，
             保留 projects/历史；对项目独有项以编号表格多选删除（默认保留）
```

## 目录与数据模型

```
.claude/        Claude CLI 原生目录（skills/plugins/commands/projects/...，软件本体）
                临时=/home/AISC/.claude（镜像）  项目=/home/AISC/app/.claude（挂载卷）
.cc-config/     cs 运行配置：settings.json(env) + api-keys（密钥，gitignore）
```

容器包含：

| 层级 | 内容 |
|------|------|
| 基础镜像 | `node:20-slim`（`--build-arg NODE_IMAGE=` 可换源）|
| 网络优化 | `USE_CN_MIRROR=1` → apt 清华 + npm 淘宝（可关）|
| 运行时 | Claude Code 全局安装（`/home/AISC/.claude` 内置完整配置）|
| 插件套件 | 6 套技能（cache + marketplace + enabledPlugins + statusLine）|
| 切换工具 | `cs` / `claude-switch` |
| 鉴权 | 官方用 `ANTHROPIC_API_KEY`，第三方用 `ANTHROPIC_AUTH_TOKEN` |

## 容器残留清理

`--rm` 正常退出自动删除；强关 Terminal 可能残留：

```bash
# Linux / macOS
docker ps -aq --filter "name=super-claude-station" --filter "status=exited" | xargs -r docker rm
```
```powershell
# Windows PowerShell
docker ps -aq --filter "name=super-claude-station" | ForEach-Object { docker rm -f $_ }
```

> 启动器使用唯一容器名（`super-claude-station-<id>`），支持项目+临时**多开并行**互不挤掉。

## 项目结构

```
.
├── Dockerfile                  # 多阶段：插件注入 + 解符号链接 + 版本戳
├── entrypoint.sh               # 作用域选择 + .claude 复制/校验 + env 注入 + 启动菜单
├── claude-switch               # cs：后端切换 / upgrade / show
├── claude-wrapper              # claude 包装器：启动注入 env
├── claude-settings.json        # CLI settings（enabledPlugins + marketplaces + statusLine）
├── stage-skills.sh             # _bundle 生成器（从 ~/.claude 暂存插件/技能，一次性）
├── global-claude.md            # 全局 CLAUDE.md
├── commands/                   # gstack 6 个斜杠命令
├── _bundle/                    # 内置插件 + gstack 文档（纳入 git → 自包含构建）
├── 一键启动_AI工作站.bat       # Windows 启动器（英文，防乱码）
├── 启动_AI工作站.sh            # Linux 启动器
├── 启动_AI工作站.command       # macOS 启动器
├── README.md
└── devlog.md                   # 开发日志
```

## 许可证

MIT
