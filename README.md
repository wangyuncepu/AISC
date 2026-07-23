# AISC 用户手册

AISC 是一个在 Docker 容器中运行 Claude Code 和 OpenAI Codex 的个人开发工具。提供 `aisc` 命令行，可在宿主机上构建镜像、管理容器、切换 AI 模型服务。

> **状态：Alpha / 开发中。** 当前稳定版本为 **v2.1.3**；项目版本以仓库根目录 [`VERSION`](VERSION) 为唯一事实源。

## v2.1.3 版本要点

- 容器统一以 `root` 运行，宿主工作区固定挂载到 `/root/app`，并设置 `IS_SANDBOX=1`。
- Claude 与 Codex 的 Provider、代理路由和 skills 统一交给 cc-switch 管理，不再维护第二套 AISC Provider、密钥或 `cs` 快捷命令。
- 项目作用域把 `.claude`、`.codex` 和 `.cc-switch` 保存在宿主工作区；临时作用域使用 `/tmp/aisc-home`，容器退出后重置。
- cc-switch 离线登记并以 copy 模式同步 caveman、document-skills、grill-me、superpowers，Claude 与 Codex 共用同一组启用状态。
- `VERSION` 同时驱动 CLI、wheel、PyInstaller、bundle、安装包和 Git 标签；Windows checkout 的 vendored 文件行尾也已固定，避免跨平台 SHA256 漂移。
- 推送 `v*` 标签后，GitHub Actions 自动构建 Linux x86_64、Windows x86_64 和 macOS arm64 产物并发布 Release；带 `-dev` 的标签发布为 Pre-release。

## 目录

- [v2.1.3 版本要点](#v213-版本要点)
- [安装](#安装)
  - [前置条件](#前置条件)
  - [方式一：GitHub Release 安装包（推荐）](#方式一github-release-安装包推荐)
    - [Windows](#windows)
    - [macOS](#macos)
    - [Linux](#linux)
  - [方式二：从源码安装（开发者 / 高级用户）](#方式二从源码安装开发者--高级用户)
- [快速开始](#快速开始)
- [配置位置](#配置位置)
- [命令手册](#命令手册)
  - [全局选项](#全局选项)
  - [version — 版本信息](#version--版本信息)
  - [doctor — 环境诊断](#doctor--环境诊断)
  - [build — 构建镜像](#build--构建镜像)
  - [run — 运行容器](#run--运行容器)
  - [status — 容器状态](#status--容器状态)
  - [stop — 停止容器](#stop--停止容器)
  - [restart — 重启容器](#restart--重启容器)
  - [shell — 进入容器 Shell](#shell--进入容器-shell)
  - [switch — 切换 AI 后端](#switch--切换-ai-后端)
  - [config — 配置管理](#config--配置管理)
  - [cc-switch — Provider 与 Skill 管理](#cc-switch--provider-与-skill-管理)
  - [profile — Profile 管理](#profile--profile-管理)
- [升级](#升级)
- [卸载](#卸载)
- [常见故障](#常见故障)
- [许可](#许可)

## 安装

### 前置条件

**必须安装 Docker。** Windows 安装程序、macOS PKG 和各平台便携包运行时无需 Python、uv 或 Git。Linux/macOS 如果选择仓库中的安装脚本，还需要 Git 获取脚本。

| 平台 | Docker | 说明 |
| --- | --- | --- |
| Windows | Docker Desktop | 启动后等待 daemon ready |
| macOS | Docker Desktop | 启动后等待 daemon ready |
| Linux | Docker Engine | 当前用户需加入 `docker` 组 |

验证：

```bash
docker version
```

### 方式一：GitHub Release 安装包（推荐）

从 [GitHub Releases](https://github.com/wangyuncepu/AISC/releases) 下载目标版本对应平台的安装包。发布标签使用 `v<VERSION>`，安装包文件名使用 `VERSION` 中的值（不带前导 `v`）。

`v2.1.3` 是稳定 Release；带 `-dev` 后缀的历史版本显示为 Pre-release。普通用户直接从上面的 Release 页面下载即可，无需进入 Actions 页面。

#### Windows

下载 `AISC-<VERSION>-windows-x86_64-setup.exe`，双击运行。

- **仅支持 x86_64**；ARM Windows 不支持。
- 默认安装到 `%LOCALAPPDATA%\Programs\AISC`。
- 自动将安装目录加入用户 PATH（安装后**重新打开终端**生效）。
- 通过 **设置 → 应用 → 已安装的应用** 或 **控制面板 → 程序和功能** 卸载。
- 卸载会移除程序文件和 PATH 条目，**不删除** `%USERPROFILE%\.aisc`、工作区中的 `.cc-switch` 或 Docker 资源。

> **未签名提示：** AISC 尚未经代码签名。首次运行时 Windows SmartScreen 可能弹出“Windows 保护了你的电脑”，点击 **更多信息 → 仍要运行**。

备用：ZIP 便携版

```powershell
Expand-Archive AISC-*-windows-x86_64.zip -DestinationPath .
cd AISC-*-windows-x86_64
.\aisc.exe version
```

`aisc.exe` 与 `aisc-bundle\` 目录必须保持在同一父目录下。

#### macOS

##### 安装程序（推荐）

下载 `AISC-<VERSION>-macos-arm64.pkg`，双击运行。

- **仅支持 Apple Silicon（arm64）**；Intel Mac 不支持。
- 需**管理员密码**（安装到 `/usr/local/`）。
- 安装路径：
  - 可执行文件：`/usr/local/lib/aisc/aisc`
  - Bundle：`/usr/local/lib/aisc/aisc-bundle/`
  - 符号链接：`/usr/local/bin/aisc` → `../lib/aisc/aisc`
- `/usr/local/bin` 默认在 macOS PATH 中，安装后**新开终端**即可使用。
- 卸载：`sudo /usr/local/lib/aisc/uninstall.sh`（移除文件、符号链接和 pkg 收据；**不删** `~/.aisc` 或工作区中的 `.cc-switch`）。
- 升级：双击新版 `.pkg` 覆盖安装。

> **未签名提示：** AISC 尚未经 Apple 开发者签名。首次双击 `.pkg` 时，macOS Gatekeeper 可能阻止运行。前往 **系统设置 → 隐私与安全性**，滚动到底部点击 **“仍要打开”**。不要全局关闭 Gatekeeper（`spctl --master-disable`）。

##### 便携版（备用）

```bash
tar -xzf AISC-*-macos-arm64.tar.gz
cd AISC-*-macos-arm64
./aisc version
```

或使用安装脚本安装到 `$HOME/Library/Application Support/AISC`：

```bash
# install.sh / uninstall.sh 位于 AISC 源码仓库的 packaging/ 目录
git clone --depth 1 https://github.com/wangyuncepu/AISC.git
cd AISC
bash packaging/install.sh ~/Downloads/AISC-*-macos-arm64.tar.gz
bash packaging/uninstall.sh   # 卸载
```

#### Linux

##### tar.gz + 安装脚本

```bash
# 1. 下载 AISC-<VERSION>-linux-x86_64.tar.gz

# 2. 可选的 SHA256 校验
sha256sum -c AISC-*-linux-x86_64.tar.gz.sha256

# 3. 获取仓库中的安装脚本并安装
git clone --depth 1 https://github.com/wangyuncepu/AISC.git
cd AISC
bash packaging/install.sh ~/Downloads/AISC-*-linux-x86_64.tar.gz
```

安装脚本会：
- 将 `aisc` + `aisc-bundle/` 安装到 `${XDG_DATA_HOME:-$HOME/.local/share}/aisc`
- 在 `${XDG_BIN_HOME:-$HOME/.local/bin}/aisc` 创建符号链接
- 支持重复安装；先在临时目录完成 staging，再替换旧安装
- 若 `${XDG_BIN_HOME}` 不在 PATH，提示手动配置

解压直接运行（无需安装脚本）：

```bash
tar -xzf AISC-*-linux-x86_64.tar.gz
cd AISC-*-linux-x86_64
./aisc version
```

> **仅支持 x86_64**；arm64/aarch64 不支持。`aisc` 与 `aisc-bundle/` 必须保持在同一父目录。

卸载：

```bash
bash packaging/uninstall.sh
# 不删除 Docker 镜像/容器、~/.aisc 配置或工作区
```

### 方式二：从源码安装（开发者 / 高级用户）

需要 Python ≥3.11 和 uv。适合需要修改源码或参与开发的用户。

```bash
# 1. 克隆仓库
git clone https://github.com/wangyuncepu/AISC.git AISC
cd AISC

# 2. editable 安装
uv tool install --editable .

# 3. 将 tool bin 加入 PATH
uv tool update-shell
# 重新打开终端生效
```

更新：

```bash
cd /path/to/AISC && git pull
uv tool upgrade aisc  # 如有新增依赖
```

卸载：

```bash
uv tool uninstall aisc
```

> 仓库不可删除或移动（editable 安装记录绝对路径）。如需移动，先 `uv tool uninstall aisc`，移动后重新 `uv tool install --editable .`。

## 快速开始

```bash
# 验证安装
aisc version

# 检查环境（Docker CLI、daemon、权限等）
aisc doctor

# 构建 Docker 镜像（首次约需数分钟，需网络拉取基础镜像）
aisc build

# 前台运行容器（默认挂载当前目录为工作区）
aisc run
```

`aisc run` 是前台命令。运行后在另一个终端可执行：

```bash
aisc status        # 查看容器状态
aisc shell         # 进入容器 Bash
aisc switch        # 打开服务切换界面
```

### 使用 Claude Code 或 Codex

容器启动时会提示选择要使用的 AI CLI：

1. **bash** - 进入命令行，可手动配置后启动任意 CLI
2. **claude** - 直接启动 Claude Code
3. **codex** - 直接启动 OpenAI Codex
4. **cc-switch** - 打开 Provider、代理路由与 Skills 管理界面

默认选择为 **bash**。

你也可以直接指定启动方式：

```bash
# 启动容器，在菜单中选择 2
aisc run

# 启动 Codex
docker exec -it <container-name> codex

# 打开 cc-switch 管理界面
docker exec -it <container-name> cc-switch

# 或在容器内切换
aisc shell
codex   # 启动 Codex
claude  # 启动 Claude
cc-switch  # 管理 Provider、路由与 Skills
```

**Codex 配置说明：**

Codex Provider 与认证信息由 cc-switch 管理。进入容器后先检查或选择 Provider：

```bash
cc-switch -a codex provider list
cc-switch -a codex provider current
cc-switch -a codex provider switch <provider>
cc-switch proxy -a codex enable
```

镜像会在全新 cc-switch 数据库中尝试选择 `codex-official`，但内置条目不包含你的真实凭据。使用官方登录或自定义 API 时，仍需在 cc-switch 中完成 Provider 配置。

Codex 配置目录与 Claude 类似，支持临时模式和项目模式：
- **临时模式**：使用 `/tmp/aisc-home/.codex`，容器退出后重置
- **项目模式**：使用 `/root/app/.codex`，持久化到宿主机工作区；Codex 原生配置文件为 `config.toml`

## 配置位置

| 路径 | 说明 |
| --- | --- |
| `<aisc-root>/config/versions.env` | 镜像版本环境变量（`NODE_IMAGE`、`USE_CN_MIRROR`） |
| `<workspace>/.cc-switch/` | cc-switch 项目配置根（SQLite 数据库、Provider、设置、备份及 skills SSOT） |
| `<workspace>/.claude/` | 项目作用域的 Claude 配置、插件与同步后的 skills |
| `<workspace>/.codex/` | 项目作用域的 Codex 配置与同步后的 skills |
| `<aisc-root>/container/Dockerfile` | 镜像构建文件 |
| `<aisc-root>/.aisc/state.env` | 容器状态（`CONTAINER_NAME`、`IMAGE`，由 `aisc run` 写入） |

`<aisc-root>` 由 `--aisc-root` 显式指定，或自动定位到可执行文件同目录下的 `aisc-bundle/`。

## 命令手册

### 全局选项

所有命令均支持以下选项：

| 选项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--format` | `text` / `json` | `text` | 输出格式。`build`/`run` JSON 模式下 stdout 为纯 JSON envelope，Docker 输出转发到 stderr |
| `--no-color` | flag | `False` | 禁用 ANSI 颜色输出 |
| `--aisc-root PATH` | string | 自动 | 显式指定有效的 AISC 资源根目录；该目录本身须包含 `VERSION`、`container/Dockerfile`、`config/versions.env` |
| `--events` | flag | `False` | 启用 JSONL 事件流（仅 `build` 和 `run` 支持） |

- `--format json` 与 `--events` 互斥，同时指定报错退出（exit 2）。
- `--aisc-root` 支持 “last wins” 语义（无论放在命令前还是命令后，以最后一个为准）。
- 裸 `aisc`（不带子命令）打印帮助。
- 裸分组命令（`aisc config`、`aisc profile`）打印该分组的帮助，exit 0。

### version — 版本信息

```bash
aisc version [--format json]
```

**只读**，不依赖 Docker / 网络。

输出内容：

| 字段 | 说明 |
| --- | --- |
| `cli_version` | CLI 版本号（源自 `VERSION`；PyInstaller 构建时将该文件嵌入可执行文件） |
| `python_version` | Python 运行版本 |
| `bundle_version` | Bundle 中的 VERSION 文件内容 |
| `image_version` | 镜像版本（`IMAGE_VERSION` 来自 `versions.env`） |
| `contract_version` | 契约版本（`CONTRACT_VERSION` 来自 `versions.env`） |
| `claude_version` | 声明的 Claude Code 版本（`CLAUDECODE_VERSION` 来自 `versions.env`） |

退出码：0（成功）或 1（AISC root 未找到等错误）。

### doctor — 环境诊断

```bash
aisc doctor [--format json] [--no-color]
```

**只读**，仅诊断宿主机（无 `--container` 选项）。不依赖 Docker daemon 也会检查（部分检查会 SKIP）。

主要检查 Docker CLI/daemon/权限与 buildx、TUN 设备、Git、AISC 资源根及关键文件、目录可写性和 brief 文件。前置检查失败时，依赖它的后续项目会显示为 SKIP。

文本模式下带 ANSI 颜色标记 PASS（绿）、WARN（黄）、FAIL（红）。

退出码：

| 最高严重级别 | 退出码 |
| --- | --- |
| 全部 PASS 或 WARN | 0 |
| Docker CLI 或 daemon 不可用 | 3（`AISC_ERR_DOCKER_UNAVAILABLE`） |
| Docker 权限不足 | 9（`AISC_ERR_PERMISSION_DENIED`） |
| AISC root 或其他检查失败 | 1（`AISC_ERR_GENERAL`） |

### build — 构建镜像

```bash
aisc build [--tag TAG] [--no-cache] [--pull] [--dry-run]
           [--format json] [--events]
```

**会调用 Docker**（`docker build`），需要 Docker daemon 和网络（拉取基础镜像）。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--tag, -t` | string | `super-claude:latest` | 镜像标签；若不含 `:` 自动追加 `:latest` |
| `--no-cache` | flag | `False` | 禁用 Docker 构建缓存 |
| `--pull` | flag | `False` | 始终拉取基础镜像 |
| `--dry-run` | flag | `False` | 仅输出构建计划（`docker build` 命令行），不执行 |

**效果：**
- 读取 `config/versions.env` 中的 `USE_CN_MIRROR`（默认 `1`）和 `NODE_IMAGE` 作为 build-arg。
- `--dry-run` 模式不调用 Docker，仅输出 `docker build ...` 命令行。
- 非 `--dry-run` 时：
  - `--events` 模式：输出 JSONL 事件流（`build.start` → `build.plan` → `build.step.complete` → `build.complete`/`build.failed`）。
  - 文本模式：Docker 日志实时输出到 stdout。
  - JSON 模式：Docker 输出转发到 stderr，stdout 仅在结束时输出 JSON envelope。

**退出码：**

| 退出码 | 错误码 | 场景 |
| --- | --- | --- |
| 0 | — | 成功 |
| 1 | `AISC_ERR_GENERAL` | 前置条件缺失（Dockerfile 不存在、`NODE_IMAGE` 未配置等） |
| 3 | `AISC_ERR_DOCKER_UNAVAILABLE` | Docker CLI 未找到 |
| 4 | `AISC_ERR_BUILD_FAILED` | Docker 构建失败 |

**示例：**

```bash
# 默认构建
aisc build

# 指定标签
aisc build --tag my-super-claude:v1

# 不缓存、重新拉取基础镜像
aisc build --no-cache --pull

# 仅预览构建计划
aisc build --dry-run

# JSONL 事件流
aisc build --events
```

### run — 运行容器

```bash
aisc run [--image IMAGE] [--workspace PATH] [--name NAME]
         [--network direct|proxy] [--profile proxy] [--non-interactive]
         [--keep-alive] [--dry-run] [--format json] [--events]
```

**会调用 Docker**（`docker run`），需要 Docker daemon。默认容器退出后自动删除（`--rm`）；使用 `--keep-alive` 可保持容器运行。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--image, -i` | string | `super-claude:latest` | Docker 镜像名；若不含 `:` 自动追加 `:latest` |
| `--workspace` | string | 当前目录 | 宿主机工作区路径，bind-mount 进容器 |
| `--name` | string | `super-claude-station` | 容器名前缀（自动追加 8 位随机后缀确保唯一） |
| `--network` | `direct` / `proxy` | `direct` | 网络模式；`proxy` 需 `.claude/mihomo/config.yaml` |
| `--profile` | `proxy` | — | 兼容别名，等价于 `--network proxy`；与 `--network direct` 冲突 |
| `--non-interactive` | flag | `False` | 非交互模式：无 `-it`，stdin=DEVNULL，设置 `AISC_NON_INTERACTIVE=1`、`CLAUDE_SCOPE=project` |
| `--keep-alive` | flag | `False` | 保持容器运行：省略 `--rm`，使用后台模式（`-d`）启动并自动 attach；客户端断开后容器继续运行，不会导致 CPU/Memory 状态变为 N/A |
| `--dry-run` | flag | `False` | 仅输出运行计划，不执行 |

**效果：**
- 生成唯一容器名（`<name>-<8 位 hex>`）。
- 实际启动容器前写入 `<aisc-root>/.aisc/state.env` 中的 `CONTAINER_NAME` 和 `IMAGE`，供其他终端通过 `status`/`shell` 等自动发现。容器退出并由 `--rm` 删除后，该文件可能保留最近一次容器名。
- 将宿主机 `<workspace>/` 挂载到容器 `/root/app`；项目文件及 `.cc-switch`、`.claude`、`.codex` 配置都随工作区持久化。
- 首次启动时将 cc-switch 配置根初始化为 `<workspace>/.cc-switch/`；Provider 只由 cc-switch 的 SQLite 状态管理。
- entrypoint 会以 detach 模式启动 cc-switch daemon，等待其可达，尝试初始化 Codex 当前 Provider，再以 best-effort 方式启用 Claude/Codex 路由。Provider 缺少真实凭据时，路由“已启用”不等于上游模型可用。
- entrypoint 将 caveman、document-skills、grill-me、superpowers 登记到 cc-switch，并以 copy 模式同步给 Claude 和 Codex。
- 交互式启动菜单的第 4 项会直接进入 cc-switch TUI；退出 TUI 即结束该前台容器会话。
- `--dry-run` 只输出 `docker run ...` 命令行，不创建或修改项目配置目录，也不校验本地 proxy 配置文件。
- 非 `--dry-run` 时：
  - 检查 Docker 可用性（preflight）。
  - 检查镜像是否存在（`docker inspect`），不存在则报错（exit 5）。
  - 文本交互模式（默认）：`docker run -it --rm`，stdin/stdout 直通。
  - `--non-interactive` 模式：`docker run --rm`，无 `-it`。
  - JSON / events 模式：Docker 输出转发到 stderr，stdout 纯净。
- 退出后容器自动删除（`--rm`）。

**退出码：**

| 退出码 | 错误码 | 场景 |
| --- | --- | --- |
| 0 | — | 容器正常退出 |
| 1 | `AISC_ERR_GENERAL` | proxy 配置缺失等 |
| 3 | `AISC_ERR_DOCKER_UNAVAILABLE` | Docker CLI 未找到或 daemon 不可达 |
| 5 | `AISC_ERR_IMAGE_NOT_FOUND` | 镜像不存在（先运行 `aisc build`） |
| 9 | `AISC_ERR_PERMISSION_DENIED` | 工作区不可访问 |
| 10 | `AISC_ERR_CONTAINER_FAILED` | 容器以非零退出码退出 |

**示例：**

```bash
# 前台运行（默认当前目录为工作区）
aisc run

# 指定镜像和工作区
aisc run --image my-super-claude:v1 --workspace ~/projects/myapp

# 使用代理网络
aisc run --network proxy

# 非交互模式（脚本/CI）
aisc run --non-interactive

# 预览运行计划
aisc run --dry-run
```

### status — 容器状态

```bash
aisc status [--name NAME] [--format json]
```

**会调用 Docker**（`docker inspect`）。容器不存在返回 `exists=False`（exit 0），daemon 不可达则报错。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--name` | string | 自动发现 | 显式指定容器名；未指定则从 `<aisc-root>/.aisc/state.env` 读取 `CONTAINER_NAME` |

**容器发现优先级：** `--name` 覆盖 → 状态文件（`<aisc-root>/.aisc/state.env`）→ 报错（`AISC_ERR_CONTAINER_NOT_FOUND`）。

文本输出示例：

```
Container:  super-claude-station-a1b2c3d4
Exists:     yes
Running:    running
Status:     running
Image:      super-claude:latest
ID:         a1b2c3d4e5f6
```

### stop — 停止容器

```bash
aisc stop [--name NAME] [--format json]
```

**会调用 Docker**（`docker stop`）。幂等：容器已停止返回成功（`already_stopped: true`）。容器不存在报错。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--name` | string | 自动发现 | 显式指定容器名 |

### restart — 重启容器

```bash
aisc restart [--name NAME] [--format json]
```

**会调用 Docker**（`docker restart`）。容器不存在报错。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--name` | string | 自动发现 | 显式指定容器名 |

### shell — 进入容器 Shell

```bash
aisc shell [--name NAME]
```

**会调用 Docker**（`docker exec -it <name> bash`）。仅支持文本交互模式，`--format json` 和 `--events` 均不支持（报 usage error，exit 2）。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--name` | string | 自动发现 | 显式指定容器名 |

容器必须存在且正在运行，否则报错。

### switch — 切换 AI 后端

```bash
aisc switch [--name NAME] [--quick PROVIDER]
```

**会调用 Docker**（`docker exec`）。仅支持文本交互模式，`--format json` 和 `--events` 均不支持。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--name` | string | 自动发现 | 显式指定容器名 |
| `--quick` | string | — | Provider id 或别名，快速切换（跳过 TUI） |

**效果：**
- 默认（无 `--quick`）：运行 `cc-switch`（全功能 TUI 界面）。
- `--quick` 模式：通过 scope-preserving wrapper 读取 PID 1 的 `CLAUDE_CONFIG_DIR`、`CODEX_CONFIG_DIR` 和 `CC_SWITCH_CONFIG_DIR`，再执行 `cc-switch -a claude provider switch <provider>`。
- 容器必须存在且正在运行。

**示例：**

```bash
# 交互式 TUI 切换
aisc switch

# 快速切换到 DeepSeek
aisc switch --quick deepseek
```

### config — 配置管理

```bash
aisc config validate [--config PATH] [--workspace PATH] [--format json]
aisc config effective [--config PATH] [--workspace PATH] [--format json]
aisc config show      [--config PATH] [--workspace PATH] [--format json]
```

**只读**，不依赖 Docker / 网络。`config show` 是 `config effective` 的别名。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--config` | string | 自动 | 显式指定用户配置文件路径 |
| `--workspace` | string | 自动 | 工作区根路径 |

**子命令：**

| 子命令 | 说明 |
| --- | --- |
| `validate` | 校验配置文件合法性，输出每项来源的状态（FOUND / MISSING / ERROR）、有效性与问题清单 |
| `effective` / `show` | 显示合并后的有效配置（JSON），包含来源、有效值、来源追溯（provenance）和问题清单 |

### cc-switch — Provider 与 Skill 管理

旧的宿主机 Provider 目录和容器快捷命令已经移除。可在容器启动菜单选择 **4** 进入 cc-switch TUI，也可进入容器后直接使用命令：

```bash
# Provider
cc-switch -a claude provider list
cc-switch -a claude provider switch <provider>
cc-switch -a codex provider list
cc-switch -a codex provider switch <provider>

# Skills
cc-switch skills list
cc-switch skills sync
```

Provider、认证信息和路由状态都由 cc-switch 管理。请用 cc-switch TUI 或其 provider 命令新增、编辑和切换 Provider；不要在工作区维护第二份 AISC Provider 配置。

启用或停用 caveman 等 skill 只会改变 agent 的指令/工作流，不会修改 Provider、代理端口或 API 凭据。如果启用 skill 后无法连接模型，应先检查 cc-switch daemon、当前 Provider 和路由，而不是删除 skill。

### profile — Profile 管理

```bash
aisc profile list                 [--format json]
aisc profile show [NAME]          [--format json]
```

**只读**，返回内置 profile（safe / unsafe），无用户自定义 profile。

| 子命令 | 说明 |
| --- | --- |
| `list` | 列出所有可用 Profile（name、description、dangerously_skip_permissions） |
| `show [NAME]` | 查看指定 Profile 详情；NAME 默认 `safe`（可选参数） |

## 升级

### 安装包版（方式一）

下载新版安装包，覆盖安装即可：

- Windows：双击新版 `.exe`
- macOS：双击新版 `.pkg`
- Linux：重新运行 `bash packaging/install.sh <new.tar.gz>`

配置文件、Docker 镜像/容器不受影响。

### 源码版（方式二）

```bash
cd /path/to/AISC
git pull
uv tool upgrade aisc  # 如有新增依赖
```

## 卸载

| 安装方式 | 卸载方法 |
| --- | --- |
| Windows setup.exe | **设置 → 应用 → 已安装的应用** 卸载 |
| macOS pkg | `sudo /usr/local/lib/aisc/uninstall.sh` |
| Linux install.sh | `bash packaging/uninstall.sh` |
| uv tool | `uv tool uninstall aisc` |

卸载**不会删除**以下内容（需手动清理）：
- `~/.aisc/` 配置目录
- 工作区中的 `.cc-switch/` 配置目录
- `~/.cache/ai-brief/` 资讯缓存
- Docker 镜像（`docker rmi`）和容器

## 常见故障

### `aisc: command not found`

- 安装包版：安装后需**重新打开终端**。确认安装目录在 PATH 中。
- Linux 安装脚本：确认 `${XDG_BIN_HOME:-$HOME/.local/bin}` 在 PATH 中。
- 解压直用：使用 `./aisc` 或 `.\aisc.exe`（当前目录路径），而非裸 `aisc`。

### `AISC root not found`

安装包中的 `aisc` 命令依赖可执行文件旁边的 `aisc-bundle/`：
- 确认 `aisc` 与 `aisc-bundle/` 在同一父目录。
- 或用 `--aisc-root` 显式指定资源根目录（通常就是 `aisc-bundle/` 本身）：
  ```bash
  aisc --aisc-root /path/to/install/dir/aisc-bundle version
  ```

### Docker 相关错误

| 错误 | 解决 |
| --- | --- |
| `docker: command not found` | 安装 Docker CLI |
| `permission denied` | Linux：将用户加入 `docker` 组 |
| `Cannot connect to the Docker daemon` | 启动 Docker Desktop/Engine |
| `Image not found` | 先运行 `aisc build` |

### cc-switch daemon 或模型路由不可用

在容器内依次检查：

```bash
cc-switch daemon status
cc-switch proxy show
cc-switch -a claude provider current
cc-switch -a codex provider current
```

- `daemon not reachable`：查看 `/tmp/cc-switch-daemon.log`，并运行 `cc-switch daemon logs` 获取详细日志。
- `Running: no`：daemon 可达后，按需执行 `cc-switch proxy -a claude enable` 或 `cc-switch proxy -a codex enable`。
- Provider 为空或只有无凭据的默认项：先在 cc-switch TUI 或 provider 命令中配置真实上游地址和凭据，再启用路由。
- `cc-switch` 报 `cannot execute: required file not found`：通常是旧镜像或 Windows checkout 的 CRLF shebang；拉取当前版本并重新执行 `aisc build --no-cache`。

### 其他问题

提交 [GitHub Issues](https://github.com/wangyuncepu/AISC/issues)。附上操作系统、Docker 版本、完整报错和复现步骤；**删除 API Key 等敏感信息**。

## 许可

MIT License。详见仓库 [LICENSE](LICENSE)。

## 推荐服务

以下是两个相互独立的第三方服务，链接中含推广或邀请参数。请按实际需求选择，并在使用前自行确认价格、服务条款、适用地区及合规要求。

### Codesome｜Codex 与 Claude Code 二合一服务

Codesome AIO 同时支持 Codex 和 Claude Code。一个 Key 可用于不同客户端和模型场景，例如：

- 在 Claude Code、Claude Desktop 等客户端中配置该 Key，使用 Claude 模型。
- 在 Codex、Codex Desktop 等客户端中配置该 Key，使用 Codex 模型。

#### 购买与开通

通过以下链接在浏览器中打开 Codesome 下单页面：

[前往 Codesome 选购](https://fk.codesome.cn?aff=wvoiJ4PY)

通过此链接下单可享 **5% 折扣**。支付后请妥善保存订单详情中的序列号或卡密。根据所购产品，开通方式有所不同：

- **额度包**：订单中的序列号是兑换码。登录 [Codesome 控制台](https://cc.codesome.ai)，在**兑换区**填写兑换码，兑换成功后美元额度会一次性到账；随后进入**API 密钥**菜单创建专属 API Key。
- **AIO 产品**：收到的卡密就是 Key，格式类似 `codesome_aio_XX: aaaaaaaa aaaaaa`。请完整、妥善地保存，不要公开分享或提交到 Git 仓库。

#### 配置地址

Claude Code 与 Codex 使用不同的 API URL，配置时请勿混用：

| 使用端 | API URL |
| --- | --- |
| Claude Code / Claude | `https://v5.codesome.cn/api` |
| Codex | `https://v5.codesome.cn/openai/` |

Key 可配置到对应的命令行工具或桌面客户端中。具体字段和配置步骤请以 Codesome 最新教程为准。

#### 教程、用量查询与技术支持

可在以下页面查看使用教程，并查询 Key 的用量和当前状态：

[查看教程及 Key 用量状态](https://aio.codesome.ai/admin-next/api-stats)

Codesome 的下单购买、价格、稳定性说明、使用指南、扫码进群和福利领取等信息统一收录在飞书入口：

[打开 Codesome 飞书总入口](https://my.feishu.cn/wiki/Vaifwy0aAisdP8kDLPoc0jV5nCb?from=from_copylink)

详细使用问题请进入 Codesome 飞书群联系工作人员或客服。技术问题统一在飞书群内解答；微信渠道主要用于交友和商务合作。

Codesome 创始人 Mens 专注于 Claude Code 相关产品，并感谢用户对产品的支持。

> API Key 属于敏感凭据。请勿将其粘贴到公开页面、聊天记录或代码仓库中。

### 赔钱机场｜网络连接服务

赔钱机场提供网络连接服务，可用于改善部分网络环境下的访问体验。可通过以下邀请链接注册并查看可用套餐：

[前往赔钱机场注册](https://pqjc.site/register?code=EVYrdlM4&cover=sfw)

请在购买前确认套餐价格、流量限制、节点覆盖、退款政策及当地合规要求。AISC 与该服务相互独立，不对其可用性、稳定性或数据处理方式作保证。
