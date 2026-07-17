# P3：跨平台统一 CLI 与体验优化

> 状态：**提案（待审核 · Oracle 审查修订版）**
>
> 核心目标：用跨平台 Python stdlib CLI（argparse + dataclasses + json）替换当前 Bash/PowerShell 双轨 CLI 业务引擎，支撑安全默认、可审计配置、容器契约验证，最终交付独立可执行 CLI + release bundle。
>
> 编写日期：2026-07-17（修订：同）
>
> **重要提示：本文档为计划方案，P3 功能代码尚未获用户批准。提交后等待审核，审核通过后方可进入实施。**

---

## 1. 背景与现状链路

### 1.1 当前架构

经过 P0–P2 重构，AISC 已具备：

| 层级 | 现状 | 关键文件 |
|------|------|----------|
| 宿主入口 | 三平台薄启动器（`start.sh`/`start.bat`/`start.command`），全部委托到 `scripts/run.{sh,ps1}` | `start.sh`（39 行）、`start.bat`（23 行） |
| 宿主业务引擎 | Bash 流水线（`01_check_env`→`02_config_wizard`→`03_build_image`→`04_launcher`）+ PowerShell 镜像实现 | `scripts/*.sh`、`scripts/*.ps1` |
| CLI 工具 | 仅有 `cli/commands/doctor.sh`，`start.sh` 不支持子命令 | `cli/commands/doctor.sh`（188 行） |
| 配置 | `config/versions.env`、`container/providers.json`（schema v1，7 个 provider） | `config/versions.env`、`container/providers.json` |
| 运行时状态 | `.aisc/state.env`（回退 `.deploy/state.env`）；密钥 `.aisc/secrets/`（回退 `.cc-config/api-keys`） | `_state.{sh,ps1}` |
| 容器内部 | `entrypoint.sh` 调度 `claude-switch`/`claude-wrapper`/`mihomo-build-config.js` 等 | `container/entrypoint.sh` |
| CI | GitHub Actions：语法检查、JSON 校验、gitleaks（`continue-on-error: true`，非阻断）、Docker smoke | `.github/workflows/{checks,docker-smoke}.yml` |
| 分发 | 纯源码，用户 clone 后运行 shell 脚本，无预构建制品 | — |

### 1.2 已明确的问题

1. **双轨维护成本**：Bash 和 PowerShell 各维护一套相同业务逻辑（`01-04_*` 共 12 个文件），任何业务变更需同步两份，漂移风险高。
2. **CLI 入口缺失**：`start.sh` 只支持 `--workspace PATH`，没有子命令路由（`doctor`/`config`/`build`/`run`/`version` 等），诊断需直接执行 `bash cli/commands/doctor.sh`。
3. **跨平台行为不一致**：PowerShell 5.1 兼容、路径分隔符、状态文件解析、颜色输出等在 Bash 和 PS 间存在已有或潜在漂移。
4. **安全默认值偏离**：当前 `claude-wrapper` 默认注入 `--dangerously-skip-permissions`，容器内 AISC 用户 NOPASSWD sudo，不符合最小权限原则。CLI 侧尚未提供 `safe`/`unsafe` profile 选择机制。
5. **配置模型不完整**：用户级持久配置（provider 选择、API key、profile 偏好、workspace）散落在交互式 TUI `02_config_wizard` 和容器内 `claude-switch` 中，缺少统一的非交互 CLI 接口。
6. **无结构化输出**：所有输出为纯文本，不支持 `--format json`，无法被 CI 或自动化脚本消费。
7. **密钥安全边界未闭合**：`claude-switch` 将 `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY` 写入 `.claude/settings.json`（env 块），与 `.aisc/secrets/` + `.cc-config/` 形成三处副本（devlog 已记录为已知技术债）。
8. **无容器契约验证**：没有机制检查宿主 Docker 能力、内核特性是否满足容器需求；`--cap-add=NET_ADMIN` 仅凭用户 TUI 选择决定，无 preflight 验证。

### 1.3 已批准的核心决策

| 决策 | 内容 | 来源 |
|------|------|------|
| D1 | 长期 CLI 方案为跨平台 Python stdlib（argparse + dataclasses + json），独立可执行文件分发 | 用户批准 |
| D2 | 不使用 Typer / Click / Pydantic；初版尽量 stdlib-only | 用户批准 |
| D3 | `start.sh`/`start.bat`/`start.command` 长期保留为薄 passthrough/locator | 用户批准 |
| D4 | 旧 `scripts/*.sh`/`scripts/*.ps1` 业务引擎在 P3.2 默认入口切换后保留到 S11，之后删除 | 用户批准 |
| D5 | GUI 是远景规划：当前不实施、不选型、不定时间表。CLI 协议仅为 CI/脚本/第三方调用而稳定化 | 用户批准 |
| D6 | P3 功能代码尚未获用户批准，本文档提交后等待审核 | 用户批准 |

### 1.4 决策记录：为何不选"容器内 Python 作为宿主统一 CLI"

在 v2 计划（P3）中曾建议"评估小型 Python CLI 统一多平台逻辑"。一个看似省力的方案是：**以容器内 Python 作为宿主 CLI 运行时**。

**否决原因**：

| 场景 | 为何不能依赖容器 |
|------|------------------|
| `aisc doctor` | 诊断 Docker daemon 是否运行——若 Docker 不可用，无法拉容器来诊断 Docker。循环依赖。 |
| `aisc build` | 构建镜像——`docker build` 是宿主操作，需在容器外发起。 |
| `aisc version` | 显示 CLI 自身版本——若 CLI 本身在容器内，需要先 pull 旧镜像才能得知有新版本。 |
| `aisc config migrate` | 迁移旧状态——这些文件在宿主机，迁移逻辑在容器内意味着需要 bind mount 宿主状态并处理 UID 差异。 |
| image-missing 阶段 | 镜像尚未构建时，任何"先用容器做 CLI"的前提都不成立。 |

**但承认**：独立二进制 + release bundle 分发存在成本（打包体积、PyInstaller 复杂度、三平台 CI）。这些成本通过明确资源模型和定位优先级来消解（见 §4）。

---

## 2. 目标与非目标

### 2.1 目标

| 编号 | 目标 | 验收标准 |
|------|------|----------|
| G1 | 单一跨平台 CLI 入口 `aisc`，schema/错误类别/退出语义一致 | Linux/macOS/Windows 执行相同 `<cmd>` 产生等价语义输出；platform-specific 数据允许不同 |
| G2 | 安全默认：`safe` profile 下不注入 `--dangerously-skip-permissions`，不授予 NET_ADMIN | `aisc run --profile safe` 容器内无危险 flag |
| G3 | CLI 可脚本化：所有交互式路径有对应的 `--non-interactive` 等效路径 | CI 中 `aisc build --non-interactive --profile safe` 可无人工干预完成 |
| G4 | 结构化输出：`--format json` 对所有查询命令输出稳定 JSON envelope | `aisc doctor --format json` 返回机器可解析的诊断结果 |
| G5 | 容器契约验证：`aisc doctor` 进行能力探测（capability detection），提前发现不兼容 | `aisc build` 前自动 preflight，失败给出可执行修复建议 |
| G6 | 配置/状态/密钥彻底分离，无新增密钥写入 `.claude/settings.json` | S7/S8 runtime fixture integration test 验证新写路径仅使用 host secret store；S5 copy-only 阶段允许 legacy fixture 继续保留原凭据 |
| G7 | 独立可执行文件分发：普通用户无需预装 Python | 下载 release bundle archive 即可运行 |
| G8 | 旧业务引擎可控删除 | 满足具体截止条件（见 §14.4）后安全移除 |

### 2.2 非目标

| 编号 | 非目标 | 说明 |
|------|--------|------|
| NG1 | GUI 实施、GUI 框架选型、daemon、本地服务、GUI 打包发布 | 远景规划，不在 P3 范围内，不影响 P3 完成门槛，无时间表 |
| NG2 | 替换容器内所有业务逻辑 | P3 只修改容器内**最小必要安全/契约接口**（`claude-wrapper` 安全默认、`entrypoint.sh` non-interactive 路径、Dockerfile LABEL）。`claude-switch` 在兼容期内只保留 show 能力，不再写 `.cc-config`/`.aisc/secrets`/`.claude/settings.json`。`claude-switch` 在 S10 后进入退役期 |
| NG3 | 完整 TUI/交互式菜单 | 初版 CLI 面向脚本化/自动化优先；交互式特性按需追加 |
| NG4 | 插件/扩展系统、MCP server 管理、skills 管理 CLI | 容器内 `cc-switch-cli` 已覆盖，不重复建设 |
| NG5 | 预构建镜像 registry push/发布自动化 | 本地构建足够；预构建镜像属于独立分发决策 |
| NG6 | 遥测、用量统计、错误上报 | 不做 |

### 2.3 GUI 远景声明

GUI 是长期远景计划。当前仅确保 CLI 协议（JSON envelope、JSONL event stream）可被第三方/脚本/CI 稳定消费，不产生阻碍未来 GUI 集成的硬编码耦合。P3 不产生任何 GUI 相关任务、依赖、DoD、时间表或框架选择。

---

## 3. P3.1 与 P3.2 范围（修订顺序）

**核心原则**：safe 真正生效和 container contract 完成前**不**默认切换到新 CLI。单向依赖，legacy 删除最后。

### 3.1 P3.1：契约 → 只读 core → Docker backend → artifact preview

| 切片 | 名称 | 内容摘要 | 产出 |
|------|------|----------|------|
| S1 | **契约与特征测试** | 定义协议规范、稳定退出码/错误码、JSONL 格式。为 **兼容行为**（workspace 解析、Docker argv/build args、proxy 参数、错误分类等）录制特征测试。**不冻结**完整 stdout/不安全旧行为——safe 默认、secret/output 变更是明确有意改变。实现 CLI contract test harness。 | `tests/features/*.py`、`tests/harness/test_runner.py` |
| S2 | **Python 领域模型与只读 core** | 实现 `src/aisc/domain/` 纯 dataclasses + `src/aisc/application/` 只读查询。实现 `aisc version`（含 CLI/bundle/image/contract/Claude 版本细节）和 `aisc doctor`（只读诊断）。 | `src/aisc/domain/*.py`、`src/aisc/application/*.py`、`aisc version`、`aisc doctor` |
| S3 | **Docker planner/executor（legacy-compatible）** | 实现 Docker adapter + `aisc build`/`aisc run`。**此时不默认切换到新 CLI**。`aisc run` 对已有旧镜像保持兼容（不加 contract 检查），`--dry-run` 输出对照现有 Bash 行为验证。 | `src/aisc/adapters/docker_.py`、`aisc build`、`aisc run` |
| S4 | **Artifact 组装与 smoke（workflow artifact）** | PyInstaller 打包独立可执行 CLI + **完整 release bundle archive**（含 `container/`、`config/`、`container/_bundle`、`container/downloads` 等资源）。CI 生成三平台 archive + SHA256 checksums + bundle manifest 校验 + `aisc version` smoke + `aisc build --dry-run` bundle 定位验证。产物仍为 **workflow artifact**（仅 CI 内部），不对外公开发布、不默认切换入口。 | CI workflow artifact（CLI+bundle archive）、checksums |

**P3.1 验收门**：CLI 可构建完整独立 archive；`version`/`doctor`/`build`/`run`（legacy-compatible 模式）在 CI 三平台 workflow artifact 中可运行；不默认切换用户入口；不影响旧 `start.sh` 行为。

### 3.2 P3.2：迁移 → profile → provider 权威 → contract → 协议 → 分发门 → 默认切换 → 观察 → 删除

| 切片 | 名称 | 内容摘要 | 产出 |
|------|------|----------|------|
| S5.1 | **配置/密钥发现与 schema** | 定义 config.json 最小 schema（用户级 + workspace 级）；定义 provider secret 每 provider 单文件 opaque UTF-8 credential 模型；定义 provider ID grammar 与 `secret_ref` 解析语义；定义 source inventory 固定为精确路径（`W/.aisc/secrets/api-keys`、`W/.cc-config/api-keys`、`W/.claude/api-keys`、`W/.claude/settings.json`、`R/.aisc/state.env`、`R/.deploy/state.env`）；定义 provider 映射规则（api-keys 仅按 `providers.json` 的 `auth_key_name` 唯一精确映射；settings token 仅在 canonical `base_url` 规范化后唯一精确匹配且 `auth_type` 对应时映射，禁止模型/url_fragment/token 外形猜测）；定义冲突规则（不同 secret source 无自动 precedence，相同值去重，不同值 conflict；目标不同绝不覆盖；目标已存在且相同→already_current）；定义 legacy state `.aisc` > `.deploy` 逐 key 策略，仅记录 shadowed。 | `src/aisc/domain/config.py`、`src/aisc/schemas/config_schema.py`、plan 级 source inventory |
| S5.2 | **config validate/effective** | 实现 `aisc config validate`（schema 校验，text+json 输出）与 `aisc config effective`（脱敏合并有效配置，text+json 输出）。`--events` 与 validate/effective 组合→usage error（exit 2）。 | `src/aisc/application/config_service.py`、`aisc config validate/effective` |
| S5.3 | **secure store adapter** | 实现 secret store adapter：平台原生路径解析（Linux XDG config/state/data、macOS Application Support/aisc、Windows APPDATA config + LOCALAPPDATA state/secrets）；POSIX 0700/0600 + owner；Windows DACL current user SID + SYSTEM full control、禁继承/Everyone/Users/Authenticated Users、写后验证、失败 exit 9（DACL 是实现 blocker）；journal/HMAC/原子写基础设施：不含明文/last4/普通 hash，使用 `migration-integrity.key`；per-target atomic、可重入、全局 lock；dry-run 零目录/lock/key/journal/chmod。**不含实密钥 contact**。 | `src/aisc/adapters/secret_store.py` |
| S5.4 | **config migrate + journal** | 实现 `aisc config migrate`（text+json+events）：Phase 1 copy-only——从 source inventory 精确路径读取，**不修改/删除/重命名/chmod/chown legacy 源或 settings，源文件和 settings bytes 不变**；按 S5.1 映射规则进行 provider 映射与 secret 复制→新 store；冲突按 S5.1 规则处理；未映射 secret → exit 14 `AISC_EXIT_MIGRATION_CONFLICT`；legacy state 仅报告现状（`.aisc` > `.deploy` 逐 key），不过度承诺 state migration；若后续 S6-S8 无消费者 S5 仅报告 legacy state。回滚依靠源未变 + 目标逐文件原子 + journal；**不创建 `.bak-YYYYMMDD` 或明文备份**。退出码：0 成功/全部 already_current；14 冲突/未映射；6 schema 错误；7 必要文件缺失；9 权限不足；1 通用；130 中断（**不含部分成功退出码**）。`--dry-run` 零目录/lock/key/journal/chmod。 | `src/aisc/application/config_service.py`、`aisc config migrate` |
| S5.5 | **cleanup 拒绝 stub** | 实现 `aisc config cleanup` **固定拒绝 stub**：exit 11、`AISC_ERR_CLEANUP_NOT_AUTHORIZED`、零读 secret、零写。cleanup mutation engine、真实 cleanup、legacy 删除**均不在 S5 实现**，需后续切片单独批准。**不存在 `--force-cleanup` flag**。 | `src/aisc/cli/commands/config.py`（cleanup stub） |
| S6 | **最小 safe/unsafe resolver + network 正交** | 仅内置 `safe`/`unsafe` profile（首版不支持 user-defined profile 或 `custom_docker_args`）。safe 不含 `network` 字段、不含 `sudo_policy` 字段。network 由 `--network direct\|proxy` 单独控制。sudo 由容器内固定最小 sudoers allowlist（具体规则在 S8 落地）。`--non-interactive` 正交。 | `src/aisc/domain/profiles.py`、`aisc profile list/show` |
| S7 | **Provider 唯一权威路径 + 端到端 non-interactive** | host `aisc provider use` 是**唯一持久写路径**。`aisc run --provider ID` 仅单次 override（不持久）。容器 `cs` 在兼容期只能 show 当前配置/委托到统一 contract，不再独立写 `.cc-config`/`.aisc/secrets`/`.claude/settings.json`。端到端 non-interactive 链路完成。providers 唯一事实源：`container/providers.json`。 | `src/aisc/application/provider_service.py`、`aisc provider list/show/use`、端到端测试 |
| S8 | **容器契约/安全默认/移除 wrapper 默认 unsafe** | ① contract 按请求 capability label 校验（`safe`→`supports.safe`、`proxy`→`supports.proxy`、`non-interactive`→`supports.non-interactive`，任一缺失→`AISC_EXIT_CONTRACT_MISMATCH`）。无 label 仅 `--allow-legacy-image`+`--accept-unsafe-risk` 放行；safe 绝不降级。② `claude-wrapper` 改为仅在 `AISC_PROFILE=unsafe` 时注入 `--dangerously-skip-permissions`。③ `proxy` 显式请求但 TUN/preflight 失败必须非零 exit。④ 未请求 proxy 时 TUN 不可用只 warning。⑤ non-interactive 端到端无 stdin read。⑥ 密钥仅通过环境变量注入。⑦ 容器内固定最小 sudoers allowlist。⑧ API key 不再写入 `.claude/settings.json`。 | `container/Dockerfile` LABEL、`container/claude-wrapper` 重构、contract 验证 |
| S9 | **CLI 机器协议稳定化** | 对 **本期已实现命令**（`version/doctor/config/profile/provider/build/run`）进行 `--format json`/`--events` 协议验证测试。`docs/rfc/aisc-cli-v1.md` 归档。`logs`/`clean` 仍为后续候选，非 P3 DoD。动机仅为 CI/脚本/第三方调用，非 GUI。 | `docs/rfc/aisc-cli-v1.md`、自动化协议验证测试 |
| **分发授权门** | **S10 强制前置条件（非独立切片）** | **CLI+bundle 完整 archive 必须通过用户单独批准的正式分发渠道发布且普通用户可访问。**具体：① 用户批准并完成至少一个可访问渠道（GitHub Release / Gitee / OSS，由用户择一）。② 匹配版本的 CLI+完整 bundle archive 三平台 smoke 通过。③ `start.*` 定位的二进制路径与已发布 URL 一致。**没有批准并完成可访问渠道，S10 不得执行**。clone 下不得默认切换到不存在的 `aisc`。**不假设已经发布**。 | release archive 公开 URL、可下载验证 |
| S10 | **默认入口切换** | 进入条件同时满足 S8 contract 完成 + S9 协议稳定化完成 + **分发授权门通过**（release archive 可访问）。`start.*` 改为纯 locator：检测同目录/系统 PATH 下 `aisc` 二进制 → 有则转发 → 无则 **不静默 fallback**，报错并提示获取 CLI。旧 path 仅通过显式 `AISC_CLI_ENGINE=legacy` 环境变量可达。新 CLI 失败绝不静默回退旧引擎。 | 更新 `start.*` |
| S11 | **观察期后删除 legacy** | S10 发布后监控 ≥2 周。满足 legacy 删除门槛（见 §14.4）后且获用户另行批准：删除 `scripts/01-04_*`、`_state.*`、`run.*`；`start.*` 移除 `AISC_CLI_ENGINE=legacy` 分支；CI 移除 Bash/PS 双轨检查。**legacy 删除和真实 secret cleanup 均需用户另行批准**。 | 删除的旧文件、精简后的 CI |

**P3.2 验收门**：config migrate 幂等且 journal 完整，Phase 1 copy-only 源文件与 settings bytes 不变；cleanup stub 正确拒绝（exit 11 / `AISC_ERR_CLEANUP_NOT_AUTHORIZED` / 零读写）；safe 下容器无危险权限；provider 由 host 唯一权威管理；container contract 按 capability label 校验生效；S9 协议验证覆盖本期已实现命令；分发授权门通过后 S10 默认入口切换；legacy 按条件删除且经用户批准。

---

## 4. 资源模型与目标目录结构

### 4.1 独立制品资源模型

P3 CLI **不是单文件即可完整 build/run**——`aisc version` 与 `aisc doctor` 可独立运行；`aisc build`/`aisc run`/`aisc provider` 需要兼容的 AISC release bundle（含 `container/Dockerfile`、`container/providers.json`、`config/versions.env`、`container/_bundle`、`container/downloads` 等资源）。

**CLI 定位 bundle 的优先级**：

1. `--aisc-root PATH` 显式指定
2. `AISC_ROOT` 环境变量
3. CLI 可执行文件同目录下的 bundle（`<exe_dir>/aisc-bundle/`）
4. 仓库发现：向上遍历查找含 `container/Dockerfile` + `VERSION` 的 Git 仓库根目录
5. 以上均失败 → 明确错误，提示用户获取 release bundle

**bundle manifest**：`aisc-bundle/manifest.json` 声明 CLI-bundle 兼容版本映射，CLI 启动时校验。

**正式分发格式**：包含 CLI 可执行文件 + bundle 资源的 tar.gz/zip archive。普通用户下载解压即用，无需 Python/pip。

### 4.2 目标目录结构

```text
AISC/
├── pyproject.toml                     # 元数据、包发现、dev/build 依赖（unittest/PyInstaller）
├── src/
│   └── aisc/                          # Python CLI 源码（runtime stdlib-only）
│       ├── __init__.py
│       ├── __main__.py                # entry point: `python -m aisc`
│       ├── cli/                       # CLI 层（argparse 子命令路由）
│       │   ├── __init__.py
│       │   ├── main.py                # 顶层 ArgumentParser，全局参数解析
│       │   ├── commands/
│       │   │   ├── __init__.py
│       │   │   ├── version.py
│       │   │   ├── doctor.py
│       │   │   ├── config.py
│       │   │   ├── profile.py
│       │   │   ├── provider.py
│       │   │   ├── build.py
│       │   │   └── run.py
│       │   └── output.py              # stdout/stderr 格式化 (text/json/JSONL)
│       ├── domain/                    # 领域模型（纯 dataclasses，零副作用）
│       │   ├── __init__.py
│       │   ├── config.py              # Config, WorkspaceConfig, UserConfig
│       │   ├── provider.py            # Provider, ProviderAuth
│       │   ├── profile.py             # Profile, SafeProfile, UnsafeProfile
│       │   ├── version.py             # VersionInfo, ImageVersion
│       │   ├── docker_.py             # DockerImage, ContainerRunSpec, ContainerContract
│       │   └── events.py              # CliEvent, CliEnvelope
│       ├── application/               # 应用服务层（通过 adapter/port 编排副作用，不直接调用 IO API）
│       │   ├── __init__.py
│       │   ├── diagnostic.py          # Doctor 诊断逻辑
│       │   ├── config_service.py      # Config validate/effective/migrate/cleanup
│       │   ├── profile_service.py     # Profile 解析
│       │   ├── provider_service.py    # Provider 查询/切换
│       │   └── build_service.py       # Build 规划（干运行 + 真实执行调度）
│       ├── adapters/                  # 外部依赖封装（IO 边界/port 实现）
│       │   ├── __init__.py
│       │   ├── docker_.py             # docker CLI 封装 (info/ps/build/run)
│       │   ├── filesystem.py          # 跨平台路径、权限、文件操作
│       │   ├── process.py             # 子进程管理
│       │   └── secret_store.py        # 密钥读写（平台原生 ACL，不以 chmod/stat 跨平台证明）
│       └── schemas/                   # JSON Schema / 序列化格式定义
│           ├── __init__.py
│           ├── config_schema.py
│           └── envelope.py

├── tests/
│   ├── unit/
│   │   ├── domain/
│   │   └── application/
│   ├── integration/
│   │   ├── docker/
│   │   └── config/
│   ├── features/                      # S1 特征测试（记录兼容行为，非完整 stdout golden）
│   │   ├── fixtures/
│   │   └── test_contract.py
│   ├── contract/                      # CLI 协议验证
│   │   └── test_cli_v1.py
│   └── harness/
│       └── test_runner.py

├── packaging/
│   ├── pyinstaller/
│   │   ├── aisc.spec
│   │   └── hooks/
│   └── release/
│       └── checksums.sh

├── docs/
│   ├── rfc/
│   │   └── aisc-cli-v1.md
│   ├── adr/
│   │   └── 001-python-stdlib-cli.md
│   └── plans/
│       └── PLAN-p3-unified-cli.md

├── start.sh                           # 薄 locator
├── start.bat
├── start.command
├── scripts/                           # 旧业务引擎（P3.2 S11 后删除）
│   └── ...
└── ... (其余目录不变)
```

**pyproject.toml 策略**：最小 `pyproject.toml` 用于元数据、包发现、PyInstaller 等 dev/build 依赖声明。runtime **stdlib-only**，普通用户无需 Python/pip。测试使用 stdlib `unittest`，不引入 pytest。开发/CI 阶段可通过 `pip install -e .` 或 `PYTHONPATH=src python -m aisc` 运行，**后者不是用户路径**。

**配置路径使用平台原生目录**：
- Linux：`$XDG_CONFIG_HOME/aisc/`（默认 `~/.config/aisc/`）
- macOS：`~/Library/Application Support/aisc/`
- Windows：`%APPDATA%/aisc/`

Windows secrets 使用平台 ACL 策略保护，不以 POSIX `chmod`/`stat` 作为跨平台证明。

---

## 5. 命令树与所有权

### 5.1 命令所有权表

| 命令 | 初版/候选 | Host 责任 | Container 责任 | 注记 |
|------|-----------|-----------|-----------------|------|
| `aisc version` | ✅ 初版 | 显示 CLI 版本、bundle 版本 | 镜像显示 image version、contract version | 可接受 `--format json` 区分 CLI/bundle/image/contract/Claude 版本 |
| `aisc doctor` | ✅ 初版 | host Docker/网络/权限诊断 | 容器 contract 兼容性检查（`aisc doctor --container`） | host/container 分拆为子命令 |
| `aisc config validate` | ✅ 初版 | 校验用户/workspace config schema | — | — |
| `aisc config effective` | ✅ 初版 | 显示脱敏合并有效配置 | — | — |
| `aisc config migrate` | ✅ 初版 | copy-only：从 source inventory 精确路径读取→按映射规则写入新 store→journal | — | text+json+events；unmapped→exit 14；`.bak-YYYYMMDD` 不存在 |
| `aisc config cleanup` | ✅ 拒绝 stub (S5.5) | 固定拒绝：exit 11、`AISC_ERR_CLEANUP_NOT_AUTHORIZED`、零读写 | — | 真实 cleanup、legacy 删除仍单独批准，不在 S5 实现 |
| `aisc profile list` | ✅ 初版 | 列出内置 profile | — | 首版仅内置 safe/unsafe |
| `aisc profile show` | ✅ 初版 | 显示 profile 详情 | — | — |
| `aisc provider list` | ✅ 初版 | 从 `container/providers.json` 读取 | — | — |
| `aisc provider show` | ✅ 初版 | 显示 provider 详情（脱敏） | — | — |
| `aisc provider use` | ✅ 初版 | **唯一持久写路径**，保存 key → host secret store | **兼容期 `cs` 仅可 show**，不再写任何文件 | `aisc run --provider ID` 单次 override |
| `aisc build` | ✅ 初版 | Docker build 执行 | — | — |
| `aisc run` | ✅ 初版 | Docker run 参数组装+执行 | 入口点调度 | — |
| `aisc logs` | ❌ 候选 | 查看最近启动日志 | — | 初版候选，非 P3 DoD |
| `aisc clean` | ❌ 候选 | 清理缓存 | — | 初版候选，非 P3 DoD |
| `completion` | 候选 | shell completion 脚本生成 | — | — |
| `diagnostic-bundle` | 候选 | 收集诊断信息打包 | — | — |

### 5.2 `cs`（容器内 `claude-switch`）兼容/退役路径

| 阶段 | 时间线 | `cs` 行为 |
|------|--------|-----------|
| 当前 | 2026-07 | 读/写 `.cc-config`、`.aisc/secrets`、`.claude/settings.json` |
| S7 完成 | P3.2 中期 | `cs` **只读**：可 `cs show` 显示当前配置委托自 host。**停止双写**——不再写 `.cc-config`/`.aisc/secrets`/`.claude/settings.json` |
| S10 完成 | 默认入口切换 | `cs` 标记为 deprecated，stderr 输出迁移提示 |
| 退役截止 | ≥ v3.1.0 且 ≥ S11 | `cs` 及相关双写逻辑从仓库删除 |

### 5.3 命令树总览

```text
aisc
├── version                              # S2
├── doctor [--container]                 # S2 (host) + S8 (container)
├── config
│   ├── validate                         # S5.2
│   ├── effective                        # S5.2
│   ├── migrate                          # S5.4
│   └── cleanup                          # S5.5 (拒绝 stub)
├── profile
│   ├── list                             # S6
│   └── show [NAME]                      # S6
├── provider
│   ├── list                             # S7
│   ├── show [NAME]                      # S7
│   └── use NAME                         # S7 (唯一持久写路径)
├── build                                # S3
└── run                                  # S3
```

---

## 6. 全局参数与语义

所有命令共享以下全局参数（在 `aisc` 顶层定义）。

| 参数 | 类型 | 默认值 | 语义 |
|------|------|--------|------|
| `--workspace PATH` | `Path` | `$(pwd)` | 用户工作目录（bind mount 源），不与 AISC 仓库路径耦合 |
| `--profile NAME` | `str` | `safe` | 执行 profile：`safe`（默认）、`unsafe`（显式确认后）。首版仅这两个内置值 |
| `--network MODE` | `str` | `direct` | 网络模式：`direct`（直连）、`proxy`（容器内 TUN 代理）。**正交于 profile** |
| `--provider ID` | `str` | （上次持久化的值） | 单次 run 的 provider override。不持久化。持久化用 `aisc provider use` |
| `--non-interactive` | `flag` | `false` | 禁止 stdin read/prompt。缺少必要配置时快速失败（非零 exit + 明确修复命令到 stderr）。**不等于 unsafe** |
| `--format FORMAT` | `str` | `text` | 输出格式：`text`（人类友好）、`json`（稳定 JSON envelope）。JSON 输出走 stdout，诊断/日志走 stderr |
| `--events` | `flag` | `false` | 启用 JSONL event stream（仅 `build`/`run` 等长命令）。与 `--format json` 冲突 → **usage error** |
| `--no-color` | `flag` | `false` | 禁用终端颜色输出（text 模式） |
| `--log-level LEVEL` | `str` | `warn` | 日志级别：`debug`/`info`/`warn`/`error`。日志输出走 stderr |
| `--config PATH` | `Path` | 平台原生 auto-detect | 用户配置文件路径（覆盖自动检测） |
| `--aisc-root PATH` | `Path` | auto-detect | AISC release bundle/repo 根路径（CLI 定位资源的最高优先级） |
| `--accept-unsafe-risk` | `flag` | `false` | 显式接受 unsafe profile 的风险（非交互模式下必需）。`--yes` **不能批准 unsafe** |
| `--dry-run` | `flag` | `false` | 显示将要执行的操作，不实际执行（仅 `build`/`run`/`config migrate`） |
| `--allow-legacy-image` | `flag` | `false` | 允许使用无 contract label 的旧镜像（兼容期过度 flag，有截止版本） |

**关键行为规则**：

1. `--yes` 可跳过非安全相关的确认（如"已有镜像，是否重建？"），但**绝对不能批准 unsafe**。
2. `--non-interactive` 下若 profile 为 `unsafe` 且无 `--accept-unsafe-risk`，exit `AISC_EXIT_NEEDS_CONFIRMATION`。
3. `--network proxy` 与 `--profile safe|unsafe` 正交组合。

---

## 7. 稳定 `aisc.cli/v1` 协议

### 7.1 JSON Envelope（`--format json`）

```json
{
  "meta": {
    "protocol": "aisc.cli/v1",
    "command": "doctor",
    "exit_code": 0,
    "timestamp": "2026-07-17T12:00:00Z",
    "version": "3.0.0"
  },
  "data": { "... command-specific payload ..." },
  "errors": []
}
```

**stdout/stderr 边界**：
- `--format json` 时，JSON envelope 写入 stdout；诊断/日志/错误描述写入 stderr。
- `--format text` 时，人类可读输出写入 stdout，错误写入 stderr。
- `--events` 时，JSONL event 行写入 stdout。`--events` 与 `--format json` 同时指定 = **usage error**（非零 exit）。

**密钥绝不输出到 stdout/stderr**。脱敏策略：API key 替换为 `****<last4>`；event stream 中不含密钥。

### 7.2 JSONL Event Stream（`--events`）

每行一个 JSON 事件。**每个 event 必须包含**：

```jsonl
{"protocol":"aisc.cli/v1","command":"build","run_id":"uuid","seq":1,"type":"build.step.start","ts":"2026-07-17T12:00:01Z","data":{"step":"pull_base_image"}}
{"protocol":"aisc.cli/v1","command":"build","run_id":"uuid","seq":2,"type":"build.step.complete","ts":"2026-07-17T12:00:10Z","data":{"step":"pull_base_image","status":"ok"}}
{"protocol":"aisc.cli/v1","command":"build","run_id":"uuid","seq":999,"type":"build.complete","ts":"2026-07-17T12:05:00Z","data":{"image_tag":"aisc:3.0.0","exit_code":0}}
```

| 字段 | 必需 | 说明 |
|------|------|------|
| `protocol` | ✅ | `"aisc.cli/v1"` |
| `command` | ✅ | 执行的命令名 |
| `run_id` | ✅ | UUID，同一次命令调用内一致 |
| `seq` | ✅ | 单调递增序号 |
| `type` | ✅ | 事件类型（`<command>.<phase>.<subtype>`） |
| `ts` | ✅ | ISO 8601 UTC |
| `data` | ✅ | 事件特定 payload |

**强制终止事件**：每个 JSONL stream 必须以 `type: "<command>.complete"` 或 `type: "<command>.failed"` 或 `type: "<command>.cancelled"` 结尾。final event 的 `exit_code` 与进程退出码一致。

Docker 原始输出（build log/run log）进入 stderr 或编码为 `data.raw` event。不裸输出到 stdout JSONL 行外。

### 7.3 退出码与 JSON 错误码

进程退出码命名：`AISC_EXIT_*`。JSON `errors[].code` 命名：`AISC_ERR_*`。**不采用 sysexits.h**。

| 退出码 | 常量名 | 对应 JSON code | 含义 |
|--------|--------|-----------------|------|
| `0` | `AISC_EXIT_OK` | — | 成功 |
| `1` | `AISC_EXIT_GENERAL` | `AISC_ERR_GENERAL` | 通用错误 |
| `2` | `AISC_EXIT_USAGE` | `AISC_ERR_USAGE` | 命令行参数错误 |
| `3` | `AISC_EXIT_DOCKER_UNAVAILABLE` | `AISC_ERR_DOCKER_UNAVAILABLE` | Docker CLI 或 daemon 不可用 |
| `4` | `AISC_EXIT_BUILD_FAILED` | `AISC_ERR_BUILD_FAILED` | 镜像构建失败 |
| `5` | `AISC_EXIT_IMAGE_NOT_FOUND` | `AISC_ERR_IMAGE_NOT_FOUND` | 指定镜像不存在 |
| `6` | `AISC_EXIT_CONFIG_INVALID` | `AISC_ERR_CONFIG_INVALID` | 配置文件格式/Schema 错误 |
| `7` | `AISC_EXIT_CONFIG_MISSING` | `AISC_ERR_CONFIG_MISSING` | 缺少必要配置（含修复命令到 stderr） |
| `8` | `AISC_EXIT_NETWORK_REQUIRED` | `AISC_ERR_NETWORK_REQUIRED` | 网络不可达但操作需要网络 |
| `9` | `AISC_EXIT_PERMISSION_DENIED` | `AISC_ERR_PERMISSION_DENIED` | 文件/目录权限不足 |
| `10` | `AISC_EXIT_CONTAINER_FAILED` | `AISC_ERR_CONTAINER_FAILED` | 容器启动后异常退出 |
| `11` | `AISC_EXIT_NEEDS_CONFIRMATION` | `AISC_ERR_NEEDS_CONFIRMATION` | 需用户确认（unsafe profile 未确认 / 其他需要确认的操作） |
| `12` | `AISC_EXIT_CONTRACT_MISMATCH` | `AISC_ERR_CONTRACT_MISMATCH` | 容器 contract version 不兼容 |
| `13` | `AISC_EXIT_PROXY_FAILED` | `AISC_ERR_PROXY_FAILED` | `--network proxy` 显式请求但 TUN/preflight 失败 |
| `14` | `AISC_EXIT_MIGRATION_CONFLICT` | `AISC_ERR_MIGRATION_CONFLICT` | 迁移冲突（secret 映射冲突/未映射/目标冲突） |

**合并说明**：原 `EX_PROFILE_REQUIRES_CONFIRM(11)` 和 `EX_NEEDS_CONFIRMATION(12)` 合并为一个 `AISC_EXIT_NEEDS_CONFIRMATION(11)`；JSON 层可选 `AISC_ERR_PROFILE_REQUIRES_CONFIRM` 区分原因。

**退出码 130**：`AISC_EXIT_INTERRUPTED`（`AISC_ERR_INTERRUPTED`）表示用户中断（SIGINT/Ctrl+C）。shell 约定退出码 128+信号编号（SIGINT=2→130），CLI 在收到 SIGINT 后以 130 退出。

---

## 8. Config / State / Secrets 分离

### 8.1 存储模型与 platform paths

**用户级**（跨 project 持久，平台原生路径）：

| 平台 | config | state | secrets |
|------|--------|-------|---------|
| Linux | `$XDG_CONFIG_HOME/aisc/`（默认 `~/.config/aisc/`） | `$XDG_STATE_HOME/aisc/`（默认 `~/.local/state/aisc/`） | `$XDG_DATA_HOME/aisc/secrets/`（默认 `~/.local/share/aisc/secrets/`） |
| macOS | `~/Library/Application Support/aisc/` | `~/Library/Application Support/aisc/` | `~/Library/Application Support/aisc/secrets/` |
| Windows | `%APPDATA%/aisc/` | `%LOCALAPPDATA%/aisc/` | `%LOCALAPPDATA%/aisc/secrets/` |

**项目级**（workspace-local）：`.aisc/config.json`（非秘密配置）、`.aisc/state.json`（运行时状态）。**workspace `.aisc/` 不存储 secret**。

普通用户没有 `--secrets-dir` 覆盖参数。平台路径解析由上表决定，不依赖环境变量注入（除标准 XDG/APPDATA/LOCALAPPDATA）。

POSIX：目录 0700、密钥文件 0600、owner 校验。Windows：current user SID + SYSTEM full control、禁继承/Everyone/Users/Authenticated Users、写后验证 DACL、失败 exit 9（DACL 是实现 blocker）。macOS：POSIX 0700/0600 + extended ACL 校验，无法证明 fail closed。

### 8.2 两个根：`--workspace` 与 `--aisc-root`

| 参数 | 用途 | 定位内容 |
|------|------|----------|
| `--workspace W` | workspace legacy key/settings 精确路径 | `W/.aisc/secrets/api-keys`、`W/.cc-config/api-keys`、`W/.claude/api-keys`（历史候选，非 active）、`W/.claude/settings.json` |
| `--aisc-root R` | launcher state 精确路径 | `R/.aisc/state.env`、`R/.deploy/state.env` |

**不得递归搜索**层级子目录。仅使用上述精确路径。若 `R` 不可定位（例如 CLI 以独立可执行文件运行且无 bundle/repo），key/settings 迁移**可继续**（仅依赖 W），state 迁移标记为 `skipped:not_located`。

### 8.3 source inventory（固定）

| 类型 | 精确路径 | 说明 |
|------|----------|------|
| secret | `W/.aisc/secrets/api-keys` | legacy `KEY=VALUE`；按 `providers.json` 的 `auth_key_name` 唯一精确映射 |
| secret | `W/.cc-config/api-keys` | 同上 |
| secret | `W/.claude/api-keys` | 同上（历史候选，非 active 源） |
| credentials | `W/.claude/settings.json` | `env.ANTHROPIC_AUTH_TOKEN` / `env.ANTHROPIC_API_KEY` |
| state | `R/.aisc/state.env` | key=value；`.aisc` > `.deploy` 逐 key，仅记录 shadowed |
| state | `R/.deploy/state.env` | key=value |

仅以上精确路径。不扫描其他位置。

### 8.4 config.json 最小 schema

用户级 `config.json`（platform path）：
```json
{
  "schema_version": 1,
  "provider": {
    "id": "deepseek",
    "auth": {
      "secret_ref": "provider:deepseek"
    }
  },
  "defaults": {
    "profile": "safe",
    "network": "direct"
  }
}
```

workspace `.aisc/config.json`：
```json
{
  "schema_version": 1,
  "provider": {
    "id": "deepseek"
  },
  "defaults": {
    "profile": "safe",
    "network": "direct"
  }
}
```

**provider ID grammar**：`^[a-z0-9][a-z0-9._-]{0,63}$`，并拒绝 `/`、`\\`、`..`、控制字符及尾随点/空格。`secret_ref` 必须严格为 `provider:<provider_id>`——在用户 secrets 目录下查找 `<platform-secrets-dir>/providers/<id>` 文件。文件内容为 opaque UTF-8 credential：无 BOM、单行、允许一个最终换行，移除该最终换行后不得含 NUL/CR/LF；不得调用 `strip()` 改变凭据字节。

### 8.5 provider 映射规则

**api-keys 源**（`api-keys` 文件）：
- 仅按 `container/providers.json` 中各 provider 的 `auth_key_name` 字段进行**唯一精确映射**。
- 若一个 `auth_key_name` 出现在多个 provider 定义中→无法唯一映射→标记为 unmapped。
- 禁止按模型名、URL fragment、token 外形/长度猜测映射。

**settings.json 源**（`.claude/settings.json` 的 `env.ANTHROPIC_AUTH_TOKEN`/`env.ANTHROPIC_API_KEY`）：
- 仅在 canonical `base_url` 规范化后**唯一精确匹配**某个 provider 且该 provider 的 `auth_type` 为对应类型时映射。
- 若 base_url 匹配多个 provider 或无匹配→unmapped。
- 禁止按 model 名、URL fragment、token 外形猜测。

**未映射 secret**→标记 unmapped，migrate 命令 exit 14 `AISC_EXIT_MIGRATION_CONFLICT`。

### 8.6 冲突规则

| 场景 | 行为 |
|------|------|
| 同一 secret 值出现在多个 source | 去重（仅保留一份） |
| 不同 secret source 产生**不同值**映射到**同一目标 provider** | conflict——不迁移、不覆盖，标记 conflict |
| 不同 secret source 映射到**不同目标 provider** | 永不覆盖，各自写入各自目标 |
| 目标文件已存在且内容**相同** | `already_current`（幂等跳过） |
| 目标文件已存在且内容**不同** | 保留现有，标记 conflict（不覆盖用户新数据） |

不同 secret source **无自动 precedence**。不对不同 source 的 secret 进行自动合并/优选。

### 8.7 legacy state 处理

legacy state（`R/.aisc/state.env` + `R/.deploy/state.env`）：
- 按 `.aisc` > `.deploy` 逐 key 读取（同名 key 以 `.aisc` 为准）。
- S5 **仅报告** legacy state 现状（列出 key、标记 shadowed），不过度承诺 state migration。
- 若后续 S6-S8 无 legacy state 消费者，S5 仅 report，不做任何 state 写入。

### 8.8 journal / HMAC / 原子写

- journal 不含明文 secret、不含 last4、不含普通 hash。
- 完整性保护使用 `migration-integrity.key`（HMAC，存储在受保护的 `<platform-secrets-dir>/migration-integrity.key`，权限与 secret 相同）。
- per-target atomic write（先写临时文件→重命名）。可重入，全局 `flock`/`LockFileEx`。
- `--dry-run`：零目录创建、零 lock 获取、零 integrity key 生成、零 journal 写入、零 chmod/chown。仅报告将要执行的操作。

### 8.9 `secret_ref` 解析语义

workspace `.aisc/config.json` 不直接存 API key。需引用密钥时使用 `"secret_ref": "provider:<provider_id>"`。解析规则：在用户 secrets 目录 `<platform-secrets-dir>/providers/<provider_id>` 查找对应文件，读取 opaque UTF-8 credential。缺失时交互提示，非交互模式报 `AISC_EXIT_CONFIG_MISSING`。

### 8.10 Legacy 双写/读取停止版本

| 操作 | 停止版本 | 说明 |
|------|----------|------|
| `cs` 写 `.cc-config`/`.aisc/secrets`/`.claude/settings.json` | **S7 完成** | `cs` 改为只读 show |
| 新 CLI 读 `.cc-config`/`.aisc/state.env` | **S10 完成** | 仅 `config migrate` 保留读能力 |
| source inventory 旧路径文件从磁盘删除 | 未来 cleanup 正式开放且用户单独授权后 | 不在 S5 实现；S11 legacy 代码删除与此相互独立 |

### 8.11 Secret 唯一注入模型

- **Host CLI 是 secret owner**：host 从 `<platform-secrets-dir>/providers/` 读取密钥。
- **容器只接收运行时注入**：Docker argv 仅使用 `-e ANTHROPIC_AUTH_TOKEN` / `-e ANTHROPIC_API_KEY` 这样的变量名继承形式，实际 secret 值只进入启动 Docker 子进程的 environment，不进入 argv、dry-run、JSON、JSONL 或日志。容器**不直接读取** host secret 路径、**不挂载**整个 secret 目录。
- **诚实注明**：Docker env 可被有 Docker 权限者通过 `docker inspect` 查看。短期只读 secret file（`--secret` / tmpfs mount）作为未来增强考量，首版不实现。

---

## 9. Profile：typed overrides only

### 9.1 核心定义

**Profile = 命名 typed overrides，仅控制执行安全维度。无继承、无表达式、无链式合并。首版仅内置 `safe` 和 `unsafe`，不支持 user-defined profile。**

Profile 设计约束：
- 首版 **不含** `network` 字段——网络模式由 `--network direct|proxy` 单独控制。
- 首版 **不含** `sudo_policy` 字段——sudo 由容器内固定最小 sudoers allowlist 控制（在 S8 落地）。
- 首版 **不含** `custom_docker_args` 字段。
- `--non-interactive` 与 profile **正交**。

### 9.2 内置 Profile

| Profile | 名称 | 用途 | 包含的 overrides |
|---------|------|------|-------------------|
| `safe` | 安全（默认） | 日常使用 | `dangerously_skip_permissions: false` |
| `unsafe` | 显式危险权限 | 受信任项目 | `dangerously_skip_permissions: true` |

### 9.3 `proxy` 不作为 profile 的原因

| 考量 | 说明 |
|------|------|
| 概念独立性 | 网络代理与执行安全是两个正交维度。若 proxy 作为 profile 则需要 `safe`/`safe-proxy`/`unsafe`/`unsafe-proxy` 组合，概念混杂 |
| UX 清晰度 | `--network proxy` 比"切换一个 profile"更直接地表达用户意图 |
| 安全纯粹性 | `safe` profile 不含危险能力（NET_ADMIN 只在 `--network proxy` 时追加） |

**推荐方案**：network 通过 `--network direct|proxy` + config 持久偏好管理。

### 9.4 Profile 表示

```python
@dataclass(frozen=True)
class Profile:
    name: str                        # "safe" | "unsafe"
    dangerously_skip_permissions: bool
    description: str
```

`--profile unsafe` 行为：
1. 交互模式：显示安全警告 + `y/N` 等待。
2. 非交互模式：必须 `--accept-unsafe-risk`，否则 exit `AISC_EXIT_NEEDS_CONFIRMATION`。
3. **`--yes` 不能批准 unsafe**。

---

## 10. 容器契约（Container Contract）

### 10.1 Contract 兼容性表

**Contract version 兼容**：

| Image contract | Host CLI max contract | 行为 |
|----------------|----------------------|------|
| `contract=1` | `>= 1` | ✅ 正常启动 |
| `contract>1` | `< image_contract` | ❌ 拒绝，提示升级 CLI |
| `contract<1` 或无 label | — | 兼容期内仅同时使用 `--allow-legacy-image --accept-unsafe-risk` 放行（**safe 绝不降级**）。有截止版本（S11 后移除 flag） |

**Capability label 校验（按请求检查）**：

| 请求 capability | 要求 LABEL | 缺失行为 |
|-----------------|------------|----------|
| `--profile safe` | `aisc.supports.safe=1` | ❌ `AISC_EXIT_CONTRACT_MISMATCH` |
| `--network proxy` | `aisc.supports.proxy=1` | ❌ `AISC_EXIT_CONTRACT_MISMATCH` |
| `--non-interactive` | `aisc.supports.non-interactive=1` | ❌ `AISC_EXIT_CONTRACT_MISMATCH` |

**`--allow-legacy-image` 截止**：S11 legacy 删除后此 flag 一并移除。届时无 contract label 或缺失 capability label 的镜像直接拒绝。safe profile 绝不接受无 capability label 的镜像。

**版本区分**：
- **Product version**（`VERSION`）：AISC 产品版本（如 `3.0.0`）
- **Image version**（`LABEL aisc.image.version`）：Docker 镜像版本
- **Contract version**（`LABEL aisc.contract.version`）：CLI-镜像兼容协议版本（独立演进）

Dockerfile 示例：
```dockerfile
LABEL aisc.contract.version="1"
LABEL aisc.supports.safe="1"
LABEL aisc.supports.proxy="1"
LABEL aisc.supports.non-interactive="1"
LABEL aisc.image.version="${AISC_VERSION}"
```

### 10.2 Host 兼容性检查（能力探测）

`aisc doctor` 执行能力探测（不设硬编码的最低版本门槛如 "Docker ≥ 20.10"）：

| 检查项 | 方法 | 失败行为 |
|--------|------|----------|
| Docker CLI 可执行 | `which docker` / `docker --version` | FAIL |
| Docker daemon 响应 | `docker info` | FAIL |
| BuildKit/构建能力 | `docker buildx version` | WARN |
| `/dev/net/tun` 存在（Linux） | `test -c /dev/net/tun` | `--network proxy` 时 FAIL，否则 WARN |
| 用户 docker 权限 | `docker ps` | FAIL |
| bind mount uid 兼容 | 检查 AISC 用户 uid=1000 与宿主 uid 一致 | WARN |

### 10.3 环境变量注入（host → container）

| 环境变量 | 来源 | 语义 |
|----------|------|------|
| `AISC_PROFILE` | `--profile` | `safe` 或 `unsafe` |
| `AISC_NETWORK_MODE` | `--network` | `direct` 或 `proxy` |
| `AISC_WORKSPACE` | `--workspace` | 容器内工作目录 |
| `AISC_PROVIDER_ID` | `aisc provider use` 结果 | 当前 provider id |
| `AISC_NON_INTERACTIVE` | `--non-interactive` | `1` 或 `0` |
| `ANTHROPIC_BASE_URL` | provider 配置 | API 端点 |
| `ANTHROPIC_MODEL` | provider 配置 | 模型名 |
| `ANTHROPIC_AUTH_TOKEN` | host secret store | API key（仅 env 注入） |
| `ANTHROPIC_API_KEY` | host secret store | API key（兼容） |

### 10.4 安全默认规则

**safe profile**：
- `claude-wrapper` **不**注入 `--dangerously-skip-permissions`。
- docker run **不加** `--cap-add=NET_ADMIN --device /dev/net/tun`（除非 `--network proxy`）。
- 容器内固定最小 sudoers allowlist（仅 `ensure_writable` 路径修复 + mihomo 启动，不含全局 NOPASSWD）。
- API key 只通过环境变量注入，**不写入** `.claude/settings.json`。

**unsafe profile**：
- `claude-wrapper` 注入 `--dangerously-skip-permissions`。
- 需显式 `--accept-unsafe-risk`。

**`--network proxy`**（与 profile 正交）：
- 追加 `--cap-add=NET_ADMIN --device /dev/net/tun`。
- 挂载 mihomo 配置 `/etc/mihomo/config.yaml:ro`。
- proxy 显式请求但 TUN/preflight 失败 → **非零 exit**（`AISC_EXIT_PROXY_FAILED`），**不允许 WARN 后直连**。
- **未**请求 proxy 时 TUN 不可用 → WARN（不阻断）。

### 10.5 非交互端到端行为

`aisc run --non-interactive` 下：
- `entrypoint.sh` **不从 stdin read**。
- 作用域默认 `project`（`CLAUDE_SCOPE=project`）。
- provider 密钥缺失 → exit `AISC_EXIT_CONFIG_MISSING` + 修复命令到 stderr。
- 不执行 AI 简讯。
- entrypoint 直接 `exec claude`。

---

## 11. 每个切片详细说明

每个切片须独立 commit、可单独发布、可独立回滚。回滚须覆盖代码、用户数据、artifact、image、参数旧版本行为。

### S1：契约与特征测试（P3.1）

| 维度 | 内容 |
|------|------|
| **进入条件** | 无 |
| **修改范围** | 新建 `tests/features/` + `tests/harness/`。不修改业务代码 |
| **核心工作** | ① 定义协议规范初稿（退出码/错误码、JSON envelope、JSONL）。② 为**兼容行为**（workspace 解析、Docker argv/build args、proxy 参数、错误分类）录制特征测试。③ **不冻结**完整 stdout 或不安全旧行为。④ 实现 `tests/harness/test_runner.py`（跨平台 subprocess，语义断言） |
| **依赖** | 无 |
| **测试证据** | 特征测试可重复执行；harness 自测通过 |
| **验收门** | 协议规范草案完整；特征测试覆盖兼容行为；harness 跨平台可用 |
| **回滚** | 删除 `tests/features/` + `tests/harness/` |
| **文档更新** | `docs/rfc/aisc-cli-v1.md` 初稿；`docs/adr/001-python-stdlib-cli.md` |
| **Commit** | 约 2–4 个 |

### S2：Python 领域模型与只读 core（P3.1）

| 维度 | 内容 |
|------|------|
| **进入条件** | S1 完成 |
| **修改范围** | 新建 `src/aisc/domain/`、`src/aisc/application/`（diagnostic + version）、`src/aisc/cli/`（骨架）、`src/aisc/schemas/`、`pyproject.toml` |
| **核心工作** | ① domain dataclasses。② `aisc version`（CLI/bundle/image/contract/Claude 版本区分）。③ `aisc doctor`（只读诊断，等价于旧 `doctor.sh` + 增强） |
| **依赖** | S1（特征测试验证等价性） |
| **测试证据** | domain 单元测试；`aisc doctor` 与旧行为语义对比；`aisc version --format json` 结构正确 |
| **验收门** | `aisc doctor` 检查项与旧一致；所有测试通过 |
| **回滚** | 删除 `src/aisc/`。旧 `doctor.sh` 不受影响 |
| **文档更新** | README 增加 `aisc version`/`aisc doctor`；Devlog |
| **Commit** | 约 5–8 个 |

### S3：Docker planner/executor — legacy-compatible（P3.1）

| 维度 | 内容 |
|------|------|
| **进入条件** | S2 完成 |
| **修改范围** | 新建 `src/aisc/adapters/docker_.py`、`src/aisc/cli/commands/build.py`、`src/aisc/cli/commands/run.py` |
| **核心工作** | ① Docker adapter（统一 `DockerExecutor` 协议：preflight/inspect_image/run_captured/run_streaming，生产 `RealDockerExecutor`，测试 `FakeDockerExecutor`）。② `aisc build`（`--tag/-t` 默认 super-claude:latest、`--no-cache`、`--pull`、`--dry-run`；从 `config/versions.env` 读取 `NODE_IMAGE`/`USE_CN_MIRROR`；`NODE_IMAGE` 缺失→exit 1；`Dockerfile` 缺失→exit 1；text 模式 streaming 实时日志；json/events 模式 captured 转发 stderr）。③ `aisc run`（`--image/-i`、`--workspace`、`--name`、`--network direct|proxy`、`--dry-run`；text 模式 `-it` streaming；json/events 模式无 `-it` captured；image inspect 结构化分类；proxy 固定 `<root>/.claude/mihomo/config.yaml` 验证+挂载；legacy-compatible——不加 contract 检查）。④ 退出码映射：docker build 非零→4（保留 raw docker_exit_code），docker run 非零→10（保留 raw container_exit_code）；preflight 失败→3/9；image not found→5；workspace 不可读→9；dry-run 零 Docker 调用。⑤ `--events` JSONL（完整实现）：`build.start/plan/step.complete/complete/failed`；`run.start/plan/container.start/container.complete/complete/failed/cancelled`；terminal 由 main.py 统一发，恰好一个，最后一行；`--format json --events` 互斥→exit 2。⑥ 全局参数支持命令前后。 |
| **依赖** | S2 |
| **测试证据** | Docker adapter mock 测试；集成测试（需 Docker daemon）；`--events` JSONL 有效 |
| **验收门** | `aisc build` 等价于旧行为；`aisc run` 可正常启动容器；JSONL 有效 |
| **回滚** | 删除 build/run 代码。旧 `scripts/03-04_*` 继续可用 |
| **文档更新** | Devlog |
| **Commit** | 约 6–10 个 |

### S4：Artifact 组装与 smoke（P3.1 · workflow artifact）

| 维度 | 内容 |
|------|------|
| **进入条件** | S3 完成 |
| **修改范围** | 新建 `packaging/pyinstaller/`；CI workflow artifact 步骤；bundle manifest |
| **核心工作** | ① PyInstaller 打包独立可执行 CLI。② 组装**完整 release bundle archive**（CLI 可执行文件 + `container/` + `config/` + `container/_bundle` + `container/downloads` + manifest.json）。③ CI 生成三平台 archive + SHA256 checksums。④ smoke：`aisc version` + `aisc build --dry-run` 验证 bundle 定位。⑤ **产物仅为 workflow artifact（CI 内部），不对外公开、不默认切换** |
| **依赖** | S3 |
| **测试证据** | 三平台 CI archive 可下载解压执行；`aisc version` + `aisc build --dry-run` 正确 |
| **验收门** | 三平台完整 archive 通过 smoke；checksums 可验证；bundle manifest 校验 CLI-bundle 版本匹配 |
| **回滚** | 删除 CI artifact 步骤和 packaging 目录。旧 `start.*` 不受影响 |
| **文档更新** | Devlog（仅记录 CI artifact 产出） |
| **Commit** | 约 4–6 个 |

### S5.1：配置/密钥发现与 schema（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S2（domain 模型） |
| **修改范围** | `src/aisc/domain/config.py`、`src/aisc/schemas/config_schema.py` |
| **核心工作** | ① 定义 config.json 最小 schema（用户级 + workspace 级）。② 定义 provider secret 每 provider 单文件 opaque UTF-8 credential 模型。③ 定义 provider ID grammar `^[a-z0-9][a-z0-9._-]{0,63}$`、路径危险字符拒绝规则与 `provider:<id>` secret_ref 语义。④ 定义 source inventory 固定为精确路径（`W/.aisc/secrets/api-keys`、`W/.cc-config/api-keys`、`W/.claude/api-keys`、`W/.claude/settings.json`、`R/.aisc/state.env`、`R/.deploy/state.env`）。⑤ 定义 provider 映射规则（api-keys 仅按 `providers.json` 的 `auth_key_name` 唯一精确映射；settings token 仅在 canonical `base_url` 规范化后唯一精确匹配且 `auth_type` 对应时映射，禁止模型/url_fragment/token 外形猜测）。⑥ 定义冲突规则（不同 secret source 无自动 precedence，相同值去重，不同值 conflict；目标不同绝不覆盖；目标已存在且相同→already_current）。⑦ 定义 legacy state `.aisc` > `.deploy` 逐 key 策略，仅记录 shadowed。⑧ 明确两个根：`--workspace W`（workspace legacy key/settings 精确路径）、`--aisc-root R`（launcher state 精确路径），不得递归搜索。 |
| **依赖** | S2 |
| **测试证据** | source inventory 枚举、provider ID grammar regex、映射规则单元测试（fixture 使用 temp PathPolicy，不读取真实 HOME/APPDATA/XDG/工作区真实密钥；sentinel 不出现在 stdout/stderr/json/jsonl/journal/errors） |
| **验收门** | schema 定义完整；映射/冲突规则文档化；source inventory 固定 |
| **回滚** | 删除 domain/schema 新增代码 |
| **文档更新** | Devlog |
| **Commit** | 约 2–3 个 |

### S5.2：config validate/effective（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S5.1（schema 已定义） |
| **修改范围** | `src/aisc/application/config_service.py`、`src/aisc/cli/commands/config.py`（validate/effective） |
| **核心工作** | ① `aisc config validate`（schema 校验，text+json 输出）。② `aisc config effective`（脱敏合并有效配置，text+json 输出）。③ `--events` 与 validate/effective 组合→usage error（exit 2）。 |
| **依赖** | S5.1 |
| **测试证据** | schema 校验正确；有效配置脱敏；validate/effective `--events` → exit 2；fixture 使用 temp PathPolicy |
| **验收门** | `aisc config validate/effective` text+json 输出正确 |
| **回滚** | 删除 validate/effective 命令逻辑 |
| **文档更新** | Devlog |
| **Commit** | 约 2–3 个 |

### S5.3：secure store adapter（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S5.1（路径模型已定义） |
| **修改范围** | `src/aisc/adapters/secret_store.py` |
| **核心工作** | ① 平台原生路径解析（Linux XDG config/state/data、macOS Application Support/aisc、Windows APPDATA config + LOCALAPPDATA state/secrets）。② POSIX 0700/0600 + owner 校验。③ Windows DACL current user SID + SYSTEM full control、禁继承/Everyone/Users/Authenticated Users、写后验证、失败 exit 9；DACL 的真实设置与回读验证是本切片完成条件，不允许以未接线 stub 延后。④ macOS：POSIX 0700/0600 + extended ACL 校验，无法证明 fail closed。⑤ journal/HMAC/原子写基础设施：不含明文/last4/普通 hash；完整性保护使用 `<platform-secrets-dir>/migration-integrity.key`；per-target atomic write（临时文件→重命名）；可重入，全局 `flock`/`LockFileEx`；`--dry-run` 零目录/lock/key/journal/chmod。生产实现不读取现有用户 secret；测试仅使用临时 PathPolicy fixture。 |
| **依赖** | S5.1 |
| **测试证据** | 平台路径解析正确；DACL/ACL 断言（mock 平台）；atomic write + journal HMAC；dry-run 零副作用。fixture 使用 temp PathPolicy |
| **验收门** | adapter 可执行原子读/写；journal 可校验；Linux mode/owner、macOS extended ACL、Windows NTFS DACL 均有平台原生集成证据；无法证明安全权限时 fail closed（exit 9） |
| **回滚** | 删除 secret_store adapter |
| **文档更新** | Devlog |
| **Commit** | 约 3–4 个 |

### S5.4：config migrate + journal（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S5.3（secure store adapter 就绪） |
| **修改范围** | `src/aisc/application/config_service.py`（migrate 逻辑）、`src/aisc/cli/commands/config.py`（migrate 命令） |
| **核心工作** | ① `aisc config migrate`（text+json+events）：Phase 1 copy-only——从 S5.1 source inventory 精确路径读取；**不修改/删除/重命名/chmod/chown legacy 源或 settings，源文件和 settings bytes 不变**。② 按 S5.1 映射规则进行 provider 映射与 secret 复制→新 store。③ 冲突按 S5.1 规则处理（相同去重、不同 conflict、目标不同不覆盖、目标已存在相同→already_current）。④ 未映射 secret → exit 14 `AISC_EXIT_MIGRATION_CONFLICT`。⑤ legacy state 仅报告现状（`.aisc` > `.deploy` 逐 key，标记 shadowed），不过度承诺 state migration；若后续 S6-S8 无 legacy state 消费者，S5 仅报告。⑥ 回滚依靠源未变 + 目标逐文件原子 + journal；**不创建 `.bak-YYYYMMDD` 或明文备份**。⑦ 退出码：0 成功/全部 already_current；14 冲突/未映射；6 schema 错误；7 必要文件缺失；9 权限不足；1 通用；130 中断（**不含部分成功退出码**）。⑧ `--dry-run` 零目录/lock/key/journal/chmod。 |
| **依赖** | S5.2、S5.3 |
| **测试证据** | ① fixture 覆盖 source inventory 全量精确路径（`.aisc/secrets/api-keys`、`.cc-config/api-keys`、含两个密钥字段及 plugins/statusLine/model 的 `.claude/settings.json`、`.aisc/state.env`、`.deploy/state.env`）。② migrate 后新 store 去重/冲突/already_current 正确；全部旧文件与 settings 密钥字段仍存在、bytes 不变；journal 完整且可验证（HMAC）。③ 重复 migrate 幂等。④ unmapped→exit 14；`--dry-run` 零副作用。⑤ fixture 使用 temp PathPolicy，sentinel 不出现在 stdout/stderr/json/jsonl/journal/errors。 |
| **验收门** | Phase 1 copy-only：可从全部旧源导入，密钥去重正确，所有 legacy 源与整个 `settings.json` 均 byte-for-byte 不变，journal 完整、幂等。fixture credential 预期同时保留在 legacy fixture 与新 secret store；“settings 不再含密钥/磁盘仅剩一份”不属于 S5，须等待 S7/S8 停止 runtime 写路径及未来获授权 cleanup。 |
| **回滚** | ① 代码：删除 migrate 逻辑。② 用户数据：旧源在 Phase 1 后完好（copy-only——源文件 bytes 不变）。③ 已迁移：回退 CLI 到旧版本继续读旧路径。④ 目标 store：必要时从 platform state path 回退/删除新 store 文件（journal 提供审计轨迹） |
| **文档更新** | README 配置章节；Devlog |
| **Commit** | 约 4–6 个 |

### S5.5：cleanup 拒绝 stub（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S5.4（migrate 就绪） |
| **修改范围** | `src/aisc/cli/commands/config.py`（cleanup stub） |
| **核心工作** | 实现 `aisc config cleanup` **固定拒绝 stub**：exit 11、`AISC_ERR_CLEANUP_NOT_AUTHORIZED`、零读 secret、零写。cleanup mutation engine、真实 cleanup、legacy 删除**均不在 S5 实现**，需后续切片单独批准。**不存在 `--force-cleanup` flag**。 |
| **依赖** | S5.4 |
| **测试证据** | `aisc config cleanup` 在任何参数组合下均 exit 11；无文件访问/写入 |
| **验收门** | cleanup stub 正确拒绝（exit 11 + `AISC_ERR_CLEANUP_NOT_AUTHORIZED`） |
| **回滚** | 删除 cleanup stub |
| **文档更新** | Devlog |
| **Commit** | 1 个 |

### S6：最小 safe/unsafe resolver + network 正交（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S5.4（config migrate/journal 已就绪） |
| **修改范围** | 新建 `src/aisc/domain/profiles.py`、`src/aisc/application/profile_service.py`、`src/aisc/cli/commands/profile.py` |
| **核心工作** | ① 仅内置 `safe`/`unsafe`（无 user-defined、无 `custom_docker_args`、无 `network` 字段、无 `sudo_policy` 字段）。② `aisc profile list/show`。③ `--profile unsafe` 确认逻辑 |
| **依赖** | S5.4 |
| **测试证据** | `safe`/`unsafe` 正确解析；`--yes` 不批准 unsafe；`--non-interactive` + unsafe 无 confirm 时 exit 11 |
| **验收门** | `aisc profile list` 列出 safe/unsafe；unsafe gate 生效 |
| **回滚** | ① 代码：删除 profile 模块。② 行为：回退到旧镜像时，显式 safe 请求必须拒绝；只有用户同时提供 `--allow-legacy-image --accept-unsafe-risk` 才可按旧 unsafe 行为启动，绝不把 safe 静默 no-op。③ image：不依赖 profile 参数的旧镜像仅通过上述显式风险门继续可用 |
| **文档更新** | README security 章节；Devlog |
| **Commit** | 约 3–5 个 |

### S7：Provider 唯一权威路径 + E2E non-interactive（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S5.4（secrets 存储）、S6（profile） |
| **修改范围** | 新建 `src/aisc/application/provider_service.py`、`src/aisc/cli/commands/provider.py`、`src/aisc/adapters/secret_store.py`；修改 `container/claude-switch`（改为只读 show） |
| **核心工作** | ① `aisc provider list/show/use`。② host `aisc provider use` 是唯一持久写路径；`aisc run --provider` 仅单次 override。③ 容器 `cs` 改为只读 show，停止写 `.cc-config`/`.aisc/secrets`/`.claude/settings.json`。④ providers 唯一事实源：`container/providers.json`。⑤ 端到端 non-interactive CI 测试 |
| **依赖** | S5.4、S6、容器内 `cs` 修改 |
| **测试证据** | provider list 与 `container/providers.json` 一致；`cs` 不再写文件；e2e non-interactive 通过 |
| **验收门** | `aisc provider use` 是唯一持久写路径；`cs` 仅 show；`--non-interactive` 端到端通过 |
| **回滚** | ① 代码：删除 provider CLI。② 容器：`cs` 回滚到只读 show 模式，**不默认恢复双写**（需单独 revert `cs` 修改）。③ 用户数据：host secret store 不受影响（与旧 `.cc-config` 共存）。④ 若需恢复旧写路径：显式 revert 容器内 `cs` 双写 commit |
| **文档更新** | README provider 章节；Devlog |
| **Commit** | 约 6–10 个 |

### S8：容器契约/安全默认/移除 wrapper 默认 unsafe（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S7（provider 已权威化） |
| **修改范围** | `container/Dockerfile`（LABEL）、`container/claude-wrapper`（条件化权限）、`container/entrypoint.sh`（non-interactive 路径、sudo 收紧）；`src/aisc/application/diagnostic.py`（contract 检查） |
| **核心工作** | ① contract compatibility table（§10.1）。② wrapper 仅 unsafe 注入 `--dangerously-skip-permissions`。③ proxy 失败非零 exit。④ non-interactive 端到端无 stdin。⑤ 密钥仅 env 注入。⑥ 容器固定最小 sudoers。⑦ `.claude/settings.json` 零密钥残留 |
| **依赖** | S7、`claude-wrapper`/`entrypoint.sh` 修改 |
| **测试证据** | S7/S8 runtime fixture test：新写路径不再向 `settings.json` 或 legacy api-keys 写入 fixture credential（非 gitleaks 替代）；proxy 失败 exit 13；safe 下无 `--dangerously-skip-permissions`。S5 copy-only fixture 仍保留 legacy credential，不与此验收混淆 |
| **验收门** | safe 下真安全；proxy 失败是非零；contract 不兼容被拒；settings.json 零密钥 |
| **回滚** | ① 代码：回退 `container/*` 修改。② image：用旧 immutable image tag 启动（保留旧安全行为）；旧镜像必须同时使用 `--allow-legacy-image --accept-unsafe-risk`，safe 请求拒绝无 capability label 的旧镜像。③ 回退版本 CLI **也检测 contract**（S8 rollback 不跳过 contract 验证）。④ 参数：`--profile unsafe` 回退到旧 wrapper 行为 |
| **文档更新** | README 安全说明更新；Devlog |
| **Commit** | 约 6–12 个 |

### S9：CLI 机器协议稳定化（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S8（所有本期已实现命令——`version/doctor/config/profile/provider/build/run`——已完成） |
| **修改范围** | `tests/contract/test_cli_v1.py`（协议验证）；`docs/rfc/aisc-cli-v1.md`（正式归档）。**不修改业务代码** |
| **核心工作** | ① 对 **本期已实现命令**（`version/doctor/config/profile/provider/build/run`）执行 `--format json` → 验证 JSON envelope + error code。② `--events` 输出验证（必填字段、终止 event、最终 exit 一致）。③ RFC 归档。`logs`/`clean` 仍为后续候选，**非 P3 DoD**。动机仅为 CI/脚本/第三方调用 |
| **依赖** | S8 |
| **测试证据** | 协议验证测试全通过（仅覆盖本期已实现命令） |
| **验收门** | RFC 与本期已实现命令的行为一致 |
| **回滚** | 删除 RFC 和测试 |
| **文档更新** | `docs/rfc/aisc-cli-v1.md` 正式版 |
| **Commit** | 1–3 个 |

### S10：默认入口切换（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S8 contract 完成 + S9 协议稳定化完成 + **分发授权门通过**（用户批准发布渠道且完整 archive 可被普通用户访问） |
| **修改范围** | `start.sh`/`start.bat`/`start.command`（改为纯 locator） |
| **核心工作** | ① `start.*` 检测并通过已发布路径定位 `aisc` 二进制 → 有则转发 → 无则**不静默 fallback**，报错并提示获取 CLI。② 显式 `AISC_CLI_ENGINE=legacy` 可达旧路径。③ 新 CLI 失败绝不静默回退。④ clone 下**不得默认切换到不存在的 `aisc`**——`start.*` 在无二进制时以明确错误退出 |
| **依赖** | S4 artifact（作为 S10 分发前置）+ S8 contract + S9 协议 + 分发授权门 |
| **测试证据** | `start.sh` 有已发布 CLI 时正确转发；无 CLI 时 fail 不静默（含错误提示和获取 CLI 链接）；`AISC_CLI_ENGINE=legacy` 可手动调用旧引擎 |
| **验收门** | 默认入口走新 CLI（仅在分发授权门通过后）；新 CLI 失败不静默回退；clone 无二进制时报错不默认切换 |
| **回滚** | 将 `start.*` 改回直接调 `scripts/run.*` |
| **文档更新** | README 更新启动说明；Devlog |
| **Commit** | 2–3 个 |

### S11：观察期 + 删除 legacy（P3.2）

| 维度 | 内容 |
|------|------|
| **进入条件** | S10 发布 + 分发授权门通过 |
| **核心工作** | ≥2 周监控 → 满足 legacy 删除门槛 + **用户另行批准 legacy 删除和真实 secret cleanup** → 删除 `scripts/01-04_*`、`_state.*`、`run.*`；移除 `start.*` 的 `AISC_CLI_ENGINE=legacy` 分支；CI 去双轨。**legacy 删除和真实 secret cleanup（`aisc config cleanup` 正式开放）均需用户另行批准** |
| **依赖** | S10 稳定无 blocker + 满足 §14.4 门槛 + 用户批准 |
| **测试证据** | 三平台 artifact smoke + Linux 真实 Docker integration + 场景矩阵 |
| **验收门** | 仓库无旧业务引擎；CI 仅新 CLI；用户已批准 |
| **回滚** | `git revert` 整个 S11 commit |
| **文档更新** | README 目录结构更新；Devlog |
| **Commit** | 1–2 个 |

---

## 12. 跨平台 CI

### 12.1 CI 矩阵

| Runner | 触发 | Job 内容 |
|--------|------|-----------|
| `ubuntu-latest` | push + PR | Python unit tests、feature tests、contract tests、config-path tests、JSON/JSONL/exit-code 协议验证、Linux Docker E2E integration tests（`python -m unittest tests/integration/docker/`）、gitleaks（**阻断**）、文档一致性检查 |
| `windows-latest` | push + PR | Python unit tests、feature tests、contract tests、config-path tests、JSON/JSONL/exit-code 协议验证、locator smoke（`start.bat` 转发验证）、PowerShell parser check（对 `*.ps1` 文件）。**无 Docker daemon——Docker Desktop E2E 属于 release checklist** |
| `macos-14` (arm64) | push + PR | Python unit tests、feature tests、contract tests、config-path tests、JSON/JSONL/exit-code 协议验证、locator smoke（`start.command` 转发验证）。**无 Docker daemon——Docker Desktop E2E 属于 release checklist** |

**说明**：Windows/macOS CI runner 无 Docker daemon 可用。Docker Desktop E2E 测试属于 **release checklist**（在真实 Docker Desktop 环境手动或自动化执行），在有 GitHub-hosted runner 支持前不进入 CI 矩阵。

### 12.2 gitleaks 强化

- **阻断门禁**（非 `continue-on-error`）。
- `docs/` allowlist 缩窄：仅 `docs/devlog.md` + `docs/archive/`。
- 自定义规则：检测 `.claude/settings.json` 中 `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY` 非空明文值。
- `container/_bundle/` 保留 allowlist。
- `vendor/` 保留 allowlist。

**gitleaks 仅作为 repo 门禁。runtime 密钥安全以 S7/S8 behavior fixture integration test 验收**（验证新写路径只写 host secret store，不再向 `settings.json` 或 legacy api-keys 新增 credential）。S5 copy-only 迁移明确保留旧源，不要求磁盘仅剩一份。

### 12.3 Artifact smoke（workflow-only）

- 三平台独立可执行文件构建后 `aisc version` smoke。
- SHA256 checksums 自动生成。
- **正式 GitHub/Gitee/OSS 发布是后续 release 切片，等待渠道决策**。

---

## 13. 分发策略

### 13.1 产物要求

首版承诺产出的平台/架构（以 CI runner native smoke 为准）：

| 平台 | 架构 | Runner | 备注 |
|------|------|--------|------|
| Linux | x86_64 | `ubuntu-latest` native | CI artifact + Docker E2E |
| Windows | x86_64 | `windows-latest` native | CI artifact（Docker-free tests） |
| macOS | arm64 (Apple Silicon) | `macos-14` native | CI artifact（Docker-free tests） |

**artifact 命名规范**：`aisc-<version>-<os>-<arch>.tar.gz`（如 `aisc-v3.0.0-linux-x86_64.tar.gz`、`aisc-v3.0.0-darwin-arm64.tar.gz`、`aisc-v3.0.0-windows-x86_64.zip`）。

**后续候选**（有 runner 后再承诺）：Linux arm64、macOS x86_64、Windows arm64。

### 13.2 打包工具

实施方案阶段评估 PyInstaller 或 Nuitka。PyInstaller 为初版优先选择。runtime stdlib-only。

### 13.3 China-Network Considerations

- 正式 release 渠道（GitHub Release + 国内镜像）在后续 release 切片中决策。
- S4 阶段仅 workflow artifact（CI 内部验证用）。
- `aisc build` 继续支持 `USE_CN_MIRROR=1`。

---

## 14. 安全边界、失败模式、回滚策略、Legacy 删除门槛

### 14.1 安全边界

| 边界 | 措施 | 验收方式 |
|------|------|----------|
| 密钥不输出 | 强制脱敏 | CI contract test 验证 JSON 输出无原始 key |
| 密钥不写入 settings.json | env-only 注入 | runtime fixture integration test（非 gitleaks） |
| secrets 保护 | 平台原生 ACL | Windows ACL / Linux chmod 600 |
| unsafe gate | 需确认，`--yes` 不批准 | 单元测试 |
| gitleaks 阻断 | CI 阻断 + 缩窄 allowlist | CI 配置 review |
| contract mismatch | 能力探测拒绝不兼容 | 集成测试 |
| proxy 失败 | 显式请求时非零 exit | 集成测试（mock TUN 不可用） |

### 14.2 失败模式

| 失败场景 | CLI 行为 | 退出码 |
|----------|----------|--------|
| Docker daemon 不运行 | fail + 修复说明 | `AISC_EXIT_DOCKER_UNAVAILABLE(3)` |
| 镜像不存在 | 提示 `aisc build` | `AISC_EXIT_IMAGE_NOT_FOUND(5)` |
| 构建失败 | 转发 docker 错误到 stderr | `AISC_EXIT_BUILD_FAILED(4)` |
| 缺少 provider 密钥 | non-interactive 下 fail + 修复命令 | `AISC_EXIT_CONFIG_MISSING(7)` |
| 配置格式错误 | 报告具体错误 | `AISC_EXIT_CONFIG_INVALID(6)` |
| unsafe 未确认 | non-interactive 无 flag → fail | `AISC_EXIT_NEEDS_CONFIRMATION(11)` |
| proxy 显式请求但 TUN 不可用 | **非零 exit**（不允许 warn 后直连） | `AISC_EXIT_PROXY_FAILED(13)` |
| proxy 未请求但 TUN 不可用 | WARN（不阻断） | `0` |
| contract 不兼容 | 拒绝运行 + 具体原因 | `AISC_EXIT_CONTRACT_MISMATCH(12)` |

### 14.3 回滚策略（强化）

每切片回滚必须覆盖：

| 回滚维度 | 内容 |
|----------|------|
| 代码 | `git revert` 该切片 commit |
| 用户数据 (config/secrets/state) | Phase 1 后旧源完好（copy-only——源文件 bytes 不变）；回滚依靠源未变 + 目标逐文件原子 + journal（不依赖 `.bak` 备份）；旧路径在 S11 前持续可读 |
| CLI artifact | 回退到上一版 immutable release archive；`start.*` locator 可指向上版二进制或回退到直接调 `scripts/run.*` |
| image | 用上一版 immutable image tag 启动，不依赖当前正在运行的容器 |
| 参数行为 | 回退版本的 `--profile`/`--network`/`--provider` 语义等价于旧行为（profile 回退不得 no-op 到 safe） |

**不合法回滚**：profile 回滚不能只是 no-op（移除 `--profile` 时应等效于旧 unsafe 行为，非 silent safe）。迁移回滚不能只删新文件（必须确保旧路径持续可读且源文件 bytes 不变——依靠 copy-only 保证源完好）。S8 回滚的 CLI 版本也必须检测 contract（不跳过）。

### 14.4 Legacy 删除门槛（具体条件）

旧 `scripts/` 业务引擎删除必须**全部满足**以下条件：

1. 新 CLI 已随一个正式版本发布（如 **v3.0.0**）。
2. 当前版本 ≥ **v3.1.0** 且不早于 **2026-09-01**（二者同时满足）。
3. `aisc config migrate` 已跨至少一个完整发布版本可用。
4. 三平台完整 archive（CLI+bundle）smoke 通过。
5. Linux 真实 Docker integration 测试通过。
6. 场景矩阵（safe/unsafe × direct/proxy × non-interactive/interactive × 至少 3 个 provider）全部通过。
7. 零 blocker 级 issue。
8. **用户另行批准** legacy 删除。

**与 `aisc config cleanup` 的关系**：
- cleanup 在 S5.5 仅实现为**固定拒绝 stub**（exit 11、`AISC_ERR_CLEANUP_NOT_AUTHORIZED`、零读写）。cleanup mutation engine 不在 S5 实现。
- 真实 cleanup 正式开放不早于 **v3.1.0 / 2026-09-01**，且**仍需用户另行批准进行不可逆清理**。
- S11（legacy 删除）和 cleanup 正式开放是两个独立决策点，均需用户单独授权。cleanup 不可逆删除后用户依赖 journal + 源文件不变恢复；legacy 删除后用户需 `git checkout` 旧版本恢复。

**不使用旧代码覆盖率（<1%）作为门槛**——旧脚本功能性验证须通过上述场景矩阵。

---

## 15. 最终总验收标准

### 15.1 P3.1 完成标准

- [ ] 协议规范草案完整；特征测试覆盖兼容行为
- [ ] `aisc version`/`aisc doctor` 可运行
- [ ] `aisc build`/`aisc run` 在 legacy-compatible 模式等价于旧行为
- [ ] 三平台 CI workflow artifact（完整 CLI+bundle archive）生成 + smoke + `aisc build --dry-run` bundle 定位验证
- [ ] 默认入口**未**切换到新 CLI（旧 `start.sh` 行为不变）
- [ ] gitleaks 阻断且无新 secret leak

### 15.2 P3.2 完成标准

- [ ] `aisc config migrate` 幂等、journal 完整，Phase 1 copy-only 源文件与 settings bytes 不变；unmapped→exit 14
- [ ] `aisc config effective` 输出脱敏；`aisc config cleanup` stub 正确拒绝（exit 11 / `AISC_ERR_CLEANUP_NOT_AUTHORIZED` / 零读写）
- [ ] `aisc profile list/show` 列出 `safe`/`unsafe`
- [ ] `aisc provider use` 是**唯一持久写路径**；`aisc provider list/show` 完整
- [ ] `aisc run --non-interactive --profile safe` 端到端通过
- [ ] safe profile 下容器无 `--dangerously-skip-permissions`；safe 拒绝无 capability label 的旧镜像
- [ ] API key 不写入 `.claude/settings.json`（fixture integration test 逐字段验证）
- [ ] container contract 按 capability label 校验生效；proxy 失败非零 exit
- [ ] S9 协议验证全部通过（仅覆盖 `version/doctor/config/profile/provider/build/run`）
- [ ] 分发授权门通过（用户批准渠道 + archive 可被普通用户访问）
- [ ] S10 默认入口切换到新 CLI；clone 无二进制时不默认切换
- [ ] 满足 legacy 删除门槛且用户批准后 legacy `scripts/` 已删除

### 15.3 实施前需用户审核的决策点

| 编号 | 决策点 | 推荐方案 | 说明 |
|------|--------|----------|------|
| R1 | 打包工具选择 | PyInstaller（实施阶段可评估 Nuitka） | CI 成熟度优先 |
| R2 | `proxy` 建模方式 | `--network direct\|proxy` + config 持久偏好 | 正交于 profile |
| R3 | Legacy config 迁移策略 | Phase 1 copy-only（源文件不变）；cleanup 仅拒绝 stub（exit 11）；真实 cleanup 与 legacy 删除仍需单独授权 | copy-only 最安全 + 拒绝 stub 明确边界 |
| R4 | Legacy 删除门槛 | §14.4 全部条件满足 | v3.1.0 + 2026-09-01 双门槛 |
| R5 | 分发渠道 | 用户批准后择一（GitHub Release / Gitee / OSS），**未批准前 S10 不得执行** | S10 强制前置分发授权门 |
| R6 | Python 构建环境 | 3.11+ | 同容器内版本 |
| R7 | `--non-interactive` 默认 profile | `safe` | 安全优先 |
| R8 | S1 特征测试范围 | 仅兼容行为（非完整 stdout golden） | 有意改变的行为不冻结 |
| R9 | gitleaks `docs/` allowlist 缩窄 | 仅保留 `docs/devlog.md` + `docs/archive/` | 其余 docs 接受扫描 |
| R10 | Secret 注入方式 | host env 注入（诚实注明 Docker inspect 风险） | 短期 secret file 为未来增强 |
| R11 | Legacy 删除和真实 secret cleanup | **均需用户另行批准**；cleanup 不早于 v3.1.0/2026-09-01 | 不可逆操作须单独授权 |
| R12 | macOS runner/架构 | `macos-14` (arm64, Apple Silicon) | 另一架构候选 |

---

## 16. 文档维护政策

与修订前一致：

| 文档 | 更新时机 | 更新内容 |
|------|----------|----------|
| `README.md` | 仅写入已上线、用户可感知的行为 | 新命令用法、安全默认变化 |
| `docs/devlog.md` | **仅在独立验证切片完成后更新** | 变更摘要、取舍、验证结果 |
| `docs/plans/PLAN-p3-unified-cli.md` | 随切片推进更新状态 | 勾选完成切片、记录偏离决策 |
| `docs/rfc/aisc-cli-v1.md` | S1 初稿 → S9 正式版本 | 协议定义 |
| `docs/adr/*.md` | 架构决策时 | 决策背景、选项、结果 |

**规则**：不做 transient edit；Devlog 只记已完成并独立验证的切片；README 绝不包含"计划支持"或"即将上线"。

---

## 附录 A：切片依赖关系图（终版）

```text
S1 (契约/特征测试)
 │
 └─→ S2 (领域模型/只读core)
      │
      ├─→ S3 (Docker planner/executor — legacy-compatible)
      │    │
      │    └─→ S4 (Artifact 组装与 smoke — workflow artifact)
      │         │
      │         └──────────────────────────┐
      │                                    │
      └─→ S5.1 (配置/密钥发现与 schema)     │
           │                               │
           ├─→ S5.2 (config validate/effective)
           │    │                           │
           │    └─→ S5.4 (config migrate + journal)
           │         │                      │
           └─→ S5.3 (secure store adapter)  │
                │    │                      │
                ├────┘                      │
                │                           │
           S5.4 ─┘                          │
           │                               │
           ├─→ S5.5 (cleanup 拒绝 stub)     │
           │                               │
           └─→ S6 (最小 safe/unsafe + network 正交)
                │                          │
                └─→ S7 (Provider 唯一权威 + e2e non-interactive)
                     │                     │
                     └─→ S8 (Container contract/安全默认)
                          │                │
                          └─→ S9 (CLI 机器协议稳定化)
                               │           │
                               └─────→ S10 (默认入口切换)
                                        │
                           [分发授权门] ─┘  ← S4 产物 + 用户批准发布渠道
                                        │
                                        └─→ S11 (观察期 + 删除 legacy)
```

**依赖说明**：
- P3.1 = S1→S4。P3.2 = S5.1→S11。
- S5.1→S5.2→S5.3→S5.4→S5.5→S6→S7→S8→S9→S10→S11 严格单向顺序。
- S5.2 依赖 S5.1；S5.3 依赖 S5.1；S5.4 依赖 S5.2+S5.3；S5.5 依赖 S5.4。
- S4 同时是 S10 的**分发前置**（S4 产出完整 archive → 分发授权门 → S10 默认入口切换）。
- S10 额外条件：S8 contract 完成 + S9 协议稳定化 + 分发授权门通过（用户批准发布渠道且 archive 可被普通用户访问）。
- Legacy 删除（S11）最后，依赖所有迁移/安全/contract/协议/默认切换稳定 + 用户另行批准。

---

## 附录 B：与 v2 计划的关系

v2 中 P0/P1/P2 已完成的工作（目录重组、provider 数据化、versions.env、CI、VERSION、vendor 清单）是本计划的基础设施。P3 在这些基础上做 CLI 层升级。

---

## 附录 C：术语表（修订）

| 术语 | 定义 |
|------|------|
| **host** | 用户宿主机（Linux/macOS/Windows），运行 `aisc` CLI 和 Docker daemon |
| **container** | Docker 容器内 AISC 工作站运行时 |
| **CLI executable** | PyInstaller 打包的独立可执行文件 |
| **release bundle** | 与 CLI 兼容的 `container/Dockerfile`、providers.json、_bundle、downloads 等资源集合 |
| **profile** | 命名 typed overrides，仅控制执行安全维度 |
| **network mode** | 正交于 profile 的网络模式（`direct`/`proxy`） |
| **contract** | 容器镜像 LABEL 声明的兼容性版本号 |
| **capability detection** | 运行时探测 Docker/内核能力（不设硬编码最低版本门槛） |
| **non-interactive** | 不在 stdin 读取任何输入 |
| **copy-only migration** | Phase 1 仅复制 secret（源文件与 settings bytes 不变）；回滚依靠源未变 + journal；不创建 `.bak` 备份 |
| **cleanup refusal stub** | `aisc config cleanup` 在 S5.5 固定拒绝（exit 11、零读写）；真实 cleanup 需后续切片单独批准 |
| **journal** | 迁移操作的密码学审计轨迹（HMAC 保护，不含明文/last4/普通 hash） |
| **source inventory** | 固定的精确路径集合（`W/.aisc/secrets/api-keys` 等），不得递归搜索 |
| **feature test** | 记录兼容行为的回归测试（非完整 stdout golden） |
