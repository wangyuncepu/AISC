# Super Claude — 开发日志

## v1.2.1 (2026-06-30) — README 手动构建/运行 文档完善

- **README 手动构建/运行部分重写**：拆分为构建/运行/常用变体三个小节，覆盖三平台命令。
  - 构建：明确 `USE_CN_MIRROR` 默认=1，新增 `--no-cache` 示例。
  - 运行：新增 Windows PowerShell/CMD 的 `-v` 语法，强调 `TERM=xterm-256color` 必要性。
  - 常用变体：`CLAUDE_SCOPE` 跳过菜单、`bash` 直接进 shell、`cs <后端>` 一键切换、`--name` 容器命名。

## v1.2.0 (2026-06-30) — 插件化重构 + 双作用域 + 跨平台修复

### 架构重构

- **临时 / 项目双作用域**：用 Claude CLI 原生 `CLAUDE_CONFIG_DIR` 驱动。
  临时 = 镜像内置 `/root/.claude`（即用即弃）；项目 = `/app/.claude`（从镜像完整复制，持久到宿主机卷）。
  entrypoint 交互菜单 / `CLAUDE_SCOPE` 环境变量选择，导出并写入 `.bashrc`/`profile.d`。
- **`.claude` 与 `.cc-config` 分离**：`.claude` 为 CLI 原生完整目录（skills/plugins/projects…）；
  `.cc-config` 仅存 cs 的 `api-keys`（密钥隔离，gitignore）。
- **插件机制集成 6 套技能**（离线可用，预置 cache + marketplaces + 注册表 + `enabledPlugins`）：
  caveman（SessionStart hook 默认激活）/ claude-hud（statusLine HUD）/ document-skills /
  superpowers / skill-creator + gstack（扁平文档，6 子技能 + 斜杠命令）。
  `skill-creator` 构建期从本地 marketplace 离线 install。
- **自包含构建**：插件包 `_bundle` 纳入 git（约 24M），`docker build` 不再依赖宿主机 `~/.claude`。
  `stage-skills.sh` 作为一次性生成器（裁剪 marketplace、cache 版本剪枝、gstack 仅 6 子技能）。
- **cs 实时切换**：env 块改写入 `.claude/settings.json`（Claude Code 原生读取），`!cs ds` 当场生效；
  `write_settings` 合并保留 `enabledPlugins/statusLine`。`cs cc` 允许留空清空所有配置。
- **cs upgrade + 出厂版本检测**：`.factory-version`（出厂内容哈希）；项目版本旧则提示升级；
  `cs upgrade` 叠加更新出厂部分、合并 settings（留 env）、保留运行态、孤项编号表格多选删除。

### 启动器增强（.sh / .bat / .command）

- 镜像不存在自动构建；已存在三选一（直接运行 / 删旧重建防悬空 / 新镜像名）。
- 构建前两问：是否用缓存（`--no-cache`）、是否用国内镜像源（`USE_CN_MIRROR` + daocloud 基础镜像）。
- 容器名唯一后缀（`$$` / `%RANDOM%`），仅清理已退出容器 → 项目+临时多开互不挤掉。

### 跨平台修复（Windows 重点）

- **`.bat` 改纯英文 ASCII**：UTF-8 中文被 cmd 按代码页解析断行报错（wt 同样），英文根治；`chcp 65001` 仅保障 claude 输出。
- **基础镜像 docker.io 超时**：国内镜像选项同时把 `NODE_IMAGE` 指向 daocloud，绕开 `auth.docker.io`。
- **HUD 不显示（多根因）**：① 强制 `TERM=xterm-256color`（Windows 容器 TERM 缺失致 statusLine 隐藏）；
  ② 符号链接（superpowers AGENTS.md）`cp -r` 在 grpcfuse 创建失败 + `set -e` 中断致 `.claude` 复制残缺 →
  镜像内解引用所有 symlink + entrypoint 完整性校验补拷 + `cp -rL`；
  ③ **插件自带 `.gitignore`（含 `dist/`）导致 claude-hud `dist/index.js` 漏提交** → 用户 clone 缺文件、
  statusLine `MODULE_NOT_FOUND`；stage-skills 删除嵌套 `.gitignore` + 补提交；
  ④ `installed_plugins.json` 路径写死 `/root` → CLI 误判项目副本 orphan 可能删 dist → 复制后重写路径为项目目录。
- **`.claude.json` 缺失**：新版 CLI 核心状态在 `.claude.json`，构建期写入 onboarding + 跑一次 CLI 补全运行字段。

### 网络 / 工具（前置工作）

- WSL → Windows Clash 代理（7890）走 SSH-over-443（`ssh.github.com`），9 仓库切 SSH remote。
- 主机 `claude-switch` 增加 `duo-cc` 后端。

## 修复：.bat WT 启动逻辑重做 (2026-06-29, bug4 后续)

### 🐛 no.4 修复后暴露的两个新问题

- **4a 重复开窗** — 已在 Windows Terminal 内运行 `.bat` 仍无条件再开一个 wt。
  根因：脚本只 `where wt` 判断系统是否装 wt，未判断**当前是否已在 wt 内**。
  修复：读环境变量 `WT_SESSION`，已在 wt 则 `goto run` 直接当前标签运行。
- **4b docker 丢参** — 新 wt 内报 `'docker run' requires at least 1 argument`（`%IMAGE%` 丢失）。
  根因：`wt ... cmd /k "...""%cd%:/app""...%IMAGE%"` 的嵌套双引号经 **wt tokenizer**（非 cmd）解析时被拆断，
  命令在 `-v` 后截断，`%IMAGE%` 落入 wt 的其它参数而丢失。
  修复：改为**自重启模式** — wt 仅以本脚本 `cmd /k ""%~f0""` 开新标签，
  `docker run` 在重启实例内**直接执行**，不再把命令串塞进 wt 解析器；`wt -d "%cd%"` 保留工作目录。
  结构用 `if defined WT_SESSION goto run` + `where wt` / `if errorlevel 1 goto run` + `:run` 标签，
  规避 `&&( ... )` 括号块的批处理解析坑。

### ⚠️ 验证

本机 Linux 无法执行 `.bat`，仅做静态校验（含 `WT_SESSION`/`wt -d`、docker run 参数完整、无嵌套 docker 串）。
**需 Windows + Windows Terminal 实测三场景**：① 已在 wt 标签内双击/运行 ② CMD/PowerShell 双击 ③ 未装 wt。

## 修复：容器运行时与 Windows 启动问题 (2026-06-29, no.3-5)

### 🐛 三项缺陷修复

- **no.5 中文乱码** — 容器内未配置 UTF-8 locale，`ls` 等输出八进制转义乱码。
  Dockerfile 注入 `ENV LANG=C.UTF-8 LC_ALL=C.UTF-8`（debian-slim/glibc 内置，无需 locale-gen），
  `entrypoint.sh` 追加 `export LANG/LC_ALL` 作运行期兜底。已在容器内验证 `locale`=`C.UTF-8`、中文文件名与渲染正常。
- **no.4 .bat 报错** — `一键启动_AI工作站.bat` 经 Windows Terminal 启动报 `参数格式不正确 - >nul`，
  根因为 `wt ... cmd /k "chcp 65001 ^>nul && ..."` 中 caret 转义的 `>nul` 被 wt 参数切分误判。
  去除该重定向（保留一行 `Active code page` 输出，无害）。
- **no.3 残留容器** — `docker run --rm` 无 `--name`，窗口被强制关闭时容器残留需手动删。
  启动脚本（`.bat` + `启动_AI工作站.sh`）改用固定 `--name super-claude-station`，
  并在每次启动前 `docker rm -f` 清理同名 stale 容器，保证不堆积。正常退出仍建议 `exit`。

### ✅ 验证

`docker build` 通过；容器内 `locale` 确认 `C.UTF-8`，`ls` 中文无乱码。
Windows `.bat` 的 no.4 需在 Windows + Windows Terminal 环境实测确认。

## v1.1.3 (2026-06-28)

### 🚀 启动体验与全局行为优化

**重大变更**：后端配置与 Key 统一持久化到项目挂载目录 `/app/.claude/`，并在 `entrypoint.sh` 与 `claude-wrapper` 中自动注入环境变量，解决配置后仍进入登录引导、首次进入 bash 后手动 `claude` 不生效等问题。

### ✨ 变更

| 项 | 说明 |
|----|------|
| 配置持久化 | `cs` 在 Docker 内优先写入 `/app/.claude/settings.json`，随项目挂载卷保留 |
| Key 持久化 | `cs` 在 Docker 内优先写入 `/app/.claude/api-keys`，容器重建不丢失 |
| `claude-wrapper` | 新增包装器：每次运行 `claude` 前读取 settings env，注入 `ANTHROPIC_*` / `CLAUDE_CODE_*` 后再执行 `claude-real` |
| 全局 `CLAUDE.md` | 新增 `global-claude.md`，构建时复制到 `/root/.claude/CLAUDE.md` |
| karpathy-flow 默认启用 | 将 Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution 写入全局 `CLAUDE.md` |
| Caveman 默认启用 | 全局默认 Caveman `full` 沟通风格，用户可用 `normal mode` / `stop caveman` 关闭 |
| 跨平台启动脚本 | 新增 Linux `启动_AI工作站.sh` 与 macOS `启动_AI工作站.command`，Windows `.bat` 更新为 v1.1.2 横幅并优先使用 Windows Terminal |
| README 启动说明 | 按 Windows / Linux / macOS 拆分，补充启动模式、单次运行、容器残留清理、终端乱码说明 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| 登录引导误触发 | `entrypoint.sh` 读取 settings 后真正 `export` env，避免只有配置文件但 Claude 进程无 token |
| 首次 bash 后手动 `claude` 不生效 | `claude-wrapper` 每次启动都重新注入 env，解决 `cs` 写入配置后当前 bash 环境未更新的问题 |
| 项目级 settings 覆盖全局 settings | `cs` 优先写 `/app/.claude/settings.json`，避免 `.claude/settings.json` 与 `~/.claude/settings.json` 不一致 |
| `/model` pin 冲突 | `cs` 写 settings 时删除 `model` 字段，让 `env.ANTHROPIC_MODEL` 接管当前后端 |
| 空 API Key 覆盖 Auth Token | env 注入时对空值执行 `unset`，避免 `ANTHROPIC_API_KEY=""` 干扰 `ANTHROPIC_AUTH_TOKEN` |
| 单次运行模式 | 验证 `docker run ... claude -p "..."` 可用，并写入 README |
| CMD 中文乱码 | `.bat` 优先使用 Windows Terminal；README 明确传统 CMD 可能乱码 |

### 📝 已知问题

- [ ] Termius SSH 配置文档未编写
- [ ] gstack 仅有技能描述，完整运行时安装方案待确认

---

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
