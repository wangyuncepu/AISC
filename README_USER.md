# AISC 用户手册

AISC 是一个在 Docker 容器中运行 Claude Code 的个人开发工具。提供 `aisc` 命令行，可在宿主机上构建镜像、管理容器、切换 AI 模型服务。

> **状态：Alpha / 开发中。** 当前版本 `v2.0.2-dev`。

## v2.0.2-dev 更新内容

### 新增功能

- **Windows 安装器支持自定义目录**
  - setup.exe 现在允许用户在安装向导中选择安装位置
  - 默认位置仍为 `%LOCALAPPDATA%\Programs\AISC`
  
- **`--keep-alive` 参数**：`aisc run` 现在支持 `--keep-alive` 标志
  - 默认行为：容器退出时自动删除（`--rm`）
  - 使用 `--keep-alive`：容器退出后保持，便于调试或重用
  - 示例：`aisc run --keep-alive`

- **完整的容器和镜像 CRUD 操作**：
  - 容器操作：`list_containers`、`stop_container`、`remove_container`、`inspect_container`
  - 镜像操作：`list_images`、`remove_image`、`pull_image`、`tag_image`
  - 所有 Docker 操作统一整合在 `docker_.py` 模块

### 改进

- **镜像检测逻辑**：`aisc build` 在构建前检查镜像是否存在
  - 存在时显示警告：可能产生悬空 `<none>` 镜像
  - 建议先删除旧镜像或使用不同标签
  
- **简化 run 命令**：`aisc run` 不再自动构建镜像
  - 镜像不存在时报错，提示用户先执行 `aisc build`
  - 更明确的工作流程：先 build，后 run
  
- **修复 Windows 兼容性**：处理 `os.getuid()`/`os.getgid()` 在 Windows 上不存在的问题
- **修复挂载权限问题**：自动使用宿主机用户的 uid:gid 运行容器（仅 Unix 系统），确保挂载文件可正常读写
- **CI/CD 优化**：
  - 所有分支推送都运行语法检查和测试
  - 只有带 `v*` 标签时才构建和发布二进制包

## 目录

- [安装](#安装)
  - [前置条件](#前置条件)
  - [方式一：GitHub Release 安装包（推荐）](#方式一github-release-安装包推荐)
    - [Windows](#windows)
    - [macOS](#macos)
    - [Linux](#linux)
  - [方式二：从源码安装（开发者 / 高级用户）](#方式二从源码安装开发者--高级用户)
- [快速开始](#快速开始)
- [工作流程](#工作流程)
- [配置位置](#配置位置)
- [命令手册](#命令手册)
  - [全局选项](#全局选项)
  - [version — 版本信息](#version--版本信息)
  - [doctor — 环境诊断](#doctor--环境诊断)
  - [build — 构建镜像](#build--构建镜像)
  - [run — 运行容器](#run--运行容器)
  - [ps — 列出所有容器](#ps--列出所有容器)
  - [status — 容器状态](#status--容器状态)
  - [stop — 停止容器](#stop--停止容器)
  - [restart — 重启容器](#restart--重启容器)
  - [shell — 进入容器 Shell](#shell--进入容器-shell)
  - [switch — 切换 AI 后端](#switch--切换-ai-后端)
  - [config — 配置管理](#config--配置管理)
  - [provider — Provider 管理](#provider--provider-管理)
  - [profile — Profile 管理](#profile--profile-管理)
  - [brief — AI 资讯简报](#brief--ai-资讯简报)
  - [skill — Skill 管理](#skill--skill-管理)
- [升级](#升级)
- [卸载](#卸载)
- [常见故障](#常见故障)
- [许可](#许可)

## 安装

### 前置条件

**必须安装 Docker。** Windows 安装程序、macOS PKG 和各平台便携包运行时无需 Python、uv 或 Git。

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

从 [GitHub Release v2.0.2-dev](https://github.com/wangyuncepu/AISC/releases/tag/v2.0.2-dev) 下载对应平台的安装包。

当前版本已作为 GitHub **Pre-release** 发布；普通用户直接从上面的 Release 页面下载即可，无需进入 Actions 页面。

#### Windows

下载 `AISC-2.0.2-dev-windows-x86_64-setup.exe`，双击运行。

- **仅支持 x86_64**；ARM Windows 不支持。
- **安装向导支持自定义目录**：
  - 默认位置：`%LOCALAPPDATA%\Programs\AISC`（通常为 `C:\Users\<用户名>\AppData\Local\Programs\AISC`）
  - 可在安装向导中修改为任意目录
- 安装内容：
  - `aisc.exe`：主可执行文件
  - `aisc-bundle\`：运行时依赖文件（Dockerfile、配置等）
- 自动将安装目录加入用户 PATH（安装后**重新打开终端**生效）。
- 验证安装：打开新的 PowerShell 或 CMD 窗口，运行 `aisc version`
- 通过 **设置 → 应用 → 已安装的应用** 或 **控制面板 → 程序和功能** 卸载。
- 卸载会移除程序文件和 PATH 条目，**不删除** `%USERPROFILE%\.aisc`、`.cc-config` 或 Docker 资源。

> **未签名提示：** AISC 尚未经代码签名。首次运行时 Windows SmartScreen 可能弹出"Windows 保护了你的电脑"，点击 **更多信息 → 仍要运行**。
>
> **找不到安装文件？** 在文件资源管理器地址栏中输入 `%LOCALAPPDATA%\Programs\AISC` 并回车，即可直接打开默认安装目录。

备用：ZIP 便携版

```powershell
Expand-Archive AISC-2.0.2-dev-windows-x86_64.zip -DestinationPath .
cd AISC-2.0.2-dev-windows-x86_64
.\aisc.exe version
```

`aisc.exe` 与 `aisc-bundle\` 目录必须保持在同一父目录下。

#### macOS

##### 安装程序（推荐）

下载 `AISC-2.0.2-dev-macos-arm64.pkg`，双击运行。

- **仅支持 Apple Silicon（arm64）**；Intel Mac 不支持。
- 需**管理员密码**（安装到 `/usr/local/`）。
- 安装路径：
  - 可执行文件：`/usr/local/lib/aisc/aisc`
  - Bundle：`/usr/local/lib/aisc/aisc-bundle/`
  - 符号链接：`/usr/local/bin/aisc` → `../lib/aisc/aisc`
- `/usr/local/bin` 默认在 macOS PATH 中，安装后**新开终端**即可使用。
- 卸载：`sudo /usr/local/lib/aisc/uninstall.sh`（移除文件、符号链接和 pkg 收据；**不删** `~/.aisc`、`~/.cc-config`）。
- 升级：双击新版 `.pkg` 覆盖安装。

> **未签名提示：** AISC 尚未经 Apple 开发者签名。首次双击 `.pkg` 时，macOS Gatekeeper 可能阻止运行。前往 **系统设置 → 隐私与安全性**，滚动到底部点击 **"仍要打开"**。不要全局关闭 Gatekeeper（`spctl --master-disable`）。

##### 便携版（备用）

```bash
tar -xzf AISC-2.0.2-dev-macos-arm64.tar.gz
cd AISC-2.0.2-dev-macos-arm64
./aisc version
```

#### Linux

下载 `AISC-2.0.2-dev-linux-x86_64.tar.gz`，解压使用：

```bash
tar -xzf AISC-2.0.2-dev-linux-x86_64.tar.gz
cd AISC-2.0.2-dev-linux-x86_64
./aisc version
```

或使用安装脚本安装到 `~/.local/share/AISC`：

```bash
# install.sh / uninstall.sh 位于 AISC 源码仓库的 packaging/ 目录
git clone --depth 1 https://github.com/wangyuncepu/AISC.git
cd AISC
bash packaging/install.sh ~/Downloads/AISC-2.0.2-dev-linux-x86_64.tar.gz
```

安装脚本会：
- 解压到 `~/.local/share/AISC/`
- 创建符号链接 `~/.local/bin/aisc`
- 确保 `~/.local/bin` 在 PATH 中（手动添加到 shell rc 文件）

卸载：

```bash
bash packaging/uninstall.sh
```

### 方式二：从源码安装（开发者 / 高级用户）

需要 Python 3.11+：

```bash
git clone https://github.com/wangyuncepu/AISC.git
cd AISC
pip install -e .
aisc version
```

## 快速开始

安装完成后，验证 Docker 和 AISC：

```bash
# 确认 Docker 可用
docker version

# 确认 AISC 安装成功
aisc version

# 检查环境
aisc doctor
```

**首次使用的完整工作流程：**

```bash
# 1. 进入工作目录
cd ~/my-project

# 2. 构建 Docker 镜像（首次构建需 5-15 分钟）
aisc build

# 3. 运行容器
aisc run

# 容器启动后，在容器内：
cs deepseek    # 配置 DeepSeek API
claude         # 启动 Claude Code
```

## 工作流程

### 镜像与容器的关系

```
aisc build → Docker 镜像（模板，只需构建一次）
             ↓
aisc run   → Docker 容器（运行实例，可创建多个）
```

### 典型工作流程

**首次使用：**

1. `aisc build` — 构建镜像（5-15 分钟，下载依赖）
2. `aisc run` — 启动容器
3. 在容器内配置 API 并使用 Claude Code

**日常使用：**

1. `aisc run` — 直接启动容器（镜像已存在）
2. 工作完成后退出容器

**更新镜像：**

1. `git pull` — 更新 AISC 代码
2. `aisc build --no-cache` — 重新构建镜像
3. `aisc run` — 使用新镜像

### 镜像管理最佳实践

**避免悬空镜像：**

```bash
# 方式1：删除旧镜像后重建
docker rmi super-claude:latest
aisc build

# 方式2：使用新标签
aisc build --tag super-claude:v2
aisc run --image super-claude:v2
```

**`aisc build` 的行为：**
- 构建前检查镜像是否已存在
- 存在时显示警告（可能产生 `<none>` 悬空镜像）
- 不会自动删除旧镜像或询问用户
- 直接执行构建命令

**`aisc run` 的行为：**
- 检查指定镜像是否存在
- **不存在时报错**，提示用户先执行 `aisc build`
- 不会自动构建镜像

## 配置位置

AISC 支持两种配置作用域：

| 作用域 | 配置位置 | 保存内容 | 适用场景 |
| --- | --- | --- | --- |
| **临时（temp）** | 容器内 `/home/AISC/.claude` | 仅在容器内，退出即失 | 临时试用、一次性任务 |
| **项目（project）** | 工作区 `.claude/` 目录 | 持久化到宿主机 | 长期项目、配置共享 |

首次运行时会提示选择作用域。选择"项目"后：
- `.claude` 目录会创建在工作区中
- 配置、技能、会话历史都会保存到宿主机
- 多个容器可共享同一配置

## 命令手册

### 全局选项

```bash
aisc [GLOBAL_OPTIONS] <command> [ARGS]
```

全局选项：
- `--aisc-root <path>` — 指定 AISC 根目录（包含 container/Dockerfile）
- `--output json` — 输出 JSON 格式（机器可读）
- `--output text` — 输出文本格式（默认，人类可读）
- `--help` — 显示帮助
- `--version` — 显示版本

### version — 版本信息

显示 AISC CLI、Python、Bundle、Claude Code 的版本。

```bash
aisc version [--output json|text]
```

示例输出：

```
AISC CLI version  : 2.0.2-dev
Python version     : 3.11.5
Bundle version     : 2.0.2-dev
Claude Code version: (not found)
```

### doctor — 环境诊断

检查 Docker、镜像、容器、配置文件等的健康状态。

```bash
aisc doctor [--output json|text]
```

检查项：
- Docker CLI 可用性
- Docker daemon 连接
- 默认镜像是否存在
- 运行中的容器
- 配置文件完整性

### build — 构建镜像

构建 Docker 镜像。**镜像存在时会显示警告，但仍继续构建。**

```bash
aisc build [OPTIONS]
```

选项：
- `--tag <name>` — 镜像标签（默认：`super-claude:latest`）
- `--no-cache` — 不使用缓存，完全重新构建
- `--pull` — 构建前拉取最新基础镜像
- `--dry-run` — 仅显示构建命令，不执行

示例：

```bash
# 默认构建
aisc build

# 完全重新构建（不使用缓存）
aisc build --no-cache

# 使用自定义标签
aisc build --tag super-claude:dev

# 查看构建命令
aisc build --dry-run
```

**行为说明：**
1. 检查镜像是否已存在
2. 存在时显示警告：
   ```
   ⚠️  Image already exists: super-claude:latest
      Building will replace it (may create dangling <none> images).
      Tip: Use 'docker rmi {tag}' before build, or use a different tag.
   ```
3. 继续执行构建

**避免悬空镜像：**
```bash
# 删除旧镜像后重建
docker rmi super-claude:latest
aisc build

# 或使用新标签
aisc build --tag super-claude:v2
```

### run — 运行容器

启动 Docker 容器。**镜像必须已存在，否则报错。**

```bash
aisc run [OPTIONS]
```

选项：
- `--image <name>` — 使用的镜像（默认：`super-claude:latest`）
- `--workspace <path>` — 挂载的工作区目录（默认：当前目录）
- `--name <prefix>` — 容器名前缀（默认：`super-claude-station`）
- `--network <mode>` — 网络模式：`direct`（默认）或 `proxy`
- `--keep-alive` — 容器退出后保留（不使用 `--rm`）
- `--dry-run` — 仅显示运行命令，不执行

示例：

```bash
# 默认运行
aisc run

# 指定工作区
aisc run --workspace ~/my-project

# 使用特定镜像
aisc run --image super-claude:dev

# 保留容器用于调试
aisc run --keep-alive

# 启用代理网络
aisc run --network proxy

# 查看运行命令
aisc run --dry-run
```

**行为说明：**
1. 检查指定镜像是否存在
2. **不存在时报错并退出：**
   ```
   Image 'super-claude:latest' not found. Please build it first:
     aisc build --tag super-claude:latest
   Or specify an existing image with --image <name>.
   ```
3. 镜像存在时启动容器

**容器生命周期：**
- 默认行为（无 `--keep-alive`）：容器退出后自动删除（`docker run --rm`）
- 使用 `--keep-alive`：容器退出后保留，可用 `docker start` 重启或 `docker rm` 删除

### ps — 列出所有容器

列出所有 AISC 管理的容器（运行中和已停止的）。

```bash
aisc ps [--output json|text]
```

示例输出：

```
CONTAINER ID   NAME                        STATUS      IMAGE                  WORKSPACE
a1b2c3d4e5f6   super-claude-station-12ab   Up 2 hours  super-claude:latest    /home/user/project
```

### status — 容器状态

显示指定容器的详细状态。

```bash
aisc status [CONTAINER_NAME_OR_ID] [--output json|text]
```

省略容器名时使用默认容器。

### stop — 停止容器

停止运行中的容器。

```bash
aisc stop [CONTAINER_NAME_OR_ID]
```

选项：
- `--timeout <seconds>` — 强制停止前等待的秒数（默认：10）

### restart — 重启容器

重启容器（先停止，再启动）。

```bash
aisc restart [CONTAINER_NAME_OR_ID]
```

### shell — 进入容器 Shell

在运行中的容器内打开交互式 shell。

```bash
aisc shell [CONTAINER_NAME_OR_ID]
```

示例：

```bash
aisc shell
# 进入容器后
cs deepseek
claude
```

### switch — 切换 AI 后端

**注意：此命令在容器内运行，不是 `aisc` 的子命令。**

在容器内使用 `cs` 命令切换 AI 后端：

```bash
cs <provider>  # anthropic, openai, deepseek, 等
```

### config — 配置管理

管理 AISC 配置文件。

```bash
aisc config [SUBCOMMAND]
```

子命令：
- `show` — 显示当前配置
- `set <key> <value>` — 设置配置项
- `get <key>` — 获取配置项
- `unset <key>` — 删除配置项

### provider — Provider 管理

管理 AI provider 配置（API 端点、密钥等）。

```bash
aisc provider [SUBCOMMAND]
```

子命令：
- `list` — 列出所有 provider
- `add <name>` — 添加新 provider
- `remove <name>` — 删除 provider
- `show <name>` — 显示 provider 详情

### profile — Profile 管理

管理 AI 模型配置文件（model、temperature 等参数）。

```bash
aisc profile [SUBCOMMAND]
```

子命令：
- `list` — 列出所有 profile
- `show <name>` — 显示 profile 详情
- `create <name>` — 创建新 profile

### brief — AI 资讯简报

获取 AI 领域最新资讯摘要。

```bash
aisc brief [OPTIONS]
```

选项：
- `--days <n>` — 过去 n 天的资讯（默认：7）
- `--sources <list>` — 指定资讯来源

### skill — Skill 管理

管理 Claude Code skills。

```bash
aisc skill [SUBCOMMAND]
```

子命令：
- `list` — 列出所有已安装的 skill
- `install <name>` — 安装 skill
- `uninstall <name>` — 卸载 skill
- `update <name>` — 更新 skill

## 升级

### 更新 AISC CLI

**使用安装包的用户：**

1. 从 [GitHub Release](https://github.com/wangyuncepu/AISC/releases) 下载新版安装包
2. 运行安装包（Windows/macOS 会覆盖安装，Linux 先卸载旧版）

**从源码安装的用户：**

```bash
cd AISC
git pull
pip install -e . --force-reinstall
```

### 更新 Docker 镜像

```bash
cd AISC
git pull
aisc build --no-cache
```

## 卸载

### Windows

1. 打开 **设置 → 应用 → 已安装的应用**
2. 搜索 "AISC"
3. 点击 **卸载**

或使用控制面板：

1. **控制面板 → 程序和功能**
2. 找到 "AISC"
3. 右键 → **卸载**

卸载后手动清理（可选）：

```powershell
# 删除配置目录
Remove-Item -Recurse -Force $env:USERPROFILE\.aisc
Remove-Item -Recurse -Force $env:USERPROFILE\.cc-config

# 删除 Docker 资源
docker rmi super-claude:latest
docker system prune -a
```

### macOS

```bash
sudo /usr/local/lib/aisc/uninstall.sh
```

手动清理（可选）：

```bash
rm -rf ~/.aisc ~/.cc-config
docker rmi super-claude:latest
docker system prune -a
```

### Linux

```bash
# 使用安装脚本的用户
bash packaging/uninstall.sh

# 手动安装的用户
rm -rf ~/.local/share/AISC
rm -f ~/.local/bin/aisc

# 清理配置和 Docker 资源（可选）
rm -rf ~/.aisc ~/.cc-config
docker rmi super-claude:latest
docker system prune -a
```

## 常见故障

### Docker 相关

**问题：`docker: command not found`**

解决：
- 确认已安装 Docker Desktop（Windows/macOS）或 Docker Engine（Linux）
- Windows：确认 Docker Desktop 正在运行
- Linux：确认 Docker 服务已启动：`sudo systemctl start docker`

**问题：`permission denied while trying to connect to Docker daemon`**

解决（Linux）：

```bash
sudo usermod -aG docker $USER
# 注销并重新登录，或运行：
newgrp docker
```

**问题：`Cannot connect to the Docker daemon`**

解决：
- Windows/macOS：启动 Docker Desktop
- Linux：`sudo systemctl start docker`

### 镜像和容器

**问题：`Image 'super-claude:latest' not found`**

解决：

```bash
aisc build
```

**问题：构建镜像时提示悬空镜像警告**

这是正常行为。解决方案：

```bash
# 方式1：删除旧镜像后重建
docker rmi super-claude:latest
aisc build

# 方式2：使用新标签
aisc build --tag super-claude:v2
aisc run --image super-claude:v2

# 方式3：忽略警告，继续构建（会产生 <none> 镜像）
aisc build
# 事后清理悬空镜像：
docker image prune
```

**问题：容器启动后立即退出**

解决：

```bash
# 查看容器日志
docker logs <container-id>

# 使用 --keep-alive 保留容器进行调试
aisc run --keep-alive
```

**问题：工作区文件权限错误**

这通常在 Linux 上发生。已在 v2.0.2-dev 中修复（容器自动使用宿主机 uid:gid）。

如果仍有问题：

```bash
# 检查工作区权限
ls -la

# 确保当前用户有读写权限
chmod -R u+rw .
```

### 配置和 API

**问题：API Key 不生效**

解决：

1. 确认配置作用域正确（project vs temp）
2. 检查 `.claude` 目录位置：
   ```bash
   # 项目作用域
   ls -la .claude
   
   # 查看配置文件
   cat .claude/.claude.json
   ```
3. 重新配置 API Key：
   ```bash
   cs <provider>
   ```

**问题：容器内无法访问外网**

解决：

```bash
# 检查 Docker 网络
docker network ls

# 尝试使用 host 网络（仅 Linux）
docker run --network host ...

# 或使用代理模式
aisc run --network proxy
```

### Windows 特定问题

**问题：安装时提示"Windows 保护了你的电脑"**

这是正常的 SmartScreen 警告（AISC 未签名）。

解决：点击 **更多信息 → 仍要运行**。

**问题：找不到安装目录**

默认位置：`%LOCALAPPDATA%\Programs\AISC`

在文件资源管理器地址栏输入并回车即可打开。

**问题：PATH 未生效**

安装后需要**重新打开终端窗口**。

验证：

```powershell
echo $env:PATH | Select-String AISC
```

### macOS 特定问题

**问题：无法打开 .pkg 文件**

这是 Gatekeeper 阻止未签名应用。

解决：
1. 前往 **系统设置 → 隐私与安全性**
2. 滚动到底部
3. 点击 **"仍要打开"**

**不要**全局关闭 Gatekeeper。

**问题：`aisc: command not found`（安装后）**

解决：

```bash
# 确认符号链接存在
ls -l /usr/local/bin/aisc

# 确认 /usr/local/bin 在 PATH 中
echo $PATH | grep /usr/local/bin

# 如果不在，添加到 shell rc 文件
echo 'export PATH="/usr/local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

## 许可

MIT License. 详见 [LICENSE](LICENSE)。

## 相关资源

- [AISC 项目首页](https://github.com/wangyuncepu/AISC)
- [Claude Code 官方文档](https://docs.anthropic.com/claude/docs/claude-code)
- [Docker 文档](https://docs.docker.com/)
- [问题反馈](https://github.com/wangyuncepu/AISC/issues)
