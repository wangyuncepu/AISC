# AISC 用户手册

AISC 是一个在 Docker 容器中运行 Claude Code、OpenAI Codex 和 cc-switch 的个人开发工作站。宿主机只提供一个受支持的入口：`aisc`。它负责诊断环境、构建镜像、启动和管理一个或多个容器；AI CLI、Provider、凭据、路由和 Skills 管理在容器内完成。

> **状态：Alpha。** 当前版本为 **v2.1.4**，版本号以仓库根目录 [`VERSION`](VERSION) 为准。Alpha 版本的命令、配置和持久化契约仍可能变化，升级前请阅读 Release Notes 并备份重要工作区。

## 安全边界

AISC 以开发便利为优先，不是生产级安全沙箱：

- 容器以 `root` 运行，挂载的工作区对容器内进程可读写。
- Claude 包装器默认追加 `--dangerously-skip-permissions`；Codex 包装器默认追加 `--dangerously-bypass-approvals-and-sandbox` 和 `--dangerously-bypass-hook-trust`。这会绕过工具自身的危险操作确认。
- `IS_SANDBOX=1` 只是运行环境标记，不会建立额外隔离。Docker daemon 权限本身通常等同宿主机高权限。
- 代理模式额外授予 `NET_ADMIN` 并挂载 `/dev/net/tun`，扩大了容器网络权限。
- 只在可信代码和可恢复的工作区中运行。不要挂载密钥目录、生产数据或整段用户主目录；先提交或备份未保存的工作。
- API Key、登录令牌和 Provider 配置只交给 cc-switch 或对应官方 CLI，不要写入仓库、AISC 配置、Issue 或日志。

## 安装前提与支持平台

运行 AISC 必须安装并启动 Docker：

| 平台 | 官方产物 | Docker |
| --- | --- | --- |
| Linux | x86_64 | Docker Engine；当前用户需有 daemon 权限 |
| Windows | x86_64 | Docker Desktop |
| macOS | Apple Silicon arm64 | Docker Desktop |

官方 Release **不提供** Linux arm64、Windows arm64 或 Intel macOS 产物。Release 安装不需要 Python、uv 或 Git；从源码安装需要 Python 3.11+ 和 Git，推荐使用 uv。

先验证 Docker：

```bash
docker version
```

## 从 GitHub Release 安装

从 [GitHub Releases](https://github.com/wangyuncepu/AISC/releases) 下载对应平台的 v2.1.4 产物及 `.sha256`，或使用汇总文件 `SHA256SUMS` 校验。发布标签带前导 `v`，产物文件名中的版本不带 `v`。

### Linux x86_64

下载 `AISC-2.1.4-linux-x86_64.tar.gz`：

```bash
sha256sum -c AISC-2.1.4-linux-x86_64.tar.gz.sha256
tar -xzf AISC-2.1.4-linux-x86_64.tar.gz
cd AISC-2.1.4-linux-x86_64
./aisc version
```

便携运行时，`aisc` 与 `aisc-bundle/` 必须保持相邻。也可获取仓库中的安装脚本，安装到用户目录：

```bash
git clone --depth 1 https://github.com/wangyuncepu/AISC.git
cd AISC
bash packaging/install.sh /path/to/AISC-2.1.4-linux-x86_64.tar.gz
aisc version
```

默认程序目录为 `${XDG_DATA_HOME:-$HOME/.local/share}/aisc`，命令链接为 `${XDG_BIN_HOME:-$HOME/.local/bin}/aisc`。若后者不在 `PATH`，脚本会提示需要添加的路径。

### Windows x86_64

推荐下载 `AISC-2.1.4-windows-x86_64-setup.exe` 并运行。安装器默认写入 `%LOCALAPPDATA%\Programs\AISC`，并添加用户 `PATH`；安装后重新打开终端：

```powershell
aisc version
```

AISC 尚未代码签名。SmartScreen 提示时，请先确认文件来自项目 Release 且 SHA256 正确，再选择“更多信息 -> 仍要运行”。

便携版为 `AISC-2.1.4-windows-x86_64.zip`：

```powershell
Expand-Archive .\AISC-2.1.4-windows-x86_64.zip -DestinationPath .
cd .\AISC-2.1.4-windows-x86_64
.\aisc.exe version
```

`aisc.exe` 与 `aisc-bundle\` 必须保持相邻。仓库中的 `packaging/install.ps1` 也可安装便携包到 `%LOCALAPPDATA%\AISC`，该路径与 setup.exe 的默认目录不同。

### macOS arm64

推荐下载 `AISC-2.1.4-macos-arm64.pkg`。安装需要管理员密码，内容位于 `/usr/local/lib/aisc/`，并创建 `/usr/local/bin/aisc` 链接。安装后新开终端：

```bash
aisc version
```

PKG 尚未签名和公证。若 Gatekeeper 阻止打开，请确认 Release 和 SHA256 后，在“系统设置 -> 隐私与安全性”中选择“仍要打开”；不要全局关闭 Gatekeeper。

便携包为 `AISC-2.1.4-macos-arm64.tar.gz`：

```bash
tar -xzf AISC-2.1.4-macos-arm64.tar.gz
cd AISC-2.1.4-macos-arm64
./aisc version
```

也可使用 `packaging/install.sh` 安装到 `$HOME/Library/Application Support/AISC`，并在 `${XDG_BIN_HOME:-$HOME/.local/bin}` 创建命令链接。

## 从源码安装

适合开发者或需要自行构建当前分支的用户：

```bash
git clone https://github.com/wangyuncepu/AISC.git
cd AISC
uv tool install --editable .
uv tool update-shell
```

重新打开终端后验证：

```bash
aisc version
```

editable 安装记录仓库绝对路径。不要直接移动或删除仓库；需要移动时先运行 `uv tool uninstall aisc`，再在新位置重新安装。

## 快速开始

```bash
# 1. 查看版本和宿主环境
aisc version
aisc doctor

# 2. 构建默认镜像 super-claude:latest
aisc build

# 3. 前台运行容器（默认挂载当前目录为工作区）
aisc run

# 使用指定目录作为工作区
aisc run --workspace /path/to/project
```

交互式文本终端中，裸 `aisc build` 会打开构建向导；通过 `--tag`、`--no-cache`、`--pull` 或 `--dry-run` 明确给出构建选项时直接执行对应计划。

`aisc run` 默认行为是：

- 镜像为 `super-claude:latest`，工作区为当前目录并挂载到 `/root/app`。
- 网络为 `direct`。
- 使用前台交互终端 `-it`，容器退出后由 `--rm` 自动删除。
- 自动生成 `<name>-<8位十六进制>` 容器名，并登记到 `<aisc-root>/.aisc/containers.json`。

容器初始化时先选择作用域：

1. `temporary`：Claude、Codex 和 cc-switch 状态位于 `/tmp/aisc-home`，容器结束即重置。
2. `project`：状态写入挂载工作区的 `.claude/`、`.codex/`、`.cc-switch/`，跨容器保留；默认选项。

随后可选择 `bash`、`claude`、`codex` 或 `cc-switch`，默认进入 `bash`。

需要从另一个终端管理当前容器时：

```bash
aisc ps
aisc status
aisc shell
aisc switch
```

希望断开终端后仍保留容器：

```bash
aisc run --keep-alive --label work
# docker attach 的 detach 组合键通常为 Ctrl-p Ctrl-q
aisc shell --label work
aisc stop --label work
```

脚本或 CI 中使用非交互模式：

```bash
aisc run --non-interactive
```

该模式不分配 `-it`，stdin 使用 DEVNULL，并设置 `AISC_NON_INTERACTIVE=1` 和项目作用域。

## 容器内使用

进入容器后可直接运行：

```bash
claude
codex
cc-switch
```

### Claude、Codex 与 Provider

Provider、认证信息和路由状态只由 cc-switch 管理。AISC 不维护另一份 Provider 或凭据配置：

```bash
# 查看和切换 Provider
cc-switch -a claude provider list
cc-switch -a claude provider current
cc-switch -a claude provider switch <provider>
cc-switch -a codex provider list
cc-switch -a codex provider current
cc-switch -a codex provider switch <provider>

# 查看或调整本地路由
cc-switch proxy show
cc-switch proxy -a claude enable
cc-switch proxy -a codex enable
```

启动时 AISC 会 detach 启动 cc-switch daemon。Claude 路由以 best-effort 方式自动启用；失败不会阻止进入容器。Codex 默认保持官方直连，支持官方网页登录和原生凭据；只有需要 cc-switch 托管的 Codex Provider 时才执行 `cc-switch proxy -a codex enable`。

全新数据库会尝试导入 Codex `config.toml`，仍无当前 Provider 时选择内置 `codex-official`。该条目不包含用户凭据，不能替代登录或 API Key 配置。

### Skills 同步

镜像内置 `caveman`、`document-skills`、`grill-me`、`superpowers`，由 cc-switch 登记并复制到 Claude/Codex 目标目录：

```bash
cc-switch skills list
cc-switch skills sync
```

容器入口识别 `AISC_SKILLS_SYNC`：

| 值 | 行为 |
| --- | --- |
| `auto` | 默认；仅在首次安装、bundle 变化、登记缺失或已启用目标缺失时同步 |
| `always` | 每次启动都请求同步，但不会绕过文件锁降级时的保护性确认 |
| `off` | 完全跳过 AISC 的自动同步 |

同步更新已有记录的元数据，不强制改写 `enabled_claude` 或 `enabled_codex`，因此用户在 cc-switch 中停用的状态可跨重启保留。当前 `aisc run` 没有通用的 `--env` 参数；未通过镜像环境注入该变量时使用 `auto`。

正常情况下 `.cc-switch/.aisc-bundled-skills.lock` 串行化同步。Windows/Docker Desktop 的绑定挂载不支持文件锁时，如果 `.cc-switch/skills`、`.claude/skills`、`.codex/skills` 任一已存在，会询问是否合并覆盖，默认拒绝；非交互模式也默认跳过，保护宿主内容。

### 代理网络

```bash
aisc run --network proxy
```

代理模式要求：

- 宿主支持 `/dev/net/tun`，Docker 可授予 `NET_ADMIN` 和 TUN 设备。
- `<aisc-root>/.claude/mihomo/config.yaml` 存在且可读；运行时只读挂载到 `/etc/mihomo/config.yaml`。
- 配置或订阅可被 `container/mihomo-build-config.js` 转换，Mihomo 能建立 TUN 和路由。

`aisc run --profile proxy` 只是 `--network proxy` 的兼容网络别名，不是权限 Profile；新命令应使用 `--network proxy`。

## 配置与持久化

### AISC 用户配置

`aisc config` 读取 JSON 配置，用户层路径按平台确定：

| 平台 | 用户配置 |
| --- | --- |
| Linux | `${XDG_CONFIG_HOME:-$HOME/.config}/aisc/config.json` |
| macOS | `$HOME/Library/Application Support/aisc/config.json` |
| Windows | `%APPDATA%\aisc\config.json` |

工作区层固定为 `<workspace>/.aisc/config.json`，优先级为内置默认值 < 用户配置 < 工作区配置。也可用 `--config PATH` 指定用户层文件。

最小配置：

```json
{
  "schema_version": 1,
  "defaults": {
    "profile": "safe",
    "network": "direct"
  }
}
```

当前配置命令只负责校验和展示合并结果；`defaults.profile`、`defaults.network` **尚未接入** `aisc run` 参数决策。运行行为仍以命令行选项为准。未知键会告警并忽略，Provider 和认证字段不属于 AISC schema。

### 持久化路径

| 路径 | 所有者与用途 |
| --- | --- |
| `<workspace>/.cc-switch/` | cc-switch SQLite、Provider、路由、备份及 Skills 源状态 |
| `<workspace>/.claude/` | 项目作用域 Claude 配置、插件、命令和 Skills |
| `<workspace>/.codex/` | 项目作用域 Codex `config.toml`、运行状态和 Skills |
| `<workspace>/.aisc/config.json` | 工作区 AISC 配置层 |
| `<aisc-root>/.aisc/containers.json` | 多容器 registry；默认目标及每个容器的镜像、工作区、网络、label、创建时间 |
| `<aisc-root>/.aisc/state.env` | 兼容状态标志；只允许 `DO_RUN`、`PROXY_ENABLED`，不保存容器名、Provider 或凭据 |
| `<aisc-root>/config/versions.env` | 镜像外部依赖和构建变量 |

`containers.json` 采用临时文件加替换的原子写入；支持 `fcntl` 时还使用文件锁。查询容器时会尽力清理 Docker 中已不存在的登记项。不要在容器运行期间手工编辑 registry。

### AISC root

资源根必须包含 `VERSION`、`container/Dockerfile`、`config/versions.env`。查找顺序是：

1. `--aisc-root PATH`
2. `AISC_ROOT` 环境变量
3. 冻结可执行文件旁的 `aisc-bundle/`
4. 从当前目录向上查找有效 Git 仓库
5. editable 安装包源码路径的祖先目录

显式来源存在但结构不完整时会报错，不会静默换用其他目录。

## CLI 参考

宿主机唯一入口为 `aisc`。不带子命令会打印帮助并以 usage error 结束；裸 `aisc config`、`aisc profile` 打印分组帮助并成功退出。

### 全局选项

全局选项可放在子命令前或后：

| 选项 | 说明 |
| --- | --- |
| `--format text|json` | 默认 `text`；JSON 模式输出统一 envelope |
| `--no-color` | 禁用 ANSI 颜色 |
| `--aisc-root PATH` | 指定资源根；重复出现时最后一个值生效 |
| `--events` | 仅 `build`、`run` 支持的 JSONL 事件流 |

`--format json` 与 `--events` 互斥。机器输出模式下 stdout 只保留 JSON envelope 或 JSONL，Docker 子进程输出转发到 stderr。`shell`、`switch` 只支持文本交互模式。不要依赖未声明命令对 `--events` 的处理。

### 命令总览

| 命令 | 主要参数 | 作用 |
| --- | --- | --- |
| `aisc version` | 全局选项 | 显示 CLI、Python、bundle 和声明依赖版本信息 |
| `aisc doctor` | 全局选项 | 只读检查 Docker、权限、buildx、TUN、Git、资源根和目录可写性 |
| `aisc build` | `--tag/-t`, `--no-cache`, `--pull`, `--dry-run` | 构建镜像；默认 tag 为 `super-claude:latest` |
| `aisc run` | `--image/-i`, `--workspace`, `--name`, `--label`, `--network`, `--profile proxy`, `--non-interactive`, `--keep-alive`, `--dry-run` | 启动并登记容器 |
| `aisc ps` | 全局选项 | 列出 registry 中容器的 label、实时状态、镜像和工作区 |
| `aisc status` | `--name`, `--label` | 查看目标容器状态 |
| `aisc stop` | `--name`, `--label` | 停止目标容器；已停止时幂等成功 |
| `aisc restart` | `--name`, `--label` | 重启目标容器 |
| `aisc shell` | `--name`, `--label` | 执行 `docker exec -it <name> bash` |
| `aisc switch` | `--name`, `--label`, `--quick PROVIDER` | 打开 cc-switch TUI，或快速切换 Claude Provider |
| `aisc config validate` | `--config`, `--workspace` | 只读校验用户层和工作区层配置 |
| `aisc config effective` | `--config`, `--workspace` | 展示有效配置、来源追踪和问题；`show` 是兼容别名 |
| `aisc profile list` | 全局选项 | 只读列出 Profile |
| `aisc profile show [NAME]` | 全局选项 | 只读显示 Profile；默认 `safe` |

### build

```bash
aisc build [--tag TAG] [--no-cache] [--pull] [--dry-run]
```

镜像名不含 `:` 时自动追加 `:latest`。构建从 `config/versions.env` 读取 `USE_CN_MIRROR`、`NODE_IMAGE`、`NODE_IMAGE_CN`，生成 `docker build` 计划。`--dry-run` 不调用 Docker；实际构建需要 daemon 和下载基础镜像/依赖所需的网络。

```bash
aisc build --tag team-image:2.1.4
aisc build --no-cache --pull
aisc build --dry-run --format json
aisc build --events
```

### run

```bash
aisc run [--image IMAGE] [--workspace PATH] [--name PREFIX] [--label LABEL]
         [--network direct|proxy] [--profile proxy]
         [--non-interactive] [--keep-alive] [--dry-run]
```

- `--name` 是容器名前缀，不是最终名称；每次追加随机后缀。
- `--label` 是 registry 寻址标签，不是 Docker label；建议为并行工作区设置唯一值。
- `--keep-alive` 省略 `--rm`，交互文本模式以 `-d` 启动后自动 attach；客户端 detach 后容器继续运行。
- `--non-interactive` 取消 TTY 和交互输入；它与机器输出捕获是不同概念。
- `--dry-run` 仍校验工作区；proxy 模式要求能解析配置路径，但跳过配置文件内容检查，不调用 Docker，也不写 registry。

### 多容器寻址

```bash
aisc run --keep-alive --label api
aisc run --keep-alive --label web
aisc ps
aisc status --label api
aisc shell --label web
aisc restart --label api
aisc stop --label web
```

目标解析顺序为：显式 `--name` -> 唯一匹配的 `--label` -> registry 的默认目标（最近一次 `run`）-> 唯一登记容器。多个候选无法消歧时会列出容器并要求指定 `--name` 或 `--label`；同一 label 匹配多个容器时必须用 `--name`。

`stop` 成功后移除活动登记；默认前台容器因 `--rm` 消失后，会在后续发现或 `ps` 时由惰性清理移除。

### switch 与 profile

```bash
aisc switch --label api
aisc switch --label api --quick deepseek
aisc profile list
aisc profile show safe
aisc profile show unsafe
```

`switch --quick` 从容器 PID 1 安全读取当前 Claude/Codex/cc-switch 作用域路径，再执行 Claude Provider 切换。`profile list/show` 当前只是查看接口；内置 `safe`/`unsafe` 的 `dangerously_skip_permissions` 值不控制 `aisc run`，也不能抵消容器包装器的危险权限默认值。

## 升级

- Windows setup.exe：运行新版安装器覆盖安装。
- macOS PKG：运行新版 `.pkg` 覆盖安装。
- Linux/macOS 便携脚本：重新执行 `bash packaging/install.sh <new-archive>`。
- 源码 editable：在仓库执行 `git pull`；依赖发生变化时执行 `uv tool upgrade aisc` 或重新安装。

程序升级不会自动删除 Docker 镜像、容器、用户配置和工作区状态。若容器镜像内容有变化，升级宿主 CLI 后还需重新运行 `aisc build`；需要排除缓存时使用 `aisc build --no-cache`。

## 卸载

| 安装方式 | 卸载方式 |
| --- | --- |
| Windows setup.exe | Windows“设置 -> 应用 -> 已安装的应用” |
| Windows `packaging/install.ps1` | 在仓库运行 `powershell -File packaging/uninstall.ps1` |
| macOS PKG | `sudo /usr/local/lib/aisc/uninstall.sh` |
| Linux/macOS `packaging/install.sh` | `bash packaging/uninstall.sh` |
| uv tool | `uv tool uninstall aisc` |

卸载器不会删除工作区、用户配置或 Docker 资源。确认不再需要后可手工处理：

```bash
docker ps -a
docker images super-claude
```

谨慎删除 `<workspace>/.cc-switch/`、`.claude/`、`.codex/`、`.aisc/` 以及各平台用户配置；其中可能包含登录状态、Provider 凭据和自定义 Skills。

## 故障排查

### 找不到 `aisc`

- 安装后重新打开终端。
- Linux/macOS 确认 `${XDG_BIN_HOME:-$HOME/.local/bin}` 在 `PATH`。
- 便携包使用 `./aisc` 或 `.\aisc.exe`，并保持 executable 与 `aisc-bundle/` 相邻。

### `AISC root not found` 或 bundle 损坏

```bash
aisc --aisc-root /path/to/aisc-bundle version
```

指定目录必须同时包含 `VERSION`、`container/Dockerfile`、`config/versions.env`。冻结产物旁存在 `aisc-bundle/` 但缺少这些文件时会按损坏处理。

### Docker 或镜像错误

| 现象 | 处理 |
| --- | --- |
| Docker CLI 不存在 | 安装 Docker Desktop 或 Docker Engine |
| daemon 无法连接 | 启动 Docker；Linux 检查 socket 权限和 `docker` 组 |
| `Image not found` | 先运行 `aisc build`，或用 `--image` 指定已有镜像 |
| 工作区权限错误 | 确认路径存在、是目录且当前用户和 Docker 均可访问 |
| 容器立即退出 | 默认容器为前台且 `--rm`；需要保留时使用 `--keep-alive` |

先运行：

```bash
aisc doctor
aisc build --dry-run
aisc run --dry-run
```

### 多容器目标不明确

```bash
aisc ps
aisc status --name <full-container-name>
aisc status --label <unique-label>
```

如果 label 重复，使用 `--name`。registry 损坏时读取会退化为空 registry；先用 `docker ps -a` 核对真实容器，不要盲目删除正在使用的容器。

### cc-switch daemon、Provider 或路由不可用

在容器内检查：

```bash
cc-switch daemon status
cc-switch daemon logs
cc-switch proxy show
cc-switch -a claude provider current
cc-switch -a codex provider current
```

- daemon 启动日志位于 `/tmp/cc-switch-daemon.log`。
- “路由已启用”只表示本地代理接管成功，不证明上游地址或凭据有效。
- Codex `Running: no` 在默认官方直连场景是正常的；托管 Provider 才需启用 Codex 路由。
- `cannot execute: required file not found` 常见于旧镜像或 CRLF shebang，拉取当前源码并运行 `aisc build --no-cache`。

### Skills 没有更新

检查 `/tmp/cc-switch-skills-init.log`、`.cc-switch/.aisc-bundled-skills.sha256` 和三个 Skills 目录。文件锁不可用且已有目录时，默认拒绝覆盖属于保护行为；不要先删除包含自定义内容的目录。

提交 [GitHub Issues](https://github.com/wangyuncepu/AISC/issues) 时附上操作系统、CPU 架构、Docker 版本、`aisc version`、复现命令和已脱敏日志。不要上传 API Key、Cookie、登录令牌、Provider 数据库或完整配置目录。

## 许可

MIT License，详见 [LICENSE](LICENSE)。镜像还包含第三方组件，其来源、校验和与许可证记录在 `vendor/` 中。

## 推荐服务

以下是两个相互独立的第三方服务，链接中含推广或邀请参数。请按实际需求选择，并在使用前自行确认价格、服务条款、适用地区及合规要求。

### Codesome｜Codex 与 Claude Code 二合一服务

Codesome 提供 API 调用形式的二合一月卡：一张 `cr-...` API Key 可分别接入 Claude Code 和 Codex。这是 API 服务，不是 Claude 或 Codex 成品账号。

#### 购买与开通

Codesome 调整的是注册和下单入口，并非服务使用地址。请在新入口注册账号后选购产品：

[注册并前往 Codesome 选购](https://meta.codesome.cn/?aff=FAP2ASVX)

支付后请妥善保存订单详情中的序列号或卡密。不同产品的开通方式不同，请勿混用：

- **二合一产品（V5）**：订单中的 `cr-...` 卡密就是 API Key，可直接用于 Claude Code 和 Codex，不需要前往 V3 兑换。
- **普通 Claude/GPT 月卡及按量产品（V3）**：需要先在 V3 控制台兑换，再创建 `sk-...` API Key。

#### Claude Code 与 Codex 的区别

二合一 Key 可以同时用于两类客户端，但它们的 API URL 和配置字段不同，不能混用：

| 使用端 | API URL |
| --- | --- |
| Claude Code / Claude | `https://v5.codesome.cn/api` |
| Codex / OpenAI 格式客户端 | `https://v5.codesome.cn/openai` |

Claude Code 通过 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_AUTH_TOKEN` 配置；Codex 使用 OpenAI 格式的配置。完整安装和配置步骤请查看 Codesome 文档：

- [Claude Code 二合一配置教程](https://doc.codesome.ai/#/01-%E4%BA%8C%E5%90%88%E4%B8%80%E8%AE%A1%E5%88%92-ClaudeCode%E5%AE%89%E8%A3%85%E9%85%8D%E7%BD%AE)
- [Codex 二合一配置教程](https://doc.codesome.ai/#/01-%E4%BA%8C%E5%90%88%E4%B8%80%E8%AE%A1%E5%88%92-Codex%E5%AE%89%E8%A3%85%E9%85%8D%E7%BD%AE)
- [Codesome 文档首页](https://doc.codesome.ai/)



> 注册/下单入口与 Claude Code、Codex 的 API 地址用途不同。API Key 属于敏感凭据，请勿将其粘贴到公开页面、聊天记录或代码仓库中。

### 赔钱机场｜网络连接服务

赔钱机场提供网络连接服务，可用于改善部分网络环境下的访问体验。可通过以下邀请链接注册并查看可用套餐：

[前往赔钱机场注册](https://pqjc.site/register?code=EVYrdlM4&cover=sfw)

请在购买前确认套餐价格、流量限制、节点覆盖、退款政策及当地合规要求。AISC 与该服务相互独立，不对其可用性、稳定性或数据处理方式作保证。
