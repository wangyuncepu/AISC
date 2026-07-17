# Super Claude · v2.0.0-dev

基于 [Claude Code](https://claude.ai/code) 的 Docker 工作站 —— 插件化技能套件、**7 大模型后端一键切换**、**临时/项目双作用域**、**自包含离线构建**。

## 快速开始

### 前置

- [Docker](https://www.docker.com/)（Linux 原生 / Windows Docker Desktop / macOS Docker Desktop）
- Windows 推荐 **Windows Terminal**（cmd 旧窗口可能乱码且 HUD 不渲染）

### 启动

| 平台 | 入口 |
|------|------|
| Linux | `./start.sh [--workspace PATH]` |
| Windows | 双击 `start.bat`（PowerShell 5.1 兼容） |
| macOS | 双击 `start.command`（透传 start.sh，测试较少） |

启动器执行：检测镜像 → 不存在则自动构建（交互选择缓存/国内源）→ 菜单选作用域 → 启动容器。

### 手动构建

```bash
# 默认构建（自包含，仓库含 container/_bundle + container/downloads；CN 镜像源默认开）
docker build -f container/Dockerfile -t super-claude:latest .

# 海外网络：关闭 CN 镜像源（apt/npm 走官方）
docker build -f container/Dockerfile --build-arg USE_CN_MIRROR=0 -t super-claude:latest .

# 国内 + 基础镜像走 daocloud（绕开 docker.io 拉取超时）
docker build -f container/Dockerfile \
  --build-arg NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim \
  -t super-claude:latest .

# 完全从头构建（禁用 Docker 缓存）
docker build -f container/Dockerfile --no-cache -t super-claude:latest .
```

**构建参数 (ARGs)**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `NODE_IMAGE` | `node:20-slim` | 基础镜像（可替换拉取源；digest 未 pin） |
| `USE_CN_MIRROR` | `1` | `1`=清华 apt + 淘宝 npm；`0`=官方源 |
| `MIHOMO_VERSION` | `v1.19.27` | Mihomo TUN 代理核心版本 |
| `GH_PROXY` | (空) | GitHub release 加速前缀（国内可设 `https://ghfast.top/`） |
| `CC_SWITCH_VERSION` | `v5.9.0` | cc-switch-cli 版本 |
| `CLAUDE_CODE_VERSION` | `latest` | Claude Code npm 版本（**TODO: pin 到具体版本**） |
| `GEODATA_VERSION` | `latest` | MetaCubeX geodata 发布版本（**TODO: pin 到具体版本**） |

> 仓库内置 `container/_bundle`（插件/技能）与 `container/downloads`（mihomo + geodata），`docker build` 不依赖宿主机 `~/.claude` 且**无需访问 GitHub**（国内网络友好）。如需从本机重新生成插件包：`bash tools/stage-skills.sh`。升级 mihomo：改 Dockerfile 中 `MIHOMO_VERSION` 后跑 `bash tools/stage-mihomo.sh` 再提交。

### 运行

```bash
# Linux / macOS
docker run -it --rm -e TERM=xterm-256color -v "$(pwd):/home/AISC/app" super-claude:latest

# Windows PowerShell
docker run -it --rm -e TERM=xterm-256color -v "${PWD}:/home/AISC/app" super-claude:latest

# Windows CMD
docker run -it --rm -e TERM=xterm-256color -v "%cd%:/home/AISC/app" super-claude:latest
```

> `TERM=xterm-256color` 必须设置：Windows 下容器 TERM 常缺失，Claude Code 会判定终端不支持而隐藏 claude-hud 状态栏。

### 常用变体

```bash
# 直接进入 bash（不启动 claude，可手动 cs 配置后启动）
docker run -it --rm -e TERM=xterm-256color -v "$(pwd):/home/AISC/app" super-claude:latest bash

# 项目模式（跳过菜单，持久化配置）
docker run -it --rm -e TERM=xterm-256color -e CLAUDE_SCOPE=project \
  -v "$(pwd):/home/AISC/app" super-claude:latest

# 临时模式（配置不持久，容器退出即重置）
docker run -it --rm -e TERM=xterm-256color -e CLAUDE_SCOPE=temp \
  -v "$(pwd):/home/AISC/app" super-claude:latest

# 启动后直接切换后端
docker run -it --rm -e TERM=xterm-256color -v "$(pwd):/home/AISC/app" super-claude:latest cs deepseek

# 指定容器名（多开时区分；--rm 正常退出自动清理）
docker run -it --rm --name sc-myproject -e TERM=xterm-256color \
  -v "$(pwd):/home/AISC/app" super-claude:latest
```

## 功能概览

- **Claude Code 容器化** — 开箱即用的非 root 运行环境（AISC, uid=1000）
- **7 大模型后端** — `cs cc / deepseek / ark / 1y / duo-cc / xf / orange` 一键切换
- **插件化技能** — caveman（默认激活）、claude-hud（状态栏 HUD）、superpowers（14 工作流）、document-skills、skill-creator、gstack 全部离线内置
- **TUN 透明代理**（可选）— 容器内建 Mihomo (Clash Meta) 接管出站，宿主机零代理
- **AI 每日简讯**（可选）— 5 源并发聚合，默认不运行
- **cc-switch-cli** — 内置 Rust 二进制 v5.9.0，管理多 AI CLI 配置
- **临时/项目双作用域** — 临时即用即弃，项目持久隔离
- **自包含离线构建** — 仓库内置所有依赖，`docker build` 不访问外网

## 作用域：临时 vs 项目

启动时（交互终端）询问：

```
请选择 Claude (.claude) 作用域：
  1) 临时 temporary — 使用镜像内置 .claude，容器退出即重置
  2) 项目 project   — 当前项目独立 .claude，持久到宿主机
```

| | 临时 | 项目（默认） |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `/home/AISC/.claude`（镜像） | `/home/AISC/app/.claude`（挂载卷） |
| 持久化 | 容器退出即重置 | 持久到宿主机 |
| 适用 | 快速试用、一次性任务 | 长期项目、独立配置/历史 |
| 首次行为 | 直接用镜像 | 从镜像完整复制到挂载卷 |

- 非交互（脚本/管道）默认**项目**；环境变量 `CLAUDE_SCOPE=temp|project` 可跳过菜单
- 两模式的 `cs` 后端配置都写 `.cc-config`（恒在项目内），与 `.claude` 分离

## `cs` 模型切换

容器内 `cs`（= `claude-switch`）切换 API 后端，实时生效。密钥优先存于 `.aisc/secrets/api-keys`（chmod 600），同时保持 `.cc-config/api-keys` 兼容可用。

| 命令 | 平台 | 默认模型 | 端点 |
|------|------|----------|------|
| `cs cc` | Anthropic 官方 | （清空） | 官方默认 |
| `cs deepseek` | DeepSeek | `deepseek-v4-pro[1m]` | `api.deepseek.com/anthropic` |
| `cs ark` | 火山 Ark | `glm-5.2[1m]` | `ark.cn-beijing.volces.com/api/coding` |
| `cs 1y` | 1yuanapi | `glm-5.2[1m]` | `1yuanapi.com` |
| `cs duo-cc` | duo-cc | `claude-sonnet-5` | `api.duou.cc` |
| `cs xf` | 讯飞 | `xopdeepseekv4pro[1m]` | `maas-coding-api.cn-huabei-1.xf-yun.com/anthropic` |
| `cs orange` | OrangeAI | `glm-5.2[1m]` | `api4.orangeai.cc` |

```bash
cs show       # 查看当前后端与已存 Key
cs upgrade    # 合并镜像出厂 .claude 到当前项目（保留后端配置/历史）
```

> Key 首次输入后保存，之后自动记住。`cs X` 切换后 Claude 自动重启生效。

### cc-switch-cli（增量集成，与 cs 共存）

容器内置 [cc-switch-cli](https://github.com/saladday/cc-switch-cli)（Rust 二进制，v5.9.0），跨平台 AI CLI 管理工具，统一管理 Claude Code / Codex / Gemini / OpenCode provider 配置、MCP servers、skills、prompts。

- `cs` 是项目内置轻量切换器（7 后端一键切）；`cc-switch` 功能更全（多 AI CLI、TUI、WebDAV 同步、用量统计）
- 命令名不冲突（`cs` vs `cc-switch`），共存按需用

```bash
cc-switch              # TUI 交互界面
cc-switch --version    # 查看版本
cc-switch --help       # CLI 子命令
```

## 代理网络（容器内建 Mihomo TUN）

宿主机**无需任何代理**。容器内 Mihomo (Clash Meta) 以 TUN 模式接管出站流量，Claude Code 直连 API。

- **交互式配置**：启动器 TUI 询问 → 选本地配置/订阅链接 → 自动注入 TUN 配置
- **按需特权**：仅启用代理时追加 `--cap-add=NET_ADMIN --device /dev/net/tun`
- **格式支持**：Clash YAML / base64 订阅 / URI 直链 / JSON (SIP008)；节点协议 ss / vmess / trojan / vless / hysteria2
- **mihomo 以 root 启动**（sudo）：建 TUN 设备 + iptables 需 `CAP_NET_ADMIN`
- **geodata 预置**：镜像内已含 `geoip.metadb / geosite.dat / country.mmdb`

```bash
# 手动运行（需先放好 config.yaml）
docker run -it --rm -e TERM=xterm-256color \
  --cap-add=NET_ADMIN --device /dev/net/tun \
  -v "$(pwd):/home/AISC/app" \
  -v "$(pwd)/.claude/mihomo/config.yaml:/etc/mihomo/config.yaml:ro" \
  super-claude:latest
```

**已知限制**：
- `/dev/net/tun` 依赖：Docker Desktop (Win/macOS) LinuxKit VM 内置；原生 Linux 需 tun 内核模块
- 自动转换生成最小配置（`url-test` 自动选节点 + 全流量代理），不含原订阅分流规则
- mihomo 日志：容器内 `/home/AISC/.mihomo/mihomo.log`

## AI 每日简讯（ai-brief）

`apps/ai-brief/` 每日 AI 新闻聚合工具，从 5 个来源并发抓取并通过 LLM 生成中文精选摘要。

- **默认：关闭**（不阻塞启动）
- **启用**：环境变量 `AI_BRIEF_ON_START=background`（后台运行）或 `foreground`（同步运行，仅调试）
- **手动运行**（容器内）：`python3 /home/AISC/ai_brief/brief.py --ai --top 5`
- **调试**：支持 `--debug` 参数输出各阶段耗时
- **缓存**：`~/.cache/ai-brief/`（挂载卷持久化，跨容器复用，stale-while-revalidate）
- **模型**：`AI_BRIEF_MODEL` 环境变量可指定模型（→ `ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` 逐级回退）
- **技术**：stdlib-only（urllib + xml.etree + concurrent.futures），零外部依赖

## 内置技能

| 插件 | 作用 | 激活方式 |
|------|------|----------|
| **caveman** | 超压缩沟通（**默认激活**，省约 75% token） | SessionStart 自动 + `/caveman` |
| **claude-hud** | 终端底部状态栏 HUD（模型/上下文/git/工具…） | statusLine 自动 |
| **superpowers** | 14 个工作流技能（TDD/调试/计划/审查…） | Skill 自动 |
| **document-skills** | 文档处理：docx / pdf / pptx / xlsx | Skill 自动 |
| **skill-creator** | 创建/优化/评测技能 | Skill 自动 |
| **gstack** | 计划评审 + 斜杠命令 | `/plan-ceo-review` 等 |

> `skills-lock.json` 仅锁定 caveman 插件版本。gstack 等其他技能不受此文件锁定。

## 升级流程

```
更新 Dockerfile / 技能 → docker build
         ↓
docker run（项目模式）→ 检测版本旧 → 提示「运行 cs upgrade」
         ↓
cs upgrade → 合并出厂部分(skills/plugins/commands)，保留 projects/历史/后端配置
```

> 升级非自动：用户需手动在容器内执行 `cs upgrade`。

## 诊断工具

### P3 CLI（开发预览 / 尚未替代 start.*）

> **状态说明**：P3.1 S3 实现了 `version`、`doctor`、`build`、`run` 四个命令的最小纵向切片。当前 **默认用户入口仍是 `start.sh` / `start.bat` / `start.command`**。Python CLI 处于开发预览阶段，独立二进制（PyInstaller）要到 S4 才会完成。

```bash
# 开发用法（需要仓库源码 + Python 3.11+）
PYTHONPATH=src python3 -m aisc version
PYTHONPATH=src python3 -m aisc version --format json
PYTHONPATH=src python3 -m aisc doctor
PYTHONPATH=src python3 -m aisc doctor --format json

# 构建镜像（dry-run 规划）
PYTHONPATH=src python3 -m aisc build --dry-run
PYTHONPATH=src python3 -m aisc build --dry-run --no-cache --pull
PYTHONPATH=src python3 -m aisc build --dry-run --tag my-image:v1
PYTHONPATH=src python3 -m aisc build --dry-run --events        # JSONL 事件流

# 运行容器（dry-run 规划）
PYTHONPATH=src python3 -m aisc run --dry-run
PYTHONPATH=src python3 -m aisc run --dry-run --network proxy
PYTHONPATH=src python3 -m aisc run --dry-run --events          # JSONL 事件流

# 全局选项可放在子命令前或后
PYTHONPATH=src python3 -m aisc --format json version
PYTHONPATH=src python3 -m aisc --events build --dry-run
```

> 协议细节见 `docs/rfc/aisc-cli-v1.md`。

### Doctor（Shell 脚本版）

```bash
# 直接执行诊断脚本（188 行，11 项检查：Docker/Git/权限等）
bash cli/commands/doctor.sh
```

> `./start.sh doctor` **不可用**。start.sh 仅支持 `--workspace PATH` 参数。doctor 需直接调用。

### Smoke Test（语法验证）

```bash
bash tests/smoke/check-syntax.sh   # 检查 66+ 文件脚本/JSON 语法
```

### 文档一致性检查

```bash
bash tools/check-docs.sh           # 验证 README 路径引用 + provider 一致性
```

## 目录结构

```
.
├── README.md
├── VERSION                              # 2.0.0-dev
├── skills-lock.json                     # 锁定 caveman 插件版本
├── start.sh / start.bat / start.command  # 三平台入口
├── container/                           # 镜像构建上下文
│   ├── Dockerfile                       # 多阶段：系统依赖 + mihomo + cc-switch-cli + Claude Code + 插件
│   ├── entrypoint.sh                    # 作用域选择 + 代理注入 + 启动菜单
│   ├── mihomo-build-config.js           # 订阅转换 + TUN/DNS 强制注入
│   ├── claude-switch                    # cs 命令：后端切换 / upgrade / show
│   ├── claude-wrapper                   # claude 包装器：注入 env + --dangerously-skip-permissions
│   ├── claude-settings.json             # enabledPlugins + marketplaces + statusLine
│   ├── global-claude.md                 # 全局 CLAUDE.md
│   ├── providers.json                   # 7 个 API 后端定义
│   ├── lib/                             # 共享函数库 (path-resolve.sh 等)
│   ├── commands/                        # gstack 斜杠命令
│   ├── _bundle/                         # 内置插件 + gstack 文档（纳入 git → 自包含构建）
│   └── downloads/                       # mihomo + geodata 预置（纳入 git → 零 GitHub 依赖）
├── cli/                                 # CLI 工具
│   └── commands/doctor.sh               # 环境诊断（11 项检查）
├── scripts/                             # 启动器流水线模块
│   ├── run.sh / run.ps1                 # 编排器
│   ├── 01_check_env.*                   # 环境检测
│   ├── 02_config_wizard.*               # 代理 TUI
│   ├── 03_build_image.*                 # 镜像菜单 + 构建
│   ├── 04_launcher.*                    # docker run 组装
│   └── _state.*                         # 状态存储（.deploy/state.env）
├── apps/ai-brief/                       # AI 每日简讯聚合工具
├── config/versions.env                  # 依赖版本 pinned（Mihomo/cc-switch/Claude Code/Geodata）
├── vendor/                              # 第三方制品清单与校验（manifest.json + checksums.txt + licenses/）
├── tools/                               # 一次性工具
│   ├── stage-skills.sh                  # 暂存插件到 container/_bundle
│   ├── stage-mihomo.sh                  # 预下载 mihomo+geodata 到 container/downloads
│   └── check-docs.sh                    # 文档一致性检查
├── tests/smoke/check-syntax.sh          # 语法冒烟测试（66+ 文件）
├── .github/workflows/                   # CI：checks.yml + docker-smoke.yml
│   ├── checks.yml
│   └── docker-smoke.yml
└── docs/                                # 开发日志 + 设计方案 + TODO
```

> `.aisc/` 为运行时目录（git-ignored），存放 secrets、缓存等，不在仓库中。`.deploy/state.env` 为启动器运行状态，每次运行重生成。

## 安全说明

- **默认权限模式**：Claude 以 `--dangerously-skip-permissions` 启动（跳过逐条权限确认，适应容器内自动流）
- **sudo**：AISC 用户配置 NOPASSWD sudo（TUN 代理 + 文件所有权自愈所需）
- **TUN 代理**：仅启用时追加 `--cap-add=NET_ADMIN --device /dev/net/tun`；不启用则零特权
- **密钥存储**：主位置 `.aisc/secrets/api-keys`（chmod 600），`.cc-config/api-keys` 为兼容保留
- **挂载边界**：`ensure_writable` 使用 `sudo chown -R AISC:AISC` 自愈文件权限，可能影响主机上 bind mount 的文件所有权
- **容器用户**：非 root（AISC, uid=1000），root 下 Claude Code 拒绝 `--dangerously-skip-permissions`

## 维护工具

```bash
# 更新 vendor 清单
bash tools/vendor-refresh.sh     # 重新扫描并生成 vendor/manifest.json

# 校验 vendor 完整性
bash tools/vendor-verify.sh      # 对照 checksums.txt 验证 bundled 文件

# 暂存技能到 _bundle（从 ~/.claude 提取）
bash tools/stage-skills.sh

# 预下载 mihomo + geodata
bash tools/stage-mihomo.sh

# 升级 mimomo 版本示例
docker build -f container/Dockerfile --build-arg MIHOMO_VERSION=v1.20.0 -t super-claude:latest .
```

## 平台兼容性

| 平台 | 状态 |
|------|------|
| Linux | 完全支持，主开发平台 |
| macOS (Docker Desktop) | `start.command` 可用但测试较少；TUN 需 LinuxKit VM tun 支持 |
| Windows (Docker Desktop) | `start.bat` 支持 PowerShell 5.1；TUN 需 LinuxKit VM `/dev/net/tun` |

## 容器残留清理

`--rm` 正常退出自动删除；强关 Terminal 可能残留：

```bash
# Linux / macOS
docker ps -aq --filter "name=super-claude-station" --filter "status=exited" | xargs -r docker rm

# Windows PowerShell
docker ps -aq --filter "name=super-claude-station" | ForEach-Object { docker rm -f $_ }
```

## 链接

- [Claude Code 文档](https://docs.anthropic.com/en/docs/claude-code)
- [Issues](https://github.com/saladday/AISC/issues)
- [cc-switch-cli](https://github.com/saladday/cc-switch-cli)

## 许可证

MIT
