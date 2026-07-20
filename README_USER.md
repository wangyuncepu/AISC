# AISC — 用户指南

AISC 是一个在 Docker 容器中运行 Claude Code 的个人开发工具。它提供 `aisc` 命令行，可在宿主机上构建镜像、管理容器、切换 AI 模型服务。

> **状态：Alpha / 开发中。** AISC 面向个人和开发环境，不是生产级工作站产品。

## 前置条件

| 依赖 | 说明 |
| --- | --- |
| uv | Python 包管理工具；无需预装 Python，uv 在检测不到兼容 Python（≥3.11）时会自动下载管理。安装见下一节。 |
| Git | 用于克隆仓库；[下载](https://git-scm.com/downloads) |
| Docker | Docker Desktop（Windows/macOS）或 Docker Engine（Linux），daemon 必须启动 |

验证 Docker：

```bash
docker version
```

Linux 用户请注意 Docker 权限问题，必要时将当前用户加入 `docker` 组并重新登录。

## 安装 uv

以下任选一种方式。安装后跳至下一节验证。

### macOS / Linux（bash / zsh）

**官方独立安装脚本（推荐）**：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

如果系统没有 `curl`，可用 `wget`：

```bash
wget -qO- https://astral.sh/uv/install.sh | sh
```

**Homebrew 替代（macOS 或 Linux）**：

```bash
brew install uv
```

### Windows

**PowerShell（推荐）**：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**WinGet 替代**：

```powershell
winget install --id=astral-sh.uv -e
```

**关于 CMD**：官方安装脚本需要 PowerShell。可以先在 CMD 中执行 `powershell` 进入 PowerShell 环境，运行上述安装命令后输入 `exit`，然后重新打开 CMD 并运行 `uv --version`。如果仍找不到 `uv`，按下文的 Windows PATH 指引手动添加其可执行目录。

### 验证 uv

```bash
uv --version
```

## 安装 AISC（一次）

### 1. 克隆仓库

```bash
git clone https://github.com/wangyuncepu/AISC.git AISC
```

### 2. 用 uv 安装为 editable tool

**macOS / Linux（bash / zsh）**：

```bash
cd AISC
uv tool install --editable .
```

**Windows PowerShell**：

```powershell
cd AISC
uv tool install --editable .
```

> Windows 下 `.` 也可以用 `.\`，效果相同。

这一步会：
- 为 `aisc` 创建一个隔离的 Python 环境；
- 将 `aisc` 可执行文件安装到 uv 的 tool bin 目录；
- 保持对仓库源码的实时引用（**仓库不可删除或移动**）。

### 3. 使 `aisc` 在任意目录可用

#### bash / zsh（macOS / Linux）

执行以下命令后，**关闭并重新打开终端**：

```bash
uv tool update-shell
```

如果重新打开终端后仍然找不到 `aisc`，手动将 tool bin 目录加入 PATH：

```bash
# 查看 tool bin 目录的路径
uv tool dir --bin
# 将输出路径（通常为 ~/.local/bin）追加到 ~/.bashrc 或 ~/.zshrc：
# export PATH="$HOME/.local/bin:$PATH"
```

#### PowerShell（Windows）

执行以下命令后，**重新打开 PowerShell**：

```powershell
uv tool update-shell
```

如果仍然找不到 `aisc`，查看 tool bin 目录并手动加入用户 PATH：

```powershell
uv tool dir --bin
```

在 Windows 设置中搜索“编辑系统环境变量”→环境变量→用户变量 `Path`，将上述命令输出的目录添加进去。

#### CMD（Windows）

为避免依赖 shell 自动配置，CMD 用户可直接运行以下命令查看 tool bin 目录：

```cmd
uv tool dir --bin
```

将输出的目录路径手动添加到用户环境变量 `Path` 中：打开 Windows 设置→搜索“编辑系统环境变量”→环境变量→在用户变量中找到 `Path`→编辑→新建→粘贴该路径→确定。然后**重新打开 CMD**，`aisc` 即可使用。

## 首次验证

在仓库目录**之外**运行：

```bash
aisc version
```

预期输出版本信息。再检查环境：

```bash
aisc doctor
```

`aisc doctor` 检查宿主机环境（Docker 可用性、工作区等），不包含 `doctor --container`。

## 日常使用

`aisc` 安装后在**任意目录**均可直接调用，无需激活虚拟环境。

### 基础命令

| 命令 | 说明 |
| --- | --- |
| `aisc version` | 显示 CLI 版本、Python 版本等 |
| `aisc doctor` | 检查宿主机环境 |
| `aisc build` | 构建 Docker 镜像（需要 Docker daemon + 网络） |
| `aisc run` | 以前台方式运行容器（需要 Docker daemon） |
| `aisc brief` | AI 简讯工具（仅文本输出） |
| `aisc --help` | 查看所有命令 |

### 构建与运行

```bash
# 构建镜像
aisc build
aisc build --tag my-image:latest --no-cache
aisc build --dry-run          # 只输出计划，不执行

# 前台运行容器
aisc run
aisc run --image my-image:latest
aisc run --workspace /path/to/project
aisc run --network proxy      # 使用代理网络模式
aisc run --dry-run            # 只输出计划，不执行
```

`aisc build` 和 `aisc run` 都需要 Docker daemon。`aisc run` 是**前台**命令，容器退出后自动删除（`docker run --rm`）。

### 配置与目录

只读查看，不提供写入或切换接口：

| 命令 | 说明 |
| --- | --- |
| `aisc config validate [--config PATH] [--workspace PATH]` | 校验配置 |
| `aisc config effective [--config PATH] [--workspace PATH]` | 显示合并后的有效配置 |
| `aisc config show [--config PATH] [--workspace PATH]` | `config effective` 的别名 |
| `aisc provider list` | 列出可用的模型 Provider 目录 |
| `aisc provider show NAME` | 查看某个 Provider 的详情（NAME 为 id 或别名） |
| `aisc profile list` | 列出可用 Profile |
| `aisc profile show [NAME]` | 查看 Profile（默认 `safe`） |

### 容器生命周期命令

仅在 `aisc run` 在前台运行时有效（另一个终端）：

```bash
aisc status [--name NAME]      # 查看容器状态
aisc stop [--name NAME]        # 停止容器
aisc restart [--name NAME]     # 重启容器
aisc shell [--name NAME]       # 进入容器 Bash（需要容器正在运行）
aisc switch [--name NAME]      # 打开服务切换界面（需要容器正在运行）
aisc switch --quick deepseek   # 快速切换到 DeepSeek
```

### Skill 管理

```bash
aisc skill add URL                  # 从 GitHub URL 导入 Skill（需要网络）
aisc skill list                     # 列出已导入的 Skill
aisc skill remove NAME              # 移除 Skill
aisc skill check                    # 离线核对 Skill 文件完整性
```

导入后需重新构建镜像才能生效。

### 通用选项

| 选项 | 说明 |
| --- | --- |
| `--format text\|json` | 输出格式（默认 text）；`brief`、`shell`、`switch` 仅支持 text |
| `--no-color` | 禁用颜色 |
| `--aisc-root PATH` | 显式指定 AISC 仓库根目录 |
| `--events` | JSONL 事件流输出，仅 `build` 与 `run` 支持 |

## 涉及 Docker / 网络的命令

| 命令 | 需要 Docker | 需要网络 |
| --- | --- | --- |
| `aisc build` | 是 | 是（拉取基础镜像） |
| `aisc run` | 是 | 视网络模式而定 |
| `aisc status` / `stop` / `restart` / `shell` / `switch` | 是 | 否 |
| `aisc skill add` | 否 | 是（从 GitHub 拉取） |
| `aisc brief` | 否 | 需要网络（拉取新闻源） |

其他命令（`version`、`doctor`、`config`、`provider`、`profile`）不依赖 Docker 和网络。

## 更新

### 更新 AISC

```bash
cd /path/to/AISC
git pull
```

由于安装方式为 editable，拉取后源码变更即刻生效，无需重新安装。但如果新增了依赖项：

```bash
uv tool upgrade aisc
```

如果仅更新元数据（如入口点变动）：

```bash
uv tool install --editable /path/to/AISC --force
```

### 更新 uv

更新方式取决于安装来源：

| 安装方式 | 更新命令 |
| --- | --- |
| 官方独立安装脚本（curl/wget/irm） | `uv self update` |
| Homebrew | `brew upgrade uv` |
| WinGet | `winget upgrade --id=astral-sh.uv -e` |

## 移动仓库后的重装

**不可直接移动仓库目录。** 因为 editable 安装记录的是绝对路径，移动后 `aisc` 命令将失效。

正确操作：

**macOS / Linux（bash / zsh）**：

```bash
# 1. 卸载旧安装
uv tool uninstall aisc

# 2. 移动/复制仓库到新位置
mv /old/path/AISC /new/path/AISC

# 3. 在新位置重新安装
cd /new/path/AISC
uv tool install --editable .

# 4. 更新 shell（如果已注册则不需要重复）
uv tool update-shell
```

**Windows PowerShell**：

```powershell
# 1. 卸载旧安装
uv tool uninstall aisc

# 2. 移动仓库到新位置
Move-Item "C:\old\path\AISC" "C:\new\path\AISC"

# 3. 在新位置重新安装
cd "C:\new\path\AISC"
uv tool install --editable .
```

## 卸载

```bash
uv tool uninstall aisc
```

这会移除 `aisc` 命令和对应的隔离环境。仓库目录中的源码和配置文件不会被删除，需要可自行删除。

## 常见故障

### `aisc: command not found`

`uv tool install --editable .` 未执行，或 tool bin 目录未在 PATH 中。

- 确保已执行 `uv tool update-shell` 并重新打开终端
- 运行 `uv tool dir --bin` 查看 bin 目录，确认它已加入 PATH
- 运行 `uv tool list` 确认 `aisc` 已安装

### `AISC root not found`

`aisc` 命令依赖仓库中的结构文件（`VERSION`、`container/Dockerfile`、`config/versions.env`）。可能的原因：

- 运行 `aisc` 时，仓库目录已被移动或删除
- 手动删除了上述必要文件

**解决办法：用 `--aisc-root` 显式指定仓库路径**：

```bash
aisc --aisc-root /path/to/AISC version
```

或设置环境变量 `AISC_ROOT`：

**macOS / Linux（bash / zsh）**：

```bash
export AISC_ROOT=/path/to/AISC
aisc version
```

**Windows PowerShell（当前会话）**：

```powershell
$env:AISC_ROOT = "C:\path\to\AISC"
aisc version
```

### Docker 相关错误

- `docker: command not found` — 安装 Docker CLI
- `permission denied` — Linux 用户需加入 `docker` 组
- `Cannot connect to the Docker daemon` — 启动 Docker Desktop/Engine

### `pip install -e .` 可以，`uv tool install --editable .` 不行？

确认仓库根目录有 `pyproject.toml`，且其中 `[project.scripts]` 定义了 `aisc` 入口点。根据 uv 安装来源更新后重试：

| uv 安装方式 | 更新命令 |
| --- | --- |
| 独立安装脚本 | `uv self update` |
| Homebrew | `brew upgrade uv` |
| WinGet | `winget upgrade --id=astral-sh.uv -e` |

### 其他问题

到 [GitHub Issues](https://github.com/wangyuncepu/AISC/issues) 提交。提供操作系统、Docker 版本、完整报错和复现步骤；**删除 API Key、代理订阅等敏感信息**。

## 许可

MIT License。详见仓库中的 [LICENSE](LICENSE) 文件。
