# AISC 使用手册

AISC 是一个在 Docker 容器中运行 Claude Code、OpenAI Codex 和 cc-switch 的个人开发工作站，提供两种使用方式：

- **AISC Workbench（推荐）**——桌面应用（Windows）。图形界面完成工作区选择、镜像构建、容器启动、终端、文件管理、Provider 配置与诊断，适合绝大多数用户。
- **AISC CLI（`aisc`）**——命令行入口。既随 Workbench 内置（作为后端 sidecar），也可独立安装用于脚本化与精细管理。

容器内的 AI CLI、Provider、凭据、路由和 Skills 均由 cc-switch 统一管理；宿主机不保存第二份凭据。

> **状态：Alpha。** 当前开发预览版本为 **v2.1.7-dev**（以仓库 [`VERSION`](VERSION) 为准），公开发布以 [Releases](https://github.com/wangyuncepu/AISC/releases) 页为准。Alpha 版本的命令、配置和持久化契约仍可能变化，升级前请阅读 Release Notes 并备份重要工作区。

## 目录

- [安全边界](#安全边界)
- [安装前提](#安装前提)
- [Workbench 使用指南](#workbench-使用指南)
- [CLI 使用指南](#cli-使用指南)
- [配置与持久化](#配置与持久化)
- [升级](#升级)
- [卸载](#卸载)
- [故障排查](#故障排查)
- [许可](#许可)
- [推荐服务](#推荐服务)

## 安全边界

AISC 以开发便利为优先，不是生产级安全沙箱：

- 容器以 `root` 运行，挂载的工作区对容器内进程可读写。
- Claude 包装器默认追加 `--dangerously-skip-permissions`；Codex 包装器默认追加 `--dangerously-bypass-approvals-and-sandbox` 和 `--dangerously-bypass-hook-trust`。这会绕过工具自身的危险操作确认。
- `IS_SANDBOX=1` 只是运行环境标记，不会建立额外隔离。Docker daemon 权限本身通常等同宿主机高权限。
- 代理模式额外授予 `NET_ADMIN` 并挂载 `/dev/net/tun`，扩大了容器网络权限。
- 只在可信代码和可恢复的工作区中运行。不要挂载密钥目录、生产数据或整段用户主目录；先提交或备份未保存的工作。
- API Key、登录令牌和 Provider 配置只交给 cc-switch 或对应官方 CLI，不要写入仓库、AISC 配置、Issue 或日志。

## 安装前提

运行 AISC 需要自行安装并启动 **Docker**（AISC 不代装，检测到缺失时会给出指引）：

| 平台 | 官方产物 | Docker |
| --- | --- | --- |
| Windows | x86_64（Workbench 安装器） | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
| Linux | x86_64（CLI 便携包） | Docker Engine；当前用户需有 daemon 权限 |
| macOS | Apple Silicon arm64（CLI 便携包/PKG） | Docker Desktop |

官方 Release **不提供** Linux arm64、Windows arm64 或 Intel macOS 产物。安装 AISC 本身不需要 Python、uv 或 Git；从源码构建需要 Python 3.11+ 和 Git，推荐使用 uv。

安装 Docker 后验证：

```bash
docker version
```

## Workbench 使用指南

### 安装

从 [GitHub Releases](https://github.com/wangyuncepu/AISC/releases) 下载 Windows 安装器（如 `AISC Workbench_2.1.7-dev_x64-setup.exe`）及 `.sha256`，校验后运行。安装器默认写入 `%LOCALAPPDATA%\Programs\AISC`，并添加用户 `PATH`。

AISC 尚未代码签名。SmartScreen 提示时，请先确认文件来自项目 Release 且 SHA256 正确，再选择“更多信息 -> 仍要运行”。

### 首次使用流程

1. **启动 Workbench**——直接进入工作区选择页（无强制引导）。
2. **选择工作区**——输入或浏览一个空目录/项目目录作为工作区；最近使用的工作区会列在下方（上限 8 条 + 展开更多；失效路径可一键清除记录，绝不触碰磁盘文件）。
3. **构建工作站镜像**——首次使用会引导构建镜像。构建页显示实时进度与百分比，完整日志可展开、可定位到磁盘日志文件；初次构建通常需要 10–20 分钟。构建可随时取消。网络受限环境下会自动回退国内镜像源继续构建（页面会明确提示“未钉版”）。
4. **启动运行时**——点击「启动」。首次启动需初始化容器环境（最长约 3 分钟，页面有进度提示）；之后启动快得多。
5. **进入工作区**——左侧为资源管理器与「变更」面板，右侧为终端区。

### 日常使用

- **终端**：`bash` / `claude` / `codex` 多页签，支持分屏；首次进入有上手速查卡，容器内输入 `help` 查看常用操作。`Ctrl+Shift+V` 粘贴、`Ctrl+F` 终端内搜索。
- **资源管理器（文件）**：目录树懒加载、右键新建/重命名/复制/粘贴、拖拽文件进终端（自动转容器路径）、顶部搜索（支持模糊与 `/正则/`）。
- **变更面板**：Agent 产出与文件改动统一呈现——徽章区分类型（新增/修改/删除/移动）与来源（Agent 登记或系统检测），支持分类筛选与搜索。
- **服务面板**：容器内通过 `aisc-web-expose <端口>` 注册的 Web 服务，可从面板一键在宿主浏览器打开。
- **Provider 管理**：顶栏进入 Providers 页。镜像已预置常见供应商（见下），点击行即可激活；填入 API Key 即可使用，切换即时生效，无需重启。
- **网络与用量**（设置页）：代理模式可导入机场订阅（自动转换为容器 TUN 配置）；用量面板聚合各工作区 token 消耗与余量。
- **多工作区**：最多同时打开 3 个工作区，页签条切换；关闭即自动停止并清理对应容器。
- **彻底忘记工作区**：工作区历史右键 -> 彻底忘记，单事务清理 AISC 数据根内该工作区的状态与记录（容器先停止删除，失败自动回滚）；你磁盘上的原始文件永不被触碰。
- **诊断**：任何页面可打开诊断对话框（环境检查、最近日志、导出诊断包）。

### 预配置供应商（v2.1.7+）

镜像内置以下预置 Provider，用户只需填 API Key：

| 供应商 | 说明 |
| --- | --- |
| **DeepSeek** | V4 系列（pro/flash）；Codex 走官方 Responses 端点 |
| **火山引擎 Ark** | 兼容 OpenAI 格式；需配置接入点 ID |
| **智谱 GLM** | GLM-5.2 旗舰模型 |
| **Kimi** | 月之暗面 Kimi K3 |
| **Codesome-Group** | 二合一中转；Codex 默认模型 `gpt-5.6-sol`，Claude 侧 `https://v5.codesome.cn/api` |

v2.1.7 起所有预置供应商的 Codex 上游格式统一为 **OpenAI Responses API（原生直连）**，存量容器在下次启动时自动刷新（用户自定义值不受影响）。

## CLI 使用指南

CLI 适合脚本化、远程环境或不使用 GUI 的场景。Workbench 安装版已包含 `aisc`，也可独立安装。

### 独立安装

**Linux x86_64**（便携）：

```bash
sha256sum -c AISC-<ver>-linux-x86_64.tar.gz.sha256
tar -xzf AISC-<ver>-linux-x86_64.tar.gz
cd AISC-<ver>-linux-x86_64
./aisc version
```

便携运行时，`aisc` 与 `aisc-bundle/` 必须保持相邻。也可用仓库中的脚本安装到用户目录：

```bash
bash packaging/install.sh /path/to/AISC-<ver>-linux-x86_64.tar.gz
```

**macOS arm64**：推荐 `.pkg`（需管理员密码，安装到 `/usr/local/lib/aisc/`）；或使用便携 `.tar.gz` / `packaging/install.sh`。

**Windows**：Workbench 安装器已含 CLI；便携 `.zip` 可配合 `packaging/install.ps1` 安装到 `%LOCALAPPDATA%\AISC`。

**从源码**：

```bash
git clone https://github.com/wangyuncepu/AISC.git
cd AISC
uv tool install --editable .
```

editable 安装记录仓库绝对路径，移动仓库前先 `uv tool uninstall aisc`。

### 快速开始

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
- 前台交互终端 `-it`，容器退出后由 `--rm` 自动删除。
- 自动生成 `<name>-<8位十六进制>` 容器名，并登记到 registry。

容器初始化时先选择作用域：

1. `temporary`：Claude、Codex 和 cc-switch 状态位于 `/tmp/aisc-home`，容器结束即重置。
2. `project`：状态持久化到数据根的工作区目录，跨容器保留；默认选项。

随后可选择 `bash`、`claude`、`codex` 或 `cc-switch`，默认进入 `bash`。

需要从另一个终端管理当前容器时：

```bash
aisc ps
aisc status
aisc shell
aisc switch
```

保留容器 / 非交互模式：

```bash
aisc run --keep-alive --label work
aisc shell --label work
aisc stop --label work
aisc run --non-interactive   # 脚本/CI：无 TTY，项目作用域
```

### CLI 参考

宿主机唯一入口为 `aisc`。全局选项：

| 选项 | 说明 |
| --- | --- |
| `--format text\|json` | 默认 `text`；JSON 模式输出统一 envelope |
| `--no-color` | 禁用 ANSI 颜色 |
| `--aisc-root PATH` | 指定资源根；重复出现时最后一个值生效 |
| `--events` | 仅 `build`、`run` 支持的 JSONL 事件流 |

`--format json` 与 `--events` 互斥。机器输出模式下 stdout 只保留 JSON envelope 或 JSONL，Docker 子进程输出转发到 stderr。

| 命令 | 主要参数 | 作用 |
| --- | --- | --- |
| `aisc version` | 全局选项 | 显示 CLI、Python、bundle 和声明依赖版本信息 |
| `aisc doctor` | 全局选项 | 只读检查 Docker、权限、buildx、TUN、Git、资源根和目录可写性 |
| `aisc build` | `--tag/-t`, `--no-cache`, `--pull`, `--dry-run`, `--require-pin` | 构建镜像；默认 tag 为 `super-claude:latest` |
| `aisc run` | `--image/-i`, `--workspace`, `--name`, `--label`, `--network`, `--keep-alive`, `--non-interactive`, `--dry-run` | 启动并登记容器 |
| `aisc ps` | 全局选项 | 列出 registry 中容器的 label、实时状态、镜像和工作区 |
| `aisc status` | `--name`, `--label` | 查看目标容器状态 |
| `aisc stop` | `--name`, `--label` | 停止目标容器；已停止时幂等成功 |
| `aisc restart` | `--name`, `--label` | 重启目标容器 |
| `aisc shell` | `--name`, `--label` | 执行 `docker exec -it <name> bash` |
| `aisc session open` | — | 打开托管会话终端（Workbench 内部使用同一通道） |
| `aisc switch` | `--name`, `--label`, `--quick PROVIDER` | 打开 cc-switch TUI，或快速切换 Claude Provider |
| `aisc provider set-key` | `PROVIDER_ID`, `--name`, `--label`, `--agent` | 打开 cc-switch provider 安全交互编辑器；凭据不进命令行参数 |
| `aisc config validate/effective` | `--config`, `--workspace` | 校验/展示合并配置与来源 |
| `aisc profile list/show` | 全局选项 | 只读列出/显示 Profile |
| `aisc logs show/path` | `--source app\|cli\|ui\|all` | 查看统一 JSONL 日志时间线 |
| `aisc usage overview` | 全局选项 | 跨工作区聚合用量 |
| `aisc network subscription …` | `import/import-file/refresh/show/clear` | 代理订阅数据面（URL 与内容走 stdin） |
| `aisc maintenance docker-scan/cleanup/rebuild` | `--context`, `--root`, `--tag` | Docker 资源归属扫描/清理/重建（卸载与升级同一服务） |

多容器寻址顺序：显式 `--name` -> 唯一匹配的 `--label` -> registry 默认目标 -> 唯一登记容器；无法消歧时列出候选并要求指定。

构建相关补充：

- 网络受限时，cc-switch 版本解析按「在线 → 缓存 → 本地回执 → 无钉版国内镜像源构建」递进；`--require-pin`（或 `AISC_REQUIRE_PIN=1`）恢复严格失败。
- `aisc build --events` 输出 JSONL 进度事件（`build.progress` 等），供前端/脚本消费。

### 容器内使用

```bash
claude
codex
cc-switch
```

Provider、认证与路由只由 cc-switch 管理：

```bash
cc-switch -a claude provider list
cc-switch -a claude provider switch <provider>
cc-switch -a codex provider list
cc-switch proxy show
```

启动时 AISC 会 detach 启动 cc-switch daemon。Claude 路由 best-effort 自动启用；Codex 默认官方直连，需要托管 Provider 时执行 `cc-switch proxy -a codex enable`。

Skills 同步：镜像内置 `caveman`、`document-skills`、`grill-me`、`superpowers`，由 cc-switch 登记（`cc-switch skills list/sync`）；容器入口按 `AISC_SKILLS_SYNC=auto|always|off` 控制同步策略。

代理网络（CLI）：

```bash
aisc run --network proxy
```

要求宿主支持 `/dev/net/tun`，且存在可被 `container/mihomo-build-config.js` 转换的订阅/配置；配置只读挂载为 `/etc/mihomo/config.yaml`。`--profile proxy` 是兼容别名。

## 配置与持久化

### 数据根（推荐认知模型）

Workbench 与 CLI 共享统一数据根：

| 平台 | 数据根 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\AISC\data` |
| Linux | `${XDG_DATA_HOME:-$HOME/.local/share}/aisc` |
| macOS | `$HOME/Library/Application Support/aisc` |

其中包含全局设置、各工作区状态（`workspaces/<hash>/` 下的 claude/codex/cc-switch/runtime 目录与持久工具链）、缓存与日志（`logs/aisc.log`，JSONL 统一时间线，`aisc logs show` 查看）。

### 持久化要点

- 工作区状态在数据根（不在工作区目录内），「彻底忘记」才会清除。
- 持久工具链：Agent 安装的用户级 npm/pip/cargo 工具跨容器、跨会话保留（挂载 `/opt/aisc/toolchain`）。
- AISC 用户配置：`aisc config`（JSON，用户层 + 工作区层 `<workspace>/.aisc/config.json`，未知键告警忽略）。
- 资源根（`aisc-bundle/`）须包含 `VERSION`、`container/Dockerfile`、`config/versions.env`；查找顺序 `--aisc-root` -> `AISC_ROOT` -> 可执行文件旁 `aisc-bundle/` -> Git 仓库向上查找 -> editable 源码祖先。

## 升级

- **Windows Workbench**：运行新版安装器覆盖安装。安装器会先停止并删除 AISC 管理的容器，替换文件后对默认镜像执行**无缓存重建**（可能需要几分钟），成功后清理旧镜像；Docker 不可用时文件照常更新，镜像重建转为待办并给出手动命令。
- **macOS PKG / 便携脚本**：覆盖安装或重新执行 `packaging/install.sh <new-archive>`。
- **uv tool**：`git pull` 后 `uv tool upgrade aisc` 或重装；镜像内容变化时需重新 `aisc build`。

用户配置、工作区状态与持久工具链在升级中全部保留。

## 卸载

| 安装方式 | 卸载方式 |
| --- | --- |
| Windows Workbench 安装器 | Windows“设置 -> 应用 -> 已安装的应用” |
| Windows `packaging/install.ps1` | `powershell -File packaging/uninstall.ps1` |
| macOS PKG | `sudo /usr/local/lib/aisc/uninstall.sh` |
| Linux/macOS `packaging/install.sh` | `bash packaging/uninstall.sh` |
| uv tool | `uv tool uninstall aisc` |

默认卸载会清理 **可证明属于 AISC 的** Docker 资源（容器 + 工作站镜像）；归属不明的仅报告不删除，绝不触碰非 AISC 容器/镜像、卷和网络。保留 Docker 资源：NSIS 卸载不勾选清理项（或 `/KEEPDOCKER`）；便携/POSIX 脚本加 `--keep-docker-resources`。

卸载器不删除工作区与用户配置。需要彻底清理时（谨慎，含登录态/凭据）：

```bash
aisc maintenance docker-cleanup --context uninstall --format json
aisc maintenance docker-scan --context uninstall --format text   # 只读预览
```

## 故障排查

### 通用

```bash
aisc doctor          # 环境只读体检
aisc logs show       # 统一日志时间线
```

Workbench 内：打开诊断对话框查看环境检查与最近日志，可导出诊断包。

### 常见问题

| 现象 | 处理 |
| --- | --- |
| 找不到 `aisc` | 重开终端；Linux/macOS 确认 `~/.local/bin` 在 `PATH`；便携包保持 `aisc` 与 `aisc-bundle/` 相邻 |
| Docker 未运行 | 启动 Docker Desktop / Engine；Workbench 摘要页有「启动 Docker」唤起与自动重试 |
| Docker 未安装 | 自行安装（见[安装前提](#安装前提)）；Workbench 会给出指引并自动识别 |
| `Image not found` | 先构建镜像（Workbench 构建页或 `aisc build`） |
| 构建卡在下载/网络受限 | v2.1.7 起自动回退国内镜像源；仍失败时查看构建日志的真实错误原因 |
| 首次启动很久 | 首启需初始化容器环境（最长约 3 分钟）；二次启动恢复正常速度 |
| Windows 报「无可用网关端口」(47000-47999) | WSL2 系统级端口保留所致：管理员执行 `wsl --shutdown`，再 `netsh int ipv4 add excludedportrange protocol=tcp startport=47000 numberofports=1000`，然后重启 Docker Desktop |
| cc-switch daemon/路由异常 | 容器内 `cc-switch daemon status` / `proxy show`；daemon 日志在 `/tmp/cc-switch-daemon.log` |

提交 [GitHub Issues](https://github.com/wangyuncepu/AISC/issues) 时附上操作系统、CPU 架构、Docker 版本、`aisc version`、复现命令和已脱敏日志。不要上传 API Key、Cookie、登录令牌、Provider 数据库或完整配置目录。

## 许可

MIT License，详见 [LICENSE](LICENSE)。镜像还包含第三方组件，其来源、校验和与许可证记录在 `vendor/` 中。

## 推荐服务

以下是两个相互独立的第三方服务，链接中含推广或邀请参数。请按实际需求选择，并在使用前自行确认价格、服务条款、适用地区及合规要求。

### Codesome｜Codex 与 Claude Code 二合一服务

Codesome 提供 API 调用形式的二合一月卡：一张 `cr-...` API Key 可分别接入 Claude Code 和 Codex。这是 API 服务，不是 Claude 或 Codex 成品账号。

**v2.1.7 起 AISC 镜像已内置 Codesome-Group 预置供应商**——Workbench 的 Providers 页或容器内 cc-switch 选择 Codesome-Group、填入 API Key 即可使用，无需手工配置端点。

手动配置时的端点（二合一 Key 两端通用，URL 不同不可混用）：

| 使用端 | API URL |
| --- | --- |
| Claude Code / Claude | `https://v5.codesome.cn/api` |
| Codex / OpenAI 格式客户端 | `https://v5.codesome.cn/openai` |

Claude Code 通过 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_AUTH_TOKEN` 配置；Codex 使用 OpenAI 格式配置。完整教程见 [Codesome 文档](https://doc.codesome.ai/)。

购买与开通（注册/下单入口，非服务使用地址）：

[注册并前往 Codesome 选购](https://meta.codesome.cn/?aff=FAP2ASVX)

支付后妥善保存订单中的序列号/卡密：**二合一产品（V5）** 的 `cr-...` 卡密即 API Key；**普通月卡及按量产品（V3）** 需先在 V3 控制台兑换再创建 `sk-...` Key。

> API Key 属于敏感凭据，请勿将其粘贴到公开页面、聊天记录或代码仓库中。

### 赔钱机场｜网络连接服务

赔钱机场提供网络连接服务，可用于改善部分网络环境下的访问体验，也可作为 AISC 代理模式的订阅来源。可通过以下邀请链接注册并查看可用套餐：

[前往赔钱机场注册](https://www.xn--cp3a08l.com/register?code=EVYrdlM4&cover=sfw)

请在购买前确认套餐价格、流量限制、节点覆盖、退款政策及当地合规要求。AISC 与该服务相互独立，不对其可用性、稳定性或数据处理方式作保证。
