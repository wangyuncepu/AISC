# Super Claude · v1.5.1

开箱即用的 [Claude Code](https://claude.ai/code) Docker 工作站 —— 插件化技能套件、**5 大模型后端一键切换**、**临时/项目双作用域**、**自包含离线构建**，100% 纯终端 CLI。

## 核心亮点

- 🔌 **插件化技能** — caveman（默认激活）/ claude-hud（状态栏 HUD）/ document-skills / superpowers / skill-creator + gstack，全部离线内置
- 🔄 **5 大模型后端** — `cs cc / deepseek / ark / 1y / duo-cc` 一键切换，**实时生效**
- 🧪 **临时 / 项目 双作用域** — 临时模式即用即弃，项目模式配置持久且隔离
- 🔐 **密钥隔离** — API Key 存于 `.cc-config/api-keys`（chmod 600），与 CLI 配置 `.claude` 分离，永不入 git
- 📦 **自包含构建** — 仓库内置 `_bundle`，`docker build` 不依赖宿主机 `~/.claude`、可离线
- ⬆️ **一键升级** — 镜像更新后 `cs upgrade` 合并出厂配置，保留你的后端选择与历史
- 🚀 **智能启动器** — 自动检测/构建镜像、防悬空镜像、可选缓存与国内镜像源、多开互不干扰
- 🌐 **容器内建 TUN 透明代理** — 宿主机零代理，容器内 Mihomo (Clash Meta) TUN 接管全部出站，Claude Code 直连 Anthropic API；TUI 引导本地文件/订阅链接二选一，自动强制注入 TUN 配置
- 🧰 **cc-switch-cli** — 内置 cc-switch-cli（Rust 二进制，v5.9.0），与 `cs` 共存，统一管理多 AI CLI（Claude/Codex/Gemini）provider 配置、MCP servers、skills 和 prompts
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
| Windows | 双击 `start.bat` |
| Linux | `./start.sh` |
| macOS | 双击 `start.command` |

启动器会：
1. 检测镜像是否存在 —— 不存在则**自动构建**（构建前询问：是否用缓存 / 是否用国内镜像源）
2. 镜像已存在 → 三选一：`[1]` 直接运行 `[2]` 删旧重建（防悬空 `<none>`）`[3]` 用新镜像名构建
3. 运行容器（交互菜单选作用域 + 启动方式）

### 手动构建 / 运行

#### 构建

```bash
# 默认构建（自包含，仓库已含 image/_bundle；国内镜像源默认开）
docker build -f image/Dockerfile -t super-claude:latest .

# 海外网络 —— 显式关闭国内镜像（apt / npm 走官方源）
docker build -f image/Dockerfile --build-arg USE_CN_MIRROR=0 -t super-claude:latest .

# 国内网络 + 基础镜像也走 daocloud（绕开 docker.io 拉取超时）
docker build -f image/Dockerfile \
  --build-arg NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim \
  -t super-claude:latest .

# 完全从头构建（禁用缓存）
docker build -f image/Dockerfile --no-cache -t super-claude:latest .
```

> **⚠️ `USE_CN_MIRROR` 默认 = `1`（国内源）**：apt → 清华、npm → 淘宝。海外用户需显式传 `--build-arg USE_CN_MIRROR=0` 走官方源。
>
> 仓库内置 `image/_bundle`（插件/技能，约 24M），构建不依赖宿主机 `~/.claude`。若需从你本机重新生成插件包，运行 `bash tools/stage-skills.sh` 后再 build（一次性，普通用户无需）。

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

## cc-switch-cli（增量集成，与 cs 共存）

容器内置 [cc-switch-cli](https://github.com/saladday/cc-switch-cli)（Rust 二进制，v5.9.0），跨平台 AI CLI 管理工具，统一管理 Claude Code / Codex / Gemini / OpenCode 等 provider 配置、MCP servers、skills、prompts。

> **与 `cs` 的区别**：`cs` 是项目内置轻量切换器（5 后端一键切）；`cc-switch` 功能更全（多 AI CLI、TUI、WebDAV 同步、用量统计）。命令名不冲突（`cs` vs `cc-switch`），共存按需用。

### 使用

```bash
cc-switch              # 进 TUI 交互界面（provider/账号/会话管理）
cc-switch --version    # 查看版本
cc-switch --help       # 查看 CLI 子命令
```

### 构建参数

```bash
# 指定版本（默认 v5.9.0）
docker build -f image/Dockerfile --build-arg CC_SWITCH_VERSION=v5.9.0 -t super-claude:latest .

# 海外直连（不用 ghproxy 加速）
docker build -f image/Dockerfile --build-arg GH_PROXY= --build-arg USE_CN_MIRROR=0 -t super-claude:latest .
```

> cc-switch 下载复用 mihomo 的 `GH_PROXY` 多镜像 fallback（ghfast.top 等），国内网络无忧；musl 静态版兼容 glibc/musl。

## 代理网络（容器内建 Mihomo TUN 透明代理）

宿主机**无需开启任何代理**。容器内 Mihomo (Clash Meta) 以 TUN 模式接管全部出站流量，Claude Code 直连 Anthropic API。启动器 TUI 引导完成配置，用户无需懂技术。

### 工作原理

```
启动器 TUI（宿主）                    容器内（entrypoint）
─────────────────                    ──────────────────────
1. 询问“是否需要代理?” ── y
2. 选 1)本地文件 / 2)URL
3. 下载/拷贝原始 config.yaml
   → .claude/mihomo/config.yaml       4. 读 ro 挂载的原始配置/订阅
                                      5. 自动识别格式(yaml/base64订阅/URI直链/JSON)
                                         非yaml → 转最小Clash配置(ss/vmess/trojan/vless/hysteria2)
                                         + 强制注入 TUN 块(+ 缺失时补 DNS)
                                      6. sudo mihomo -d ~/.mihomo -f 副本（后台）
                                      7. TUN 接管路由 → exec claude
docker run 追加:
  --cap-add=NET_ADMIN --device /dev/net/tun
  -v .claude/mihomo/config.yaml:/etc/mihomo/config.yaml:ro
```

- **TUN 配置权威注入在容器内**（Node）：剥离用户配置中已有的 `tun:` 块 → 追加规范 `tun:`（`enable/stack:system/dns-hijack:any:53/auto-route/auto-detect-interface`）；若用户配置无 `dns:` 块则补一个最小可用 `dns:`（避免 TUN 劫持 53 端口形成解析死循环）。每次启动重打，幂等，手动丢配置也能兜底。
- **特权按需**：仅当 TUI 选“需要代理”时才追加 `--cap-add=NET_ADMIN --device /dev/net/tun` 与配置只读挂载；不配代理则零特权、零 tun 设备依赖。
- **mihomo 以 root 启动**（`sudo`，AISC 已 NOPASSWD sudoers）：建 TUN 设备 + `auto-route` iptables 需 `CAP_NET_ADMIN`，非 root 用户无此 cap。
- **geodata 预置**：镜像构建期下载 `geoip.metadb/geosite.dat/country.mmdb`，避免受限网络下 mihomo 运行时下载 geodata 失败导致起不来。

### 使用

启动器交互（以 `.sh` 为例，`.bat` 同理）：

```
是否需要配置代理网络? [y/N]: y
  1) 本地文件 — 输入本地 config.yaml 绝对路径
  2) 网络链接 — 输入订阅链接 / 配置直链 URL
选择 [1/2，默认 2]: 2
配置 URL: https://example.com/sub.yaml
⬇️  下载配置...
✅ 代理配置已就绪
🛡️  已启用容器内 TUN 透明代理（NET_ADMIN + /dev/net/tun）
```

容器启动日志：

```
🚀 正在内建 TUN 透明代理网络...
✅ Mihomo TUN 已就绪（PID 42）
🌐 代理连通: api.anthropic.com 可达
```

### 手动构建/运行（含代理）

```bash
# 构建（默认 pin mihomo v1.19.27；image/downloads/ 已预置，不访问 GitHub）
docker build -f image/Dockerfile -t super-claude:latest .

# 运行（启用 TUN 代理）—— 需先放好 .claude/mihomo/config.yaml
docker run -it --rm -e TERM=xterm-256color \
  --cap-add=NET_ADMIN --device /dev/net/tun \
  -v "$(pwd):/home/AISC/app" \
  -v "$(pwd)/.claude/mihomo/config.yaml:/etc/mihomo/config.yaml:ro" \
  super-claude:latest
```

### 已知限制

- **多格式订阅自动转换**：订阅链接支持 **Clash YAML / base64 订阅 / URI 直链 / JSON(SIP008)**，容器内 `mihomo-build-config.js` 自动识别并转换为最小 Clash 配置（`url-test` 自动选最快节点 + `MATCH,PROXY`）。节点协议支持 **ss / vmess / trojan / vless / hysteria2(hy2)**。无需订阅转换工具，Clash Verge 能导入的订阅链接本站也能用。
- `/dev/net/tun` 依赖：Docker Desktop（Win/macOS）LinuxKit VM 内置；原生 Linux 需 tun 内核模块（通常内置）。仅启用代理时才挂载，不影响纯直连。
- mihomo 日志：容器内 `/home/AISC/.mihomo/mihomo.log`，代理异常时优先查此。TUN 接口名为 `Meta`（非 `tun0`），`ip -br link | grep -i meta` 可查其状态。
- 自定义 mihomo 版本：`docker build -f image/Dockerfile --build-arg MIHOMO_VERSION=v1.x.x .`；指定单一镜像前缀：`--build-arg GH_PROXY=https://ghfast.top/`；海外直连：`--build-arg GH_PROXY= --build-arg USE_CN_MIRROR=0`。
- **构建零 GitHub 依赖**：mihomo 二进制 + geodata 已预下载到 `image/downloads/` 并**纳入 git**（同 `image/_bundle` 哲学），`docker build` 完全不访问 GitHub，国内网络无忧。升级 mihomo：改 `image/Dockerfile` 的 `MIHOMO_VERSION` 后跑 `bash tools/stage-mihomo.sh` 更新 `image/downloads/` 再提交。若 `image/downloads/` 被清空，构建自动回退多镜像下载（`ghfast.top` 优先 + `--http1.1` + 直连兜底）。
- **转换局限**：自动转换生成的是最小配置（自动选最快节点 + 全流量走代理），不含原订阅的分流规则/分组。若需精细分流，仍可直接提供 Clash YAML 直链（原样使用，仅注入 TUN）。

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
改 image/Dockerfile / 技能 → docker build -f image/Dockerfile .（.factory-version 自动变）
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
.claude/mihomo/ Mihomo 代理配置（用户原始 config.yaml，订阅凭据敏感，gitignore）
                容器内 ro 挂载至 /etc/mihomo/config.yaml，TUN 块由 entrypoint 注入
.cc-config/     cs 运行配置：settings.json(env) + api-keys（密钥，gitignore）
```

容器包含：

| 层级 | 内容 |
|------|------|
| 基础镜像 | `node:20-slim`（`--build-arg NODE_IMAGE=` 可换源）|
| 网络优化 | `USE_CN_MIRROR=1` → apt 清华 + npm 淘宝（可关）|
| 运行时 | Claude Code 全局安装（`/home/AISC/.claude` 内置完整配置）|
| Python | python3 3.11 + pip + 默认 venv `/home/AISC/.venv`（PATH 头，`pip install` 直达，绕过 PEP 668）|
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
├── README.md                   # 项目说明（GitHub 显示）
├── start.bat                   # Windows 入口（ASCII 薄壳 → scripts/run.ps1）
├── start.sh                    # Linux/macOS 入口（薄壳 → scripts/run.sh）
├── start.command               # macOS 双击入口（透传 start.sh）
├── skills-lock.json            # skills 锁文件
├── image/                      # ★ 镜像构建上下文（Dockerfile + 全部 COPY 源）
│   ├── Dockerfile              #   多阶段：插件注入 + 解符号链接 + 版本戳
│   ├── entrypoint.sh           #   作用域 + .claude 复制/校验 + Mihomo TUN + env 注入 + 启动菜单
│   ├── mihomo-build-config.js  #   订阅格式转换 + TUN/DNS 强制注入（容器内运行）
│   ├── claude-switch           #   cs：后端切换 / upgrade / show
│   ├── claude-wrapper          #   claude 包装器：启动注入 env
│   ├── claude-settings.json    #   CLI settings（enabledPlugins + marketplaces + statusLine）
│   ├── global-claude.md        #   全局 CLAUDE.md
│   ├── commands/               #   gstack 6 个斜杠命令
│   ├── _bundle/                #   内置插件 + gstack 文档（纳入 git → 自包含构建）
│   └── downloads/              #   mihomo 二进制 + geodata 预置（纳入 git → 国内网络零 GitHub 依赖）
├── scripts/                    # 启动器流水线模块（低耦合；状态经 .deploy/state.env 解耦）
│   ├── run.sh / run.ps1        #   编排器：初始化 state + 按序调 01→04，失败即中止
│   ├── 01_check_env.*          #   环境检测（docker 已装且 daemon 运行）
│   ├── 02_config_wizard.*      #   代理 TUI → .claude/mihomo/config.yaml + state(PROXY_ENABLED)
│   ├── 03_build_image.*        #   镜像菜单 + 构建 → state(IMAGE, DO_RUN)
│   ├── 04_launcher.*           #   读 state → docker run（按需加 NET_ADMIN/tun/挂载）
│   └── _state.*                #   状态文件读写助手（KEY=value，两平台共读共写）
├── tools/                      # 一次性生成器
│   ├── stage-skills.sh         #   从 ~/.claude 暂存插件/技能到 image/_bundle
│   └── stage-mihomo.sh         #   预下载 mihomo+geodata 到 image/downloads（弱网/离线兜底）
└── docs/                       # 文档
    ├── devlog.md               #   开发日志
    ├── plans/                  #   设计方案（PLAN-*.md）
    └── TODO/                   #   待办 + 日期归档
```

## 启动器架构（v1.3.0 模块化）

启动器已从单体脚本拆为 4 个低耦合生命周期模块，按流水线执行，模块间用 `.deploy/state.env`（KEY=value，gitignored）解耦传参：

```
入口(.sh/.bat) → run.* 编排器 → 01_check_env → 02_config_wizard → 03_build_image → 04_launcher
                                  (docker?)      (代理TUI)          (镜像构建)        (docker run)
```

- **状态契约**：`state.env` 只存简单值 `IMAGE` / `PROXY_ENABLED` / `CONTAINER_NAME` / `DO_RUN`；路径不入状态，各模块从自身位置推导 `PROJECT_ROOT`。
- **跨平台**：bash 模块（Linux/macOS）+ PowerShell 模块（Windows，UTF-8 BOM）平行；`.bat` 为纯 ASCII 薄壳（规避 cmd 中文 DBCS 解析缺陷）。
- **行为不变**：根文件名 + 双击入口不变；代理 TUI / 构建菜单 / docker run 参数等价迁移。API Key 仍在容器内 `cs`，作用域仍在 entrypoint。

## 许可证

MIT
