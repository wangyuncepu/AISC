# AISC

在 Docker 容器中使用 Claude Code，并按项目保存配置的个人开发工具。

> **状态：Alpha / 开发中。** AISC 面向个人和开发环境，不是生产级工作站产品。请先阅读文末的安全边界与已知限制。

## 从这里开始

第一次使用，推荐走**启动器路径**：不需要安装 Python，也不需要理解 `aisc` CLI。

### 1. 准备 Docker 与 Git

- Windows / macOS：安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Linux：安装并启动 Docker Engine
- 安装 Git，用于取得和更新仓库

先确认 Docker 可用：

```bash
docker version
```

### 2. 下载 AISC

```bash
git clone https://github.com/wangyuncepu/AISC.git AISC
cd AISC
```

也可以下载 ZIP；解压后在终端进入解压出的 `AISC` 目录。

### 3. 用启动器启动容器

| 平台 | 推荐入口 | 说明 |
| --- | --- | --- |
| Linux | `./start.sh` | 首次如有需要：`chmod +x start.sh` |
| macOS | `./start.command` | 可在 Finder 双击，或在终端运行 |
| Windows | `start.bat` | 建议从 Windows Terminal 启动 |

Linux 示例：

```bash
chmod +x start.sh
./start.sh
```

启动器会检查 Docker、询问代理设置、提供镜像构建选项，然后启动容器。首次构建可能需要一些时间。

> `start.sh`、`start.command`、`start.bat` 是普通使用者的入口；它们**不是** Python `aisc` 命令的包装器，也不会转发 `aisc` 子命令。比如 `./start.sh doctor` 无效。

### 4. 选择配置作用域

容器首次启动会询问 `.claude` 的作用域：

| 选择 | 配置位置 | 适合场景 |
| --- | --- | --- |
| **临时**（temp） | 容器内置 `.claude` | 试用或一次性会话；容器删除后改动不保留 |
| **项目**（project） | 挂载工作区中的 `.claude` | 长期使用同一项目；配置、技能与状态随项目保留 |

不确定时选择**项目**。在自动化或非交互场景，可在启动前设置 `CLAUDE_SCOPE=temp` 或 `CLAUDE_SCOPE=project`；实现也接受 `global` 作为临时作用域的兼容值。

### 5. 在容器内配置服务并进入 Claude Code

进入容器 shell 后，以 DeepSeek 为例：

```bash
cs deepseek
claude
```

首次切换会要求输入自己的 API Key，输入不会显示。不要把真实 API Key 写入 README、聊天记录或 Git 提交。第三方服务会收到你的 API 请求和密钥；只使用你信任、并已了解其条款的服务。

## 先分清两个入口

| 入口 | 运行位置 | 面向谁 | 用途 |
| --- | --- | --- | --- |
| `start.sh` / `start.command` / `start.bat` | 宿主机 | 大多数使用者 | 检查环境、配置代理、构建并启动容器 |
| `cs` | **容器内** | 容器使用者 | 配置或切换模型服务、执行 `cs upgrade` |
| `aisc` | **宿主机** | 开发者预览 | 构建镜像、运行/管理容器、导入构建期 Skill |

`cs` 在宿主机找不到是正常的。`aisc` 也不是默认安装的命令：它需要 Python 3.11+ 并按下文“开发者 CLI”安装。

## 工作区、AISC 根目录与配置

这三个概念容易混淆：

| 概念 | 是什么 | 主要内容 |
| --- | --- | --- |
| **AISC 安装根目录** | 克隆得到的 `AISC` 仓库 | `container/`、镜像构建输入、`skills-lock.json`、`.aisc/state.env` |
| **工作区** | 你希望交给 Claude 操作的项目目录 | 代码，以及项目模式下的 `.claude`、`.aisc/`、`.cc-config/` |
| **当前工作目录** | 你执行命令时所在的目录 | `aisc run` 未指定 `--workspace` 时，它就是工作区 |

启动器默认把**启动前所在目录**作为工作区；可以显式指定：

```bash
./start.sh --workspace /path/to/your-project
```

`start.command` 会将参数交给 `start.sh`，`start.bat` 也支持 `--workspace PATH`。在 Windows 中按平台的路径写法传入目录即可。

开发者 CLI 会自动定位 AISC 安装根目录。需要明确指定时使用：

```bash
aisc --aisc-root /path/to/AISC version
aisc run --workspace /path/to/your-project
```

安装根目录保存 AISC 的资源和容器发现状态；工作区保存你的项目数据。即使在其他项目目录运行 `aisc`，也不要把两者误认为同一个目录。

### 密钥与运行时文件

- `cs` 的 API Key 主存储位置是当前工作区的 `.aisc/secrets/api-keys`，即使使用临时 `.claude` 作用域也是如此。
- `.cc-config/api-keys` 仍可能因旧版本兼容而被读取；新使用请以 `.aisc/secrets/api-keys` 为准。
- 这些都是运行时私密数据，不应提交到 Git。请检查 `.gitignore`，也不要在共享或不受信任的工作区中保存密钥。
- 密钥文件会尽力限制为当前用户可读；Windows、网络盘和部分绑定挂载未必能严格保留 Unix 权限。

## 容器内切换模型服务

在容器 shell 中，`cs` 可直接切换服务。当前有 **7 大模型后端**；`cs cc` 会回到 Claude 官方默认配置，`cs show` 显示当前服务和已保存密钥的状态，不会完整显示密钥。

| 切换命令 | Provider ID |
| --- | --- |
| `cs cc` | `cc` |
| `cs deepseek` | `deepseek` |
| `cs ark` | `ark` |
| `cs 1y` | `1y` |
| `cs duo-cc` | `duo-cc` |
| `cs xf` | `xf` |
| `cs orange` | `orange` |

## 开发者 CLI（预览）

> `aisc` 是独立的宿主机管理 CLI，不替代启动器，也不替代容器内的 `cs`。

在 AISC 安装根目录中创建虚拟环境并安装：

```bash
# Linux / macOS（Bash / Zsh）
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

Fish：

```fish
python3 -m venv .venv
source .venv/bin/activate.fish
python3 -m pip install -e .
```

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

安装后可先检查环境：

```bash
aisc version
aisc doctor
```

第二个终端不会自动继承虚拟环境；请重新激活它，或直接使用 `.venv/bin/aisc`（Windows 使用对应的 `.venv\Scripts\aisc`）。

### 命令地图与通用选项

下面是当前实现的完整顶层命令。表格用于定位功能；参数细节按后续分区展开。

| 分组 | 命令 | 用途 |
| --- | --- | --- |
| 基础 | `version` · `doctor` | 显示版本信息；检查宿主机环境 |
| 镜像与运行 | `build` · `run` | 构建镜像；以前台方式运行容器 |
| 配置查看 | `config` · `provider` · `profile` | 校验/查看配置；查看 Provider 与 Profile 目录，均不执行切换或应用 |
| 简讯 | `brief` | 在宿主机运行 AI 简讯工具（仅文本） |
| 容器管理 | `status` · `stop` · `restart` · `shell` · `switch` | 管理已运行的容器；见“生命周期命令” |
| 构建期 Skill | `skill` | 导入、列出、移除、校验 Skill；见“持久化导入 Skill” |

所有顶层命令都能在命令前或后接受 `--aisc-root PATH`；它指定 AISC 安装根目录。其余通用选项如下：

| 选项 | 用途与边界 |
| --- | --- |
| `--format text\|json` | 选择文本或 JSON 输出；具体命令的限制见下文。 |
| `--no-color` | 禁用 ANSI 颜色。 |
| `--aisc-root PATH` | 显式指定 AISC 安装根目录。 |
| `--events` | **只对 `build` 与 `run` 有意义**，输出 JSONL 事件流；不能与 `--format json` 同时使用。其他命令虽然在帮助中继承此参数，运行时不提供事件流。 |

输出支持按命令区分：`version`、`doctor`、`config`、`provider`、`profile`、`skill`、`status`、`stop`、`restart` 可使用文本或 JSON；`brief` 仅文本；`shell` 与 `switch` 仅交互式文本。`build` 与 `run` 支持文本、JSON，或通过 `--events` 输出 JSONL。

### 基础、构建与运行

| 命令 | 可用参数 | 说明 |
| --- | --- | --- |
| `aisc version` | 通用选项 | 显示 AISC、Python 与平台版本信息。 |
| `aisc doctor` | 通用选项 | 检查宿主机环境；不包含 `doctor --container`。 |
| `aisc build` | `--tag/-t TAG`、`--no-cache`、`--pull`、`--dry-run` | 构建 Docker 镜像。 |
| `aisc run` | `--image/-i IMAGE`、`--workspace PATH`、`--name PREFIX`、`--network direct\|proxy`、`--profile proxy`、`--non-interactive`、`--dry-run` | 运行 Docker 容器。 |
| `aisc brief` | `--date`、`--days`、`--top`、`--source`、`--ai`、`--save`、`--no-cache`、`--strict`、`--debug` | 运行 AI 简讯；仅文本输出。 |

`--name` 是容器**名称前缀**，实际运行时会附加唯一后缀。`--profile proxy` 只是 `--network proxy` 的兼容别名，优先使用 `--network proxy`；它不是安全 Profile。`--non-interactive` 不分配交互终端，并以无 stdin 的方式运行。

### 构建与运行：前台命令，不是后台服务

`aisc build` 构建镜像；`aisc run` 使用该镜像运行容器：

```bash
aisc build
aisc run
```

`aisc run` 是**前台**命令：容器和初始化交互会占用当前终端。它使用 `docker run --rm`；退出或停止后，容器会被删除。它不是后台启动命令，也没有后台运行选项。

常用的已实现选项：

```bash
aisc build --tag my-image:latest --no-cache
aisc run --image my-image:latest --workspace /path/to/project
aisc run --network proxy
aisc run --dry-run
```

`aisc run` 可使用 `--image/-i`、`--workspace`、`--name`、`--network direct|proxy`、`--profile proxy`、`--non-interactive`、`--dry-run`。`--name` 是前缀，实际容器名会自动加唯一后缀。完整参数以 `aisc run --help` 为准。

### 配置与目录：只读查看

配置命令读取并展示信息，不提供写入或切换接口：

| 命令 | 作用 |
| --- | --- |
| `aisc config validate [--config PATH] [--workspace PATH]` | 校验用户配置与工作区配置。 |
| `aisc config effective [--config PATH] [--workspace PATH]` | 显示合并后的有效配置。 |
| `aisc config show [--config PATH] [--workspace PATH]` | `config effective` 的兼容别名。 |
| `aisc provider list` | 列出 Provider 目录。 |
| `aisc provider show NAME` | 按 Provider ID 或别名查看详情。 |
| `aisc profile list` | 列出可用 Profile。 |
| `aisc profile show [NAME]` | 查看 Profile；省略名称时默认为 `safe`。 |

没有 `provider use`：实际切换请使用已运行容器上的 `aisc switch`，或在容器内使用 `cs`。`profile list/show` 也只是查看；`safe` / `unsafe` 尚未接入 `aisc run` 的安全控制。当前唯一名为 `--profile` 的运行参数是 `run --profile proxy`，它仅是网络代理兼容别名。

### 生命周期命令：操作已经运行的容器

`status`、`stop`、`restart`、`shell`、`switch` **不会创建容器，也不会把容器转到后台**。它们的目标是一个已经运行的容器。

当容器由 `aisc run` 启动时，CLI 会把容器名写入 `<AISC 根目录>/.aisc/state.env`，后续命令可自动找到它；也可以用 `--name NAME` 指定目标。`aisc run` 仍须在另一个终端保持前台运行。

```bash
# 终端 1：保持运行
aisc run

# 终端 2：管理同一个已运行容器
aisc status
aisc shell
aisc restart
aisc stop
```

| 命令 | 作用 | 条件 |
| --- | --- | --- |
| `aisc status [--name NAME]` | 查看容器存在与运行状态 | 容器可已退出；不存在会明确显示 |
| `aisc stop [--name NAME]` | 停止容器 | 容器必须存在；已停止时幂等成功 |
| `aisc restart [--name NAME]` | 重启容器 | 容器必须存在 |
| `aisc shell [--name NAME]` | 进入容器的 Bash | 容器必须正在运行 |
| `aisc switch [--name NAME]` | 打开容器内的完整服务切换界面 | 容器必须正在运行 |
| `aisc switch --quick PROVIDER` | 在容器内执行 `cs PROVIDER` | 容器必须正在运行 |

`shell` 与 `switch` 是交互式文本命令，不支持 JSON 输出。`status`、`stop`、`restart` 支持 `--format json`。所有命令可用 `--help` 查看实际参数。

### 通过 `aisc switch` 切换服务

```bash
# 打开完整切换界面
aisc switch

# 快速切换；示例为 DeepSeek
aisc switch --quick deepseek
```

切换结果会保存在**该运行中容器启动时选定的 `.claude` 作用域**中。CLI 会读取容器 PID 1 的 `CLAUDE_CONFIG_DIR` 与 `CC_CONFIG_DIR`，不会擅自写到另一份配置。

切换后，已经运行的 Claude Code 进程不会自动重新读取设置：请**新建 Claude 会话或重启 Claude Code**。若重启容器，项目作用域中的持久化设置会继续使用；临时作用域则随容器删除而消失。

## 持久化导入 Skill

Skill 导入是面向个人使用的简化 MVP。它修改的是 **AISC 安装根目录**中的镜像构建输入，而不是正在运行的容器。

### 推荐流程

在 AISC 安装根目录中执行：

```bash
# 1. 从 GitHub 导入一个平铺 Skill 目录
aisc skill add https://github.com/user/repo/tree/main/skills/my-skill

# 2. 离线核对导入文件
aisc skill check

# 3. 构建包含该 Skill 的新镜像
aisc build
```

日常管理命令：

```bash
aisc skill list
aisc skill remove my-skill
aisc skill check
```

`aisc skill add` 支持 GitHub HTTPS 的 `blob`、`tree`、`raw` URL，目标必须是含 `SKILL.md` 的平铺 Skill 文件或目录。它会将完整目录写入 `container/_bundle/skills/<name>/`，并管理根目录的 `skills-lock.json`。

锁文件为 **v2**：记录来源 URL、解析后的精确 commit SHA、文件大小与 SHA-256 哈希。`aisc skill check` 不访问网络，检查本地文件是否仍与锁一致。不要手动编辑 `skills-lock.json`。

> **不要在运行中的容器里安装后指望它长期存在。** 这类改动会随 `--rm` 容器删除而丢失。需要持久化时，始终使用 `aisc skill add`，然后 `aisc build`。

### 已有项目如何收到新 Skill：`cs upgrade`

新镜像中的内容是“出厂 `.claude`”。**`cs upgrade` 不会更新 AISC 源码、Docker 镜像或 Claude CLI，也不会下载 Skill。** 它只把已构建镜像中的出厂 `.claude` 内容同步/合并到一个**已经存在的项目作用域 `.claude`**，并保留用户的后端配置与历史。

- 新建的项目作用域首次启动会直接从镜像复制出厂内容，通常**不需要** `cs upgrade`。
- 临时作用域直接使用镜像内出厂内容，通常也**不需要** `cs upgrade`。
- 已存在项目作用域的 `.claude` 不会在启动时被覆盖；在换用新镜像后，才需要用 `cs upgrade` 合并新增的出厂内容。

对正在使用 `aisc run` 的既有项目，完整流程如下。注意：`aisc run` 必须保持前台，而 `aisc stop` 会使带 `--rm` 的旧容器结束并删除。

```bash
# 在 AISC 安装根目录：导入、检查、构建
aisc skill add https://github.com/user/repo/tree/main/skills/my-skill
aisc skill check
aisc build

# 若旧容器正在运行：在另一终端停止它
aisc stop

# 在终端 1：用刚构建的镜像重新前台运行
aisc run

# 在终端 2：进入新的、正在运行的容器
aisc shell

# 容器内：将新镜像的出厂内容合并到既有项目 .claude
cs upgrade
```

`cs upgrade` 会更新出厂的 skills、plugins、commands、`CLAUDE.md` 与相关设置，并在处理项目独有项时询问；默认保留这些项目独有项。它不是无提示的全量覆盖操作。

### 这个 Skill MVP 不做什么

- 不接收任意插件 URL；**只支持 GitHub 平铺 Skill**，不导入插件。
- 不提供许可证审核、风险审批或供应链工作流。
- 不自动导入依赖。发现类似 `/grilling` 的引用时只给出提示。

Skill 本身是会影响模型行为的指令；请仅导入可信来源。

## 常见问题

### Docker 找不到、daemon 未启动或 permission denied

`docker: command not found` 表示 Docker CLI 未安装或不在 PATH。连接 daemon 失败时，启动 Docker Desktop 或 Docker Engine 后重试。Linux 的 `permission denied` 通常说明当前用户没有 Docker 权限；请按所用发行版的 Docker 文档配置用户组并重新登录终端。

### 提示镜像不存在

首次使用或清理镜像后先构建镜像：重新运行启动器并在菜单中选择构建，或执行 `aisc build`。不要假定本机已有 `super-claude:latest`。

### Windows 无法启动 PowerShell

从 `start.bat` 启动；它以 `-ExecutionPolicy Bypass` 调用 PowerShell。若企业策略、终端设置或安全软件仍阻止执行，请联系设备管理员。Windows 的完整验证仍在进行中。

### 如何报告问题

请提供操作系统、Docker 版本、完整报错和复现步骤；删除 API Key、代理订阅等敏感信息后，到 [GitHub Issues](https://github.com/wangyuncepu/AISC/issues) 提交。

## 安全边界与已知限制

> **只在可丢弃或你信任的工作区运行，并先检查会挂载到容器中的目录。** AISC 为便利做了取舍，容器不是严格隔离环境。

- Claude Code 的容器默认参数可能包含 `--dangerously-skip-permissions`，会跳过逐项权限确认。
- 容器用户拥有免密码 `sudo`。为修复可写权限，脚本可能对绑定挂载文件执行 `chown`，从而改变宿主机文件所有者。
- 启用 Mihomo TUN 代理时，容器需要 `NET_ADMIN` 和 `/dev/net/tun`；不了解这些权限时不要启用。
- 第三方 provider 会收到 API 请求和 API Key；仅选择你愿意信任的 provider。

Linux 是当前主要验证平台。安全存储相关测试已通过 **429 项**，另有 **11 项 Windows 专用测试跳过**。Windows 的个人作用域 smoke test 曾在 Windows 11（build 10.0.26200）/ Python 3.14.5 上通过，Q1–Q5 全部 PASS 且清理无残留；请参阅 [Windows 个人作用域 smoke test](docs/testing/S5.3-personal-smoke-test.md)。这只是狭窄的个人使用冒烟结果，**不是 Windows 生产安全声明**；retained-handle Windows 路径仍有意未接线。

以下能力尚未实现或尚未接线，不应视为可用功能：

- `provider use`
- `config migrate`
- `config cleanup`
- `logs`
- `clean`
- `doctor --container`
- `profile safe/unsafe` 的运行安全控制（目前只可只读查看，尚未接入 `aisc run`）

## 其他内容

### Mihomo TUN 代理

启动器的代理向导可配置容器内 Mihomo TUN；它只影响容器网络，但需要前述额外 Docker 权限。代理配置或节点不可用时，可在容器内查看：

```bash
/home/AISC/.mihomo/mihomo.log
```

### AI 简讯

镜像包含 AI 简讯工具，默认不会在启动时运行。进入容器后可执行：

```bash
python3 /home/AISC/ai_brief/brief.py --ai --top 5
```

`--ai` 需要已配置模型服务和网络。

## 许可证与参考

本项目采用 [MIT License](LICENSE)。贡献或反馈时，请勿包含 API Key、代理订阅或其他私密配置。

- [Issues](https://github.com/wangyuncepu/AISC/issues)
- [Claude Code 文档](https://docs.anthropic.com/en/docs/claude-code)
- [cc-switch-cli](https://github.com/saladday/cc-switch-cli)
- [CLI RFC](docs/rfc/aisc-cli-v1.md)
- [统一 CLI 计划](docs/plans/PLAN-p3-unified-cli.md)
