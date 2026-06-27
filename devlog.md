# Super Claude — 开发日志

## v1.1.2 (2026-06-27)

### 🔐 安全重构：API Key 与脚本分离

**重大变更**：`cs` 脚本不再硬编码 Key，改为从 `~/.claude/api-keys` 读取，无 Key 时交互式提示输入。

### ✨ 变更

| 项 | 说明 |
|----|------|
| Key Store | `~/.claude/api-keys`（chmod 600），`KEY_NAME=value` 格式，5 组 Key 独立存储 |
| `get_key()` | 新函数：先查 Key Store → 没有则提示用户输入 → 输入后自动保存 |
| `cs show` 增强 | 显示当前后端 + 各后端 Key 保存状态（✓/✗） |
| URL 保留 | 端点 URL 仍留在脚本中（非机密），仅 Key 走外部存储 |
| Dockerfile | 构建时不执行 `cs`，改为创建空 `api-keys` + 空 `settings.json` |
| entrypoint 引导 | 未配置时自动显示 `cs deepseek` / `cs ark` 等可用命令 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| 硬编码 Key | `claude-switch` 第 21-27 行移除全部默认 Key |
| 构建时依赖 Key | Dockerfile 不再 `RUN cs deepseek`，避免 build 阶段要求交互输入 |
| Key 注入 JS 字符串 | 改为 env var 传递（`export CS_AUTH_TOKEN`），消除 `'` `\` 等特殊字符引发的 SyntaxError |
| `get_key()` stdout 污染 | `echo` 提示文案全部改 `>&2`，`$()` 只捕获纯 Key 值 |
| CRLF 混入 Key | `grep` → `tr -d '\r'` 清洗 Windows 行尾 |
| 密钥路径 | Docker 容器内自动使用 `/app/.claude/api-keys`（随 `-v` 挂载） |
| entrypoint 重复提示 | Section 3 改为单行状态；Section 5 仅在拦截时显示一次性引导 |
| entrypoint 未配置拦截 | `claude` 命令在无后端时 `exec bash` 而非直接进 Claude Code |
| `.gitignore` | 新增 `api-keys` + `super-claude-v1.1.2.tar` 排除规则 |

### 📝 已知问题

- [ ] Termius SSH 配置文档未编写
- [x] ~~`cs` 脚本内 API Key 硬编码~~ → v1.1.2 修复

---

## v1.1.1 (2026-06-27)

### 🔄 切换脚本重构：`cs` 统一入口

**重大变更**：废弃交互式菜单方案，改用 `cs` 一键切换 + `~/.claude/settings.json` 持久化。

### ✨ 变更

| 项 | 说明 |
|----|------|
| `cs` 统一入口 | `cs` / `claude-switch` 指向同一脚本，写入 `~/.claude/settings.json` |
| 放弃菜单交互 | 旧版 `claude-switch` 菜单 + `.claude_keys` 方案全部移除 |
| 5 后端内嵌 Key | cc / deepseek / ark / 1y / duo-cc 的 API Key 内置脚本，切换即用 |
| `cs show` | 快速查看当前后端 |
| `SC_RESTART=1` | 切换后自动重启 Claude Code（Docker 直连模式） |
| 默认后端初始化 | Dockerfile 构建时 `RUN cs deepseek`，不再用 `ENV` 硬编码 |
| `ARG NODE_IMAGE` | 基础镜像可通过 `--build-arg` 替换，解决国内拉取问题 |
| `.gitignore` | 排除 `super-claude-v1.tar`、`.claude_keys` |
| 构建导出流程 | `docker build` + `docker save` → `super-claude-v1.tar` |

### 🔧 修复

| 项 | 说明 |
|----|------|
| CRLF 行尾 | `claude-switch` 从 CRLF 转为 LF，修复容器内 `bash\r` 错误 |
| DeepSeek 无 Key | 移除 Dockerfile 中 `ENV ANTHROPIC_BASE_URL`（有 URL 无 Token 导致 `ERR_BAD_REQUEST`） |
| entrypoint 横幅 | 改为从 `~/.claude/settings.json` 读取后端信息，不再依赖 Docker ENV |
| `claude` 包装器 | 简化为直接移交 `claude-real`，不再做 Key 检测（切换交给 `cs`） |
| cygpath 兼容 | `cs` 脚本自动识别 Windows/Linux 环境，Linux 容器内直接使用 POSIX 路径 |

### 📝 文档

- README.md 重写：`cs` 用法、平台详情表、构建导出流程
- 新增 `cs` 直连模式说明：`docker run ... cs ark`

### 🗑️ 移除

- 旧版交互式 `claude-switch` 菜单（Anthropic/DeepSeek/硅基流动/OpenRouter/智谱 5 选 1）
- `.claude_keys` Key 持久化文件（改为 `~/.claude/settings.json` 管理）
- `entrypoint.sh` 中无 Key 自动引导逻辑（不再需要）
- Dockerfile 中 7 行 `ENV` 硬编码 DeepSeek 变量

### 📂 当前项目结构

```
.
├── Dockerfile
├── entrypoint.sh
├── claude-switch                       # 同时是 cs 和 claude-switch 的源
├── 一键启动_AI工作站.bat
├── devlog.md
├── README.md
├── skills/
│   ├── claude.json
│   ├── karpathy-flow/
│   └── ... (20+ 技能)
├── .claude/
│   └── settings.local.json
├── .claude_keys                        (已废弃，不再使用)
└── todo/
    ├── todo.md
    └── 20260625/
        ├── claude-switch               (开发过程中的中间版本)
        └── setup-ssh-portproxy.ps1
```

### 已知问题

- [ ] Termius SSH 配置文档未编写
- [ ] `cs` 脚本内 API Key 硬编码，后续可改为环境变量覆盖 + 运行时输入

---

## v1.1.0 (2026-06-27)

### 🔄 架构重构：纯终端闭环

**重大决策**：彻底切断对第三方 GUI 黑盒工具的依赖，转向 100% 内部闭环的纯终端 CLI 工作流。

### ✨ 新增

| 项 | 说明 |
|----|------|
| `claude-switch` | 内置模型后端切换器 CLI，支持 5 大平台、15+ 模型 |
| 平台接入 | Anthropic 官方 / DeepSeek 官方 / 硅基流动 / OpenRouter / 智谱 Z.AI |
| 硅基流动子菜单 | 5 款国产模型可选（DeepSeek-V4-Pro、GLM-5.2、Nex-N2-Pro、MiniMax M3、Qwen3.6-35B） |
| OpenRouter 子菜单 | 6 款全球模型可选（Claude Opus 4.8、Sonnet 4.6、DeepSeek V3.2、GLM-5.2、Qwen3 Coder、Kimi K2.7） |
| 智谱 Z.AI 子菜单 | 3 款 GLM 模型可选（GLM-4.6、GLM-4.5、GLM-4.5-Air） |
| `一键启动_AI工作站.bat` | Windows 一键启动脚本，`chcp 65001` 防乱码，零参数开箱即用 |
| API Key 持久化 | `/app/.claude_keys`（chmod 600），5 组 Key 独立存储，容器重启不丢失 |
| `karpathy-flow` 技能 | Andrej Karpathy 编码规范 skill，自动化入容器 |
| `devlog.md` | 开发日志，提升至项目根目录 |
| entrypoint 自动引导 | 无 Key 时启动 `claude` 自动重定向到 `claude-switch` |
| `claude` 包装器 | 重命名原版为 `claude-real`，包装脚本统一拦截：有 Key → 原版，无 Key → `claude-switch` |
| `AUTH_METHOD` 双通道 | Anthropic 官方用 `ANTHROPIC_API_KEY`，第三方平台用 `ANTHROPIC_AUTH_TOKEN` + 清空 `API_KEY` |
| Claude Code 启动绕过 | 预置 `config.json`（`hasCompletedOnboarding: true`）跳过首次联网验证 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| Dockerfile — VPN 依赖 | 注入清华 apt 镜像源 + 淘宝 NPM 镜像源，国内网络无需 VPN 即可构建 |
| Dockerfile — `.claude/` 报错 | 不再 `COPY .claude/`（宿主机缺失时构建失败），改为镜像内生成默认 `settings.local.json` |
| entrypoint.sh — 覆盖风险 | 原逻辑缺文件就强覆盖，现改为仅首次运行注入，保护用户自定义配置 |
| entrypoint.sh — root 锁死 | 新增 `chown` 权限修复，自动检测宿主机 UID/GID 归还文件所有权 |
| entrypoint.sh — Shell | `#!/bin/sh` → `#!/bin/bash`，支持 `echo -e` 等特性 |
| Dockerfile — 工具链 | 补上 `sudo`、`tmux` |
| `claude-switch` — Anthropic 模型 | `claude-3-5-sonnet-20241022`（已退役）→ `claude-opus-4-8` |
| `claude-switch` — 硅基流动模型 | `Pro/deepseek-ai/DeepSeek-V3` → `Pro/deepseek-ai/DeepSeek-V4-Pro` |
| Claude Code — 国内无 VPN 无法启动 | 预置 `config.json` 跳过 onboarding + 第三方平台改用 `ANTHROPIC_AUTH_TOKEN` |
| `claude` 包装器 — 死循环 | 兼容 `ANTHROPIC_AUTH_TOKEN`，两个变量任非空即放行 |
| `claude-switch` — Anthropic 模型 | `claude-3-5-sonnet-20241022`（已退役）→ `claude-opus-4-8` |
| `claude-switch` — 硅基流动模型 | `Pro/deepseek-ai/DeepSeek-V3` → `Pro/deepseek-ai/DeepSeek-V4-Pro` |

### 📝 文档

- README.md 全面重写：5 大平台菜单、子菜单表格、claude-switch 详解

### 🗑️ 移除

- `docker_version/` 子目录清理，文件全部提升至项目根目录

### 📂 当前项目结构

```
.
├── Dockerfile
├── entrypoint.sh
├── claude-switch
├── 一键启动_AI工作站.bat
├── devlog.md
├── README.md
├── skills/
│   ├── claude.json
│   ├── karpathy-flow/SKILL.md     ← v1.1.0 新增
│   └── ... (20+ 技能)
├── .claude/
│   └── settings.local.json
├── .claude_keys                   (运行时生成)
└── todo/
    └── todo.md
```

---

## v1.0.0 (2026-06-25)

### 初始版本

- `node:20-slim` 基础镜像
- 全局安装 `@anthropic-ai/claude-code`
- 预配置 DeepSeek Anthropic 兼容 API（`ANTHROPIC_BASE_URL`、模型映射、effort）
- `claude.json` 全局配置（claude-hud + document-skills 插件）
- 20+ 预装技能库 → `/root/.claude/skills/`
- `entrypoint.sh` 入口脚本：自动注入项目级 `.claude/` 模板
- Windows SSH 端口代理配置（`setup-ssh-portproxy.ps1`）

### 已知问题

- [x] ~~无 VPN 时 `node:20-slim` apt/npm 安装失败~~ → v1.1.0 修复
- [x] ~~`.claude/` 缺失导致 Docker 构建报错~~ → v1.1.0 修复
- [x] ~~Skill 引入（andrej-karpathy-skills）~~ → v1.1.0 完成
- [x] ~~全局 claude-switch 命令~~ → v1.1.0 完成
- [ ] Termius SSH 配置文档未编写
