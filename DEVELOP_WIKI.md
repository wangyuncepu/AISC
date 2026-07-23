# AISC 开发者手册

> **面向版本**: `develop` 分支。本文描述的是当前 `develop` 分支**实际已实现**的行为。
> 暂未合入 `develop` 的能力（仅在 `main` 或其他特性分支中存在）不在本文范围内。

---

## 1. 阅读路径与适用范围

本手册同时服务两类读者：

| 读者类型 | 目标 | 推荐路径 |
|---------|------|---------|
| **新贡献者** | 约 15 分钟完成环境搭建、跑通测试、完成一次典型修改 | §2 → §4 → §5 中相关任务 → §11 |
| **核心维护者** | 查找维护流程、CI 与发布步骤、兼容性契约 | §3 → §6 → §7 → §8 → §11 |

每个“常见开发任务”（§5）固定覆盖：**入口文件 → 调用链 → 容易漏改的关联文件 → 最低验证命令**。

本文**不包含**：用户安装教程、完整用户命令参考、用户 FAQ、推荐服务或推广内容。这些内容见 `README.md`。

---

## 2. 15 分钟开发环境

### 前提

- Python 3.11+（`python3 --version`）
- Git
- Docker（仅 `aisc build`/`aisc run` 和容器相关测试需要；纯 Python 单元测试不需要）

### 搭建步骤

```bash
# 1. 克隆仓库
git clone https://github.com/wangyuncepu/AISC.git
cd AISC

# 2. 切换到 develop 分支
git checkout develop

# 3. 创建虚拟环境并安装（editable 模式）
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .

# 4. 验证安装（确认输出中包含 2.0.0-dev）
aisc version

# 5. 检查宿主机环境
aisc doctor

# 6. 运行最小测试（无需 Docker 的 unittest 模块）
PYTHONPATH=src python3 -m unittest \
  tests.unit.test_version \
  tests.unit.test_doctor \
  tests.unit.test_config_s5_final \
  -v

# 7. 确认 shell 语法
bash tests/smoke/check-syntax.sh
```

> **Windows PowerShell 用户**: 将 `source .venv/bin/activate` 替换为 `.venv\Scripts\Activate.ps1`。
> 虚拟环境每次新终端都需要重新激活。

### 排查：命令指向旧安装时

如果 `aisc version` 的行为与预期不符（例如版本号不对、或 `command not found`），说明可能指向了系统上的另一个 `aisc` 安装。先确认当前调用的路径：

```bash
command -v aisc                          # 显示实际调用的路径
python3 -c "import aisc; print(aisc.__file__)"  # 查看 Python 能找到的包位置
```

重新激活虚拟环境后再试：

```bash
source .venv/bin/activate
# 或直接使用虚拟环境内的绝对路径:
.venv/bin/aisc version
```

不要用 `pip uninstall aisc` 破坏性卸载——系统中可能存在多个 AISC 安装（PyInstaller 版本、其他虚拟环境等），直接卸载可能影响这些安装。

### 完整测试

以上步骤 6 只跑了最小测试。完整单元测试（包含所有 `tests/unit/` 模块）和集成测试（部分需要 Docker）的命令见 §7 和 §11。15 分钟内不需要跑全量。

### 可选：安装 uv（加速依赖管理）

```bash
# CI 使用 uv 管理 editable install 的 smoke test
uv tool install --editable .
# 之后可直接运行 aisc（uv 管理的隔离环境）
```

---

## 3. 架构与运行模型

### 3.1 整体架构

```
┌─────────────────────────────────────────────┐
│  宿主机 (Host)                               │
│  ┌─────────────┐  ┌──────────────────────┐   │
│  │ Shell 启动器  │  │  Python CLI (aisc)   │   │
│  │ start.sh     │  │  src/aisc/cli/main.py │   │
│  │ start.command│  │  ≥ 15 个子命令         │   │
│  │ start.bat    │  └──────────┬───────────┘   │
│  └──────┬───────┘             │               │
│         │                     │               │
│         └──────────┬──────────┘               │
│                    │ Docker CLI               │
│                    ▼                          │
│  ┌─────────────────────────────────────┐      │
│  │  Docker 容器 (super-claude:latest)   │      │
│  │  ┌────────┐ ┌──────────────────┐    │      │
│  │  │ cs /   │ │ entrypoint.sh    │    │      │
│  │  │ claude-│ │ claude-wrapper   │    │      │
│  │  │ switch │ │ providers.json   │    │      │
│  │  └────────┘ └──────────────────┘    │      │
│  └─────────────────────────────────────┘      │
└─────────────────────────────────────────────┘
```

### 3.2 双入口策略

| 入口 | 运行位置 | 目标 | 当前状态 |
|------|---------|------|---------|
| `start.sh` / `.command` / `.bat` | 宿主机 | 最终用户一键启动 | 稳定，保持维护 |
| `aisc` Python CLI | 宿主机 | 开发者管理 + 逐步替代启动器 | 活跃开发中 |

**逐步统一方向**：新增宿主机能力优先通过 Python CLI 实现。Shell 启动器保持稳定但不再扩展功能。两者在容器发现状态（`.aisc/state.env`）上互通。

### 3.3 Python 包分层

```
src/aisc/
├── __init__.py          # __version__ = "2.0.0-dev"
├── cli/                 # 表现层：argparse、输出格式化、命令分发
│   ├── main.py          # CLI 入口、参数解析、命令路由
│   ├── output.py        # JSON envelope、JSONL emitter、文本格式化
│   └── commands/        # 每个子命令的具体实现
│       ├── build.py
│       ├── run.py       # --keep-alive: 后台模式 + docker attach
│       ├── config.py
│       ├── provider.py  # provider add: 编辑器模式
│       ├── profile.py
│       ├── container.py
├── application/         # 应用服务层：业务逻辑编排
│   ├── version.py       # 版本信息收集
│   ├── doctor.py        # 宿主机环境诊断
│   ├── config_service.py # 配置校验/合并（只读）
│   ├── provider_service.py
│   ├── profile_service.py
│   ├── skill_service.py # Skill 导入/列表/删除/校验
│   └── resources.py     # AISC 根目录发现
├── domain/              # 领域模型：纯数据，零 I/O
│   ├── models.py        # VersionInfo、DoctorReport、BuildPlan、RunPlan
│   ├── config.py        # ProviderCatalog、PathPolicy、CredentialValue
│   └── skill_models.py  # SkillLockV2、ParsedGitHubURL
├── adapters/            # 适配器：所有 I/O 和外部调用
│   ├── docker_.py       # DockerExecutor（Real + Fake）
│   ├── github_client.py # GitHubTransport（Real + Fake）
│   ├── config_reader.py # 安全的配置读取（POSIX/Windows）
│   ├── config_source.py # 配置源发现（密钥、状态文件）
│   ├── secret_store.py  # 安全目录/文件创建
│   ├── state_file.py    # .aisc/state.env 读写
│   ├── skill_validator.py
│   ├── lock_serializer.py
│   └── system.py        # ProcessRunner
└── schemas/             # 配置 schema 校验
    └── config_schema.py
```

**依赖方向**: `cli → application → domain ← adapters`。`domain` 无任何外部依赖。

### 3.4 测试架构

```
tests/
├── unit/                # 单元测试（stdlib unittest）
│   ├── test_version.py
│   ├── test_doctor.py
│   ├── test_secret_store.py
│   ├── test_skill_service.py
│   ├── test_config_*.py
│   ├── test_provider_service.py
│   ├── test_profile_service.py
│   ├── test_cli_brief.py
│   ├── test_build_run_plans.py
│   └── ...
├── integration/         # 集成测试
│   ├── test_cli.py
│   ├── test_build_run.py
│   └── test_container_cli.py
├── smoke/               # 冒烟脚本
│   ├── check-syntax.sh
│   ├── packaging_smoke.sh
│   └── editable_install_smoke.sh
├── harness/             # 测试工具
│   ├── fake_github.py   # FakeGitHubTransport（无网络测试）
│   └── test_runner.py
└── features/            # 特性测试
```

### 3.5 容器运行模型

```
docker run --rm \
  -v $(pwd):/root/app \          # 工作区挂载
  -e CLAUDE_SCOPE=project \     # 配置作用域
  super-claude:latest

容器内：
  /root/
  ├── .claude/           # Claude CLI 原生目录（出厂 / 项目）
  ├── app/               # 挂载的工作区
  │   ├── .claude/       # 项目作用域（持久化）
  │   ├── .cc-config/    # 兼容层（cs 脚本当前双写到此处和 .aisc/secrets/）
  │   └── .aisc/secrets/ # 密钥存储
  ├── providers.json     # 模型提供商元数据
  └── ai_brief/          # AI 简讯工具
```

---

## 4. 仓库地图

```
AISC/                          # 仓库根（也是 AISC 安装根目录）
├── VERSION                    # 版本号（2.0.0-dev）
├── pyproject.toml             # Python 包元数据
├── skills-lock.json           # Skill 导入锁文件（v2）
├── README.md                  # 用户手册
├── DEVELOP_WIKI.md            # 本文档
├── LICENSE                    # MIT
├── .gitignore
├── .gitleaks.toml             # 密钥扫描配置
├── .dockerignore
├── .gitattributes             # 跨平台换行符策略
│
├── src/aisc/                  # Python CLI 源码
│   ├── __init__.py            # __version__ 声明点
│   ├── cli/                   # CLI 入口 + 表现层
│   ├── application/           # 应用服务
│   ├── domain/                # 领域模型
│   ├── adapters/              # I/O 适配器
│   └── schemas/               # 配置 schema
│
├── container/                 # Docker 镜像构建输入
│   ├── Dockerfile             # 镜像定义
│   ├── entrypoint.sh          # 容器入口脚本
│   ├── claude-switch          # cs 命令（容器内模型切换）
│   ├── claude-wrapper         # Claude CLI 包装器
│   ├── providers.json         # 模型提供商元数据
│   ├── claude-settings.json   # 默认 Claude CLI 设置
│   ├── global-claude.md       # 全局 CLAUDE.md
│   ├── commands/              # 斜杠命令（gstack 等）
│   ├── lib/                   # 共享 bash 库
│   ├── _bundle/               # 构建期暂存的 skills/plugins（纳入 git）
│   └── downloads/             # 预下载的 mihomo/geodata（纳入 git）
│
├── config/
│   └── versions.env           # 外部依赖版本 pin（AISC_VERSION + CLAUDE_CODE_VERSION 等）
│
├── tools/                     # 维护脚本
│   ├── stage-skills.sh        # 从宿主机暂存 plugins/skills 到 _bundle
│   ├── stage-skills-cleanup.sh # _bundle 清理辅助
│   ├── stage-mihomo.sh        # 预下载 mihomo + geodata
│   ├── vendor-refresh.sh      # 刷新 vendored artifacts + 重新生成校验和
│   ├── vendor-verify.sh       # 校验 vendor/checksums.txt
│   └── check-docs.sh          # 文档一致性检查
│
├── scripts/                   # Shell 启动器流水线模块
│   ├── 01_check_env.sh / .ps1 # 环境检查
│   ├── 02_config_wizard.sh/.ps1 # 代理配置向导
│   ├── 03_build_image.sh/.ps1 # 镜像构建
│   ├── 04_launcher.sh / .ps1  # 容器启动
│   ├── run.sh / run.ps1       # 直接运行入口
│   └── _state.sh / _state.ps1 # 状态文件辅助
│
├── start.sh / start.command / start.bat  # 用户启动器入口
│
├── tests/                     # 测试
│   ├── unit/
│   ├── integration/
│   ├── smoke/
│   ├── harness/
│   └── features/
│
├── packaging/                 # 打包与分发
│   ├── artifact.py            # stage/archive/verify 构建产物
│   ├── ci_smoke.py            # CI 冒烟验证
│   ├── pyinstaller/           # PyInstaller 入口
│   ├── macos/                 # macOS .pkg 构建
│   ├── windows/               # Windows 安装器 (Inno Setup)
│   ├── install.sh / install.ps1
│   └── uninstall.sh / uninstall.ps1
│
├── vendor/                    # Vendored 清单
│   ├── manifest.json          # 组件来源声明
│   ├── checksums.txt          # 容器文件校验和
│   └── licenses/              # 第三方许可证
│
├── apps/ai-brief/             # AI 简讯工具（独立应用）
│
├── .github/workflows/         # CI 定义
│   ├── checks.yml             # 语法 + 单元测试 + smoke + gitleaks
│   ├── artifact.yml           # PyInstaller 跨平台构建
│   └── docker-smoke.yml       # Docker 镜像构建验证
│
├── docs/                      # 设计文档
│   ├── adr/                   # 架构决策记录
│   ├── rfc/                   # RFC
│   ├── plans/                 # 开发计划
│   └── testing/               # 测试文档
│
└── .aisc/                     # 运行时状态（gitignored）
    └── state.env              # 容器名发现（shell 启动器写入，CLI 读取）
```

---

## 5. 常见开发任务

### 5.1 修改 CLI 命令

**入口文件**: `src/aisc/cli/main.py` — 参数解析、命令路由、JSON/text 输出格式化
**子命令实现**: `src/aisc/cli/commands/<name>.py`

**调什么**:
- 新增子命令 → 在 `main.py` 的 `_build_parser()` 中添加 subparser，并在 `main()` 函数中添加 `elif args.command == "..."` 分支
- 修改命令行为 → 找到对应 `_cmd_*` 函数，修改其调用链
- 修改输出格式 → 修改对应子命令的 `print_*_text()` 函数或 JSON 数据构造

**容易漏改的关联文件**:
- `src/aisc/cli/output.py` — 如果新增 JSON envelope 字段或修改错误格式
- `src/aisc/domain/models.py` — 如果涉及新领域数据类型
- `src/aisc/application/*.py` — 如果涉及新业务逻辑

**最低验证命令**:
```bash
# 单元测试
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_*.py' -v -k <pattern>

# CLI 集成测试（部分需要 Docker）
PYTHONPATH=src python3 -m unittest tests.integration.test_cli -v

# 手动快速冒烟
aisc version --format json | python3 -m json.tool
```

### 5.2 修改配置 / Provider 系统

**入口文件**:
- Provider 元数据: `container/providers.json`
- 配置 Schema: `src/aisc/schemas/config_schema.py`
- 配置源发现: `src/aisc/adapters/config_source.py`
- 配置读取: `src/aisc/adapters/config_reader.py`
- 配置服务: `src/aisc/application/config_service.py`

**调用链**:
```
providers.json → config_source.load_provider_catalog() → ProviderCatalog
工作区 .aisc/secrets/api-keys → config_source.discover_sources() → CredentialResult[]
工作区 .cc-config/api-keys → 同上（config_source.py 仍将其列为配置源之一）
```

**容易漏改的关联文件**:
- `container/claude-switch` — cs 命令在容器内读取 `providers.json` 做模型切换
- `container/lib/path-resolve.sh` — 容器内解析 `.cc-config` 目录的共享库
- `src/aisc/domain/config.py` — ProviderSpec、CredentialValue 模型定义
- `tests/unit/test_provider_service.py`
- `src/aisc/cli/commands/provider.py`
- `tools/check-docs.sh` — 文档一致性检查会比对 provider 数量

**兼容性注意事项**:
- `.cc-config/` 是**待彻底移除的兼容层**。当前实现中，容器内 `claude-switch` 脚本的 `get_key()` 在用户输入新密钥时**同时写入** `.aisc/secrets/api-keys` 和 `.cc-config/api-keys`（双写向后兼容），读取时以 `.aisc/secrets/` 为主、`.cc-config/` 为 fallback。`src/aisc/adapters/config_source.py` 也将 `.cc-config/api-keys` 列为配置源之一。
- 这是 **Legacy Shell / 容器脚本的现存兼容行为**，不是目标设计。新增 Python / 宿主机代码**不得扩大** `.cc-config/` 的使用范围，不得新增以 `.cc-config/` 为主存储的写入。
- 后续移除兼容双写前，需处理迁移（确保所有密钥已存在于 `.aisc/secrets/`）和兼容测试（验证仅读取 `.aisc/secrets/` 时容器内 `cs` 命令正常工作）。

**最低验证命令**:
```bash
# 查看 provider 列表（只读）
aisc provider list --format json
aisc provider show deepseek --format json

# 校验配置
aisc config validate
aisc config effective

# 运行相关测试
PYTHONPATH=src python3 -m unittest tests.unit.test_config_s5_final -v
PYTHONPATH=src python3 -m unittest tests.unit.test_config_service -v
```

### 5.3 修改 Docker 镜像 / 容器

**入口文件**:
- `container/Dockerfile` — 镜像定义
- `container/entrypoint.sh` — 容器启动入口
- `container/claude-wrapper` — Claude CLI 包装器
- `container/claude-switch` — cs 命令
- `src/aisc/adapters/docker_.py` — Docker 操作适配器
- `src/aisc/cli/commands/build.py`, `run.py` — 构建/运行命令

**调用链**:
```
aisc build → plan_build() → RealDockerExecutor.run_streaming(["docker", "build", ...])
aisc run   → plan_run()   → RealDockerExecutor.run_streaming(["docker", "run", ...])
容器启动   → entrypoint.sh → 选择作用域 → 配置 TUN/简讯 → exec claude
```

**容易漏改的关联文件**:
- `.dockerignore` — 修改 COPY 源时需要更新
- `config/versions.env` — 修改外部依赖版本时同步更新
- `src/aisc/domain/models.py` — BuildPlan / RunPlan 的 `docker_argv` 属性
- `container/lib/` — 共享 bash 库
- 测试: `tests/unit/test_build_run_plans.py`

**最低验证命令**:
```bash
# dry-run（不需要 Docker daemon）
aisc build --dry-run
aisc build --dry-run --format json

# 完整构建（需要 Docker）
aisc build --no-cache
```

### 5.4 修改 Skill 导入功能

**入口文件**:
- `src/aisc/application/skill_service.py` — 核心业务逻辑（add/list/remove/check）
- `src/aisc/domain/skill_models.py` — 数据模型（SkillLockV2, ParsedGitHubURL）
- `src/aisc/adapters/github_client.py` — GitHub API 访问（RealGitHubTransport）
- `src/aisc/adapters/lock_serializer.py` — 锁文件序列化
- `src/aisc/adapters/skill_validator.py` — Skill 校验和依赖扫描

**调用链**:
```
aisc skill add <url>
  → parse_github_url() → resolve_ref() → get_tree() → get_blob()
  → validate_tree() → materialize → write skills-lock.json
  → 写入 container/_bundle/skills/<name>/
```

**容易漏改的关联文件**:
- `skills-lock.json` — 锁文件 v2 格式，**不要手动编辑**
- `container/_bundle/skills/` — 实际 Skill 文件存放位置
- `tools/stage-skills.sh` — 构建前从宿主机暂存 plugins
- `tests/harness/fake_github.py` — 无网络测试用的 FakeGitHubTransport
- `tests/unit/test_skill_service.py`

**最低验证命令**:
```bash
# 查看当前 skill 状态
aisc skill list
aisc skill check

# 运行单元测试（不需要网络）
PYTHONPATH=src python3 -m unittest tests.unit.test_skill_service -v
```

### 5.5 修改 Shell 启动器

**入口文件**:
- `start.sh` — Linux/macOS 用户入口（薄壳，调用 `scripts/` 模块）
- `start.command` — macOS Finder 双击入口
- `start.bat` — Windows 入口
- `scripts/01_check_env.sh`, `02_config_wizard.sh`, `03_build_image.sh`, `04_launcher.sh`

**调用链**:
```
start.sh → scripts/01_check_env.sh → 02_config_wizard.sh → 03_build_image.sh → 04_launcher.sh
                                                                            → docker run ...
```

**容易漏改的关联文件**:
- `scripts/_state.sh` — 状态文件读写
- `.aisc/state.env` — 容器名发现（与 Python CLI 共享）
- `scripts/run.sh` / `run.ps1`

**边界**：
- Shell 启动器**不转发** Python CLI 子命令（`./start.sh doctor` 无效）
- 新增宿主机管理功能优先通过 Python CLI 实现

**最低验证命令**:
```bash
# 语法检查
bash -n start.sh
bash -n scripts/01_check_env.sh

# 完整冒烟
bash tests/smoke/check-syntax.sh
```

### 5.6 维护构建资源（tools/stage-\* / tools/vendor-\*）

**工具清单及用途**:

| 工具 | 用途 | 何时运行 |
|------|------|---------|
| `tools/stage-skills.sh` | 从宿主机 `~/.claude` 暂存 plugins + skills 到 `container/_bundle/` | 更新内置 plugin/skill 版本后 |
| `tools/stage-skills-cleanup.sh` | `stage-skills.sh` 调用的内部清理脚本 | 仅被 `stage-skills.sh` 调用 |
| `tools/stage-mihomo.sh` | 预下载 mihomo 二进制 + geodata 到 `container/downloads/` | 更新 mihomo 版本需要离线/弱网构建时 |
| `tools/vendor-refresh.sh` | 重新生成 `vendor/checksums.txt` 并验证 `container/downloads/` | 修改容器内任何文件后 |
| `tools/vendor-verify.sh` | 校验 `vendor/checksums.txt` 完整性 | 提交前验证 |
| `tools/check-docs.sh` | 文档一致性检查（README 路径、Provider 数量等） | 修改 README 或 `providers.json` 后 |

**工作流示例**（更新内置 plugin 后）:
```bash
bash tools/stage-skills.sh       # 重新暂存 plugins/gstack
bash tools/vendor-refresh.sh     # 更新校验和
bash tools/vendor-verify.sh      # 验证
bash tests/smoke/check-syntax.sh # 语法验证
```

---

## 6. 状态、配置与兼容性契约

### 6.1 版本号声明点

当前 `develop` 分支上版本号 `2.0.0-dev` 在以下位置**分别声明**，**尚未统一为单一事实源**：

| 位置 | 文件 | 用途 |
|------|------|------|
| `VERSION` | 仓库根 | 打包脚本读取（`packaging/artifact.py`） |
| `src/aisc/__init__.py` | `__version__ = "2.0.0-dev"` | Python CLI 自身版本 |
| `config/versions.env` | `AISC_VERSION=2.0.0-dev` | Docker 构建上下文 |
| `packaging/artifact.py` | `get_version()` / `get_package_version()` | 打包时比对两者一致性 |

**发版同步清单**（修改版本号时）:
- [ ] `VERSION` 文件
- [ ] `src/aisc/__init__.py` 的 `__version__`
- [ ] `config/versions.env` 的 `AISC_VERSION`
- [ ] 确认 `packaging/artifact.py` 的 `_assert_version_guard()` 通过

### 6.2 外部依赖版本 Pin

**事实源**: `config/versions.env`

| 变量 | 当前值 | 说明 |
|------|-------|------|
| `MIHOMO_VERSION` | `v1.19.27` | 容器内 TUN 透明代理核心 |
| `CC_SWITCH_VERSION` | `v5.9.0` | cc-switch-cli Rust 二进制 |
| `CLAUDE_CODE_VERSION` | `latest` | Claude Code npm 包（**TODO: pin 到具体版本**） |
| `GEODATA_VERSION` | `latest` | Geo 数据版本（**TODO: pin 到具体日期标签**） |
| `NODE_IMAGE` | `node:20-slim` | Node.js 基础镜像 |

### 6.3 配置源兼容性

```
密钥存储（当前实际行为）:
  .aisc/secrets/api-keys  ← 优先读取；cs 脚本输入新密钥时写入
  .cc-config/api-keys     ← fallback 读取；cs 脚本新密钥时同时写入（双写兼容）
                             config_source.py 仍将其列为配置源之一

容器名发现:
  .aisc/state.env         ← Shell 启动器写入 / Python CLI 读取
  .deploy/state.env       ← 历史路径（仅读取，不再写入新数据）
```

- `.cc-config/` 是待彻底移除的兼容层；容器当前以 `/root/.aisc` 作为项目配置目录，`container/lib/path-resolve.sh` 仍保留 `.cc-config` 回退路径，Python 侧 `config_source.py` 仍将其列为配置源。
- 这是 **Legacy Shell / 容器脚本的现存兼容行为**，不是目标设计。
- **禁止**在新代码（Python CLI 或宿主机逻辑）中添加 `.cc-config/` 依赖或将其作为新写入路径。
- 后续移除兼容双写前需：确认所有密钥已存在于 `.aisc/secrets/`；修改 `claude-switch` 的 `get_key()` 移除双写和 fallback 读取；修改 `entrypoint.sh` / `path-resolve.sh` 的路径解析；更新 `config_source.py` 的配置源清单；运行容器内 `cs` 命令兼容测试。
- `.deploy/` 目录内容每次运行重新生成，已纳入 `.gitignore`。

### 6.4 Profile 安全控制

- `aisc profile list` / `aisc profile show [safe|unsafe]` 可**只读查看**
- `safe` / `unsafe` Profile **尚未**接入 `aisc run` 的安全控制
- `aisc run --profile proxy` 仅是 `--network proxy` 的兼容别名，**不是安全 Profile**

---

## 7. 测试策略

### 7.1 测试框架与约定

- **框架**: Python stdlib `unittest`（**不是 pytest**）
- **运行命令**: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`
- **CI 执行**: `.github/workflows/checks.yml` 的 `Run Python unit tests` step
- **不使用** pytest 特性（fixtures、parametrize、conftest 等）

### 7.2 测试类别

| 类别 | 位置 | 运行条件 | 命令 |
|------|------|---------|------|
| 单元测试 | `tests/unit/` | 纯 Python，无外部依赖 | `PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_*.py' -v` |
| 集成测试 | `tests/integration/` | 部分需要 Docker | 同上，替换路径为 `tests/integration` |
| Shell 冒烟 | `tests/smoke/check-syntax.sh` | 需要 bash + node | `bash tests/smoke/check-syntax.sh` |
| 打包冒烟 | `tests/smoke/packaging_smoke.sh` | 需要 Python | `bash tests/smoke/packaging_smoke.sh` |
| Editable 安装冒烟 | `tests/smoke/editable_install_smoke.sh` | 需要 Python + uv（可选） | `bash tests/smoke/editable_install_smoke.sh` |

### 7.3 测试工具

- `tests/harness/fake_github.py` — `FakeGitHubTransport`，完全无网络的 GitHub API 模拟
- `src/aisc/adapters/docker_.py` 中的 `FakeDockerExecutor` — 无 Docker 守护进程的测试用执行器
- 单元测试通过注入 Fake 对象实现确定性测试

### 7.4 编写新测试

```python
# tests/unit/test_my_feature.py
import unittest
from pathlib import Path

class MyFeatureTest(unittest.TestCase):
    def test_something(self):
        result = my_function()
        self.assertEqual(result, expected_value)

if __name__ == "__main__":
    unittest.main()
```

- 位于 `tests/unit/` 下的测试文件自动被 discover 发现
- 不需要 `__init__.py` 中的显式导入

---

## 8. 打包、CI 与发布

### 8.1 CI 流水线

**Checks** (`.github/workflows/checks.yml`) — push/PR 触发：
1. Shell 语法检查（`bash -n`）
2. Python 语法检查（`py_compile`）
3. Node.js 语法检查（`node --check`）
4. JSON 验证（`json.tool`）
5. 项目冒烟测试（`bash tests/smoke/check-syntax.sh`）
6. Python 单元测试（`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`）
7. 打包冒烟测试
8. Editable 安装冒烟测试（使用 `uv`）
9. 密钥扫描（Gitleaks，continue-on-error）

**Artifact** (`.github/workflows/artifact.yml`) — push/PR/手动触发：
- 跨平台 PyInstaller 构建矩阵：
  - `ubuntu-22.04` → linux x86_64
  - `windows-2022` → windows x86_64（含 Inno Setup 安装器）
  - `macos-14` → macos arm64（含 .pkg 安装器）
- 每个平台的构建流程：
  1. `pip install -e .` → PyInstaller 6.21.0
  2. 运行打包单元测试
  3. 构建 onedir → 冒烟验证
  4. 构建 onefile
  5. `packaging/artifact.py stage` → `verify` → `archive`
  6. 平台特定安装器构建 + 冒烟
- 聚合 Job：校验所有平台产物、生成 `SHA256SUMS`

**Docker Smoke** (`.github/workflows/docker-smoke.yml`) — PR/手动触发：
- 使用 Docker Buildx 构建镜像（不推送），验证 Dockerfile 可构建

### 8.2 打包命令参考（维护者视角）

```bash
# 暂存 bundle
python3 packaging/artifact.py stage
python3 packaging/artifact.py verify --bundle <staging>/aisc-bundle

# 构建 onefile（需要 PyInstaller 6.21.0）
python3 packaging/artifact.py build-onefile

# 构建分发档案
python3 packaging/artifact.py archive \
  --staging <staging-dir> \
  --executable <onefile-path> \
  --platform linux --arch x86_64

# 验证档案
python3 packaging/artifact.py verify --archive <archive-path>

# 验证版本一致性
python3 -c "
from packaging.artifact import _assert_version_guard
from pathlib import Path
_assert_version_guard(Path('.'))
"
```

### 8.3 版本号一致性检查

打包脚本 `packaging/artifact.py` 在 `stage` 命令中会调用 `_assert_version_guard()`：
- 读取 `VERSION` 文件的第一行
- 读取 `src/aisc/__init__.py` 中的 `__version__`
- 两者不一致则**退出并报错**

CI 的 artifact smoke（`ci_smoke.py`）会进一步验证构建产物运行 `aisc version --format json` 输出的 `cli_version` 与 bundle 中的 `VERSION` 一致。

### 8.4 发布步骤与边界

**当前仓库没有自动 Release 工作流**。`.github/workflows/` 下三个 workflow（`checks.yml`、`artifact.yml`、`docker-smoke.yml`）均不包含 `gh release create`、tag 触发发布或自动上传到 GitHub Release 的逻辑。`artifact.yml` 中的 `upload-artifact` 只是 CI 内部临时产物（7 天保留期），不是公开发布。

维护者发布流程（手动）：

```bash
# 1. 版本同步 — 按 §6.1 清单确认所有版本声明点一致
#    VERSION / src/aisc/__init__.py / config/versions.env

# 2. 确保 focused checks 通过（至少 checked-in 语法 + 单元测试）
bash tests/smoke/check-syntax.sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_*.py' -v

# 3. 等待或手动触发 full CI（artifact.yml 跨平台构建）
#    确认 linux/windows/macos 三个平台的构建产物均通过 verify + smoke

# 4. 从 CI artifacts 下载各平台产物，验证 SHA256SUMS
#    或本地构建：
python3 packaging/artifact.py stage
python3 packaging/artifact.py verify --bundle <staging>/aisc-bundle

# 5. 创建并推送 tag（示例，需维护者确认）
#    git tag -a v2.0.0 -m "Release v2.0.0"
#    git push origin v2.0.0
#    注意：push tag 不会自动触发 Release，需手动在 GitHub 创建

# 6. 在 GitHub Releases 页面手动创建 Release：
#    - 选择上一步推送的 tag
#    - 上传各平台 .tar.gz / .zip / .pkg / setup.exe 及对应 .sha256
#    - 附上 SHA256SUMS
```

**故障定位层次**（CI 失败时按此顺序排查）：
1. **Checks 失败** — 通常是代码语法错误或单元测试失败；问题在最近提交中
2. **Artifact 失败** — 通常是 PyInstaller 打包问题（入口文件、依赖、路径变更）；检查 `packaging/pyinstaller/entrypoint.py` 和 `packaging/artifact.py`
3. **Docker Smoke 失败** — 通常是 Dockerfile 语法错误或构建上下文文件缺失；检查 `container/Dockerfile` 和 `.dockerignore`
4. **跨平台不一致** — 通常是一个平台通过了但另一个失败；检查平台特定路径处理（`sys.platform` 分支、Windows `\\` vs POSIX `/`）

**边界**：
- 本文不提供具体的 `git tag` 签名策略或 Release 命名规范——这些是项目治理决策，不在代码范围内
- 本文不虚构未实现的工作流步骤

---

## 9. 安全与敏感数据

### 9.1 密钥存储

| 路径 | 用途 | 当前实际行为 |
|------|------|-------------|
| `工作区/.aisc/secrets/api-keys` | 密钥存储 | cs 脚本优先读取；新密钥时写入 |
| `工作区/.cc-config/api-keys` | 兼容层 | cs 脚本 fallback 读取；新密钥时**同时写入**（双写兼容）；`config_source.py` 仍列为配置源 |
| `容器内 /root/.aisc/secrets/api-keys` | 容器内密钥 | cs 命令写入 |

- `.cc-config/` 双写是 Legacy Shell / 容器脚本的现存兼容行为，不是目标设计。详见 §6.3。
- API Key 使用 `CredentialValue` 类型（`src/aisc/domain/config.py`），`__str__` 和 `__repr__` 始终返回 `"****"`
- 密钥文件尝试设为 `0600`（仅所有者可读写）
- `.gitleaks.toml` 配置跳过 `container/_bundle/`、`docs/`、`vendor/` 目录的扫描

### 9.2 开发中的安全注意事项

- **绝对不要**在代码、注释、commit message 中包含真实 API Key
- 测试中使用的密钥必须使用明确的测试占位符（如 `test-key-placeholder`）
- `src/aisc/adapters/secret_store.py` 实现了严格的 TOCTOU-safe 目录/文件创建（POSIX `O_NOFOLLOW` + `dir_fd`，Windows `CreateFileW` + handle 验证）
- Gitleaks 扫描在 CI 中运行（continue-on-error，不阻塞），但本地提交前应确保不泄露密钥

### 9.3 容器安全边界

- 容器默认以 `--dangerously-skip-permissions` 运行（跳过 Claude Code 权限确认）
- 容器以 `root` 用户运行，并设置 `IS_SANDBOX=1`
- 代理模式（`--network proxy` / `--profile proxy`）需要 `--cap-add=NET_ADMIN` 和 `/dev/net/tun`
- 这些是为开发便利做的取舍，**不构成生产安全声明**

---

## 10. 文档与设计决策

### 10.1 设计文档位置

| 目录 | 内容 |
|------|------|
| `docs/adr/` | 架构决策记录（当前: `001-python-stdlib-cli.md` — 使用 stdlib 而非 Click/argparse 扩展） |
| `docs/rfc/` | RFC（当前: `aisc-cli-v1.md` — CLI 的 JSON envelope / JSONL 协议） |
| `docs/plans/` | 开发计划（启动器重构、Mihomo TUN、统一 CLI 等） |
| `docs/devlog.md` | 开发日志（历史记录） |

### 10.2 关键设计决策

| 决策 | 位置 | 要点 |
|------|------|------|
| Python stdlib CLI | `docs/adr/001-python-stdlib-cli.md` | 不引入 Click/rich/typer，使用 argparse + 自定义输出格式化 |
| JSON Envelope 协议 | `docs/rfc/aisc-cli-v1.md` | 所有 `--format json` 输出使用固定结构的 JSON envelope |
| JSONL 事件流 | `docs/rfc/aisc-cli-v1.md` | `build`/`run` 的 `--events` 输出 RFC §3 格式的 JSONL |
| Skill 锁 v2 | `src/aisc/domain/skill_models.py` | 每 Skill 记录的 SHA-256 校验和 + 完整文件清单 |
| 双入口逐步统一 | `docs/plans/PLAN-p3-unified-cli.md` | Shell 启动器保持稳定，新功能优先 Python CLI |

### 10.3 文档编写规范

- 在 `README.md` 中引用真实存在的文件路径
- 修改 `README.md` 或 `providers.json` 后运行 `bash tools/check-docs.sh`
- 设计决策文档放入 `docs/adr/`（使用数字前缀命名）

---

## 11. 提交前检查

### 必须通过

```bash
# 1. 语法检查
bash tests/smoke/check-syntax.sh

# 2. Python 单元测试
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v

# 3. git diff 格式检查（无空白错误）
git diff --check

# 4. 暂存前确认不包含敏感文件
git status
```

### 修改特定区域后的额外检查

| 修改区域 | 额外检查 |
|---------|---------|
| `VERSION` 或 `src/aisc/__init__.py` | 确认两者一致；检查 `config/versions.env` 中 `AISC_VERSION` |
| `README.md` | `bash tools/check-docs.sh` |
| `container/providers.json` | `bash tools/check-docs.sh`；验证 `scripts/` 中是否有硬编码引用 |
| `container/` 下任意文件 | `bash tools/vendor-refresh.sh && bash tools/vendor-verify.sh` |
| `container/_bundle/` 来源文件 | `bash tools/stage-skills.sh`（从宿主机重新构建） |
| `skills-lock.json` 格式 | `aisc skill check` |
| Dockerfile 或依赖版本 | `config/versions.env` 同步更新 |
| 新增 `.sh` / `.py` / `.js` 文件 | 确认被 `check-syntax.sh` 覆盖 |
| Shell 启动器脚本 | `bash -n start.sh && bash -n scripts/*.sh` |

### Gitleaks 扫描（可选）

```bash
# 本地密钥扫描
gitleaks detect --config .gitleaks.toml --source .
```

---

## 12. 关键文件索引

### A. 按“我要改什么”索引

| 要改什么 | 从哪里开始 | 关联文件 | 最低验证 |
|---------|----------|---------|---------|
| 新增 CLI 子命令 | `src/aisc/cli/main.py` | `cli/commands/` 下新文件、`output.py`（如需新格式） | `unittest` + 手动 `aisc <cmd> --format json` |
| 修改模型切换逻辑 | `container/claude-switch` | `container/providers.json`、`entrypoint.sh` 中 env 注入 | 容器内 `cs deepseek` |
| 新增 Provider | `container/providers.json` | `container/claude-switch`、`tools/check-docs.sh` | `aisc provider list --format json` |
| 修改容器入口逻辑 | `container/entrypoint.sh` | `container/claude-wrapper`、`container/lib/` | Docker 构建 + 启动测试 |
| 修改 PyInstaller 打包 | `packaging/pyinstaller/entrypoint.py` | `packaging/artifact.py`、`.github/workflows/artifact.yml` | `artifact.py build-onefile` |
| 维护 Vendored 资源 | `tools/vendor-refresh.sh` | `vendor/checksums.txt`、`vendor/manifest.json` | `tools/vendor-verify.sh` |

### B. 按文件类型索引

| 类型 | 关键文件 |
|------|---------|
| **版本号** | `VERSION`, `src/aisc/__init__.py`, `config/versions.env` |
| **入口点** | `src/aisc/cli/main.py` (CLI), `start.sh` (用户启动器), `container/entrypoint.sh` (容器) |
| **数据模型** | `src/aisc/domain/models.py`, `src/aisc/domain/config.py`, `src/aisc/domain/skill_models.py` |
| **I/O 适配器** | `src/aisc/adapters/docker_.py`, `src/aisc/adapters/github_client.py`, `src/aisc/adapters/config_source.py`, `src/aisc/adapters/state_file.py` |
| **安全** | `src/aisc/adapters/secret_store.py`, `src/aisc/adapters/config_reader.py`, `.gitleaks.toml` |
| **容器定义** | `container/Dockerfile`, `container/entrypoint.sh`, `container/claude-switch`, `container/providers.json` |
| **CI** | `.github/workflows/checks.yml`, `.github/workflows/artifact.yml`, `.github/workflows/docker-smoke.yml` |
| **打包** | `packaging/artifact.py`, `packaging/ci_smoke.py`, `packaging/pyinstaller/` |
| **维护工具** | `tools/stage-skills.sh`, `tools/stage-mihomo.sh`, `tools/vendor-refresh.sh`, `tools/vendor-verify.sh`, `tools/check-docs.sh` |
| **测试** | `tests/unit/`, `tests/integration/`, `tests/smoke/`, `tests/harness/` |
| **设计文档** | `docs/adr/`, `docs/rfc/`, `docs/plans/` |
