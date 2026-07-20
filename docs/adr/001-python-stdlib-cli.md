# ADR 001: Python stdlib CLI 作为跨平台统一运行时

> **状态**：已接受
> **日期**：2026-07-17
> **决策者**：用户批准（来源：[PLAN-p3-unified-cli.md](../plans/PLAN-p3-unified-cli.md) §1.3 决策 D1/D2）

---

## 背景

### 问题

AISC 当前跨三平台（Linux/macOS/Windows）通过 Bash/PowerShell 双轨脚本提供宿主业务引擎（`scripts/01_check_env.sh` → `04_launcher.sh` 及对应 `.ps1` 镜像）。这导致：

1. **三平台脚本漂移风险高**：Bash 和 PowerShell 各维护一套相同业务逻辑（12 个文件），任何业务变更需同步两份。路径分隔符、状态文件解析、颜色输出、错误语义在两种语言间存在已有或潜在差异。

2. **host doctor/build/run 需要宿主契约**：诊断 Docker daemon 运行状态（`aisc doctor`）、发起 `docker build`（`aisc build`）、组装 `docker run` 参数（`aisc run`）——这些操作必须在宿主机执行，不能在需要诊断的 Docker 环境内运行。

3. **Windows/macOS 无可靠预装 Python**：虽然有 Python 但版本/可用性不保证。用户路径必须是独立的可执行制品，而非 `python -m aisc` 或 `pip install`。

4. **CLI 入口缺失**：当前 `start.sh` 只支持 `--workspace PATH`，没有子命令路由（`doctor`/`config`/`build`/`run`/`version`），诊断需直接执行裸脚本。

5. **无结构化输出**：所有输出为纯文本，CI/自动化脚本无法可靠消费。

### 约束

- 需支持 Linux (x86_64)、macOS (arm64 Apple Silicon)、Windows (x86_64)。
- CLI 必须可独立于 Docker 容器运行（`doctor` 在 Docker 不可用时仍需工作）。
- 用户不应需要安装 Python 或任何运行时依赖。
- 需向后兼容现有 AISC 仓库结构（`container/`、`config/`、legacy `scripts/` 在兼容期内保留）。

---

## 决策

### 核心决策

**使用 Python 3.11+ stdlib 作为 CLI 运行时，通过 PyInstaller 生成独立可执行文件，并配套兼容 release bundle 分发。**

具体而言：

| 维度 | 选择 |
|------|------|
| 语言运行时 | Python 3.11+（与容器内 Python 版本一致） |
| 依赖策略 | **runtime stdlib-only**（`argparse`、`dataclasses`、`json`、`subprocess`、`pathlib`）。不使用 Typer / Click / Pydantic 等第三方库 |
| 打包分发 | PyInstaller 独立可执行文件（单文件或单目录 bundle）+ 配套 release bundle archive（`container/`、`config/`、`container/_bundle`、`container/downloads`） |
| 开发/CI 运行 | 开发阶段可通过 `pip install -e .` 或 `PYTHONPATH=src python -m aisc` 运行；**后者不是用户路径** |
| 测试 | 开发/CI 可使用 pytest；**S1 阶段先使用 stdlib `unittest`**（最小依赖） |
| 构建配置 | 最小 `pyproject.toml`（元数据、包发现、dev/build 依赖声明）在 **S2 阶段引入** |
| 资源模型 | CLI 可执行文件 + release bundle 的 archive。CLI 按优先级定位 bundle（`--aisc-root` → `AISC_ROOT` → 同目录 `aisc-bundle/` → Git 仓库发现 → 报错） |
| Bundle manifest | `aisc-bundle/manifest.json` 声明 CLI-bundle 兼容版本映射，CLI 启动时校验 |

### 资源定位优先级

CLI 在进行 `build`/`run`/`provider` 等依赖 bundle 资源的操作时，按以下顺序定位：

1. `--aisc-root PATH` 显式指定
2. `AISC_ROOT` 环境变量
3. CLI 可执行文件同目录下的 bundle（`<exe_dir>/aisc-bundle/`）
4. 仓库发现：向上遍历查找含 `container/Dockerfile` + `VERSION` 的 Git 仓库根目录
5. 以上均失败 → 明确错误，提示用户获取 release bundle

### pyproject.toml 策略

`pyproject.toml` 为最小化，仅包含：
- 项目元数据（name、version）
- 包发现配置
- dev dependency：`pytest`、`PyInstaller`
- script entry point：`aisc = "aisc.cli.main:main"`

runtime 依赖列表为空。普通用户下载解压 release archive 即可使用，无需 `pip install`。

### 非目标

- **不实现 daemon 或后台服务**：CLI 仅为一次性命令执行，无长驻进程。
- **不实现 GUI**：GUI 是远景规划，非 P3 实施目标，不定时间表。CLI 协议仅为 CI/脚本/第三方调用。
- **不替换容器内所有业务逻辑**：P3 只修改容器内最小必要安全/契约接口。
- **不实现插件/扩展系统**：容器内 `cc-switch-cli` 已覆盖。

---

## 备选方案

### 方案 A：继续 Bash/PowerShell 双轨维护

**描述**：保持当前架构，所有命令新增都需同时实现 Bash 和 PowerShell 版本。

**拒绝原因**：
- 维护成本随命令数量线性增长。当前 12 个文件已产生漂移风险。
- Bash/PowerShell 虽可借助各自工具生成 JSON/JSONL，但需要维护两套序列化、错误和流式事件实现，难以低成本保证跨平台协议一致性。
- 跨平台行为一致性难以保证（路径分隔符、进程管理、信号处理、颜色输出在两语言实现中存在本质差异）。
- 缺乏类型系统，重构风险高。

**代价**：逐年上升的同步开销与 bug 修复成本。

---

### 方案 B：容器内 Python 作为宿主 CLI 运行时

**描述**：以容器内已有的 Python 环境作为宿主 CLI 的运行时——用户先拉镜像，然后通过 `docker run` 执行容器内的 Python CLI。

**拒绝原因**（循环依赖）：

| 场景 | 为何不可行 |
|------|-----------|
| `aisc doctor` | 诊断 Docker daemon 是否运行——若 Docker 不可用，无法拉容器来诊断 Docker |
| `aisc build` | 构建镜像——`docker build` 是宿主机操作，需在容器外发起 |
| `aisc version` | CLI 本身版本——若 CLI 在容器内，需先 pull 旧镜像才能得知有新版本 |
| `aisc config migrate` | 迁移宿主机旧状态——需 bind mount 处理 UID 差异和文件权限 |
| 镜像尚未构建时 | 任何"先用容器做 CLI"的前提都不成立 |

**代价**：无法覆盖 CLI 核心使用场景（诊断、构建、版本），不可作为主要方案。

---

### 方案 C：Go 实现

**描述**：使用 Go 编译为静态链接的独立可执行文件。

**拒绝原因**：
- 团队/项目当前无 Go 代码基础，引入新语言增加构建工具链和维护负担。
- 容器内 Python 环境已存在——选择 Python 保持宿主-容器技术栈一致。
- Go 的静态编译优势对本项目规模（CLI 封装 Docker 子进程调用+配置管理）不构成决定性收益。
- CI 矩阵需同时维护 Python（容器内）和 Go（宿主侧），复杂度不降反升。

**代价**：引入新生态、新构建链、新测试工具链，且容器内仍需 Python，无法消除语言多样性。

---

### 方案 D：Rust 实现

**描述**：使用 Rust 编译为静态链接的独立可执行文件。

**拒绝原因**：
- 与方案 C 相似——引入无现有基础的语言生态。
- Rust 编译时间较长，CI 反馈循环变慢。
- 对以子进程调用（Docker CLI）和 JSON 序列化为主的 CLI 场景，Rust 的性能优势不明显。
- 同样面临宿主-容器双语言栈的问题。

**代价**：高于 Go 的学习曲线 + 更长的编译时间 + 双语言 CI 矩阵。

---

## 后果

### 积极影响

1. **单一代码库**：所有 CLI 逻辑在单一 Python 代码库中维护，消除双轨漂移。
2. **结构化输出**：`dataclasses` + `json` 原生支持 JSON envelope 和 JSONL event stream。
3. **结构化领域模型**：`dataclasses` 与类型注解明确数据边界，并可在后续按需接入静态检查；P3 不以 mypy/pyright 为运行时或验收依赖。
4. **测试友好**：Python 有成熟的测试生态（pytest、unittest），支持 CI 自动化。
5. **独立分发**：PyInstaller 产物使最终用户无需预装 Python。

### 消极影响与缓解

| 风险 | 缓解 |
|------|------|
| PyInstaller 打包体积大 | 可接受——CLI 为 CLI+bundle archive 的一部分，用户下载完整 release |
| PyInstaller 三平台 CI 复杂度 | 在 CI workflow 中分平台构建，产物为 workflow artifact（S4 阶段） |
| Python 3.11+ 版本约束 | 与容器内版本一致，减少版本碎片；CI runner 已提供 3.11+ |
| stdlib-only 限制 | 避免了外部依赖管理；argparse 对现有命令树规模足够 |
| 打包后的调试困难 | 开发阶段始终可用源码运行；PyInstaller 打包为 CI 产物，非开发路径 |

### 平台原生配置路径

CLI 使用平台原生目录存储用户级配置与密钥：

| 平台 | 路径 |
|------|------|
| Linux | `$XDG_CONFIG_HOME/aisc/`（默认 `~/.config/aisc/`） |
| macOS | `~/Library/Application Support/aisc/` |
| Windows | `%APPDATA%/aisc/` |

Windows secrets 使用平台 ACL 策略，不以 POSIX `chmod`/`stat` 作为跨平台证明。

---

## 回滚策略

若 Python/PyInstaller 方案在实施中遇到不可逾越的障碍：

1. **代码**：`git revert` S2–S4 相关 commit。`src/aisc/` 删除。
2. **Artifact**：删除 CI artifact 步骤和 `packaging/` 目录。
3. **入口**：旧 `start.sh`/`start.bat`/`start.command` 在 S10 之前不受影响，继续委托到旧 `scripts/run.*`。
4. **用户数据**：S1 阶段（本文档+特征测试）不产生用户数据变更，零回滚成本。

---

## 参考资料

- [PLAN-p3-unified-cli.md](../plans/PLAN-p3-unified-cli.md) §1.3（已批准核心决策 D1/D2）、§1.4（否决容器内 Python）、§4（资源模型）、§8（配置/状态/密钥分离）
- [RFC: AISC CLI v1](../rfc/aisc-cli-v1.md) — 机器消费协议
