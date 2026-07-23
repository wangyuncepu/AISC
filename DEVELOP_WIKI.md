# AISC 开发者手册

> **面向版本**：`v2.1.3` / `main` 分支。本文描述当前仓库实际实现的行为。

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

# 2. 使用 main 分支
git checkout main

# 3. 创建虚拟环境并安装（editable 模式）
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .

# 4. 验证安装（输出应与 VERSION 一致）
aisc version

# 5. 检查宿主机环境
aisc doctor

# 6. 运行当前完整 unittest（无需 Docker）
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v

# 7. 文档与 vendored 资源检查
bash tools/check-docs.sh
bash tools/vendor-verify.sh
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

以上步骤 6 已运行当前仓库全部 unittest。容器改动还应执行 Docker 镜像构建和 cc-switch 运行时验证。

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
│  ┌───────────────────────────────────────┐    │
│  │  Python CLI (aisc)                    │    │
│  │  src/aisc/cli/main.py                 │    │
│  │  宿主机唯一入口，提供全部管理子命令       │    │
│  └──────────────────┬────────────────────┘    │
│                     │ Docker CLI              │
│                     ▼                         │
│  ┌─────────────────────────────────────┐      │
│  │  Docker 容器 (super-claude:latest)   │      │
│  │  ┌────────────┐ ┌──────────────┐    │      │
│  │  │ cc-switch  │ │ entrypoint.sh│    │      │
│  │  │ daemon/TUI │ │ CLI wrappers │    │      │
│  │  │ SQLite     │ │ skills sync  │    │      │
│  │  └────────────┘ └──────────────┘    │      │
│  └─────────────────────────────────────┘      │
└─────────────────────────────────────────────┘
```

### 3.2 单一宿主入口

| 入口 | 运行位置 | 目标 | 当前状态 |
|------|---------|------|---------|
| `aisc` Python CLI | 宿主机 | 构建镜像、运行和管理容器 | 唯一受支持入口 |

`start.sh`、`start.command`、`start.bat` 及其 Shell/PowerShell 流水线已经移除。所有宿主机能力统一通过 `aisc` 子命令提供，容器状态保存在 `.aisc/state.env`。

### 3.3 Python 包分层

```
src/aisc/
├── __init__.py          # 从根目录 VERSION 解析 __version__
├── cli/                 # 表现层：argparse、输出格式化、命令分发
│   ├── main.py          # CLI 入口、参数解析、命令路由
│   ├── output.py        # JSON envelope、JSONL emitter、文本格式化
│   └── commands/        # 每个子命令的具体实现
│       ├── build.py
│       ├── run.py       # --keep-alive: 后台模式 + docker attach
│       ├── config.py
│       ├── profile.py
│       ├── container.py
├── application/         # 应用服务层：业务逻辑编排
│   ├── version.py       # 版本信息收集
│   ├── doctor.py        # 宿主机环境诊断
│   ├── config_service.py # 配置校验/合并（只读）
│   ├── profile_service.py
│   └── resources.py     # AISC 根目录发现
├── domain/              # 领域模型：纯数据，零 I/O
│   ├── models.py        # VersionInfo、DoctorReport、BuildPlan、RunPlan
│   └── config.py        # PathPolicy、SchemaIssue
├── adapters/            # 适配器：所有 I/O 和外部调用
│   ├── docker_.py       # DockerExecutor（Real + Fake）
│   ├── config_reader.py # 安全的配置读取（POSIX/Windows）
│   ├── state_file.py    # .aisc/state.env 读写
│   └── system.py        # ProcessRunner
└── schemas/             # 配置 schema 校验
    └── config_schema.py
```

**依赖方向**: `cli → application → domain ← adapters`。`domain` 无任何外部依赖。

### 3.4 测试架构

```
tests/
├── test_cc_switch_runtime.py  # cc-switch/容器契约
├── test_version_source.py     # VERSION 单一事实源
└── packaging/
    ├── test_artifact.py
    ├── test_macos_installer.py
    └── test_windows_installer.py
```

### 3.5 容器运行模型

```
docker run --rm \
  -v $(pwd):/root/app \          # 工作区挂载
  -e CLAUDE_SCOPE=project \     # 配置作用域
  super-claude:latest

容器内：
  /root/
  └── app/               # 挂载的工作区
  │   ├── .claude/       # 项目作用域（持久化）
  │   ├── .codex/        # Codex 项目配置
  │   └── .cc-switch/    # Provider/路由/skills 的唯一管理状态
```

---

## 4. 仓库地图

```
AISC/                          # 仓库根（也是 AISC 安装根目录）
├── VERSION                    # 项目版本唯一事实源
├── pyproject.toml             # Python 包元数据
├── README.md                  # 用户手册
├── DEVELOP_WIKI.md            # 本文档
├── LICENSE                    # MIT
├── .gitignore
├── .gitleaks.toml             # 密钥扫描配置
├── .dockerignore
├── .gitattributes             # 跨平台换行符策略
│
├── src/aisc/                  # Python CLI 源码
│   ├── __init__.py            # VERSION 运行时解析
│   ├── cli/                   # CLI 入口 + 表现层
│   ├── application/           # 应用服务
│   ├── domain/                # 领域模型
│   ├── adapters/              # I/O 适配器
│   └── schemas/               # 配置 schema
│
├── container/                 # Docker 镜像构建输入
│   ├── Dockerfile             # 镜像定义
│   ├── entrypoint.sh          # 容器入口脚本
│   ├── cc-switch-wrapper      # cc-switch 作用域包装器
│   ├── cc-switch-skills/      # 离线内置 skills
│   ├── claude-wrapper         # Claude CLI 包装器
│   ├── claude-settings.json   # 默认 Claude CLI 设置
│   ├── global-claude.md       # 全局 CLAUDE.md
│   ├── commands/              # 斜杠命令（gstack 等）
│   ├── lib/                   # 共享 bash 库
│   ├── _bundle/               # 构建期暂存的 skills/plugins（纳入 git）
│   └── downloads/             # 预下载的 mihomo/geodata（纳入 git）
│
├── config/
│   └── versions.env           # 外部依赖版本 pin（CLAUDE_CODE_VERSION 等）
│
├── tools/                     # 维护脚本
│   ├── stage-skills.sh        # 从宿主机暂存 plugins/skills 到 _bundle
│   ├── stage-skills-cleanup.sh # _bundle 清理辅助
│   ├── stage-mihomo.sh        # 预下载 mihomo + geodata
│   ├── vendor-refresh.sh      # 刷新 vendored artifacts + 重新生成校验和
│   ├── vendor-verify.sh       # 校验 vendor/checksums.txt
│   └── check-docs.sh          # 文档一致性检查
│
├── scripts/
│   └── demo/                  # CLI 演示脚本
│
├── tests/                     # 测试
│   ├── test_cc_switch_runtime.py
│   ├── test_version_source.py
│   └── packaging/
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
├── .github/workflows/         # CI 定义
│   └── artifact.yml           # PyInstaller 跨平台构建
│
├── docs/                      # 设计文档
│   ├── adr/                   # 架构决策记录
│   ├── rfc/                   # RFC
│   ├── plans/                 # 开发计划
│   └── testing/               # 测试文档
│
└── .aisc/                     # 运行时状态（gitignored）
    └── state.env              # 容器名发现（aisc CLI 写入）
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
# 全部 unittest
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v

# 手动快速冒烟
aisc version --format json | python3 -m json.tool
```

### 5.2 修改 cc-switch Provider / Skills 系统

**入口文件**:
- `container/entrypoint.sh` — daemon、Provider 路由初始化及 skills 同步
- `container/cc_switch_skills.py` — bundle 哈希、目标完整性检查与按需同步
- `container/cc-switch-wrapper` — 按项目/临时作用域设置 cc-switch HOME
- `container/cc-switch-skills/` — 镜像离线 skill 元数据
- `container/Dockerfile` — cc-switch 二进制和 skill 内容装配

**调用链**:
```
entrypoint → cc-switch daemon readiness → 初始化 Codex 当前 Provider → best-effort 启用 Claude/Codex 路由
镜像 /opt/aisc/skills + bundle 哈希 → auto 判断 → 必要时登记/Copy sync → .claude/.codex
交互启动菜单 4 → exec cc-switch → 项目作用域管理 TUI
```

Provider 和认证信息只由 cc-switch 管理。AISC 不再维护独立 Provider 目录、密钥目录或第二套快捷切换脚本。

`AISC_SKILLS_SYNC` 支持 `auto`（默认）、`always`、`off`。`auto` 通过构建期 bundle 哈希、SQLite 登记状态和已启用目标目录决定是否同步；已有记录只更新元数据，不修改 `enabled_claude` / `enabled_codex`。因此用户在 cc-switch 中停用 skill 后，容器重启不会重新启用。

正常情况下同步使用 `.cc-switch/.aisc-bundled-skills.lock` 的 `flock` 串行化。若 Windows/Docker Desktop 绑定挂载不支持该锁，则在确认确实需要同步后进入保护性降级：`.cc-switch/skills` 是 cc-switch Skills 源目录，并同时检查 `.claude/skills`、`.codex/skills` 两个目标目录。三者全不存在时以排他 `mkdir` 认领首次安装；任一存在或仅部分存在时显示 `[y/N]`，非交互和空输入均跳过且不更新 bundle 标记。`always` 不绕过该确认。

注意：cc-switch 的“路由已启用”只表示本地代理接管成功，不证明 Provider 已有可用凭据或上游地址。排障时必须分别检查 `daemon status`、`provider current` 和 `proxy show`。caveman 等 skill 只影响 agent 指令，不参与网络路由。

**最低验证命令**:
```bash
PYTHONPATH=src python3 -m unittest tests.test_cc_switch_runtime -v
bash tools/check-docs.sh
```

### 5.3 修改 Docker 镜像 / 容器

**入口文件**:
- `container/Dockerfile` — 镜像定义
- `container/entrypoint.sh` — 容器启动入口
- `container/claude-wrapper` — Claude CLI 包装器
- `container/cc-switch-wrapper` — cc-switch 作用域包装器
- `src/aisc/adapters/docker_.py` — Docker 操作适配器
- `src/aisc/cli/commands/build.py`, `run.py` — 构建/运行命令

**调用链**:
```
aisc build → plan_build() → RealDockerExecutor.run_streaming(["docker", "build", ...])
aisc run   → plan_run()   → RealDockerExecutor.run_streaming(["docker", "run", ...])
容器启动   → entrypoint.sh → 选择作用域 → 配置 TUN/简讯 → 菜单默认进入 bash
```

**容易漏改的关联文件**:
- `.dockerignore` — 修改 COPY 源时需要更新
- `config/versions.env` — 修改外部依赖版本时同步更新
- `src/aisc/domain/models.py` — BuildPlan / RunPlan 的 `docker_argv` 属性
- `container/lib/` — 共享 bash 库
- 测试：当前完整 unittest；容器接线另跑 `tests.test_cc_switch_runtime`

**最低验证命令**:
```bash
# dry-run（不需要 Docker daemon）
aisc build --dry-run
aisc build --dry-run --format json

# 完整构建（需要 Docker）
aisc build --no-cache
```

### 5.4 维护构建资源（tools/stage-\* / tools/vendor-\*）

**工具清单及用途**:

| 工具 | 用途 | 何时运行 |
|------|------|---------|
| `tools/stage-skills.sh` | 从宿主机 `~/.claude` 暂存 plugins + skills 到 `container/_bundle/` | 更新内置 plugin/skill 版本后 |
| `tools/stage-skills-cleanup.sh` | `stage-skills.sh` 调用的内部清理脚本 | 仅被 `stage-skills.sh` 调用 |
| `tools/stage-mihomo.sh` | 预下载 mihomo 二进制 + geodata 到 `container/downloads/` | 更新 mihomo 版本需要离线/弱网构建时 |
| `tools/vendor-refresh.sh` | 重新生成 `vendor/checksums.txt` 并验证 `container/downloads/` | 修改容器内任何文件后 |
| `tools/vendor-verify.sh` | 校验 `vendor/checksums.txt` 完整性 | 提交前验证 |
| `tools/check-docs.sh` | 文档路径与 cc-switch 内置 skills 一致性检查 | 修改 README 或内置 skills 后 |

**工作流示例**（更新内置 plugin 后）:
```bash
bash tools/stage-skills.sh       # 重新暂存 plugins/gstack
bash tools/vendor-refresh.sh     # 更新校验和
bash tools/vendor-verify.sh      # 验证
find container tools -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

`.gitattributes` 对 vendored 文本和脚本规定稳定的 checkout 行尾。不要把整个 `container/` 强制转换成另一种行尾；Windows runner 的 artifact stage 会直接校验 `vendor/checksums.txt`，行尾漂移会表现为大批 hash mismatch。

---

## 6. 状态、配置与兼容性契约

### 6.1 版本号单一事实源

项目版本只在仓库根目录 `VERSION` 中声明。修改该文件即可完成版本更新：

- `src/aisc/__init__.py` 在源码运行时读取根目录 `VERSION`。
- PyInstaller 构建通过 `--add-data VERSION:.` 嵌入同一文件，冻结程序从 `_MEIPASS/VERSION` 读取。
- setuptools 将根 `VERSION` 作为 data-file 原样装入 wheel，安装后的包从安装前缀下的 `aisc/VERSION` 读取；包元数据仅作最后兜底。
- `packaging/artifact.py`、CI、安装包命名和 bundle manifest 均直接读取 `VERSION`。
- `config/versions.env` 只维护外部依赖，不再重复声明 `AISC_VERSION`。

**发版清单**：只修改 `VERSION`，再运行完整测试、artifact stage/verify 和 PyInstaller 版本 smoke。

### 6.2 外部依赖版本 Pin

**事实源**: `config/versions.env`

| 变量 | 当前值 | 说明 |
|------|-------|------|
| `MIHOMO_VERSION` | `v1.19.27` | 容器内 TUN 透明代理核心 |
| `CC_SWITCH_VERSION` | `v5.9.0` | cc-switch-cli Rust 二进制 |
| `CLAUDE_CODE_VERSION` | `latest` | Claude Code npm 包（**TODO: pin 到具体版本**） |
| `GEODATA_VERSION` | `latest` | Geo 数据版本（**TODO: pin 到具体日期标签**） |
| `NODE_IMAGE` | `node:20-slim` | Node.js 基础镜像 |

### 6.3 运行时状态契约

- 工作区 `.cc-switch/` 是容器内 Provider、路由和 skills 的唯一管理状态。
- `.cc-switch/.aisc-bundled-skills.sha256` 记录最近一次成功同步的内置 bundle；同步失败不更新该标记，下次启动会重试。
- 容器交互启动菜单提供 bash、Claude、Codex、cc-switch 四个入口；第 4 项通过现有 wrapper 打开项目作用域管理 TUI。
- AISC 根目录 `.aisc/state.env` 只保存容器发现信息，不保存 Provider 或认证数据。
- `.deploy/state.env` 是历史容器状态路径，只读兼容，不写入新数据。

### 6.4 Profile 安全控制

- `aisc profile list` / `aisc profile show [safe|unsafe]` 可**只读查看**
- `safe` / `unsafe` Profile **尚未**接入 `aisc run` 的安全控制
- `aisc run --profile proxy` 仅是 `--network proxy` 的兼容别名，**不是安全 Profile**

---

## 7. 测试策略

### 7.1 测试框架与约定

- **框架**: Python stdlib `unittest`（**不是 pytest**）
- **运行命令**: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`
- **CI 执行**: `.github/workflows/artifact.yml` 运行 packaging 测试；提交前本地运行全部测试
- **不使用** pytest 特性（fixtures、parametrize、conftest 等）

### 7.2 测试类别

| 类别 | 位置 | 运行条件 | 命令 |
|------|------|---------|------|
| 运行时契约 | `tests/test_cc_switch_runtime.py` | 静态测试无需 Docker；部分用例在 Docker 可用时运行 | `PYTHONPATH=src python3 -m unittest tests.test_cc_switch_runtime -v` |
| 版本契约 | `tests/test_version_source.py` | 纯 Python | `PYTHONPATH=src python3 -m unittest tests.test_version_source -v` |
| 打包与安装器 | `tests/packaging/` | 纯 Python；实际 PyInstaller smoke 另跑 | `PYTHONPATH=src python3 -m unittest discover -s tests/packaging -p 'test_*.py' -v` |

### 7.3 测试工具

- `src/aisc/adapters/docker_.py` 中的 `FakeDockerExecutor` 用于无 Docker 守护进程测试。
- `packaging/artifact.py` 的测试使用临时目录生成最小 bundle/archive，避免污染仓库。

### 7.4 编写新测试

```python
# tests/test_my_feature.py
import unittest
from pathlib import Path

class MyFeatureTest(unittest.TestCase):
    def test_something(self):
        result = my_function()
        self.assertEqual(result, expected_value)

if __name__ == "__main__":
    unittest.main()
```

- 位于 `tests/` 下并匹配 `test_*.py` 的测试文件自动被 discover 发现
- 不需要 `__init__.py` 中的显式导入

---

## 8. 打包、CI 与发布

### 8.1 CI 流水线

**Artifact** (`.github/workflows/artifact.yml`) — `develop` push、面向 `main` 的 PR、`v*` tag 或手动触发：
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
- 标签构建的聚合 Job：校验所有平台产物、生成 `SHA256SUMS`
- Release Job：将聚合产物上传到对应 GitHub Release；`*-dev` 标签标记为 Pre-release，其余标签发布为稳定 Release

当前仓库只保留这一份 GitHub Actions workflow；本地完整测试、文档检查、vendor 校验和 Docker 构建仍需在提交前显式运行。

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

### 8.3 版本来源检查

打包脚本 `packaging/artifact.py` 在 `stage` 命令中直接读取 `VERSION`。Python 包在源码模式读取同一文件，PyInstaller 构建则把该文件嵌入可执行程序，不再维护需要手工同步的第二份版本字面量。

CI 的 artifact smoke（`ci_smoke.py`）会进一步验证构建产物运行 `aisc version --format json` 输出的 `cli_version` 与 bundle 中的 `VERSION` 一致。

### 8.4 发布步骤与边界

`.github/workflows/artifact.yml` 是当前唯一发布入口。推送 `v*` 标签会构建三平台产物、聚合 `SHA256SUMS`，再由 `softprops/action-gh-release` 创建或更新 GitHub Release。版本带 `-dev` 时发布为 Pre-release；例如 `v2.1.3` 是稳定 Release。

维护者发布流程：

```bash
# 1. 只修改根目录 VERSION，并确保 docs/devlog.md 严格按新到旧排列

# 2. 完整测试、文档与 vendored 资源校验
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tools/check-docs.sh
bash tools/vendor-verify.sh
python3 packaging/artifact.py stage --output /tmp/aisc-staging
python3 packaging/artifact.py verify --bundle /tmp/aisc-staging/aisc-bundle

# 3. 提交 VERSION 与发布文档

# 4. 创建并推送 tag（VERSION 不含前导 v）
VERSION_VALUE="$(head -1 VERSION)"
git tag -a "v${VERSION_VALUE}" -m "Release v${VERSION_VALUE}"
git push origin main
git push origin "v${VERSION_VALUE}"

# 5. 在 GitHub Actions 中等待 Artifact workflow 全部通过
# 6. 核对 Release 的平台产物、安装器、SHA256 sidecar 与 SHA256SUMS
```

**故障定位层次**（CI 失败时按此顺序排查）：
1. **单元测试失败** — 先在本地用相同测试命令复现
2. **Artifact 失败** — 检查 PyInstaller 入口、`VERSION` 嵌入和 bundle 路径
3. **Docker 构建失败** — 检查 `container/Dockerfile`、`.dockerignore` 与 vendored 资源
4. **跨平台不一致** — 检查平台特定路径处理（`sys.platform` 分支、Windows `\\` vs POSIX `/`）

**边界**：
- 自动发布只在 tag workflow 全部成功后发生；只推 `main` 不会创建 Release
- 不允许覆盖已存在的发布标签，也不使用 force-push
- 本文不规定 tag 签名策略

---

## 9. 安全与敏感数据

### 9.1 Provider 认证边界

- Provider 认证信息由 cc-switch 管理；AISC 不创建、读取或迁移独立密钥文件。
- `.gitleaks.toml` 继续用于阻止真实 API Key 被提交到仓库。

### 9.2 开发中的安全注意事项

- **绝对不要**在代码、注释、commit message 中包含真实 API Key
- 测试中使用的密钥必须使用明确的测试占位符（如 `test-key-placeholder`）
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
| Skills 单一管理入口 | `container/entrypoint.sh` | cc-switch 登记、同步并管理 Claude/Codex skills |
| 宿主入口统一 | `docs/plans/PLAN-p3-unified-cli.md` | 历史方案保留；当前仅支持 Python CLI |

### 10.3 文档编写规范

- 在 `README.md` 中引用真实存在的文件路径
- 修改 `README.md` 或 cc-switch 内置 skills 后运行 `bash tools/check-docs.sh`
- 设计决策文档放入 `docs/adr/`（使用数字前缀命名）

---

## 11. 提交前检查

### 必须通过

```bash
# 1. 语法检查
python3 -m compileall -q src packaging
find container tools packaging -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n

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
| `VERSION` 或 `src/aisc/__init__.py` | `PYTHONPATH=src python3 -m aisc version`；PyInstaller 版本 smoke |
| `README.md` | `bash tools/check-docs.sh` |
| `container/cc-switch-skills/` | `bash tools/check-docs.sh`；运行 cc-switch runtime 测试 |
| `container/` 下任意文件 | `bash tools/vendor-refresh.sh && bash tools/vendor-verify.sh` |
| `container/_bundle/` 来源文件 | `bash tools/stage-skills.sh`（从宿主机重新构建） |
| Dockerfile 或依赖版本 | `config/versions.env` 同步更新 |
| 新增 `.sh` / `.py` 文件 | 运行对应 `bash -n` / `compileall` |

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
| 新增 CLI 子命令 | `src/aisc/cli/main.py` | `src/aisc/cli/commands/` 下新文件、`output.py`（如需新格式） | `unittest` + 手动 `aisc <cmd> --format json` |
| 修改模型切换逻辑 | `container/entrypoint.sh` | `container/cc-switch-wrapper` | 容器内 `cc-switch proxy show` |
| 新增内置 Skill | `container/cc-switch-skills/` | `container/Dockerfile`、`tools/check-docs.sh` | `cc-switch skills list` |
| 修改容器入口逻辑 | `container/entrypoint.sh` | `container/claude-wrapper`、`container/lib/` | Docker 构建 + 启动测试 |
| 修改 PyInstaller 打包 | `packaging/pyinstaller/entrypoint.py` | `packaging/artifact.py`、`.github/workflows/artifact.yml` | `artifact.py build-onefile` |
| 维护 Vendored 资源 | `tools/vendor-refresh.sh` | `vendor/checksums.txt`、`vendor/manifest.json` | `tools/vendor-verify.sh` |

### B. 按文件类型索引

| 类型 | 关键文件 |
|------|---------|
| **版本号** | `VERSION`（唯一事实源）, `src/aisc/__init__.py`（解析器） |
| **入口点** | `src/aisc/cli/main.py` (宿主 CLI), `container/entrypoint.sh` (容器) |
| **数据模型** | `src/aisc/domain/models.py`, `src/aisc/domain/config.py` |
| **I/O 适配器** | `src/aisc/adapters/docker_.py`, `src/aisc/adapters/state_file.py` |
| **安全** | `src/aisc/adapters/config_reader.py`, `.gitleaks.toml` |
| **容器定义** | `container/Dockerfile`, `container/entrypoint.sh`, `container/cc-switch-wrapper`, `container/cc-switch-skills/` |
| **CI** | `.github/workflows/artifact.yml` |
| **打包** | `packaging/artifact.py`, `packaging/ci_smoke.py`, `packaging/pyinstaller/` |
| **维护工具** | `tools/stage-skills.sh`, `tools/stage-mihomo.sh`, `tools/vendor-refresh.sh`, `tools/vendor-verify.sh`, `tools/check-docs.sh` |
| **测试** | `tests/test_cc_switch_runtime.py`, `tests/test_version_source.py`, `tests/packaging/` |
| **设计文档** | `docs/adr/`, `docs/rfc/`, `docs/plans/` |
