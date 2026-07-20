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

### 方案 A（uv 安装）

```bash
uv tool uninstall aisc
```

这会移除 `aisc` 命令和对应的隔离环境。仓库目录中的源码和配置文件不会被删除，需要可自行删除。

### 方案 B（独立便携版）

详见下方“独立便携版”章节中的卸载说明。

---

## 独立便携版（无需 Python/uv）

> **方案 B**：直接下载预构建归档，解压即用。无需安装 Python、uv 或克隆仓库。
> 适合不想安装 Python 工具链的用户，或需要在多台机器上快速部署的场景。

### ⚠️ 重要：当前产物获取方式

**AISC 尚未自动发布 GitHub Release。** 所有 Release 必须经维护者明确批准后才会发布。
当前阶段，预构建归档仅通过以下方式获取：

1. **GitHub Actions workflow artifacts**（推荐）：访问仓库的 [Actions](https://github.com/wangyuncepu/AISC/actions) 页面，选择最新的 `Artifact` workflow run，下载 `AISC-workflow-artifacts` 归档（含三平台构建 + SHA256SUMS）。注意：workflow artifacts 保留 7 天。
2. **维护者提供**：由项目维护者手动分发的归档文件。

> **绝对不会**通过 `gh release`、tag 自动发布或任何自动化手段创建 Release。在维护者批准前，所有构建产物仅为 workflow artifacts。

### 架构限制

| 平台 | 架构 | 格式 | 说明 |
| --- | --- | --- | --- |
| Linux | x86_64 | `.tar.gz` | 仅支持 x86_64；arm64/aarch64 不支持 |
| macOS | arm64 (Apple Silicon) | `.tar.gz` | 仅支持 Apple Silicon；Intel Mac 不支持 |
| Windows | x86_64 | `.zip` | 仅支持 x86_64；ARM Windows 不支持 |

**所有平台仍需安装 Docker**（`aisc build` / `aisc run` 等命令依赖 Docker daemon）。
其他命令（`version`、`doctor`、`config`、`provider`、`profile`）不需要 Docker。

### 归档结构

每个归档文件包含一个顶层目录，内含 `aisc`（或 `aisc.exe`）可执行文件与相邻的 `aisc-bundle/` 目录：

```
AISC-2.0.0-dev-linux-x86_64/
├── aisc              # 可执行文件
└── aisc-bundle/      # 运行时所需资源（必须与可执行文件相邻）
    ├── VERSION
    ├── container/
    │   └── Dockerfile
    ├── config/
    │   └── versions.env
    └── ...
```

> `aisc` 与 `aisc-bundle/` **必须保持在同一父目录下**。移动或重命名会导致 `AISC root not found` 错误。

---

### Linux（x86_64）

#### 方式一：解压直接运行（无需安装脚本）

```bash
# 1. 下载归档（从 GitHub Actions 或维护者提供）
#    假设已下载 AISC-2.0.0-dev-linux-x86_64.tar.gz 到 ~/Downloads/

# 2. 可选：校验 SHA256
sha256sum -c AISC-2.0.0-dev-linux-x86_64.tar.gz.sha256

# 3. 解压
tar -xzf AISC-2.0.0-dev-linux-x86_64.tar.gz

# 4. 进入目录，直接运行
cd AISC-2.0.0-dev-linux-x86_64
./aisc version
./aisc doctor
```

> `./aisc` 会自动在同级目录查找 `aisc-bundle/`。如果你将 `aisc` 移动到其他位置，也必须同步移动 `aisc-bundle/` 到同一目录。

#### 方式二：使用安装脚本（从克隆仓库调用）

如果你已克隆了 AISC 仓库（方案 A 用户），可以复用仓库中的安装脚本将本地归档安装到用户目录：

```bash
# 在 AISC 仓库根目录下
bash packaging/install.sh ~/Downloads/AISC-2.0.0-dev-linux-x86_64.tar.gz
```

安装脚本会：
- 将 `aisc` + `aisc-bundle/` 安装到 `${XDG_DATA_HOME:-$HOME/.local/share}/aisc`
- 在 `${XDG_BIN_HOME:-$HOME/.local/bin}/aisc` 创建符号链接
- 自动处理重复安装（原子替换）
- 若 `${XDG_BIN_HOME}` 不在 PATH，提示你手动配置

也支持传入已解压的目录：

```bash
tar -xzf AISC-2.0.0-dev-linux-x86_64.tar.gz
bash packaging/install.sh ./AISC-2.0.0-dev-linux-x86_64
```

**卸载：**

```bash
# 在 AISC 仓库根目录下
bash packaging/uninstall.sh

# 方案 B 的卸载不会删除 Docker 镜像/容器、~/.aisc 配置或工作区
```

---

### macOS（arm64 / Apple Silicon）

#### 方式一：安装程序（推荐，需管理员密码）

下载 `AISC-2.0.0-dev-macos-arm64.pkg`，双击运行。

- **仅支持 Apple Silicon（arm64）Mac**；Intel Mac 不支持。
- 安装时要求**管理员密码**（系统级安装到 `/usr/local/`）。
- 安装路径：
  - 可执行文件：`/usr/local/lib/aisc/aisc`
  - Bundle：`/usr/local/lib/aisc/aisc-bundle/`
  - 符号链接：`/usr/local/bin/aisc` → `../lib/aisc/aisc`
- `/usr/local/bin` 默认在 macOS PATH 中，安装后**新开终端**即可直接使用 `aisc`。
- 卸载：`sudo /usr/local/lib/aisc/uninstall.sh`（会移除文件、符号链接和 pkg 收据，**不删除** `~/.aisc` 或 `~/.cc-config`）。
- 升级：双击新版 `.pkg` 覆盖安装即可。

> ⚠️ AISC 尚未经过 Apple 开发者签名。首次双击 `.pkg` 时，macOS Gatekeeper 可能阻止运行。
> 前往 **系统设置 → 隐私与安全性**，滚动到底部点击 **“仍要打开”**。
> **不要**全局关闭 Gatekeeper（`spctl --master-disable`）。正式签名/公证后续单独实现。

#### 方式二：便携版（备用，无需管理员）

从 tar.gz 解压到用户目录运行，无需管理员权限。适合无法或不愿使用系统级安装的用户。

```bash
tar -xzf AISC-2.0.0-dev-macos-arm64.tar.gz
cd AISC-2.0.0-dev-macos-arm64
./aisc version
```

或使用安装脚本（安装到 `$HOME/Library/Application Support/AISC`）：

```bash
bash packaging/install.sh ~/Downloads/AISC-2.0.0-dev-macos-arm64.tar.gz
```

**卸载：**

```bash
bash packaging/uninstall.sh
```

> ⚠️ 两种安装方式使用不同路径（系统级 vs 用户级）。如需切换，先卸载当前方式再安装另一种，避免 PATH 冲突。

---

### Windows（x86_64）

#### 方式一：安装程序（推荐）

下载 `AISC-2.0.0-dev-windows-x86_64-setup.exe`，双击运行即可。

- **无需** Python、uv、ZIP 解压或手动配置。
- 默认安装到 `%LOCALAPPDATA%\Programs\AISC`。
- 自动将安装目录加入用户 PATH（安装后**重新打开终端**即可使用 `aisc`）。
- 通过 **设置 → 应用 → 已安装的应用** 或 **控制面板 → 程序和功能** 卸载。
- 卸载会移除程序文件和 PATH 条目，**不会删除** `%USERPROFILE%\.aisc` 或 `.cc-config` 用户配置。

> ⚠️ AISC 尚未经过代码签名。首次运行时 Windows SmartScreen 可能弹出“Windows 保护了你的电脑”。点击 **更多信息 → 仍要运行** 即可。
>
> 正式 Release 必须经维护者批准后才会发布。当前阶段从 GitHub Actions workflow artifacts 获取。

#### 方式二：便携版（备用）

ZIP 归档和 PowerShell 安装脚本保留作为维护/便携备用方案。

**解压直接运行：**

```powershell
Expand-Archive AISC-2.0.0-dev-windows-x86_64.zip -DestinationPath .
cd AISC-2.0.0-dev-windows-x86_64
.\aisc.exe version
```

**PowerShell 安装脚本：**

```powershell
.\packaging\install.ps1 -Source "$env:USERPROFILE\Downloads\AISC-2.0.0-dev-windows-x86_64.zip"
```

安装脚本会：
- 将 `aisc.exe` + `aisc-bundle\` 安装到 `%LOCALAPPDATA%\AISC`
- 自动将安装目录加入用户 PATH（需重启终端生效）
- 幂等（重复安装会替换旧版本，PATH 不会重复添加）

**卸载（PowerShell）：**

```powershell
.\packaging\uninstall.ps1
```

卸载会移除安装目录并清理用户 PATH 中的对应条目，不会删除用户配置或 Docker 资源。

---

## 常见故障

### `aisc: command not found`

**方案 A：** `uv tool install --editable .` 未执行，或 tool bin 目录未在 PATH 中。

- 确保已执行 `uv tool update-shell` 并重新打开终端
- 运行 `uv tool dir --bin` 查看 bin 目录，确认它已加入 PATH
- 运行 `uv tool list` 确认 `aisc` 已安装

**方案 B（独立便携版）：**

- 若使用安装脚本，确保 `${XDG_BIN_HOME:-$HOME/.local/bin}` 在你的 PATH 中
- 若解压直接运行，使用 `./aisc` 或 `.\aisc.exe`（当前目录）而非裸 `aisc`

### `AISC root not found`

`aisc` 命令依赖同目录下的 `aisc-bundle/`。可能的原因：

- `aisc` 可执行文件被移动到没有 `aisc-bundle/` 的目录
- 手动删除了 `aisc-bundle/` 或其内容

**解决办法：**
- 将 `aisc` 和 `aisc-bundle/` 放在同一目录下
- 或用 `--aisc-root` 显式指定包含 `aisc-bundle/` 的目录路径：

```bash
aisc --aisc-root /path/to/install/dir version
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
