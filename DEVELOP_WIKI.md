# AISC 开发者手册

> **开发基线：** `develop` 分支，项目版本 `v2.1.4`，状态 Alpha。本文以当前源码、脚本、测试和 `.github/workflows/artifact.yml` 为准；用户安装与命令教程见 `README.md`。

## 1. 分支与发布角色

| 引用 | 角色 | 自动化 |
| --- | --- | --- |
| `develop` | 当前日常开发和集成基线；功能、修复、文档先在这里验证 | push 触发 Artifact 跨平台构建 |
| `main` | 面向发布的稳定线；通过 PR 接收已验证变更 | 目标为 `main` 的 PR 触发 Artifact 构建 |
| `v*` tag | 不可变发布标识，标签内容应与根 `VERSION` 和 Release Notes 一致 | push tag 构建、聚合并发布 GitHub Release |

不要把三者混成同一种工作流：开发基于 `develop`，发布候选通过 PR 进入 `main`，发布 tag 指向已审核的发布提交。普通 push 到 `main` 不在当前 workflow 的分支触发列表中，也不会创建 Release；只有 `v*` tag 会进入 aggregate 和 release jobs。

当前开发环境无需也不应为了日常贡献切换到 `main`。开始工作前确认：

```bash
git branch --show-current
git status --short
```

## 2. 开发环境

### 2.1 前提

- Python 3.11 或更高版本；CI 当前使用 Python 3.12。
- Git。
- Docker CLI 和 daemon；纯 Python 单元测试不需要 Docker，镜像和容器验证需要。
- 可选：uv，用于隔离安装或复现用户的源码安装方式。
- 打包验证需要 PyInstaller 6.21.0；Windows setup 还需要 Inno Setup，macOS PKG 需要系统打包工具。

### 2.2 本地安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

项目声明 `requires-python = ">=3.11"`，console script 只有 `aisc = aisc.cli.main:main`。`python -m aisc` 可用于源码级调试，但面向用户的唯一宿主入口是 `aisc`。

如果命令命中了旧安装：

```bash
command -v aisc
python3 -c "import aisc; print(aisc.__file__)"
.venv/bin/aisc version
```

不要为了排查路径问题盲目卸载系统中其他 AISC 安装；先明确当前 shell、虚拟环境和 executable 的来源。

## 3. 快速验证

最小无 Docker 验证：

```bash
PYTHONPATH=src python3 -m aisc version
PYTHONPATH=src python3 -m aisc build --dry-run
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
git diff --check
```

资源和文档验证：

```bash
bash tools/vendor-verify.sh
bash tools/check-docs.sh
```

`tools/check-docs.sh` 的 Markdown 扫描未排除 `.slim/worktrees/`。如果本地存在该目录，历史或临时 worktree 中的文档可能造成误报；应把它与当前工作树的真实文档问题区分，不要为了规避误报修改脚本或扫描到的临时副本。

涉及镜像或 entrypoint 时再执行：

```bash
aisc build --no-cache
aisc run
```

## 4. 架构与调用链

### 4.1 总体运行模型

```text
宿主机
  aisc (argparse CLI)
    -> application services / plans
    -> adapters (filesystem, subprocess, Docker)
    -> docker build / run / inspect / exec
         |
         v
Docker 容器，以 root 运行
  entrypoint.sh
    -> 选择 temporary/project 作用域
    -> 初始化 Claude/Codex/cc-switch 目录
    -> 启动 cc-switch daemon
    -> 初始化 Provider 与同步 Skills
    -> 可选启动 Mihomo TUN
    -> exec bash / claude / codex / cc-switch
```

宿主侧没有第二套受支持启动器。不要恢复或宣传历史 launcher、快捷切换命令或独立 Provider 文件；所有宿主管理由 `aisc` 提供，Provider/凭据由容器内 cc-switch 管理。

### 4.2 Python CLI 分层

```text
src/aisc/
  cli/
    main.py                 argparse、全局协议、命令分发
    output.py               text、JSON envelope、JSONL emitter
    commands/
      build.py              BuildPlan 编排与 Docker 执行
      run.py                RunPlan、registry 登记与 Docker 执行
      container.py          ps/status/stop/restart/shell/switch
      config.py             配置命令表现层
      profile.py            Profile 命令表现层
      wizard.py             交互式 build 向导
  application/
    resources.py            AISC root 发现
    version.py              版本信息聚合
    doctor.py               宿主诊断
    config_service.py       配置安全读取、合并、来源追踪
    profile_service.py      只读 Profile 加载
  domain/
    models.py               结果、错误、BuildPlan、RunPlan
    config.py               配置领域类型
  adapters/
    docker_.py              Real/Fake DockerExecutor
    system.py               进程执行
    config_reader.py        POSIX 安全配置读取
    windows_config_reader.py Windows 路径读取辅助
    container_registry.py   多容器 registry
    state_file.py           有限 state.env 标志
  schemas/
    config_schema.py        AISC 配置 schema
```

主要依赖方向是 `cli -> application/domain -> adapters`。`domain` 中的计划对象负责稳定地产生 Docker argv；外部 I/O 应放在 adapter 或 application orchestration，不要在参数解析中散落 `subprocess` 调用。

### 4.3 命令调用链

```text
aisc build
  -> main._cmd_build
  -> resources.locate_aisc_root
  -> commands.build.plan_build
  -> BuildPlan.docker_argv
  -> DockerExecutor.preflight / inspect_image / run_*

aisc run
  -> main._cmd_run
  -> commands.run.plan_run
  -> RunPlan.docker_argv
  -> DockerExecutor preflight + image inspect
  -> container_registry.register
  -> docker run

aisc ps/status/stop/restart/shell/switch
  -> commands.container
  -> container_registry.resolve_target
  -> DockerExecutor inspect/stop/restart/exec
```

`build` 和 `run` 在文本模式流式输出 Docker 日志；JSON/events 模式捕获子进程输出并转发到 stderr，保持 stdout 的机器协议纯净。所有 Docker 调用应继续通过 `DockerExecutor`，以便用 Fake 实现测试。

### 4.4 AISC root 发现

`src/aisc/application/resources.py` 要求 root 包含：

```text
VERSION
container/Dockerfile
config/versions.env
```

发现顺序：显式 `--aisc-root`、`AISC_ROOT`、冻结 executable 旁的 `aisc-bundle/`、从 cwd 向上发现带 `.git` 的仓库、从 installed package 路径向上发现结构标记。显式路径、环境变量或已存在的 frozen bundle 结构错误时 fail closed；editable 安装依赖最后一类回退。

### 4.5 Docker 构建与运行

`aisc build` 从 `config/versions.env` 解析 `USE_CN_MIRROR`、`NODE_IMAGE`、`NODE_IMAGE_CN`，将选定 Node image 和镜像源标志传给：

```text
docker build -f container/Dockerfile -t <tag> <aisc-root>
```

其他依赖版本目前由 `container/Dockerfile` 的 ARG 默认值消费，维护者必须保持它们与 `config/versions.env` 同步。默认镜像为 `super-claude:latest`。

`aisc run` 默认生成：

```text
docker run --rm -it \
  -e TERM=xterm-256color \
  --name super-claude-station-<suffix> \
  -v <workspace>:/root/app \
  super-claude:latest
```

`--non-interactive` 去掉 TTY，增加 `AISC_NON_INTERACTIVE=1`、`CLAUDE_SCOPE=project` 并使用 DEVNULL stdin。`--keep-alive` 去掉 `--rm`；交互文本模式使用 `-d` 启动后 `docker attach --sig-proxy=true`。proxy 模式增加 `--cap-add=NET_ADMIN`、`--device /dev/net/tun`，并把 `<aisc-root>/.claude/mihomo/config.yaml` 只读挂载到 `/etc/mihomo/config.yaml`。

### 4.6 容器 entrypoint

`container/Dockerfile` 设置 `ENTRYPOINT ["entrypoint.sh"]` 和 `CMD ["claude"]`。`container/entrypoint.sh` 的关键顺序是：

1. 设置 UTF-8、`IS_SANDBOX=1`、终端能力，加载 `container/lib/` 对应的共享 Bash 库。
2. 根据 `CLI_SCOPE` 或兼容变量 `CLAUDE_SCOPE` 选择 temporary/project；无交互环境默认 project。
3. 初始化 `.claude`、`.codex` 和 `.cc-switch`，修正插件 bundle 中的作用域路径并确保可写。
4. 从 Claude `settings.json` 注入环境变量。
5. detach 启动 cc-switch daemon，最多等待约 10 秒可达。
6. 初始化 Codex 当前 Provider、增量同步 Skills，并 best-effort 启用 Claude 路由；Codex 路由保持关闭。
7. 若存在 `/etc/mihomo/config.yaml`，生成可写配置并以 root 启动 Mihomo TUN。
8. 可选运行 AI brief，然后将 PID 1 `exec` 给用户选择的进程。

`container/claude-wrapper` 每次启动重新注入 Claude env，并默认绕过权限确认。`container/codex-wrapper` 注入 Codex env，并默认绕过 approvals/sandbox/hook trust。用户显式给出相应权限参数时 wrapper 不重复追加。`container/cc-switch-wrapper` 通过当前作用域设置 `HOME`，使 Skills 目标与 temporary/project 一致。

## 5. 仓库地图

```text
AISC/
  VERSION                     项目版本唯一事实源
  README.md                   用户手册
  DEVELOP_WIKI.md             本手册
  pyproject.toml              Python 包和 console script
  container/
    Dockerfile                镜像定义
    entrypoint.sh             容器入口
    claude-wrapper            Claude 权限与 env 包装
    codex-wrapper             Codex 权限与 env 包装
    cc-switch-wrapper         cc-switch 作用域包装
    cc_switch_skills.py       Skills 增量同步与锁保护
    cc-switch-skills/         内置 Skills 元数据/内容
    lib/                      entrypoint 共享 Bash 库
    _bundle/                  手工维护的 vendored 插件和 Skills
    downloads/                Mihomo/geodata 本地构建资源
  config/versions.env         外部依赖与镜像变量
  src/aisc/                   宿主 Python CLI
  tests/                      unittest 测试
  packaging/
    artifact.py               stage/archive/verify/build/aggregate
    ci_smoke.py               frozen artifact 版本与布局 smoke
    pyinstaller/entrypoint.py PyInstaller 入口
    windows/                  Inno Setup 与 installer smoke
    macos/                    PKG 构建和手工测试说明
    install.*                 便携安装脚本
    uninstall.*               便携卸载脚本
  tools/
    check-docs.sh             文档与资源一致性检查
    stage-mihomo.sh           预下载 Mihomo/geodata
    vendor-refresh.sh         重建 container 文件校验和
    vendor-verify.sh          校验 vendor/checksums.txt
  vendor/                     manifest、checksums、第三方许可证
  docs/
    adr/                      架构决策
    rfc/                      CLI 协议
    plans/                    历史/实施计划，不替代当前源码
    releases/                 tag 对应 Release Notes
    devlog.md                 开发日志
  .github/workflows/artifact.yml
```

`container/_bundle/` 当前是手工维护资源。文档和流程只能引用仓库中真实存在的维护脚本；不要假设有额外的 Skills staging/cleanup 工具。

## 6. 常见修改流程

### 6.1 修改或新增宿主命令

1. 在 `src/aisc/cli/main.py` 注册 argparse parser 和 dispatch。
2. 将命令编排放到 `src/aisc/cli/commands/`，通用业务放到 `application/`，纯数据契约放到 `domain/`。
3. 外部进程、Docker 和文件系统边界使用现有 adapters；不要直接拼 shell 字符串。
4. 同步 text、JSON envelope、usage error 和 exit code 行为。
5. 添加 unittest，并更新 `README.md` 的完整 CLI 表。

最低验证：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH=src python3 -m aisc <command> --help
PYTHONPATH=src python3 -m aisc <command> --format json
```

如果命令是交互式的，不应声称支持 JSON。新增 events 必须遵守 `docs/rfc/aisc-cli-v1.md` 的 JSONL 终止事件约束。

### 6.2 修改 build/run

关键文件：

- `src/aisc/cli/commands/build.py`、`src/aisc/cli/commands/run.py`
- `src/aisc/domain/models.py`
- `src/aisc/adapters/docker_.py`
- `src/aisc/cli/output.py`
- `container/Dockerfile`、`.dockerignore`、`config/versions.env`

计划阶段应保持无 Docker 副作用；`--dry-run` 可验证本地路径和输出计划，但不能调用 daemon、写 registry 或创建工作区配置。新增参数时同时验证 text/json/events、interactive/non-interactive、direct/proxy、keep-alive 组合。

```bash
aisc build --dry-run
aisc build --dry-run --format json
aisc run --dry-run
aisc run --dry-run --format json
```

### 6.3 修改容器生命周期和多容器寻址

从 `src/aisc/cli/commands/container.py` 与 `src/aisc/adapters/container_registry.py` 开始。兼容契约包括：

- `run --label` 写 registry metadata，label 不等于 Docker label。
- `status/stop/restart/shell/switch` 都接受 `--name` 和 `--label`。
- 解析优先级为 name、唯一 label、default、唯一容器；歧义必须报错并列候选。
- registry 惰性 GC 在 daemon 不可达或权限不足时不得误删条目。
- `stop` 成功后 unregister；`status` 对 Docker 中不存在的容器返回 `exists=False`。
- registry 写入保持原子；POSIX 上用 lock file + `flock` 串行化。

测试应覆盖重复 label、损坏 JSON、并发/原子写入边界、Docker 不可达和 stale entry。

### 6.4 修改容器内容或 vendored 资源

当前真实工具：

| 命令 | 用途 | 注意 |
| --- | --- | --- |
| `bash tools/stage-mihomo.sh` | 把当前架构 Mihomo 和 geodata 下载到 `container/downloads/` | 需要网络，会写 vendored 文件 |
| `bash tools/vendor-refresh.sh --dry-run` | 预览 container 校验和刷新 | 不写文件 |
| `bash tools/vendor-refresh.sh` | 重建 `vendor/checksums.txt` | 会修改 checksum 文件，先核对目标资源 |
| `bash tools/vendor-verify.sh` | 用 SHA256 验证 container 文件 | 提交前运行 |
| `bash tools/check-docs.sh` | 检查 README 路径、内置 Skills、旧入口和过时术语 | 注意 `.slim/worktrees/` 已知扫描范围问题 |

修改 `container/` 下任何被校验文件后，都需要刷新并验证 checksums。`.gitattributes` 控制跨平台文本行尾；不要批量改变 vendored 文件换行，否则 Windows artifact stage 会出现大量 hash mismatch。

## 7. cc-switch、Provider 与 Skills 契约

### 7.1 Provider 和 daemon

工作区 `.cc-switch/` 是 Provider、凭据、路由、备份和 Skills 源状态的唯一管理根。AISC 不创建、读取或迁移另一套 Provider/密钥目录。

entrypoint 使用 `cc-switch daemon start --detach`，轮询 `daemon status`。daemon 可达后：

1. 若 Codex 没有当前 Provider，优先从 `$CODEX_CONFIG_DIR/config.toml` 执行 `provider import-live`。
2. 仍没有时 best-effort 切换到无用户凭据的内置 `codex-official`。
3. best-effort 执行 `cc-switch proxy -a claude enable`。
4. 明确不自动执行 Codex proxy enable，使 Codex 默认走官方直连和原生认证。

Claude 路由失败不阻断容器启动。路由 enabled 只说明本地代理接管，不证明 Provider 上游、模型和凭据可用。诊断必须分别检查 daemon、current provider 和 proxy。

宿主 `aisc switch` 的普通模式通过 scope-preserving Bash wrapper 打开 cc-switch TUI；quick 模式从 `/proc/1/environ` 逐项读取 `CLAUDE_CONFIG_DIR`、`CC_SWITCH_CONFIG_DIR`、`CODEX_CONFIG_DIR`、`CODEX_HOME`，不使用 `eval`，然后把 Provider 作为独立 argv 传给 Claude provider switch。读取失败时以 101 fail closed。

### 7.2 Skills 增量同步

入口是 `container/cc_switch_skills.py`，bundle 位于 `/opt/aisc/skills`。构建时 Dockerfile生成 `/opt/aisc/skills/.aisc-bundle.sha256`；运行时成功同步后在配置根记录 `.aisc-bundled-skills.sha256`。

`AISC_SKILLS_SYNC` 契约：

- `auto`：默认。bundle 标记匹配、登记和源存在、已启用目标完整时返回 `current`，不做复制或数据库写入。
- `always`：请求同步，但仍遵守锁降级保护。
- `off`：返回 `off`，不自动登记或同步。

已有记录仅刷新元数据，不覆盖 `enabled_claude`、`enabled_codex`。同步失败或用户拒绝时不更新成功标记，下一次启动可重试。

正常路径锁定 `.cc-switch/.aisc-bundled-skills.lock`。绑定挂载不支持 `flock` 时：

- `.cc-switch/skills`、`.claude/skills`、`.codex/skills` 全不存在，才以排他目录创建认领首次安装。
- 任一目录存在或部分存在，交互模式显示 `[y/N]`；空输入和非交互模式拒绝覆盖。
- `always` 不绕过确认。

修改该区域至少运行：

```bash
PYTHONPATH=src python3 -m unittest tests.test_cc_switch_runtime -v
bash tools/check-docs.sh
```

## 8. 配置、状态与兼容契约

### 8.1 配置读取与合并

AISC 配置只拥有 `schema_version` 和 `defaults.profile/network`，不拥有 Provider 或凭据。路径为：

| 层 | Linux | macOS | Windows |
| --- | --- | --- | --- |
| 用户 | `${XDG_CONFIG_HOME:-$HOME/.config}/aisc/config.json` | `$HOME/Library/Application Support/aisc/config.json` | `%APPDATA%\aisc\config.json` |
| 工作区 | `<workspace>/.aisc/config.json` | 同左 | 同左 |

有效值按内置默认 < 用户 < 工作区覆盖，provenance 记录每个字段来源。schema 当前为 1，Profile 允许 `safe|unsafe`，网络允许 `direct|proxy`。解析器要求 UTF-8 JSON object，拒绝 duplicate key，并限制 JSON 深度、节点数和字符串长度；安全读取层防止不可信 symlink/reparse 路径。

`config validate/effective/show` 当前只读。`defaults.profile` 和 `defaults.network` 不驱动 `aisc run`；`profile list/show` 也只读。`run --profile proxy` 只是网络兼容别名，与 `safe/unsafe` Profile 无关。

### 8.2 多容器 registry

当前容器运行时索引是 `<aisc-root>/.aisc/containers.json`：

```json
{
  "default": "super-claude-station-1234abcd",
  "containers": {
    "super-claude-station-1234abcd": {
      "image": "super-claude:latest",
      "workspace": "/work/project",
      "network": "direct",
      "label": "api",
      "created_at": 0
    }
  }
}
```

注册发生在 Docker run 之前、preflight 和 image inspect 成功之后，因此 Docker run 自身失败时可能留下条目，后续惰性 GC 会在确认容器不存在时清理。文件损坏时 reader 返回空结构；写入采用临时文件、fsync 和 replace。

### 8.3 state.env

当前状态路径只能写 `<aisc-root>/.aisc/state.env`。adapter 的 allowlist **仅**包含：

```text
DO_RUN=0|1
PROXY_ENABLED=0|1
```

容器名和镜像已迁移到 `containers.json`，不得再写入 `state.env`。值禁止空白、控制字符和 shell metacharacters；写入原子化并尽量保留注释。不要把历史目录描述成当前运行路径。

### 8.4 版本事实源

项目版本只修改根 `VERSION`：

- `src/aisc/__init__.py` 在源码/editable 模式读取它。
- setuptools 将 `VERSION` 作为 data-file 安装，包元数据仅作兜底。
- PyInstaller 使用 `--add-data VERSION:.` 嵌入 frozen executable。
- `packaging/artifact.py` 用它命名产物、生成 bundle manifest 并执行一致性保护。
- `packaging/ci_smoke.py` 比较 executable 的 `cli_version` 与期望版本。

不要在 Python、文档模板或构建脚本再维护第二份版本字面量。发版时版本变更只改 `VERSION`；Release Notes 文件名和 tag 从该值派生。

### 8.5 外部依赖与可复现性

`config/versions.env` 是外部依赖和镜像变量的声明位置：

| 变量 | v2.1.4 当前值 | 消费与风险 |
| --- | --- | --- |
| `NODE_IMAGE` | `node:20-slim` | CLI 在非国内镜像模式传给 Docker build |
| `NODE_IMAGE_CN` | `docker.1ms.run/library/node:20-slim` | `USE_CN_MIRROR=1` 时由 CLI 选择 |
| `NODE_IMAGE_DIGEST` | 空 | 已声明但 Dockerfile `FROM` 当前不消费；不能提供 digest 固定 |
| `CLAUDE_CODE_VERSION` | `latest` | Dockerfile 对应 ARG 默认值；未固定 |
| `CODEX_VERSION` | `latest` | Dockerfile 对应 ARG 默认值；未固定 |
| `MIHOMO_VERSION` | `v1.19.27` | Dockerfile ARG / 下载资源 |
| `GEODATA_VERSION` | `latest` | Dockerfile ARG；未固定 |
| `CC_SWITCH_VERSION` | `v5.9.0` | Dockerfile 下载 cc-switch binary |
| `USE_CN_MIRROR` | `1` | CLI build arg，选择 apt/npm/下载镜像路径 |
| `GH_PROXY` | 空 | Dockerfile 支持 build arg，但当前 `aisc build` 不从 env 文件转发它 |

`latest`、无 digest 的基础镜像以及 Dockerfile/config 默认值重复，意味着同一 Git commit 在不同时间构建不保证字节级一致。维护依赖时同时检查 `config/versions.env`、`container/Dockerfile`、`tools/stage-mihomo.sh`、`vendor/manifest.json` 和 checksums；需要可复现发布时应改为具体版本和 digest，并补齐消费链测试。

### 8.6 机器输出兼容

- `--format json` 使用固定 envelope：command、version、success、exit_code、data、errors 等字段由 `src/aisc/cli/output.py` 统一生成。
- `--events` 只属于 build/run JSONL 流，并与 JSON envelope 互斥。
- build/run 在机器模式将 Docker stdout/stderr 转发到 stderr。
- usage error 退出 2；稳定业务错误通过 `CliError` 的 exit code 和 `AISC_ERR_*` code 表达。
- 改字段、事件名称、终止事件或 stdout 污染都属于兼容性变更，必须更新 RFC 和测试。

## 9. 测试

### 9.1 实际框架和主命令

仓库当前测试使用 Python stdlib `unittest`。实际完整测试命令是：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

不要把 pytest 作为项目测试主命令。`pyproject.toml` 的 dev extra 虽包含 pytest，但当前受维护测试和 CI packaging tests 都通过 unittest 运行，也不应引入依赖 pytest fixture 的必要测试。

### 9.2 测试范围

| 路径 | 覆盖重点 | 命令 |
| --- | --- | --- |
| `tests/test_cc_switch_runtime.py` | entrypoint、wrapper、Provider、Skills 和锁降级契约 | `PYTHONPATH=src python3 -m unittest tests.test_cc_switch_runtime -v` |
| `tests/test_version_source.py` | VERSION 单一事实源与版本消费 | `PYTHONPATH=src python3 -m unittest tests.test_version_source -v` |
| `tests/packaging/test_artifact.py` | stage/archive/verify、安全解压、聚合 | `PYTHONPATH=src python3 -m unittest tests.packaging.test_artifact -v` |
| `tests/packaging/test_release_notes.py` | Release Notes/tag 命名契约 | `PYTHONPATH=src python3 -m unittest tests.packaging.test_release_notes -v` |
| `tests/packaging/test_windows_installer.py` | Windows installer 定义 | `PYTHONPATH=src python3 -m unittest tests.packaging.test_windows_installer -v` |
| `tests/packaging/test_macos_installer.py` | macOS PKG 脚本结构 | `PYTHONPATH=src python3 -m unittest tests.packaging.test_macos_installer -v` |

`__pycache__` 中可能残留已删除测试模块的 bytecode，不代表这些源测试仍存在。判断测试范围以实际 `test_*.py` 源文件和 unittest discovery 为准。

### 9.3 测试边界

- `FakeDockerExecutor` 用于不连接 daemon 的计划和命令测试。
- artifact 测试使用临时目录，不应在仓库中留下 staging/dist。
- 静态 entrypoint 测试不能替代真实 Docker 启动；修改镜像、权限、TUN、文件系统锁或 Windows bind mount 后需要对应平台 smoke。
- CI 当前只显式运行 `tests/packaging`，不是完整 unittest；`develop` 合入前仍应本地运行完整命令。

## 10. 打包与产物

### 10.1 packaging/artifact.py

`packaging/artifact.py` 提供五组动作：

```bash
# 生成并立即验证 aisc-bundle
python3 packaging/artifact.py stage --output /tmp/aisc-staging

# 单独验证 bundle
python3 packaging/artifact.py verify \
  --bundle /tmp/aisc-staging/aisc-bundle

# 使用当前平台 PyInstaller 构建 onefile
python3 packaging/artifact.py build-onefile --output /tmp/aisc-onefile

# 将 executable + staged bundle 打包；Linux/macOS 为 tar.gz，Windows 为 zip
python3 packaging/artifact.py archive \
  --staging /tmp/aisc-staging \
  --executable /tmp/aisc-onefile/aisc \
  --output /tmp/aisc-dist \
  --platform linux \
  --arch x86_64

# 验证 archive 和同名 .sha256 sidecar
python3 packaging/artifact.py verify \
  --archive /tmp/aisc-dist/AISC-2.1.4-linux-x86_64.tar.gz
```

stage allowlist 复制运行所需 bundle，排除源码、测试、CI、密钥、用户配置和运行状态。verify 检查 manifest、必需文件、Dockerfile COPY 来源、vendor checksums 和 forbidden paths。archive 创建确定性元数据，并用安全解压器拒绝绝对路径、`..`、大小写折叠重复、symlink/hardlink/device 等危险成员。

### 10.2 PyInstaller

CI 固定 `PyInstaller==6.21.0`，先构建 onedir 进行 executable smoke，再构建 onefile 分发。两者入口都是 `packaging/pyinstaller/entrypoint.py`，并通过 `--paths src` 和 `--add-data VERSION:.` 注入源码和版本。

本地 `build-onefile` 要求当前 Python 平台与目标平台一致，不能在 Linux 直接交叉生成 Windows/macOS executable。图标参数由 CI 的直接 PyInstaller 命令提供；`artifact.py build-onefile` 的本地 helper 不传 icon。

### 10.3 官方产物契约

CI 矩阵及唯一官方平台集合：

- `ubuntu-22.04` -> `AISC-<version>-linux-x86_64.tar.gz`
- `windows-2022` -> `AISC-<version>-windows-x86_64.zip` 和 setup.exe
- `macos-14` -> `AISC-<version>-macos-arm64.tar.gz` 和 `.pkg`

每个 archive/installer 带 SHA256 sidecar；tag aggregate 生成 `SHA256SUMS`。bundle 中 executable 与 `aisc-bundle/` 必须相邻，bundle manifest 只允许当前 compatible CLI version。

## 11. CI 与发布

### 11.1 Artifact workflow

`.github/workflows/artifact.yml` 是当前唯一 GitHub Actions workflow：

```text
触发：push develop | PR -> main | push v* tag | workflow_dispatch

build matrix（三平台）
  -> Python 3.12 + editable install
  -> PyInstaller 6.21.0
  -> unittest discover tests/packaging
  -> onedir + ci_smoke
  -> onefile
  -> artifact.py stage + verify + archive
  -> checkout-independent archive smoke
  -> Windows setup + installer smoke / macOS pkg + structural verify
  -> upload matrix artifacts

tag only aggregate
  -> 下载三平台 archive
  -> artifact.py aggregate
  -> 纳入 Windows setup 和 macOS pkg
  -> 生成 SHA256SUMS

tag only release
  -> 读取 docs/releases/<tag>.md
  -> 上传 archive、installer、sidecar、SHA256SUMS
```

tag 名包含 `-dev` 时 GitHub Release 标为 Pre-release；其他 `v*` tag 为普通 Release。workflow 没有 Docker image build job，也没有运行完整 unittest、`check-docs.sh` 或 `vendor-verify.sh`，这些仍是本地/合入门禁。

仓库有 `.gitleaks.toml`，但当前 Artifact workflow 没有 gitleaks step；不要把配置文件存在误写成 CI 已强制扫描。

### 11.2 发布步骤

1. 在 `develop` 完成功能和完整验证，通过 PR 将候选变更合入 `main`。
2. 发布变更只修改根 `VERSION`，并新增 `docs/releases/v<VERSION>.md`；保持 `docs/devlog.md` 新到旧。
3. 确认发布提交中的 `VERSION`、Release Notes 文件名和计划 tag 完全一致。
4. 在要发布的已审核提交上创建 annotated `v<VERSION>` tag，并推送该 tag。
5. 等待 build、aggregate、release 全部通过，核对三平台 archive、Windows setup、macOS PKG、所有 sidecar 和 `SHA256SUMS`。

示例中的版本值必须从 `VERSION` 读取，避免手写漂移：

```bash
VERSION_VALUE="$(python3 -c "from pathlib import Path; print(Path('VERSION').read_text().strip())")"
git tag -a "v${VERSION_VALUE}" -m "Release v${VERSION_VALUE}"
git push origin "v${VERSION_VALUE}"
```

创建 tag 前至少运行：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tools/check-docs.sh
bash tools/vendor-verify.sh
python3 packaging/artifact.py stage --output /tmp/aisc-staging
python3 packaging/artifact.py verify --bundle /tmp/aisc-staging/aisc-bundle
git diff --check
```

不要覆盖已发布 tag，不要 force-push 发布引用。Release Notes 缺失会使 release job 无法读取 `body_path`；平台 job 任一失败会阻止 aggregate/release。

## 12. 安全边界

### 12.1 容器不是强安全沙箱

- 容器固定以 `root` 运行，目的是兼容 Windows/WSL2 bind mount 写权限。
- Claude 默认跳过 permissions；Codex 默认绕过 approvals 和 sandbox。
- `/root/app` 是宿主工作区 bind mount，危险命令可直接修改或删除宿主文件。
- Docker daemon access、root、`NET_ADMIN`、TUN 都是高风险能力，`IS_SANDBOX=1` 不降低权限。
- `safe/unsafe` Profile 尚未接入 run，不能作为安全保证。

任何权限默认值变化都必须同时检查 wrappers、README 警告、Profile 误导风险和真实容器 smoke。不要把容器称为可运行不可信代码的隔离边界。

### 12.2 凭据与配置

- Provider 和凭据仅由 cc-switch/官方 CLI 管理；AISC config schema 不接收密钥。
- `.cc-switch/` 可能包含 SQLite 凭据和备份，`.claude/`、`.codex/` 可能包含登录状态；都不得进入 artifact 或提交。
- entrypoint 对 `.cc-switch` best-effort `chmod 700`，但 CIFS/bind mount 可能忽略或拒绝 chmod，此时只告警并继续，不能据此声称宿主权限已收紧。
- 测试只使用明显占位符，不把真实 API Key、Cookie、订阅 URL 或日志提交到 Git。
- 本地可运行 `gitleaks detect --config .gitleaks.toml --source .`，但它不能替代人工审查 staged diff。

### 12.3 文件与命令注入防护

- 配置读取拒绝 symlink/reparse 绕过、重复 JSON key 和超限输入，错误消息不回显原始敏感内容。
- `state.env` 只允许两个布尔 key，并拒绝 shell metacharacters。
- `switch --quick` 使用 positional argv 和无 `eval` 的 `/proc/1/environ` 解析。
- artifact 解压先验证全部成员，再写空目标目录，禁止路径逃逸和特殊文件。
- 新代码不得把 Provider、路径或用户输入拼进 `shell=True` 字符串。

## 13. 文档与设计决策

| 位置 | 用途 | 权威性 |
| --- | --- | --- |
| `README.md` | 最终用户当前行为、安装、CLI、排障 | 用户文档事实入口 |
| `DEVELOP_WIKI.md` | 当前开发架构、流程和契约 | 维护者事实入口 |
| `docs/adr/001-python-stdlib-cli.md` | 使用 Python stdlib CLI 的决策 | 架构决策背景 |
| `docs/rfc/aisc-cli-v1.md` | JSON envelope / JSONL 协议 | 机器接口契约 |
| `docs/plans/` | 实施计划与历史设计 | 不能覆盖当前源码事实 |
| `docs/devlog.md` | 变更历史 | 非命令参考 |
| `docs/releases/v*.md` | GitHub Release body | tag 发布必需 |

文档原则：

- 路径、脚本和命令必须在当前仓库可核验。
- 用户手册不展开内部类级细节；开发手册不复制完整用户 CLI 教程。
- 删除功能时同时删除主动推荐，但历史 plan/devlog 可保留明确的历史语境。
- README 末尾从 `## 推荐服务` 开始的审计区有独立保留要求，修改前后必须逐字比较。
- 修改 README 或内置 Skills 后运行 `tools/check-docs.sh`，并正确识别 `.slim/worktrees/` 误报。

## 14. 提交前检查

通用检查：

```bash
# Python 语法和完整 unittest
python3 -m compileall -q src packaging
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v

# 当前真实 Bash 文件语法
bash -n container/entrypoint.sh
bash -n container/claude-wrapper
bash -n container/codex-wrapper
bash -n container/cc-switch-wrapper
bash -n tools/check-docs.sh
bash -n tools/stage-mihomo.sh
bash -n tools/vendor-refresh.sh
bash -n tools/vendor-verify.sh

# 内容与 diff
bash tools/vendor-verify.sh
git diff --check
git status --short
```

按修改区域追加：

| 修改区域 | 追加验证 |
| --- | --- |
| CLI parser/output | text + `--format json`；build/run 再测 `--events` |
| build/run plan | direct/proxy、dry-run、non-interactive、keep-alive 组合 |
| registry/container commands | `ps` 与 name/label/default/歧义/GC unittest |
| config | validate/effective、平台路径、symlink/reparse 和 parser limits |
| cc-switch/Skills/entrypoint | `tests.test_cc_switch_runtime` + Docker 启动 smoke |
| `container/` | `vendor-refresh.sh` 后 `vendor-verify.sh`；检查只包含预期 checksum 变化 |
| Dockerfile/外部依赖 | `versions.env`、Dockerfile ARG、manifest、离线资源一致性 + no-cache build |
| packaging | `tests/packaging` + artifact stage/verify；目标平台 installer smoke |
| `VERSION`/Release | 只改 `VERSION`，补 Release Notes，运行 ci_smoke/packaging tests |
| README/Skills 名称 | `tools/check-docs.sh`，并核对推荐服务审计区原样保留 |

最后审查 `git diff`，确认没有 `.cc-switch`、`.claude`、`.codex`、`.aisc`、`.env`、凭据、下载临时文件、虚拟环境或 build artifact 被纳入提交。

## 15. 关键索引

| 需求 | 首要入口 | 关联文件 |
| --- | --- | --- |
| 新增宿主命令 | `src/aisc/cli/main.py` | `src/aisc/cli/commands/`、`src/aisc/cli/output.py` |
| 改 build/run argv | `src/aisc/domain/models.py` | `commands/build.py`、`commands/run.py`、`adapters/docker_.py` |
| 改多容器管理 | `src/aisc/adapters/container_registry.py` | `src/aisc/cli/commands/container.py` |
| 改 AISC root | `src/aisc/application/resources.py` | artifact bundle 布局、installer smoke |
| 改配置 | `src/aisc/application/config_service.py` | `schemas/config_schema.py`、config readers |
| 改版本 | `VERSION` | `src/aisc/__init__.py`、`packaging/artifact.py`、`ci_smoke.py` |
| 改容器启动 | `container/entrypoint.sh` | 三个 wrappers、`container/lib/`、Dockerfile |
| 改 Provider/路由 | `container/entrypoint.sh` | `cc-switch-wrapper`、宿主 `switch` wrapper |
| 改 Skills | `container/cc_switch_skills.py` | `container/cc-switch-skills/`、Dockerfile bundle hash |
| 改 TUN | `container/mihomo-build-config.js` | Dockerfile、`tools/stage-mihomo.sh`、RunPlan |
| 改 artifact | `packaging/artifact.py` | `packaging/ci_smoke.py`、packaging tests、workflow |
| 改 Windows 安装器 | `packaging/windows/installer.iss` | `smoke_installer.ps1`、workflow |
| 改 macOS PKG | `packaging/macos/build_pkg.sh` | packaging test、workflow structural verify |
| 改 CI/发布 | `.github/workflows/artifact.yml` | `docs/releases/`、VERSION、artifact aggregate |
