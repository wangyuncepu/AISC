# AISC v2 结构与可用性重构计划

> 状态：提案
>
> 核心目标：项目结构清晰、工具可用性高，新手能够立即上手并开箱即用。
>
> 编写日期：2026-07-16

## 1. 背景与结论

当前项目已经具备较完整的 Claude Code 容器工作站能力，但代码组织、产品边界和用户入口随着功能增长逐渐出现漂移。

主要问题不是功能不足，而是：

- 产品边界不清楚：Claude 工作站、代理、LiteLLM、AI 简讯和供应商切换混在同一运行链路中。
- 源码、构建产物和运行状态混杂：构建脚本会临时修改 `image/`，运行状态分散在 `.claude/`、`.cc-config/` 和 `.deploy/`。
- 多平台实现逐渐漂移：Bash、PowerShell 和 macOS 启动器的行为不完全一致。
- 文档与实现不一致：启动文件名、LiteLLM 集成状态、AI 简讯缓存和耗时说明均有偏差。
- 启动路径过重：非核心 AI 简讯可能让启动额外等待约 50 秒。
- 单文件职责过多：`entrypoint.sh`、`claude-switch` 和 Dockerfile 都承担了过多职责。
- 缺少质量护栏：没有项目自有的自动化测试、CI、版本清单和可重复发布流程。

建议将 AISC 的产品定义收敛为：

> 一个开箱即用、可离线构建、支持中国网络环境的 Claude Code 容器工作站。核心只负责环境检查、构建、配置和启动；代理、LiteLLM、AI 简讯作为可选能力。

推荐的默认产品边界：

| 能力 | 定位 | 默认行为 |
| --- | --- | --- |
| Claude Code 工作站 | 核心 | 默认启用 |
| API 供应商切换 | 核心 | 首次配置，后续复用 |
| Docker 构建与启动 | 核心 | 默认启用 |
| Mihomo 代理 | 可选 profile | 默认关闭 |
| LiteLLM 协议转换 | 可选组件 | 默认不安装、不启动 |
| AI 简讯 | 可选工具 | 默认不阻塞启动 |
| 危险权限模式 | 高级 profile | 默认关闭或首次明确确认 |

## 2. 已识别的关键问题

### 2.1 新手入口已经发生漂移

- README 仍包含旧的中文启动文件名，但工作区正在迁移到 `start.sh`、`start.bat` 和 `start.command`。
- 当前 `start.command` 仍调用不存在的旧中文脚本，macOS 双击启动会失败。
- README 较长且偏功能介绍，缺少一个屏幕内的 clone-to-first-prompt 路径。
- 每次启动重复询问代理等配置，不利于日常使用。

### 2.2 产品宣传与实际实现不一致

- README 将 LiteLLM 协议转换描述为内置能力，但当前 Dockerfile 并未安装或复制 LiteLLM demo。
- `api_route_demo/`（LiteLLM demo）已移除（P0 清理），不再作为项目组件存在。
- README 中供应商数量、模型和 endpoint 与 `claude-switch` 中的实际配置不一致。
- `ai_brief/README.md` 的缓存位置、预计耗时和行为说明已经落后于代码。

### 2.3 构建过程会修改源码目录

当前 Dockerfile 的 `COPY ai_brief/` 依赖构建脚本先将文件临时复制到 `image/ai_brief/`，构建后再删除。

这会导致：

- README 中直接执行的手动 Docker build 在干净 clone 上可能失败。
- Bash 和 PowerShell staging 行为容易漂移。
- 异常退出后可能留下旧文件或 root 所有者文件。
- 构建输入不是显式、确定的仓库状态。

### 2.4 启动链路职责过多

当前 `image/entrypoint.sh` 同时负责：

- locale 和终端环境；
- 工作区 `.claude` 初始化和修复；
- 插件 registry 路径重写；
- 文件所有权修复；
- settings 和环境变量注入；
- 后端信息展示；
- Mihomo TUN 配置、启动和健康检查；
- 同步运行 AI 简讯；
- 启动菜单和命令分发；
- 最终进程启动。

非核心 AI 简讯可能占用几十秒，违背“立即可用”的核心目标。

### 2.5 供应商切换工具职责过载

`claude-switch` 同时负责：

- 供应商和模型切换；
- API key 保存；
- 当前配置展示；
- `.claude` factory 模板升级；
- 文件删除和交互确认。

供应商、模型和 endpoint 全部硬编码在大型脚本中，新增或修改供应商需要同时维护脚本和文档。

### 2.6 离线资源缺少正式制品管理

项目跟踪 `_bundle` 和下载文件是为了支持中国网络及离线构建，这一需求应保留。但当前存在以下问题：

- 缺少完整 manifest 和 checksum。
- `skills-lock.json` 不能代表全部 bundled 依赖。
- staging 工具依赖维护者本机 `~/.claude` 的可变状态。
- 版本、来源和许可证不够明确。

### 2.7 缺少项目自有测试与 CI

仓库中可见的测试主要来自 vendored 第三方内容，并不是 AISC 自己的行为测试。目前没有：

- Bash/PowerShell 语法和行为检查；
- Python、JavaScript 工具测试；
- Docker 构建 smoke test；
- 文档与配置一致性检查；
- secret scanning；
- 发布和版本一致性检查。

### 2.8 安全默认值需要明确

当前产品强调便利性，但默认使用 `--dangerously-skip-permissions`，容器用户还有无限制 passwordless sudo。对于绑定挂载用户项目的容器，这一行为风险较高。

重构后应让安全模式成为默认，危险权限通过显式 profile 或首次确认开启。

## 3. 设计原则

### 3.1 三步以内首次启动

新用户理想路径：

```bash
git clone <repo>
cd AISC
./start.sh
```

首次启动只询问真正无法推断的内容，后续启动直接复用配置。

### 3.2 一个统一入口

用户只需要认识 `aisc` 命令。根目录的 `start.*` 仅作为平台薄启动器：

```bash
./start.sh
./start.sh doctor
./start.sh config
./start.sh build
./start.sh run
```

### 3.3 核心与附加功能隔离

LiteLLM、AI 简讯和 Mihomo 不应影响最小工作站的启动与构建。

### 3.4 配置驱动

供应商、模型、镜像源、版本、下载地址和功能开关应由数据文件描述，而不是散落在大型脚本和 README 中。

### 3.5 构建不修改源码

构建过程中不再临时创建和删除 `image/ai_brief/`。构建输入必须确定、可审计、可复现。

### 3.6 默认安全

危险权限必须显式开启，并清楚说明它对绑定挂载工作目录的影响。

### 3.7 保留离线能力

Vendored 资源属于产品能力，不直接删除，而是升级为带版本、来源、哈希和许可证的正式制品。

### 3.8 小步迁移

先修复现有可用性，再调整目录和职责，最后完善质量体系。避免一次性重写所有 Bash 和 PowerShell 逻辑。

## 4. 目标目录结构

```text
AISC/
├── README.md
├── VERSION
├── CHANGELOG.md
├── LICENSE
├── .dockerignore
├── .gitignore
│
├── start.sh
├── start.bat
├── start.command
│
├── cli/
│   ├── aisc.sh
│   ├── aisc.ps1
│   ├── commands/
│   │   ├── doctor.sh
│   │   ├── config.sh
│   │   ├── build.sh
│   │   ├── run.sh
│   │   └── clean.sh
│   └── lib/
│       ├── config.sh
│       ├── docker.sh
│       └── output.sh
│
├── config/
│   ├── defaults.env
│   ├── providers.json
│   ├── versions.env
│   └── mirrors.json
│
├── container/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── bin/
│   │   ├── aisc-container
│   │   ├── claude-wrapper
│   │   ├── provider-switch
│   │   └── workspace-upgrade
│   ├── lib/
│   │   ├── settings.sh
│   │   ├── proxy.sh
│   │   └── workspace.sh
│   └── defaults/
│       ├── claude-settings.json
│       ├── global-claude.md
│       └── commands/
│
├── apps/
│   ├── ai-brief/
│   │   ├── README.md
│   │   ├── brief.py
│   │   ├── run.sh
│   │   └── tests/
│
├── vendor/
│   ├── manifest.json
│   ├── checksums.txt
│   ├── licenses/
│   ├── skills/
│   └── downloads/
│
├── tools/
│   ├── vendor-refresh.sh
│   ├── vendor-verify.sh
│   ├── release.sh
│   └── check-docs.sh
│
├── tests/
│   ├── smoke/
│   ├── fixtures/
│   ├── shell/
│   └── integration/
│
├── docs/
│   ├── getting-started.md
│   ├── configuration.md
│   ├── providers.md
│   ├── proxy.md
│   ├── troubleshooting.md
│   ├── security.md
│   ├── development.md
│   ├── architecture.md
│   └── archive/
│
└── .github/
    └── workflows/
        ├── checks.yml
        └── docker-smoke.yml
```

目录职责：

| 目录 | 职责 |
| --- | --- |
| `cli/` | 宿主机产品入口，只负责检查、配置、构建、启动和诊断 |
| `container/` | 容器镜像及容器内部运行逻辑 |
| `apps/` | 可独立使用、测试和文档化的附加工具 |
| `config/` | 供应商、版本、镜像源和默认值的唯一事实来源 |
| `vendor/` | 离线资源和第三方制品，与核心源码隔离 |
| `tools/` | 维护者工具，不进入普通用户启动链路 |
| `tests/` | AISC 自有测试，不混入第三方测试 |

启动器运行状态统一放在被 Git 忽略的 `.aisc/`：

```text
.aisc/
├── config.env
├── state.json
├── secrets/
├── cache/
└── logs/
```

Claude Code 必需的项目级 `.claude/` 可以继续保留，但启动器自身状态不再散落到 `.cc-config/` 和 `.deploy/`。

## 5. 用户命令设计

### 5.1 默认入口

```bash
./start.sh
```

等价于：

```bash
./start.sh run
```

### 5.2 推荐命令

```text
aisc run                 启动工作站
aisc doctor              检查 Docker、网络、权限和配置
aisc config              交互式修改持久配置
aisc config show         显示脱敏后的有效配置
aisc build               构建镜像
aisc build --no-cache    无缓存构建
aisc provider list       查看可用供应商
aisc provider use NAME   切换供应商
aisc proxy enable        启用代理 profile
aisc proxy disable       关闭代理 profile
aisc brief               手动运行 AI 简讯
aisc logs                查看最近启动日志
aisc version             显示 CLI、镜像和 Claude 版本
aisc clean               清理缓存，不删除用户密钥
```

高级用法：

```bash
aisc run --workspace ~/project
aisc run --profile proxy
aisc run --profile unsafe
aisc run --provider deepseek
aisc run --non-interactive
```

关键行为：

- 默认 workspace 是当前目录，不假定 AISC 仓库就是用户项目。
- `--workspace` 明确区分 AISC 安装位置和用户工作目录。
- 首次配置完成后，不再每次询问代理和镜像。
- 自动检测已有镜像，仅在必要时重建。
- 非交互模式缺少必要配置时快速失败，并给出明确修复命令。

## 6. 配置模型

### 6.1 供应商配置

将 `claude-switch` 中硬编码的供应商迁移到 `config/providers.json`：

```json
{
  "deepseek": {
    "label": "DeepSeek",
    "base_url": "https://example.com/anthropic",
    "default_model": "deepseek-chat",
    "auth": "api_key"
  }
}
```

密钥不写入该文件，只保存在：

```text
.aisc/secrets/providers/deepseek
```

收益：

- 新增供应商不需要修改大型 shell case。
- README 的供应商列表可以通过校验或生成保持同步。
- `provider list/use/show` 使用同一份数据。
- 模型和 endpoint 不再散落在脚本、README 和镜像中。

### 6.2 版本配置

`config/versions.env` 统一管理外部版本：

```bash
AISC_VERSION=2.0.0
NODE_IMAGE=node:20.x-slim@sha256:...
CLAUDE_CODE_VERSION=x.y.z
MIHOMO_VERSION=x.y.z
GEODATA_VERSION=...
```

镜像标签、Docker label、CLI `version` 和发布流程都从同一版本源读取。

## 7. 容器内部重构

将 `entrypoint.sh` 缩减为流程控制器：

```text
1. 初始化环境
2. 检查挂载目录
3. 应用用户配置
4. 按 profile 启动可选服务
5. 显示简短状态
6. exec 用户命令
```

拆分后的职责：

| 模块 | 职责 |
| --- | --- |
| `workspace.sh` | 初始化项目 `.claude/`、迁移和权限检查 |
| `settings.sh` | 生成 Claude settings 和环境变量 |
| `proxy.sh` | Mihomo 配置、启动和健康检查 |
| `provider-switch` | 仅负责供应商查看与切换 |
| `workspace-upgrade` | 单独负责 factory 模板升级 |
| `claude-wrapper` | 组装最终 Claude 启动参数 |
| `entrypoint.sh` | 调度以上模块，不实现复杂业务 |

AI 简讯不再由 entrypoint 同步执行：

1. 默认完全不运行。
2. 用户执行 `aisc brief` 时运行。
3. 可选配置 `AI_BRIEF_ON_START=background`，启动后后台生成。
4. 失败只写日志，不影响 Claude 主进程。

## 8. 构建系统重构

### 8.1 使用仓库根目录作为构建上下文

推荐统一为：

```bash
docker build -f container/Dockerfile .
```

根 `.dockerignore` 至少排除：

```text
.git
.aisc
.claude
.cc-config
.deploy
**/__pycache__
docs
tests
```

Dockerfile 可以直接复制正式源码：

```dockerfile
COPY apps/ai-brief /opt/aisc/apps/ai-brief
COPY container/bin /usr/local/lib/aisc/bin
COPY vendor /opt/aisc/vendor
```

这样可以消除构建前临时创建 `image/ai_brief/`、构建后再删除的隐式流程，并保证手动构建和 CLI 构建完全一致。

### 8.2 Dockerfile 分层

建议按以下阶段组织：

```text
base            OS 包、locale、证书
downloads       Mihomo、geodata、外部制品校验
node-runtime    固定版本 Claude Code
python-runtime  可选 Python 工具依赖
runtime         非 root 用户、脚本和默认配置
```

LiteLLM 不进入默认镜像。可以采用独立 target 或独立 Compose profile：

```bash
docker build --target core
docker build --target full
```

## 9. 文档重构

根 README 只保留：

1. 项目是什么。
2. 30 秒快速开始。
3. 支持平台。
4. 三个最常用命令。
5. 默认安全行为。
6. 功能入口。
7. 文档索引。

快速开始应控制在一个屏幕内：

```bash
git clone <repo>
cd AISC
./start.sh
```

详细内容迁移到：

- `docs/getting-started.md`
- `docs/configuration.md`
- `docs/providers.md`
- `docs/proxy.md`
- `docs/troubleshooting.md`
- `docs/security.md`
- `docs/development.md`

已经完成的历史计划和 devlog 移入 `docs/archive/`，避免与当前实施计划混淆。

必须优先修正的文档偏差：

- 统一 `start.sh`、`start.bat` 和 `start.command` 名称。
- 修复 `start.command` 调用不存在旧脚本的问题。
- 明确 LiteLLM 是内置能力还是独立示例。
- 更新 AI 简讯缓存目录、耗时、`--debug` 和失败回退说明。
- 让供应商数量、模型和 endpoint 从配置生成或接受自动校验。
- 删除当前无法兑现的“内置”或“开箱即用”声明。

## 10. 跨平台策略

不继续让 Bash 和 PowerShell 各自独立演进完整业务流程。

短期保留：

```text
start.sh      Unix/macOS 薄入口
start.bat     Windows 薄入口
start.command macOS 双击入口
```

业务流程可以暂时分别由 Bash 和 PowerShell 实现，但必须共享：

- 配置文件格式；
- 命令名称；
- 状态目录；
- Docker 参数；
- 错误码；
- 输出语义；
- 测试用例。

Windows 需要明确支持基线：

- 如果支持 Windows PowerShell 5.1，就不能依赖 `Invoke-WebRequest -SkipHttpErrorCheck`。
- 如果只支持 PowerShell 7，则 `start.bat` 应检测 `pwsh` 并给出安装提示。
- 优先兼容系统自带 Windows PowerShell 5.1，减少新手前置安装。

中期可以评估小型 Python CLI 统一多平台逻辑，但不应在第一阶段立即重写。

## 11. 安全模型

提供两个明确 profile：

```text
safe     默认，不自动跳过 Claude 权限确认
unsafe   显式启用 dangerously-skip-permissions
```

首次开启 unsafe 时提示：

```text
该模式允许 Claude 在挂载工作目录内无需逐项确认执行操作。
建议仅在受信任项目中使用。
```

其他安全措施：

- API key 只存放在 `.aisc/secrets/`，目录权限限制为当前用户。
- `config show` 必须脱敏。
- CI 增加 secret scanning。
- 容器默认不获取 `NET_ADMIN`，仅代理 profile 添加。
- 评估是否确实需要无限制 passwordless sudo。
- 文档明确宿主目录挂载边界和危险权限影响。

当前没有证据表明密钥曾被 Git 跟踪，因此无需基于现有证据重写 Git 历史，但需要加入持续扫描以防止未来误提交。

## 12. 测试与 CI

项目自有测试必须与 vendored 第三方测试严格分开。

### 12.1 快速检查

每次提交执行：

```text
bash -n
PowerShell 语法解析
python -m compileall
node --check
JSON/YAML 格式检查
文档链接检查
配置与 README 一致性检查
secret scan
```

### 12.2 单元测试

至少覆盖：

- 供应商配置读取、切换和密钥脱敏。
- workspace 路径包含空格时的 Docker 参数。
- 首次配置与已有配置复用。
- 代理开关对应的 capability 和挂载。
- 版本文件读取和镜像标签生成。
- AI 简讯超时、部分源失败和缓存回退。

### 12.3 集成测试

至少覆盖：

```text
doctor 在无 Docker和有 Docker时的行为
使用最小 fixture 构建镜像
容器启动后 claude-wrapper 可执行
默认模式不启动 Mihomo
默认模式不运行 AI 简讯
proxy profile 能生成预期 Docker 参数
手动 docker build 与 CLI build 使用相同上下文
```

项目是交互式短生命周期容器，不为形式机械添加 Docker `HEALTHCHECK`，而使用独立 smoke test 命令验证。

## 13. 分阶段迁移

### P0：修复当前可用性

目标：先让现有项目真正可启动、文档可信，不进行大规模搬迁。

- 完成启动器重命名，统一使用 `start.sh`、`start.bat` 和 `start.command`。
- 修复 `start.command` 调用错误。
- 更新 README 中所有启动命令。
- 明确 LiteLLM 当前真实状态，暂时标记为实验性示例。
- 修正 AI 简讯文档和 `.gitignore`。
- 修复 PowerShell 5.1 不兼容调用。
- 让 PowerShell 构建前明确删除旧 staging 目录，避免平台差异。
- AI 简讯默认不再阻塞启动。
- 增加最小 `doctor` 检查，至少覆盖 Docker 和路径问题。

验收标准：

- Windows、macOS、Linux 文档中的第一条命令都真实可执行。
- 新 clone 可以按 README 完成首次启动。
- 手动构建不会因为缺少临时 `image/ai_brief` 目录失败。
- 启动核心工作站不等待 AI 简讯。

### P1：建立清晰边界

目标：解决目录和职责混乱。

- 建立 `cli/`、`container/`、`apps/` 和 `config/`。
- 将 Docker 构建上下文移到仓库根目录。
- 删除构建脚本临时修改 `image/` 的机制。
- 将 `ai_brief` 移入 `apps/ai-brief/`。
- ~~将 `api_route_demo` 重命名为 `apps/litellm-proxy/`~~（P0 已移除 demo，此条不再适用）。
- 将 `claude-switch` 拆为供应商切换和工作区升级。
- 把供应商信息迁移到 `providers.json`。
- 将启动器状态归并到 `.aisc/`。
- 支持显式 `--workspace PATH`。

验收标准：

- 每个顶层目录可以用一句话说明职责。
- 构建过程中 `git status` 不产生任何变化。
- 新增供应商只需要修改配置和测试，不需要修改大型 shell case。
- LiteLLM 和 AI 简讯失败不影响核心工作站。
- 当前目录与 AISC 仓库目录可以完全不同。

### P2：可重复构建与质量保障

目标：让维护者可以稳定发布，让用户获得一致结果。

- 引入 `versions.env` 和根 `VERSION`。
- 固定 Node 基础镜像 digest、Claude Code、Mihomo 和 Python 依赖。
- 为 vendor 增加 manifest、SHA256 和许可证信息。
- 将 `stage-skills.sh` 改造成确定性的 `vendor-refresh`。
- 增加 `vendor-verify`。
- 建立 GitHub Actions。
- 加入 Docker smoke test、secret scan 和文档一致性检查。
- 规范错误码和日志位置。
- 提供 `aisc logs` 和诊断报告。

验收标准：

- 相同 commit 和配置可以得到相同版本集合。
- 离线资源损坏时，构建前可通过 checksum 检出。
- CI 可以发现 Bash/PowerShell 行为漂移。
- 发布版本、镜像标签和 README 版本一致。

### P3：体验优化

目标：真正实现新手开箱即用。

- 支持配置复用和无交互启动。
- 提供配置迁移器，将 `.cc-config`、`.deploy` 迁移到 `.aisc`。
- 提供 `safe`、`proxy` 和 `unsafe` profile。
- 提供预构建镜像，保留本地构建作为离线方案。
- 优化镜像层缓存和下载镜像选择。
- 根据维护成本决定是否将宿主 CLI 统一为 Python。
- 增加结构化诊断输出，便于提交 issue。

验收标准：

- 已配置用户再次启动时无需回答问题。
- 有预构建镜像时，首次启动不要求本地完整构建。
- 常见错误都给出可执行的修复命令。
- 普通用户无需理解 `image/`、`.deploy/` 或 Docker capability。

## 14. 实施优先级

| 优先级 | 工作 | 原因 |
| --- | --- | --- |
| P0 | 修复启动文件名和 macOS 启动器 | 当前直接阻断使用 |
| P0 | 消除手动构建对临时 staging 的依赖 | README 构建路径当前不可靠 |
| P0 | AI 简讯移出同步启动 | 直接影响“立刻可用” |
| P0 | 明确 LiteLLM 产品定位 | 文档与实现严重漂移 |
| P1 | 根构建上下文和目录重组 | 解决构建耦合根因 |
| P1 | 数据驱动供应商配置 | 降低脚本复杂度和文档漂移 |
| P1 | 拆分 entrypoint 和 claude-switch | 提升可测试性和维护性 |
| P2 | 测试、CI 和版本锁定 | 防止重构后再次漂移 |
| P2 | vendor 清单和校验 | 保留离线优势并提高可信度 |
| P3 | 统一多平台 CLI | 价值较高，但不应先大重写 |

## 15. 风险与非目标

### 15.1 主要风险

- 目录迁移可能破坏已有用户脚本和本地状态。
- Bash 与 PowerShell 同步迁移时可能再次出现行为差异。
- 固定版本后，需要建立明确的升级和安全补丁流程。
- 预构建镜像和 vendored 资源会增加发布维护工作。
- 安全默认值变化可能影响依赖无确认自动化的现有用户。

对应策略：

- 为真实存在的 `.cc-config` 和 `.deploy` 状态提供一次性迁移器。
- 在 P1 前先建立最小跨平台 smoke test。
- 通过 `versions.env` 和自动化更新流程维护固定版本。
- 将危险模式保留为显式 profile，而不是直接删除。
- 每一阶段保持可运行、可回退，不进行大爆炸式提交。

### 15.2 非目标

- 第一阶段不把所有 Bash 和 PowerShell 重写成新语言。
- 不删除 `_bundle` 和离线资源。
- 不把 LiteLLM 强制放入默认镜像。
- 不为交互式容器机械添加无意义的 `HEALTHCHECK`。
- 不继续通过构建脚本修改源码目录。
- 不为没有持久化需求的旧结构增加永久兼容层。

## 16. 最终验收目标

重构完成后，一个从未使用过该项目的新用户应能做到：

1. 阅读 README 第一屏就知道项目用途和安全边界。
2. 运行一个平台对应的启动文件。
3. 通过一次简短配置进入 Claude Code。
4. 第二次启动不再重复回答相同问题。
5. 不启用代理、LiteLLM 或 AI 简讯时，不承担它们的启动时间和失败风险。
6. 遇到问题时运行 `aisc doctor` 获得原因和修复命令。
7. 维护者能够在不修改源目录的情况下完成构建、测试和发布。

实施顺序固定为：

```text
P0 可用性修复
  -> P1 结构与职责重组
  -> P2 测试、版本和可重复构建
  -> P3 新手体验优化
```

每个阶段必须独立通过验收，避免将全部变更合并为一次不可验证的大规模重写。
