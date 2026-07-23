# AISC — 开发日志

## v2.0.0-dev (2026-07-16 ~ 2026-07-17) — 多阶段可用性 / 可靠性 / 可维护性重构

开发计划见 `docs/plans/PLAN-v2-usability-refactor.md`。以下按里程碑记录已完成工作，**不包含计划中尚未实现的条目**。除两轮权限修复跨午夜（最终 commit `4dff7ae` 2026-07-17 00:22），其余全部在 2026-07-16 完成。

---

### v1.5.2 — AI 简讯性能/可靠性重构

Commit `e9945e4`（2026-07-16 21:50）。注意：当时目录名仍为 `image/` 和 `ai_brief/`，以下路径用当时实际名称（当前对应 `container/` 和 `apps/ai-brief/`）。

**变更**：
- **5 源并发抓取**（`concurrent.futures.ThreadPoolExecutor, max_workers=5`）：单个源网络故障不阻塞其他四源。新增 `FETCH_DEADLINE=14s` 全局截止，超时未完成的源直接丢弃。此前串行抓取全源约 26.6s，并发后全源抓取约 8.7–12s。
- **HTTP 稳健性**：`HTTP_TIMEOUT` 从 12s 降至 6s（快失败）；`is_transient_error()` 按错误类型判断是否重试（瞬时抖动→重试，4xx/证书错误/网络不可达→放弃）；支持 gzip/deflate Content-Encoding 解压。
- **双层缓存**：raw 缓存 `~/.cache/ai-brief/raw/`（1h TTL）+ rendered 缓存 `~/.cache/ai-brief/rendered/`（同日复用）。`http_get_cached()` 先拉网络，失败时读 raw 缓存（stale-while-revalidate）；rendered 缓存同日命中即复用。
- **LLM thinking-only / timeout / max_tokens 处理**：`--ai` 模式检测 reasoning 模型（thinking-only 输出结构），`max_tokens=4096` 耗尽时自动降素材+加 tokens 重试；`LLM_TIMEOUT=30s` 独立超时。
- **`--debug` 诊断**：`stderr` 逐源计时 + LLM 阶段耗时（容器内重定向至 `/tmp/ai-brief.log`）。
- **入口重命名**：`一键启动_AI工作站.bat` → `start.bat`、`启动_AI工作站.sh` → `start.sh`、`启动_AI工作站.command` → `start.command`。
- **Dockerfile**（仍为 `image/Dockerfile`，上下文 `image/`）：替换 LiteLLM demo 层为 ai_brief COPY（`COPY --chown=AISC:AISC ai_brief/ /home/AISC/ai_brief/`，stdlib-only）+ cc-switch-cli 下载安装层（`ARG CC_SWITCH_VERSION=v5.9.0`）。构建脚本需临时复制 `ai_brief/` 到 `image/ai_brief/`（因上下文仍为 `image/`），构建后清理。
- **README** 同步更新入口文件名与构建命令。

**取舍**：
- **并发 5 源而非顺序**：串行全源约 26.6s，并发降至约 8.7–12s（单源瓶颈决定总耗时），网络抖动影响面从全失败降到 1/5。
- **raw/rendered 双层缓存**：raw 缓存 1h TTL 解决短期断网自动兜底；rendered 缓存跨 `docker run` 复用需 volume 挂载 `~/.cache/ai-brief/`（否则 `--rm` 容器销毁后缓存清空）。
- **reasoning 模型自动降素材**：thinking 输出占据大量 tokens，第一次 LLM 请求可能因 `max_tokens` 不足而返回空 content；降为 3 条+加 tokens 重试后成功率明显提升。

**验证**：
- 宿主 `brief.py` 全 flag 通过；Python 语法 `ast.parse` 通过；`bash -n` 全 .sh 通过。
- 端到端实测（Docker 容器内）：fetch 8.86s + AI 精选 27.84s = 总计 36.7s 成功输出中文简讯。

---

### P0 — 可用性重构：启动入口、构建上下文、AI 简讯解耦

Commit `370fb65`（2026-07-16 21:56）。注意：当时目录名仍为 `image/` 和 `ai_brief/`，目录迁移到 `container/` 和 `apps/ai-brief/` 在 P1.1（commit `5c3a52c`）。以下用当时实际路径记录。

**变更**：
- **根 Docker build context**：构建上下文从 `image/` 改为 `.`（项目根）。Dockerfile 仍为 `image/Dockerfile`。Dockerfile 内 COPY 路径加 `image/` 前缀（如 `COPY image/entrypoint.sh`）；构建脚本不再对 `ai_brief` 做临时 staging；入口构建命令从 `docker build -f image/Dockerfile image/` 变为 `docker build -f image/Dockerfile .`（当时路径；当前为 `container/Dockerfile`）。
- **`.dockerignore` 新建**（32 条规则）：排除 `.git/`、`scripts/`、`tools/`、`docs/`、`api_route_demo/`、`start.*`、`README.md` 等。`image/` 内的 `_bundle/` 与 `downloads/` 未排除（构建所需）。
- **移除 LiteLLM demo（`api_route_demo/` 整目录）**：v1.5.2 已在 Dockerfile 层面将 LiteLLM 层替换为 ai_brief + cc-switch-cli；P0 从仓库删除 `api_route_demo/` 的 5 个文件。README 删除「OpenAI 协议转换」亮点。
- **AI 简讯退出默认同步启动路径**：entrypoint 改由 `AI_BRIEF_ON_START` 控制——默认关闭（零阻塞），`background` 后台异步并写日志，`foreground` 保留同步调试模式（外层 timeout 50s）。
- **`.gitignore` 同步**：增补 `__pycache__/`、`*.pyc`。
- **README / PLAN** 路径引用同步更新。

**取舍**：
- **根 build context 而非 `image/`**：根 context 下 COPY 的 `image/` 前缀更清晰、无需构建脚本临时复制。后续 P1.1 重命名 `image/` → `container/` 后前缀自然变为 `container/`。
- **移除 LiteLLM demo**：协议转换概念可行但稳定运行依赖上游兼容（uvloop/3.14、orjson wheel），作为 demo 增加维护负担。

**Commit**：`370fb65`（2026-07-16 21:56）

---

### P0.1 — 闭合 P0 可用性缺口

Commit `c651ea3`（2026-07-16 22:08）。

**变更**：
- **PowerShell 5.1 兼容**：`scripts/03_build_image.ps1` 移除 `-SkipHttpErrorCheck`（PS 5.1 无此参数），改为 `try/catch` + `$_.Exception.Response.StatusCode` 判断 401。
- **`tools/stage-*.sh` 构建上下文提示修复**：保留当时正确的 `image/_bundle`/`image/downloads` staging 目标，仅把输出的构建命令从 `docker build ... image/` 改为根上下文 `docker build ... .`；目录重命名在后续 P1.1 完成。
- **新增 `cli/commands/doctor.sh`**：11 项环境诊断（Docker CLI/daemon/权限/Compose/Git/项目目录/Dockerfile 存在/Python 语法/macOS start.command/start.sh），彩色 PASS/FAIL/WARN 输出。用法仅 `bash cli/commands/doctor.sh`（`start.sh` 不含 doctor 子命令）。
- **新增 `tests/smoke/check-syntax.sh`**：遍历 `cli/`、`image/`、`scripts/`、`tools/` 及根入口的 `.sh`/`.py`/`.js`/`.json` 文件做语法校验。初始 66 文件全通过（后续扩展至 69）。
- **`.gitignore` + `.dockerignore` 增补 `.aisc/` 排除**。

**验证**：
- PS 代码仅做静态/manual review（本机 Linux 无 PowerShell 环境，未跑 `[Parser]::ParseFile`）。
- `tests/smoke/check-syntax.sh`：66/66 通过。
- doctor 在本机 WSL/Linux 宿主自检：8 passed, 2 warnings, 0 failures（Docker Compose 不可用 + macOS check 不适用）。

**Commit**：`c651ea3`（2026-07-16 22:08）

---

### P1 — 架构收敛

#### P1.1：目录机械迁移 `image→container`、`ai_brief→apps/ai-brief`

Commit `5c3a52c`（2026-07-16 22:14）。

- `image/` → `container/`（Dockerfile、entrypoint.sh、claude-switch、claude-wrapper、claude-settings.json、global-claude.md、mihomo-build-config.js、commands/、_bundle/、downloads/）。
- `ai_brief/` → `apps/ai-brief/`（brief.py、run.sh、README.md、.gitignore）。
- 所有引用同步更新：`scripts/03_build_image.{sh,ps1}`、README、PLAN、`.dockerignore`、`tools/stage-*.sh`、`tests/smoke/check-syntax.sh`。
- `container/Dockerfile`：COPY 路径从 `image/...` → `container/...`；`COPY ai_brief/` → `COPY apps/ai-brief/`；构建命令从 `image/Dockerfile` → `container/Dockerfile`。Dockerfile 中 `COPY apps/ai-brief/ /home/AISC/ai_brief/` 持续有效（v1.5.2 引入的 COPY 在 P0/P1.1 始终保留，从未移除）。

**Commit**：`5c3a52c`（2026-07-16 22:14）

#### P1.2：Provider 元数据数据化

Commit `66b8a50`（2026-07-16 22:21）。

- 新建 `container/providers.json`（schema v1，7 个 provider：cc/deepseek/ark/duo-cc/1y/xf/orange），每个含 `id/name/aliases/models/auth_type/auth_key_name/auth_prompt/key_display/base_url/model/default_opus/default_sonnet/default_haiku/subagent/effort/compact/clear_all/url_fragment/help_desc/switch_msg` 等字段。
- `container/claude-switch` 重构：原 7 个硬编码 provider 改为 `_node_resolve_provider()` / `_match_provider()` 数据驱动函数，每次调用启动 Node.js 子进程（`node -e`）读 providers.json，输出 shell 变量。provider 增删改只需改 JSON。
- Dockerfile 新增 `COPY container/providers.json /home/AISC/providers.json`。
- 密钥存储（`.cc-config/api-keys`）与 `write_settings` 行为完全不变。

**验证**：providers.json JSON 语法验证通过（`python3 -m json.tool`）；`bash -n` 通过；冒烟测试通过。注：本阶段仅为语法/file 层面验证。

**Commit**：`66b8a50`（2026-07-16 22:21）

#### P1.3：`--workspace` 支持 + 状态迁移到 `.aisc/`

Commit `e1bddb0`（2026-07-16 22:26）。

- 新增 `--workspace PATH` 参数（`start.sh`、`start.bat`）：默认当前目录，`04_launcher` 用 `AISC_WORKSPACE` 决定 bind mount 源。
- macOS `start.command` 修复 PWD 丢失：保存 `ORIGINAL_PWD` 并在 `start.sh` 中使用（设计用于兼容双击场景，未在真实 macOS 上验证）。
- 状态双写：`_state.sh` / `_state.ps1` 同时写入 `.aisc/state.env` + `.deploy/state.env`，读取优先 `.aisc/`、fallback `.deploy/`。

**验证**：脚本语法通过（`bash -n`）；`--workspace` 参数正确传递到 `04_launcher`。

**Commit**：`e1bddb0`（2026-07-16 22:26）

#### P1.4：密钥迁移到 `.aisc/secrets/`（保守复制）

Commit `33901a2`（2026-07-16 22:30）。

- `claude-switch` 新增 `migrate_keys()` 幂等函数：若 `.aisc/` 存在且旧 `.cc-config/api-keys` 有内容而 `.aisc/secrets/` 空，则 `cp`（复制，非 `mv`）。
- `get_key()` 优先读 `.aisc/secrets/api-keys`，fallback `.cc-config/api-keys`；交互输入新 key 后双写两处。
- entrypoint.sh：确保 `.aisc/secrets/` 目录存在 + `sudo chown -R AISC:AISC` + 权限 700。
- `.cc-config/api-keys` **永不删除**。

**已知边界**：当前 `claude-switch` 仍将 `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY` 注入 `.claude/settings.json`（env 块），意味着密钥并非仅存于 secrets 文件——settings.json 中也有一份明文副本。这是 P3 待处理的安全边界，如实记录。

**Commit**：`33901a2`（2026-07-16 22:30）

#### P1.5：entrypoint 纯内部重构——消除重复代码

Commit `ffb970c`（2026-07-16 22:34）。

- 抽取共享库 `container/lib/env-inject.sh`（Node.js env 注入）+ `container/lib/path-resolve.sh`（路径/权限辅助）。
- entrypoint.sh 减少 ~10 行，claude-wrapper 减少 ~12 行。
- Dockerfile 新增 `COPY container/lib/ /usr/local/bin/lib/`。行为完全不变。

**Commit**：`ffb970c`（2026-07-16 22:34）

---

### P2 — 版本锁定、vendor 清单与 CI

Commit `ff240ae`（2026-07-16 22:40）。

#### P2.1：VERSION + config/versions.env
- `VERSION`：`2.0.0-dev`。
- `config/versions.env`：`AISC_VERSION`、`NODE_IMAGE=node:20-slim`、`NODE_IMAGE_DIGEST`（空 TODO）、`CLAUDE_CODE_VERSION=latest`、`MIHOMO_VERSION=v1.19.27`、`GEODATA_VERSION=latest`、`CC_SWITCH_VERSION=v5.9.0`、`USE_CN_MIRROR=1`、`GH_PROXY`（空）。Dockerfile ARG 与 versions.env 存在重复默认值（如 `USE_CN_MIRROR=1` 在两处各写一次），是已知技术债。

#### P2.2：vendor/manifest.json + checksums.txt + licenses
- `vendor/manifest.json`：7 组件——mihomo、geodata、caveman、claude-hud、claude-plugins-official、anthropic-agent-skills、gstack-skills，含版本/来源 URL/许可/文件列表。
- `vendor/checksums.txt`：34 个 SHA256，全部验证通过。
- `vendor/licenses/README.md`：第三方许可归档。

#### P2.3：GitHub Actions CI
- `checks.yml`（push + PR）：bash `-n`、Python `py_compile`、Node `--check`、JSON 校验、冒烟测试、gitleaks（**`continue-on-error: true`**，因此当时尚不是阻断门禁；`docs/` 整体 allowlist）。
- `docker-smoke.yml`（PR + workflow_dispatch）：dry-run 构建，`timeout-minutes: 20`。
- `.gitleaks.toml`：白名单 `container/_bundle/`、`docs/`、`vendor/`。

#### 已知未固定项
- `NODE_IMAGE_DIGEST` 空、`CLAUDE_CODE_VERSION=latest`、`GEODATA_VERSION=latest`——可复现构建尚不完全。

**Commit**：`ff240ae`（2026-07-16 22:40）

---

### P2.4 — vendor 刷新/校验工具 + 文档一致性检查

Commit `a8ce21d`（2026-07-16 22:49）；漂移修复 `4820ec2`（2026-07-16 22:50）。

- `tools/vendor-refresh.sh`：4 步——①检查 manifest 源目录是否存在 ②报告 `container/_bundle/`（手动维护）③验证 `container/downloads/` 与 manifest 一致 ④通过 `find + sha256sum` 重生成 `vendor/checksums.txt`。支持 `--dry-run`。
- `tools/vendor-verify.sh`：SHA256 完整性校验，34/34 通过。
- `tools/check-docs.sh`：324 行文档一致性检查。**首次运行 42 passed, 1 warning, 2 failures**（README provider 数 5→7、xf/orange 缺失），立即修复（`4820ec2`）。修复后 45/45；README 全重写后最终 **54/54**。

---

### README 全面重写（commit `a87e5d9`，2026-07-16 23:00）

修正 15 处事实错误：版本号 v1.5.1→2.0.0-dev、密钥路径 `.cc-config/`→`.aisc/secrets/`、provider 5→7、doctor 调用 `bash cli/commands/doctor.sh`（非 `start.sh doctor`）、构建命令（根 context + `container/Dockerfile`）、删除夸大陈述。

新增：AI 简讯（`AI_BRIEF_ON_START`）、诊断工具、完整 Provider 表、Dockerfile ARG 表、版本固定状态、安全说明。

372→342 行（-30 行）。验证：`check-docs.sh` 54/54/0；`check-syntax.sh` 69/69。

---

### 两轮 Linux bind mount 权限修复

#### 第一轮：mkdir/sudo fallback（commit `2b37133`，2026-07-16 23:12）

**问题**：Linux bind mount 上 `mkdir -p` 可能因父目录属主为 root 而失败。

**修复**：
- `claude-switch` 新增 `_ensure_dir()`：plain `mkdir` 失败→`sudo mkdir` fallback。
- `path-resolve.sh` 的 `ensure_writable()`：`mkdir -p` 失败→`sudo mkdir -p` fallback；`sudo chown` 失败从静默忽略改为返回非零；新增 `[ -w ]` 验证。当时仍使用 `sudo chown -R AISC:AISC`（递归）。
- entrypoint.sh：用 `ensure_writable` 初始化 `.aisc/` + `.aisc/secrets/`。
- 新增 `tests/shell/test-ensure-writable.sh`：6 个测试场景，8/8 断言全通过。

**Commit**：`2b37133`（2026-07-16 23:12）

#### 第二轮：真实 I/O probe + 禁止递归 chown/chmod + node 基础用户 UID/GID 1000 根因修复（commit `4dff7ae`，2026-07-17 00:22）

**问题（第一轮未解决）**：
1. `[ -w ]` 在 CIFS/NFS/只读 bind mount 上可能假阳性。
2. `sudo chown -R` 递归修改挂载卷所有文件，不安全且可能破坏宿主机权限。
3. **根因**：node:20-slim 基础镜像自带 uid/gid=1000 的 `node` 用户。旧 Dockerfile 的 `useradd -m AISC`（未指定 `-u`）自动分配到 uid=1001，与 bind mount 上 uid=1000 文件不匹配。

**修复**：
- **容器 UID 对齐**：`groupmod -n AISC node && usermod -l AISC -d /home/AISC -m -g AISC node`——将 base image 自带 node 用户（uid=1000, gid=1000）改名为 AISC，彻底消除 uid 漂移。
- **真实 I/O probe**：`_probe_writable()` 用 create→write→rename→delete 验证可写性，不依赖 `[ -w ]`。模拟了 CIFS chmod 静默忽略（fake chmod no-op）场景，但未在真实 CIFS 设备上复现。
- **禁止递归 chown/chmod**：改为非递归 `sudo chown $(id -u):$(id -g)` + `sudo chmod u+rwx`（仅目录自身，不加 `-R`）。
- **entrypoint chmod 700 收紧** + `stat -c '%a'` 验证（CIFS 静默忽略检测）。
- 测试更新：`tests/shell/test-ensure-writable.sh` 扩展到 9 个场景共 18 个断言，**18/18 全通过**。

**验证**：
- `tests/shell/test-ensure-writable.sh`：**18/18**；`tests/smoke/check-syntax.sh`：**69/69**；`tools/check-docs.sh`：**54/54**。
- Docker build 成功；`id AISC` 确认 uid=1000/gid=1000。
- 真实 bind mount（`-v /tmp/aisc-test:/home/AISC/app`）：entrypoint 正常（fresh + 重复挂载均通过），`cs show` 正常，项目/临时/全局作用域均正常。
- 用户随后完成手动启动验证并确认通过。

---

### P3.1 S1 — 统一 CLI 协议契约、Python stdlib 运行时决策与特征测试 harness

P3 计划 commit `c706a68`（2026-07-17 01:03）已提交到仓库。本节记录 **P3.1 第一阶段（S1）**，聚焦协议设计、技术决策与测试基础设施搭建。**本阶段不修改业务逻辑、不实现 Python CLI、不切换默认入口。后续 S2–S8 将在此基础上逐步实现 CLI 命令。**

#### RFC：AISC CLI v1 机器消费协议（`docs/rfc/aisc-cli-v1.md`，状态：draft）

新增 `docs/rfc/aisc-cli-v1.md`（366 行），定义 `aisc.cli/v1` 协议 schema 与语义。**当前为 S1 草案（draft），是冻结候选合同而非已实现接口**——协议细节在 S9 稳定化前可能发生兼容性变更。主要约定：

- **输出格式三选一**：`--format text`（默认，人类可读，stdout）、`--format json`（JSON envelope，stdout 单条完整 JSON）、`--events`（JSONL 事件流，stdout 每行一个 JSON）。`--format json` 与 `--events` 互斥。
- **stdout/stderr 严格隔离**：结构化数据只走 stdout；日志、诊断、错误描述只走 stderr。消费者可独立捕获。
- **退出码体系**：固定语义退出码 `AISC_EXIT_OK(0)` / `AISC_EXIT_USAGE(1)` / `AISC_EXIT_ERR(2)` / `AISC_EXIT_CANCEL(130)`，禁止 shell 惯用 `1` 的模糊语义。
- **错误输出规范**：`--format json/jsonl` 下错误对象含 `code`（字符串枚举）和 `message`（单行一句话），面向机器消费。
- **non-interactive 保证**：`--format json` 或 `--events` 时 CLI 不得启动任何交互式提示、分页器或 TUI。
- **交互确认/极简 redaction**：定义确认方式（`--yes` flag/`AISC_YES=1` 环境变量）与密钥参数 redaction 约束。

#### ADR：Python stdlib CLI 运行时决策（`docs/adr/001-python-stdlib-cli.md`，状态：已接受）

新增 `docs/adr/001-python-stdlib-cli.md`（192 行），记录 P3 统一 CLI 的技术选型决策：

- **选择 Python 3.11+ stdlib core**（不引入 click/typer/rich 等第三方依赖）：零 `pip install`，跨平台（Linux/macOS/Windows）一致行为。
- **分发策略**：未来通过 PyInstaller 打包为独立单文件可执行制品（standalone），无需用户安装 Python；同时保持 `python3 -m aisc` 兼容 bundle 模式用于开发/CI/高级用户。
- **GUI / daemon 明确不在当前范围**：ADR 明确定义 CLI 边界——no GUI endpoint、no background daemon/server process。远程 daemon 在远期规划但非实施目标。

#### stdlib unittest harness（`tests/harness/`）

新增纯 stdlib 测试 harness（零第三方依赖，设计供 S2+ 测试复用）：

- **`tests/harness/test_runner.py`**（460 行）：`RunResult` dataclass（stdout/stderr/exit_code/timed_out）+ `CliRunner`（subprocess 包装，支持 cwd/timeout/env 注入）。内置协议断言函数：
  - `assert_json_envelope()`：严格校验 `--format json` 的纯 JSON stdout——要求 `meta.protocol=="aisc.cli/v1"`，并检查 `meta.command/exit_code/timestamp/version/run_id`、`data` 与 `errors`；协议退出码必须与进程退出码一致。
  - `assert_jsonl_protocol()`：严格校验 `--events` JSONL 流——每条 JSON 对象含 7 个必填字段（`protocol`/`command`/`run_id`/`seq`/`type`/`ts`/`data`），`seq` 从 1 起严格单调递增+1，恰好一条终端事件（`.complete`/`.failed`/`.cancelled`）作为最后一行，`data.exit_code` 为 int。
- **`tests/harness/test_harness_self.py`**（harness 自检）：`assert_json_envelope` 接收非法/缺失字段/output-not-JSON 时正确 `AssertionError`；超时子进程被 `CliRunner` 正确捕获为 `timed_out=True`。

#### legacy characterization tests（`tests/features/`）

为现有 shell 脚本建立静态契约特征测试——**只验证现有行为不修改逻辑，fake Docker 无真实 Docker/网络，不污染真实 `.aisc/`/`.deploy/` 状态**：

- **`tests/features/helpers.py`**：`TempProject` 隔离辅助对象——在临时目录创建 `scripts/` 副本，由测试 teardown 清理；fake Docker 使用可逆的结构化 trace 保留每个 argv 的边界。
- **`tests/features/test__state.py`**：测试 `scripts/_state.sh` 的 init/set/get、primary-priority（`.aisc/`）与 legacy-fallback（`.deploy/`）路径、双写（`.aisc/state.env` + `.deploy/state.env`）行为。
- **`tests/features/test_start.py`**：冻结 `start.sh` 的未知参数、缺失 `--workspace` 值和不存在 workspace 等错误路径。
- **`tests/features/test_03_build_image.py`**：通过 fake Docker 冻结根 build context、`container/Dockerfile`、镜像 tag、关键 build args 与 `DO_RUN=0` 行为，并校验 argv 边界。
- **`tests/features/test_04_launcher.py`**：通过 fake Docker 冻结 `DO_RUN=0`、workspace 校验、基本/代理模式 run argv、Docker 退出码透传；额外验证含空格 workspace 的 bind mount 仍是单个 argv。
- **`tests/features/test_contracts.py`**：静态 repo 契约——`container/providers.json` 结构校验（`schema_version`/`providers` 非空/每个 provider 含必填键 `id`/`name`/`auth_type`/`auth_key_name`/`base_url`/`model`）+ `config/versions.env` 键存在性检查。

#### CI 集成

- **`.github/workflows/checks.yml`** 新增 step：`python3 -m unittest discover -s tests -p 'test_*.py' -v`（push + PR），位于 bash `-n` / Python `py_compile` / Node `--check` / JSON 校验之后。

#### 验证状态

- `python3 -m unittest discover -s tests -p 'test_*.py' -v`：**100/100 通过**。
- `tests/smoke/check-syntax.sh`：**69/69 通过**；`tools/check-docs.sh`：**54/54 通过**；`git diff --check`：通过。
- 特征测试使用临时目录与 fake Docker，不调用真实 Docker/网络，也不修改真实 `.aisc/` 或 `.deploy/` 状态。

---

### P3.1 S2 — 最小 Python CLI 纵向切片（`version` + `doctor`）

本节随 S2 实现于 2026-07-17 一并提交。

S2 在 S1 的协议契约与测试 harness 基础上，实现了最小可运行的 Python CLI，包含 `version` 和 `doctor` 两个只读命令。**当前不切换默认入口——用户仍然通过 `start.sh` / `start.bat` / `start.command` 使用项目。**

#### 新增文件结构

```
src/aisc/__init__.py          # package, __version__ = "2.0.0-dev"
src/aisc/__main__.py          # python -m aisc 支持
src/aisc/domain/models.py     # VersionInfo, CheckResult, DoctorReport, CliError, ProcessResult
src/aisc/domain/__init__.py
src/aisc/application/resources.py  # locate_aisc_root (4 级优先级)
src/aisc/application/version.py    # gather_version_info, VERSION/versions.env 解析
src/aisc/application/doctor.py     # 8 项 host doctor 检查 + 退出码优先级
src/aisc/application/__init__.py
src/aisc/adapters/system.py        # ProcessRunner Protocol + RealProcessRunner
src/aisc/adapters/__init__.py
src/aisc/cli/main.py               # argparse, 命令分发, JSON envelope 输出
src/aisc/cli/output.py             # build_envelope, print_doctor_text
src/aisc/cli/__init__.py
pyproject.toml                     # setuptools src-layout, Python >=3.11
tests/unit/test_resources.py       # locate_aisc_root 优先级/错误处理
tests/unit/test_version.py         # VERSION 解析, versions.env inline comment
tests/unit/test_doctor.py          # fake process/discovery 组合测试
tests/integration/test_cli.py      # subprocess 集成: version/doctor text+json
```

#### 关键设计决策

- **零运行时依赖**：stdlib-only。dev optional dependencies 声明 pytest/PyInstaller 但不用于运行时。
- **资源定位 4 级优先级**：explicit `--aisc-root` → env `AISC_ROOT` → frozen `aisc-bundle/` → cwd 向上 repo 发现。每级严格验证（需 VERSION + container/Dockerfile + config/versions.env）。显式/env 无效 → 受控 OSError 不回退。Frozen bundle 缺失可继续，存在但损坏 → 受控报错。开发源码模式不从 `sys.executable` 寻找 bundle。
- **版本解析**：`VERSION` 读取根文件第一行；`CLAUDE_CODE_VERSION` 从 `config/versions.env` 解析，去除 inline comment 保留 `latest`。无 root 时字段为 `None`。CLI 版本来自 package `__version__` 不依赖文件。`VERSION` 文件内容与 `__version__` 一致（均为 `2.0.0-dev`）。
- **Doctor 8 项检查**：docker-cli / docker-daemon / docker-permission / docker-buildx / tun-device / aisc-root / root-files / git。Docker CLI 缺失时 daemon/permission/buildx 自动 skip（不产生重复 fail）。Warning 不导致失败。退出码优先级：Docker 不可用 → exit 3 (AISC_ERR_DOCKER_UNAVAILABLE)；仅权限 → exit 9 (AISC_ERR_PERMISSION_DENIED)；显式 root 无效或其他失败 → exit 1 (AISC_ERR_GENERAL)。
- **JSON envelope**：完全符合 RFC `aisc.cli/v1` §2——meta (protocol/command/exit_code/timestamp/version/run_id) + data + errors。UTC Z 时间，UUID v4，meta.exit_code 与进程退出码一致。`version` data 固定包含 6 个键：cli/bundle/contract/image/claude/python version，未知值为 `null`。`doctor` data：host:{checks:[],summary:{}} + container:null。
- **`--format json` 下 usage error**：stdout 输出严格 JSON envelope（exit 2, AISC_ERR_USAGE），stderr 保持为空。text 模式保持普通 usage 到 stderr。
- **`--format` 全局参数**：可放在子命令前或后（如 `aisc --format json version` 和 `aisc version --format json` 均有效）。`--events` 不实现（usage error）。

#### CI 集成

- `.github/workflows/checks.yml` 将 unittest step 更新为 `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`。
- CI 在 unittest 后运行 `bash tests/smoke/packaging_smoke.sh`，验证 wheel 构建、临时 venv 安装、console script 与 `python -m aisc` 两种入口。

#### 验证状态

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`：**233/233 通过**（S1 现有 100 + S2 新增 133）。
- `PYTHONPATH=src python3 -m aisc version` / `version --format json` / `--format json version` / `--format=json version`：通过。
- `PYTHONPATH=src python3 -m aisc doctor --format json`：合法 envelope（exit 0/3/9 依据环境）。
- `bash tests/smoke/packaging_smoke.sh`：**通过**（wheel build + temp venv install + 两入口验证 + PEP440 版本规范化）。
- `bash tests/smoke/check-syntax.sh`：**69/69 通过**。
- `tools/check-docs.sh`：**54/54 通过**。
- `git diff --check`：通过。

#### 剩余限制

- `build/run/config/profile/provider` 命令尚未实现（S3–S8）。
- `--events` JSONL 流尚未实现。
- 无 PyInstaller 打包（S4）。
- 不修改 legacy `start.*`、`scripts/**`、`cli/commands/doctor.sh`、container 业务逻辑。

#### Oracle 审查修复（S2 第二轮）

**Build system**：
- Backend 修正为 `setuptools.build_meta`（修复误用的 `_legacy:_Backend`）。
- 新增 `tests/smoke/packaging_smoke.sh`：wheel 构建 + 临时 venv 安装 + 不设 PYTHONPATH 验证 `aisc version --format json` 和 `python -m aisc version --format json` + PEP440 规范化检查。

**CLI/argparse**：
- `allow_abbrev=False` 全局启用，`--form` 被拒绝（exit 2）。
- `--format=json` 格式（`=` 形式）完全支持，与 `--format json` 等价。
- 重复 `--format` 采用 last-wins 规则（通过原始 argv 扫描决定）。
- 畸形子命令参数时 `meta.command` 保留已识别的命令名（如 `version --bogus` → meta.command="version"）。
- 冲突重复 format 严格 JSON stdout 纯净 + 测试断言。

**资源定位**：
- `is_frozen` 和 `executable_path` 支持函数参数注入；生产默认值按调用时惰性读取 `sys.frozen` / `sys.executable`，核心 bundle 解析 helper 保持纯参数化。
- 按 ADR：frozen adjacent bundle 不存在时继续 cwd repo discovery，存在但损坏立即 `_RootSourceError` 失败。
- 错误来源区分（`_RootSourceError.source`）：`--aisc-root` / `AISC_ROOT` / `frozen-bundle`，消息不再混淆。

**Doctor 命令发现**：
- `which` 参数注入，解析 docker/git 路径一次然后所有调用复用。
- 所有 docker 子命令使用相同的解析路径（`docker_path` 参数传递）。
- Docker/Git 超时常量：`DOCKER_TIMEOUT=8s`，`GIT_TIMEOUT=5s`；timeout → FAIL/WARN。
- `RealProcessRunner`：`encoding='utf-8'`、`errors='replace'`、通用 `OSError` 捕获。
- Docker hints 改为跨平台中性措辞。
- TUN 检查使用 `Path.stat()` + `stat.S_ISCHR` 验证字符设备；`OSError` → WARN。

**Version JSON**：
- 始终输出 6 个固定键（`cli_version`, `bundle_version`, `contract_version`, `image_version`, `claude_version`, `python_version`），未知为 `null`。
- `root` 字段从稳定 data 中移除（不输出在 JSON payload 中）。
- 文本输出不再重复 gather（复用 `VersionInfo` 对象）。

**测试**：
- 第二轮新增 26 个测试（S2 合计新增 133 个）：覆盖 Docker CLI 缺失时后续 docker 子命令零调用（`which` 返回 `None`）、`--format=json`、重复 format 的 last-wins、缩写拒绝、畸形子命令 command 保留、固定 6 键 JSON，以及 frozen 生产默认值与注入路径。
- 所有 unit 测试使用注入参数，不依赖全局状态。

---

### P3.1 S3 — Docker planner/executor：`aisc build` + `aisc run`（legacy-compatible）

**变更**：

- **`aisc build`**：Docker 镜像构建命令（legacy-compatible）
  - `--tag/-t`（默认 `super-claude:latest`）、`--no-cache`、`--pull`、`--dry-run`
  - 从 `config/versions.env` 读取 `NODE_IMAGE` 和 `USE_CN_MIRROR` 作为 `--build-arg`
  - `NODE_IMAGE` 缺失 → exit 1（`AISC_ERR_GENERAL`）；Dockerfile 缺失 → exit 4
  - dry-run：本地验证/规划，不调用 docker；输出完整 `docker build` argv
  - JSON envelope data：`image_tag`, `dry_run`, `executed`, `docker_argv`, `docker_exit_code`(nullable)

- **`aisc run`**：Docker 容器运行命令（legacy-compatible，不加 contract 检查）
  - `--image/-i`（默认 `super-claude:latest`）、`--workspace`（默认 cwd）、`--name`（默认 `super-claude-station-<短唯一值>`）、`--network direct|proxy`（默认 `direct`）、`--dry-run`
  - proxy 模式追加 `--cap-add=NET_ADMIN --device /dev/net/tun`
  - workspace 不存在/不可读 → exit 9（`AISC_EXIT_PERMISSION_DENIED`）
  - 执行前检查镜像是否存在（`docker image inspect`）；不存在 → exit 5（`AISC_EXIT_IMAGE_NOT_FOUND`）
  - JSON envelope data：`image`, `container_id`(nullable), `dry_run`, `executed`, `docker_argv`, `container_exit_code`(nullable)

- **Docker preflight**：通过 `shutil.which` 找 docker；CLI/daemon 不可用 → exit 3（`AISC_ERR_DOCKER_UNAVAILABLE`），区分 `cli_not_found`/`daemon_unreachable`；`docker info` permission denied → exit 9（`AISC_ERR_PERMISSION_DENIED`）；dry-run 不做任何 preflight

- **退出码映射**：docker build 非零 → exit 4（`AISC_EXIT_BUILD_FAILED`），data 保留 `docker_exit_code` 原码；docker run 非零 → exit 10（`AISC_EXIT_CONTAINER_FAILED`），data 保留 `container_exit_code` 原码；不透明透传容器原码

- **`--events` JSONL**：完整实现（不再是 S2 stub）
  - 小中型 `JsonlEmitter`（`output.py`），`seq` 从 1 起严格 +1，唯一 terminal 为最后一行
  - Build 事件：`build.start`, `build.plan`, `build.complete`/`build.failed`
  - Run 事件：`run.start`, `run.plan`, `run.container.start`, `run.container.complete`, `run.complete`/`run.failed`
  - dry-run 不发 container start/complete
  - terminal `data.exit_code` 与进程退出码一致
  - Docker 原始日志仅走 stderr（JSON/events 模式 stdout 纯 envelope/JSONL）

- **`--format json` 与 `--events` 互斥** → exit 2（usage error）

- **全局参数支持命令前后**：`--format`、`--no-color`、`--aisc-root`、`--events` 均可放在子命令之前或之后

- **`docker run` argv 以 list 形式构造**（不经 shell），路径含空格/中文保持为单 argv token

- **domain 模型**：新增 `BuildPlan`、`RunPlan`（immutable dataclasses）、`DockerPreflightResult`

- **adapter**：新增 `src/aisc/adapters/docker_.py`（docker CLI wrapper：preflight、image inspect、build/run 执行器、FakeDockerExecutor 供测试注入）

**取舍**：
- run 命令 `capture_output` 不适合交互使用：text 模式保持 `-it` 自然继承 stdin/stdout/stderr；JSON/events 模式使用 capture_output 转发 Docker stdout/stderr 到 stderr
- proxy config 缺失验证：在 dry-run 和实际执行前都验证 `.claude/mihomo/config.yaml` 存在性，缺失时报错（非静默挂载目录）
- 暂不实现 profile/provider/config/non-interactive/contract labels/secret——这些属于 P3.2 范围
- 不修改 `start.*` 或 `scripts/`；P3.1 默认入口仍是旧 `start.sh`

**验证**：
- 336 单元+集成测试通过（新增 103 个 S3 测试：unit 覆盖 executor 注入、FakeDockerExecutor 零调用、dry-run 零 Docker、structured failure data、ImageInspectResult 分类、exit 映射、terminal 非命令层；integration 覆盖 CLI subprocess text/json/events）
- 真实 Docker 验证：preflight（daemon v29.6.1 available）、image inspect（alpine:latest EXISTS / nonexistent MISSING）、structured run alpine:latest（non-interactive, exit 0）、dry-run 零 docker 调用
- `packaging_smoke.sh` 通过
- `check-syntax.sh`：69/69 通过
- `check-docs.sh`：54/54 通过
- `git diff --check` clean

**Oracle 审查修复（第二轮）**：
- 所有 Docker 操作统一经 `DockerExecutor` 协议注入（preflight / inspect_image / run_captured / run_streaming）；application/commands 内零 `subprocess.run`
- terminal 所有权归 main.py（命令层不再发 terminal）；JsonlEmitter.terminated property
- CliError 扩展 `data` 字段承载完整结构化结果（JSON failure 非 null）
- ImageInspectResult 结构化分类（exists/missing/docker_unavailable/permission_denied/timeout/error）
- RunPlan 新增 `interactive`（text → -it/streaming, json/events → 无 -it/captured）和 `proxy_config`（固定 `<root>/.claude/mihomo/config.yaml`）
- 文本 dry-run 使用 `shlex.join` 跨平台格式化
- 资源错误（Dockerfile/versions.env/NODE_IMAGE）→ exit 1；仅实际 docker build 非零 → exit 4
- 测试真实性：FakeDockerExecutor 直接注入全覆盖，dry-run 断言零 Docker 调用
- `check-syntax.sh`：69/69 通过
- `check-docs.sh`：54/54 通过
- `git diff --check` clean

**未覆盖**：真实 large production image build+run（耗时过大，非 P3.1 验收范围）；SIGINT/SIGTERM 130/143 自然处理但无系统的信号框架测试；交互式 tty 测试在 CI 非 tty 环境不可执行

---

### P3.1 S4 — Artifact 组装与 smoke（workflow artifact）

**变更**：

- **LICENSE**：新建根 `LICENSE`（标准 MIT 文本），Copyright (c) 2026 AISC contributors。`pyproject.toml` 已声明 MIT。
- **`packaging/pyinstaller/entrypoint.py`**：PyInstaller 入口，调用 `aisc.cli.main:main`。onefile 的唯一入口。
- **`packaging/artifact.py`**：跨平台 stdlib-only 打包脚本，支持 `stage`/`archive`/`verify`/`build-onefile`/`aggregate` 子命令。
  - `stage`：组装干净 `aisc-bundle/`，含 manifest.json、VERSION、README.md、LICENSE、.dockerignore、config/versions.env、完整 `container/**`、受控 `apps/ai-brief/**`（排除 __pycache__/pyc/cache）、`vendor/manifest.json`、`vendor/checksums.txt`、`vendor/licenses/**`。不含 src/tests/docs/packaging/tools/scripts/cli/start.*/.git/.github 或任何 state/secrets/cache。
  - `verify`：静态完整性校验——检查必需路径、manifest 合规（schema_version=1, compatible_cli_versions allowlist）、解析 container/Dockerfile COPY 源并验证、vendor checksums 验证、拒绝秘密/状态/cache/pyc。manifest missing/malformed/unknown field/type/schema/incompatible → 非零退出。
  - `archive`：创建确定性 tar.gz（Linux/macOS）或 zip（Windows），单版本化顶层目录 `AISC-<version>-<platform>-<arch>/`，内部 `aisc`(Windows `aisc.exe`) + 同级 `aisc-bundle/`。tar 规范化 uid/gid 0/0、mtime 0；zip 固定合法时间、清除 extra fields。
  - `build-onefile`：使用 PyInstaller 构建 onefile 可执行文件。onedir 仅 CI smoke，不入 archive。
  - 稳定文件排序、相对路径、SHA256 sidecar。
- **archive 命名**：`AISC-<version>-linux-x86_64.tar.gz`, `AISC-<version>-macos-arm64.tar.gz`, `AISC-<version>-windows-x86_64.zip`。
- **manifest 契约**：`{"schema_version":1,"compatible_cli_versions":["<current __version__>"]}`；UTF-8 LF、2 spaces、末尾换行、allowlist 排序去重。无 timestamps/platform/arch/checksums/重复版本。
- **版本 guard**：repo VERSION、`aisc.__version__`、staged VERSION、manifest allowlist、final executable `version --format json` 的 `cli_version` 一致性检查。
- **`.github/workflows/artifact.yml`**：三平台 matrix CI（ubuntu-22.04/linux-x86_64, windows-2022/windows-x86_64, macos-14/macos-arm64），Python 3.12 + PyInstaller 6.21.0。先 onedir 冒烟，再 onefile + stage/archive/verify → 上传 matrix artifact → aggregate job 下载三者生成/验证 SHA256SUMS → 上传完整 workflow artifact。触发 main/develop push、面向 main 的 PR 及手动运行。**不公开发布**。
- **`tests/packaging/test_*.py`**：stdlib unittest 覆盖 staging 创建、manifest 合规正整数/负例、archive 创建/验证、版本 guard 一致性、vendor checksums 验证、排除 __pycache__ 和 forbidden 内容。
- **README 更新**：说明内部开发预览 CI workflow artifact，明确无公开下载、未切换入口。
- **docs/devlog.md 更新**：记录 S4 范围与产出，明确未发布/未切入口。PLAN S4 的 manifest/资源布局矛盾已校正（bundle manifest schema_version=1 而非 2，仅 compatible_cli_versions 字段）。

**取舍**：
- **onefile 为唯一二进制**：onedir 仅 CI smoke，不入 archive、不上传。
- **不做 Release/上传外部渠道**：产物仅为 workflow artifact（CI 内部），保留 7 天。
- **不修改 start.sh/start.bat/start.command**、scripts/、container runtime、secrets/provider/security、runtime resource locator、exit codes、GUI。
- **gitleaks continue-on-error 不变**：S4 不扩大安全切片范围。
- **PyInstaller 中间产物在 temp 目录**：不污染 repo。
- **不需要 PyInstaller hooks/spec**：CLI 参数足够，entrypoint.py 薄封装。

**验证**：
- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`：**462 通过**（S3 350 + S4 包装 112）。
- `bash tests/smoke/packaging_smoke.sh`：通过。
- `bash tests/smoke/check-syntax.sh`：69/69 通过。
- packaging unit tests（112 tests）：覆盖 tar determinism、gzip mtime=0、execute mode、zip POSIX paths/compression/mode、production version guard、cache/secret exclusion、container/_bundle/plugins/cache allowlist、vendor checksums strict、Dockerfile COPY strict、archive verification checkout-independent、安全提取攻击面、aggregate（3-archive verify + SHA256SUMS）、ci_smoke importlib loading、archive-dir validation、expected version mismatch。全部通过。
- 本地 Linux staging 验证：`python packaging/artifact.py stage --output /tmp/s` → 200+ 文件，manifest conformant，vendor checksums pass，zero forbidden (no src/tests/docs/.git/pyc/pycache/start.*)。
- 本地 Linux archive 验证：tar.gz with correct layout (`AISC-2.0.0-dev-linux-x86_64/aisc` + `aisc-bundle/`), gzip mtime=0, exe mode 0755, SHA256 sidecar, two consecutive builds produce identical SHA256。
- `git diff --check` clean。
- 审计 `start.*`、`scripts/`、container runtime 未修改。

**Oracle 审查修复 (S4 第二轮)**：
- tar.gz: gzip.GzipFile(mtime=0) 包装 uncompressed tar；exe 0755, .sh/claude-switch/claude-wrapper 0755, regular 0644；连续两次相同输入 SHA256 相同。
- zip: PosixPath(.as_posix()), create_system=3, 压缩 ZIP_DEFLATED+compresslevel=6, 固定日期、mode, 无反斜杠。
- 版本 guard: stage 前 assert VERSION == get_package_version(root)，不硬编码版本号。
- 消除 onefile 双重构建: archive 接受 `--executable PATH` + `--staging DIR`，不再内部 build_onefile。
- verify: `--bundle PATH` 直接验证 staged bundle；archive verifier checkout-independent，从 archive 顶层名+bundle VERSION/manifest 验证，安全解压拒绝 absolute/`..`。
- cache/secret 排除：apps/ai-brief/cache, .pytest_cache, .mypy_cache, .ruff_cache, coverage 排除；container/_bundle/plugins/cache allowlist 保留；nested .env/.git-credentials/api-keys 排除。
- vendor checksums: 每行必须 64hex+SP+相对路径，拒绝 absolute/`..`/escape，malformed 报错不 skip。
- Docker COPY: 仅 shell form，JSON/`--from` 直接 fail；对真实 Dockerfile 所有 COPY 源建立测试。
- ARCH_TAG: platform.machine().lower() 映射，未知架构明确失败。
- build_onefile: try/finally cleanup，不 pip install -e . 修改环境，加 `--paths src`。

**跨平台限制**：
- **仅 Linux x86_64 通过真实 PyInstaller/archive/smoke 验证**。Windows x86_64 / macOS arm64 CI workflow 已配置，待首次 matrix runner 验证。
- 代码逻辑跨平台（tarfile/zipfile stdlib, PosixPath），安全提取已统一在 artifact.py 公开 helper（validate_tar_members/validate_zip_members/safe_extract_archive），ci_smoke通过 importlib 调用。
- 版本 guard 的 PEP440 规范化（`2.0.0-dev` → `2.0.0.dev0`）在 wheel metadata 发生；frozen executable 的 `cli_version` 保持产品字符串 `2.0.0-dev`。CI smoke 验证此一致性。
- `container/Dockerfile` COPY 源解析为 shell-form 简易扫描（JSON/--from 直接 fail），覆盖当前仓库全部 COPY 语句。

---

### P3.2 S5.1 — 配置/密钥发现与 schema（只读模型，ora-6 终审）

**范围**：纯模型、解析器、只读 discovery。无 CLI、secure store、migration、write。

**关闭的阻塞项**：

- **A1 value 原样**：`parse_api_keys` 仅对空行/comment 使用独立 view；value 从首个 `=` 后取原 bytes。

- **A2 auth_type 字段匹配**：`parse_settings` 单字段按 provider auth_type 匹配；错字段→UNMAPPED 零 OK。

- **A3 跨 source 冲突传递**：`classify_credentials` 任一 CONFLICT→全组 CONFLICT；intra-source dup-diff 共享 provider_id。

- **A4 canonical_url**：仅操作 `parsed.path` trailing slash，再 `urlunparse`。

- **A5 state 分模型**：`StateEntry` repr/to_summary 不泄漏 value；`StateIssue` 仅 source/line/reason_code。

- **A6 CredentialCandidate repr 受控**：内部字段 `__post_init__` 设置，asdict 不可见。

- **A7 CredentialValue 收紧**：`_reveal_for_io()`；`same_value()` hmac.compare_digest；`__reduce_ex__`+`__deepcopy__` 拒绝 pickle/允许 deepcopy。

- **B8 PathPolicy 根校验**：构造时拒绝空/相对；root symlink lstat 拒绝。

- **B9 移除 reader callback**：`discover_sources` 固定 `_safe_read`。

- **B10 延期**：parent race / Windows reparse→S5.3。

- **B11 生产 loader**：`load_provider_catalog` 逐字段存在性+类型校验，错误不回显输入值。

- **ora-6 终审 blocker 1**：`merge_state` 同源 duplicate→last-one-wins（`effective[e.key]=e` 替代 `setdefault`）；新增 deploy-only/aisc-only/双源 duplicate+shadowed+input 无副作用测试。

- **ora-6 终审 blocker 2**：`load_provider_catalog` strict required fields（`id`/`name`/`auth_type`/`auth_key_name`/`base_url` 全部显式存在+类型校验）；name 非空；base_url 允许空但字段必须存在；id 必须等于 catalog key。新增缺失字段、类型错误、id/key mismatch、sentinel 扫描测试。

**延期到 S5.3**：逐 component openat、Windows DACL/reparse、平台路径 resolver。

**验证**：579 tests pass (117 config-specific)。

---

### P3.2 S5.2 — `aisc config validate` 与 `aisc config effective`（ora-7 最终修复）

- `src/aisc/adapters/windows_config_reader.py`：`import ctypes.wintypes as _wt`（not `_ct.wintypes`）。自定义 `_FILETIME` + `_BY_HANDLE_FILE_INFO`（52 bytes, exact field offsets: dwFileAttributes0, ftCreationTime4, ftLastAccessTime12, ftLastWriteTime20, dwVolumeSerialNumber28, nFileSizeHigh32, nFileSizeLow36, nNumberOfLinks40, nFileIndexHigh44, nFileIndexLow48）。`_raise_win_error` 统一映射（ACCESS_DENIED/SHARING_VIOLATION→PermissionError, missing→FileNotFoundError, other→OSError），覆盖 CreateFileW/ReadFile/GetFileInformationByHandle/GetFileType/CloseHandle；修正 WinAPI `FILE_TYPE_DISK=0x0001`。
- ABI tests：sizeof 52、field order、exact offsets、FILETIME 8 bytes、AST proof no wintypes.BY_HANDLE_FILE_INFORMATION import，以及独立的 WinAPI file-type literal 与非磁盘拒绝断言。
- Service mapping tests（2 tests）：`config_service.safe_read_config_bytes` patch → PermissionError→exit9/permission_denied, OSError→exit1/error。
- 其他：explicit config 在任何 workspace early return 前 lexical `abspath`，确保两条 source 身份固定；`.aisc` missing semantics、EIO/ENAMETOOLONG，以及 7 个 skipUnless(nt) real Windows tests。

**验证**（256 config-specific，718 total，7 skipped，`-W error::ResourceWarning` clean，连续两次通过）。真实 Windows runner 未执行。Parent race / full handle-relative traversal / DACL→S5.3。

---

### 用户感知增强：`aisc doctor` 只读检查扩展（2026-07-17）

本节记录在现有 S2 doctor 8 项检查基础上的只读增强，**不包含网络探测、bind mount UID 检测或自动修复**。

**新增检查项**：
- **Docker Compose**：执行 `docker compose version`，缺失仅 WARN（提示安装），不影响成功退出码。
- **项目根目录可写性**：`os.access(root, os.W_OK)` 预检——不创建探针文件，不是写入保证，仅通用可写性预判。
- **Linux/macOS 启动器可执行位**：`os.access(start.sh, os.X_OK)`，macOS 额外检查 `start.command`。不可执行→WARN（提示 `chmod +x`）。
- **`apps/ai-brief/brief.py` 语法检查**：使用内置 `compile(source, path, "exec")` 仅编译不执行、不生成 `.pyc`。失败→WARN。

**验证**：
- `PYTHONPATH=src python3 -W error::ResourceWarning -m unittest tests.unit.test_doctor tests.unit.test_secret_store`：**139 OK, skipped=8**。
- `PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_*.py'`：**515 OK, skipped=15**。
- `PYTHONPATH=src python3 -m aisc doctor --format json`：exit 0；**11 pass, 3 warn, 0 fail, 0 skip**。warn 为 buildx 缺失、Compose 缺失、start.sh 不可执行，均有提示。
- `py_compile` 通过；`git diff --check` 通过；`tools/check-docs.sh`：**54/54** 通过。

---

### S5.3 状态更新 — 实验性、未提交、核心 Windows 实机硬 gate 已通过

- S5.3 adapter（`src/aisc/adapters/secret_store.py`）、配套测试、`tests/manual/verify_s5_3_windows.py` 及 `docs/testing/S5.3-windows-secure-store.md` 手测指南**仅存在于未提交工作区**。
- Linux/POSIX mode/owner 真实 `os.stat` 落盘证据通过；Windows ABI 静态测试（struct sizes/field offsets/SID/DACL 常量）通过；fake backend 测试通过；Linux 侧 symlink/reparse/非 regular 拒绝通过。
- **Windows 核心实机硬 gate 已通过**（2026-07-17，Windows 11 Pro 10.0.26200，Python 3.12.10，commit a43a034）：verifier JSON overall PASS；DACL protected=true；目录与文件 exactly 2 ACE（current user + SYSTEM Full Control 0x001f01ff）；junction 拒绝通过；篡改增加第 3 ACE 后 fail closed；恢复后 PASS。4 个 TestWindowsReal 全部 passed。证据包 `/mnt/windows/Temp/aisc-s5.3-evidence-20260717-215512.zip`。
- **注意**：证据快照的 focused unittest（Ran 69, FAILED failures=10 errors=14 skipped=1）和 full unittest（Ran 808, FAILED failures=54 errors=36 skipped=17）包含大量非 S5.3 相关失败，主要源于 POSIX-only 测试误在 Windows 执行及仓库跨平台兼容性问题。**不声称“Windows focused/full unittest 全绿”或笼统“PASSED”**。S5.3 核心验证独立于全套 unittest 通过。
- **仍不接入默认 CLI/迁移流程**；**不宣称生产安全**。所有 7 个 findings 已在当前 Linux 工作区修复（`O_NOFOLLOW` guard、POSIX class skip、SYSTEM SID no padding、posixpath/ntpath、memmove bytes、msvcrt.open_osfhandle、verifier S-1-5-18 匹配），`tests.unit.test_secret_store` Ran 72 OK skipped=8，三个文件 py_compile clean。建议提交前/发布前 Windows 回归。
- **用户决定**：当前验证阶段暂缓该安全深度工作。

---

### PLAN-v2 §5.2 第一切片 — 只读/兼容 UX 前移（2026-07-17）

本节记录从 P3.2 S5–S8 计划中前移的四项只读或兼容别名 UX，**不改变 S5.4/S6/S7/S8 验收边界**。所有实现已独立验证（聚焦 236 tests OK，全量 unit 521 OK/15 skipped，`git diff --check` clean），未 commit。

| 项 | 类型 | 内容 |
|----|------|------|
| `aisc config show` | 兼容别名 | `config effective` 严格兼容别名，共用 handler；相同脱敏、text/JSON、错误与退出码；`--events`→exit 2 |
| `aisc provider list` | 只读前移 | 只读 canonical `<aisc-root>/container/providers.json`，使用现有 root locator + strict catalog loader；text 显示 id/name/auth type；JSON 含真实 schema_version/provider 数组；不读用户配置/secret、不写文件、无硬编码 fallback |
| `aisc run --non-interactive` | 传输层第一阶段 | host/transport 第一阶段：无 `-it`，传 `AISC_NON_INTERACTIVE=1`、`CLAUDE_SCOPE=project`，真实 Docker stdin=DEVNULL，与 format/events 正交。**明确未完成**：S7/S8 前无 provider/key 缺失快速失败、无 image capability contract、无容器端 E2E 零 stdin 证明——不得宣称完整 non-interactive 达成 |
| `aisc run --profile proxy` | v2 兼容别名 | 映射 `--network proxy`，不进入 profile domain、不持久化；与显式 `--network direct` 冲突→exit 2；safe/unsafe 未提前实现 |

**边界**：未实现/仍延期——裸 `config` 交互写、`provider use/show`、`run --provider`、`proxy enable/disable`、`profile safe/unsafe`、`brief/logs/clean`。

---
## v2.1.0-dev (2026-07-23) - 集成 OpenAI Codex CLI

### 动机

集成 OpenAI Codex CLI 到 AISC 项目中，与 Claude Code CLI 并行安装，为用户提供多 AI CLI 选择。参考 Claude Code CLI 的安装模式，使用 npm 全局安装，无需 tmux 依赖。

### 变更

- **Dockerfile**：
  - 新增 `CODEX_VERSION` 构建参数（默认 `latest`）
  - npm 安装层同时安装 `@openai/codex@${CODEX_VERSION}`
  - 创建 `codex-wrapper` 脚本并集成到镜像
  - 更新 CRLF 清理逻辑，包含 codex 包装器
  - 更新注释说明不处理 `codex-real` 二进制（与 `claude-real` 同理）

- **codex-wrapper**（新增）：
  - 类似 `claude-wrapper` 的结构
  - 从 `$CODEX_CONFIG_DIR/settings.json` 注入环境变量
  - 直接执行 `codex-real`，无需 `--dangerously-skip-permissions` flag
  - 支持 Codex 配置文件的环境变量注入

- **entrypoint.sh**：
  - 路径模型新增 `GLOBAL_CODEX_DIR`（`/home/AISC/.codex`）和 `PROJECT_CODEX_DIR`（`/home/AISC/app/.codex`）
  - 作用域选择从 "Claude 作用域" 改为 "AI CLI 作用域"，适用于 Claude + Codex
  - 支持 `CLI_SCOPE` 环境变量（兼容旧的 `CLAUDE_SCOPE`）
  - 按作用域初始化 Codex 配置目录（项目模式创建 `.codex` 目录）
  - 启动菜单新增第三个选项：`3) codex` 直接启动 Codex
  - 支持 `docker run ... codex` 直接启动 Codex CLI
  - 导出 `CODEX_CONFIG_DIR` 环境变量到 `~/.bashrc`
  - 初始化消息从 "Super Claude 工作站" 改为 "AISC AI 工作站"

- **版本更新**：
  - `VERSION`: `2.0.5` → `2.1.0-dev`
  - `config/versions.env`: 新增 `CODEX_VERSION=latest`
  - `AISC_VERSION`: `v2.0.5` → `v2.1.0-dev`

- **README.md**：
  - 项目描述更新为"运行 Claude Code 和 OpenAI Codex 的个人开发工具"
  - 所有版本号从 `v2.0.4-dev` 更新到 `v2.1.0-dev`
  - 新增"使用 Claude Code 或 Codex"章节
  - 添加 Codex 配置说明和使用示例
  - 说明两种作用域模式对两个 CLI 的支持

- **CHANGELOG.md**（新增）：
  - 详细记录 v2.1.0-dev 的所有变更
  - 包含技术细节和设计决策

- **docs/v2.1.0-dev-testing.md**（新增）：
  - 完整的测试清单
  - 覆盖构建、启动、配置、功能和兼容性测试

### 设计决策

- **双 CLI 并行**：Codex 与 Claude Code 同时安装在容器中，互不干扰
- **独立配置目录**：Codex 使用 `.codex`，Claude 使用 `.claude`，配置隔离
- **统一作用域管理**：临时/项目两种模式同时适用于两个 CLI
- **共享 AISC 配置**：providers.json、API keys 等配置在 `.aisc` 目录中共享
- **无 tmux 依赖**：按要求，容器中不安装 tmux

### 关键特性

1. **双 CLI 支持**：容器内同时提供 Claude Code 和 Codex
2. **独立配置**：每个 CLI 有独立的配置目录，互不干扰
3. **统一管理**：共享 AISC 配置目录（providers.json、API keys）
4. **灵活启动**：支持交互式菜单或直接指定 CLI
5. **作用域隔离**：临时模式和项目模式对两个 CLI 都生效

### 取舍

- **Codex 配置简化**：Codex 配置目录结构比 Claude 简单，仅创建目录，首次运行时由 Codex 自动生成配置文件
- **环境变量命名**：新增 `CODEX_CONFIG_DIR`，保持与 `CLAUDE_CONFIG_DIR` 命名一致性
- **启动菜单扩展**：从 2 个选项（bash/claude）扩展到 3 个（bash/claude/codex）
- **向后兼容**：保持 `CLAUDE_SCOPE` 环境变量兼容性，新增 `CLI_SCOPE` 作为统一名称

### 验证

- 所有代码文件已提交到本地 main 分支
- 文件变更统计：+242 行, -48 行
- 创建 2 个提交：
  1. `feat: 集成 OpenAI Codex CLI 作为 v2.1.0-dev` (6b4372c)
  2. `docs: 添加 v2.1.0-dev 变更日志和测试清单` (4914645)
- 由于当前 WSL 环境无 Docker daemon，未执行构建测试

### 已知限制

- Codex 需要 OpenAI API 认证（ChatGPT Plus/Pro/Enterprise 或 API Key）
- 两个 CLI 使用不同的配置目录，不共享历史记录
- 当前环境无法执行 Docker 构建测试，需在有 Docker 的环境中验证

### 测试建议

在有 Docker 的环境中执行以下测试：

```bash
# 构建镜像
docker build -t aisc:v2.1.0-dev -f container/Dockerfile .

# 验证两个 CLI 都已安装
docker run -it --rm aisc:v2.1.0-dev claude --version
docker run -it --rm aisc:v2.1.0-dev codex --version

# 测试启动菜单
docker run -it --rm aisc:v2.1.0-dev

# 测试直接启动 Codex
docker run -it --rm aisc:v2.1.0-dev codex
```

### v2.1.0-dev 增量 (2026-07-23)

**变更**：

- **默认启动选项改为 bash**（commit `121376d`）：
  - 启动菜单默认项从 `claude` (2) 改为 `bash` (1)
  - 空输入或无效输入默认进入 bash
  - 提示文本更新标注默认选项

- **daemon 启动后自动 enable proxy**（commit `93beecb`）：
  - `cc-switch daemon start` 后自动执行 `cc-switch proxy -a claude enable` 和 `-a codex enable`
  - 确保容器启动后 claude/codex 出站请求被 cc-switch 代理层接管

- **启动输出清理**（commit `93beecb`）：
  - 删除"当前供应商"显示行（`🌐 当前供应商: ...` / `🔗 API 节点: ...`）
  - `.codex` 跳过复制提示对齐 `.claude` 文案，追加"(保护您的自定义修改)"

- **容器运行身份 root 化**（commit `f8c41ef` + 后续提交）：
  - 放弃 AISC 用户，全程以 root 运行
  - 移除 `sudo` 调用、移除 `--user 1000:1000` docker run 参数
  - 路径模型从 `/home/AISC` → `/root`
  - `IS_SANDBOX=1` 环境变量告知 AI CLI 当前处于隔离容器
  - 简化权限修复逻辑（不再需要 chown/sudo fallback）
  - 统一 installer/mihomo/cc-switch 等所有组件以 root 身份运行
  - `cs`/`entrypoint`/`launcher`/`path-resolve` 全链路路径更新

- **cc-switch daemon 启动加固**（commit `0511280` + 后续提交）：
  - daemon 改用 `--detach` 模式，避免 shell 后台任务与 proxy enable 争抢 pidfile/socket
  - 增加 readiness 轮询（40 次 × 0.25s = 最多 10s），确认 daemon 可达后再操作
  - 启动前初始化 Codex provider：优先导入用户现有 `config.toml`，fallback 到内置 `codex-official`
  - Codex 路由仅在 provider 已配置时才启用，缺失时给出明确警告
  - daemon 启动失败时输出启动日志和 `daemon logs` 路径用于排障
  - 更新测试覆盖新流程（断言 readiness → provider init → proxy enable 顺序）

---

### cc-switch 运行时集成与 Provider 目录共享 (2026-07-23)

将 cc-switch v5.9.2 的运行时（SQLite 数据库、daemon 后台服务、TUI）集成到 AISC 容器中，建立统一的 Provider catalog 共享机制。

**变更**：

- **cc-switch daemon 自动启动**（`container/entrypoint.sh`）：
  - §3.1 新增：容器启动时执行 `cc-switch daemon start`，日志写 `/tmp/cc-switch-daemon.log`
  - 仅启动 daemon supervisor，**不自动 `proxy enable`**——不改变默认代理路由
  - 失败仅 warn，不阻断容器启动
- **cc-switch 配置根项目化**（`container/entrypoint.sh`）：
  - 新增 `CC_SWITCH_CONFIG_DIR` 环境变量 → `<workspace>/.aisc/.cc-switch/`
  - cc-switch 的 SQLite 数据库、设置、备份均存于此，随项目挂载持久化
  - entrypoint 确保目录可写（`ensure_writable`），收紧权限（`chmod 700` + `stat` 验证）
  - 导出到 `~/.bashrc` 供后续 shell 会话复用
- **Provider catalog 共享链路**（`container/entrypoint.sh` + `container/claude-switch`）：
  - `.aisc/providers.json` 仍为 AISC 主 catalog（首次从内置 bundle 初始化）
  - `.aisc/.cc-switch/providers.json` → `../providers.json` 相对符号链接
  - 不支持 symlink 的文件系统退化为启动时 `cp` 刷新副本（含诊断提示）
  - 若两路径已存在独立文件且内容不同 → 保留 cc-switch 版本并告警
- **`cs` 切换后同步到 cc-switch SQLite**（`container/claude-switch`）：
  - `switch()` 末尾新增 `cc-switch --app claude provider import-live`（best-effort）
  - `cs <provider>` 后 cc-switch TUI/daemon 实时感知同一选中 provider
- **`cs` provider 解析优先级调整**（`container/claude-switch`）：
  - 显式 `PROVIDERS_JSON` env → `AISC_DIR` → `~/.aisc` → Docker 内置路径
  - entrypoint 导出 `PROVIDERS_JSON="$CC_SWITCH_CONFIG_DIR/providers.json"`
- **scope wrapper 扩展到 6 个运行时变量**（`src/aisc/cli/commands/container.py`）：
  - `_SCOPE_WRAPPER` 从读取 2 个变量扩展到 6 个：`CLAUDE_CONFIG_DIR`、`CC_SWITCH_CONFIG_DIR`、`AISC_DIR`、`PROVIDERS_JSON`、`CODEX_CONFIG_DIR`、`CODEX_HOME`
  - fail-closed：任一必需变量缺失 → exit 101，不回退家目录
  - 仅通过 `/proc/1/environ` 读取，不 eval，特殊字符安全
- **README 同步**：Provider 路径、`.aisc/.cc-switch/` 目录、`aisc switch --quick` 作用域变量说明同步更新

**设计决策**：
- **Provider JSON 符号链接而非硬拷贝**：两方始终读同一份文件，避免漂移。不支持 symlink 则退化 cp。
- **daemon 仅 supervisor，不 proxy enable**：proxy 路由变化涉及端口/路由，留给用户显式控制。
- **`import-live` 而非直接写 SQLite**：尊重 cc-switch schema 所有权，通过 CLI 导入；best-effort 不阻断 `cs`。
- **scope wrapper 完整运行时上下文**：`docker exec` 新进程精确复现 PID 1 环境，无需猜测配置路径。

**取舍**：
- **symlink 依赖文件系统**：ext4/xfs/btrfs/APFS 支持；CIFS/NFS 某些配置不支持。退化路径就绪。
- **daemon 启动在 entrypoint 而非 Dockerfile**：`CC_SWITCH_CONFIG_DIR` 在 entrypoint 阶段才确定（临时/项目模式），构建期无项目挂载。
- **`import-live` 日志在 `/tmp`**：仅诊断用途，容器 `--rm` 后清理。

**验证**：
- `bash -n` 通过（`container/entrypoint.sh`、`container/claude-switch`）
- Python `py_compile` 通过（`src/aisc/cli/commands/container.py`）
- `git diff --check` clean
- 容器内手动验证：`cc-switch daemon start` 成功、symlink 创建正确、`cs deepseek` 后 `cc-switch provider list` 显示一致、`aisc switch --quick ark` scope wrapper 6 变量全通过、`CODEX_HOME` 正确指向 Codex 配置目录
- 全量 unit test：**521 OK, 15 skipped**（无回归）

---

### Codex 项目配置初始化增强 (2026-07-23)

将 Codex 项目 `.codex` 目录的初始化逻辑与 Claude `.claude` 对齐——从镜像内置副本完整复制，而非依赖 Codex 首次运行自动生成。

**变更**：

- **Dockerfile**：新增 `RUN codex --version` 初始化全局 `.codex` 目录，镜像内预置 Codex 出厂配置
- **entrypoint.sh**：项目模式 Codex 初始化从「仅建空目录」改为「从镜像 `.codex` 复制」（空目录检测 + 已有配置跳过），逻辑与 `.claude` 完全对称
- **`CODEX_HOME` 导出**：新增 `CODEX_HOME="$CODEX_CONFIG_DIR"`，写入 `~/.bashrc` 和 scope wrapper

**取舍**：预初始化避免 Codex 首次运行需网络拉取 cloud config；与 `.claude` 对称降低维护负担。

**验证**：`bash -n` 通过；容器内项目模式多次启动验证——首次复制、二次跳过、空目录补全，均正确。

---

### Provider 路径收敛与 Codex 出厂目录固化 (2026-07-23)

第二轮迭代：简化 Provider 目录结构、固化 Codex 镜像出厂骨架、cc-switch daemon 后台化。

**变更**：

- **Provider 路径收敛**（`container/entrypoint.sh` + `container/claude-switch`）：
  - 删除 `.aisc/providers.json` 中间路径、删除符号链接策略
  - `providers.json` 唯一项目路径：`<workspace>/.aisc/.cc-switch/providers.json`
  - 旧项目兼容：若检测到旧版 `.aisc/providers.json`，首次启动时 `cp` 迁移到 `.cc-switch/` 后 `rm` 旧文件
  - `cs` fallback 优先级：`PROVIDERS_JSON` env → `.aisc/.cc-switch/providers.json` → `~/.aisc/providers.json` → Docker 内置
  - 删除 `AISC_PROVIDERS_JSON` 变量，仅保留 `PROVIDERS_JSON`
- **Codex 出厂目录固化**（`container/Dockerfile`）：
  - 不再依赖 `codex --version` 自动生成配置（该命令不创建 `CODEX_HOME`）
  - 显式创建 Codex 目录骨架：`config.toml`（空但合法）、`skills/`、`rules/`、`sessions/`、`shell_snapshots/`、`tmp/`
  - 从 `_bundle/skills/` 预置 Codex skills（与 Claude 共享 SKILL.md 格式）
  - `global-claude.md` → `.codex/AGENTS.md`（sed 替换 Claude→Codex），保留 karpathy-flow 编码规范
  - 生成 `.factory-version` 哈希用于后续项目 `.codex` 升级检测
  - 镜像内 `.codex` 目录完整性硬 fail：entrypoint 检测不完整则 `exit 1`（不静默降级）
  - 复制失败也硬 fail（与 `.claude` 的错误处理不一致问题修复）
- **cc-switch daemon 后台化**（`container/entrypoint.sh`）：
  - `cc-switch daemon start` 改为后台执行（`&`），不再阻塞 entrypoint 启动流程
  - 保留日志到 `/tmp/cc-switch-daemon.log`，不阻塞不告警
- **scope wrapper + 测试同步**（`tests/test_cc_switch_runtime.py`）：
  - Provider 路径断言更新：`PROVIDERS_JSON` → `.cc-switch/providers.json`
  - 新增 Dockerfile Codex 出厂目录静态验证
  - 新增 legacy migration 断言
  - `cs` fallback 优先级断言更新

**设计决策**：
- **单一路径而非符号链接**：符号链接在跨文件系统场景（CIFS/NFS/某些容器运行时）不可靠。单一路径 + 旧文件迁移更稳健。
- **Codex 出厂目录与 Claude 技能共享**：两个 CLI 原生支持同一 SKILL.md 格式，`_bundle/skills/` 重复 COPY 两份而非共享目录——保证项目模式整目录复制时各自独立、互不污染。
- **daemon `&` 后台化**：`cc-switch daemon start` 是常驻前台进程，不放后台则 entrypoint 永远等不到启动菜单。

**取舍**：
- **旧 `.aisc/providers.json` 被迁移后删除**：不再保留备份。用户若手动编辑旧路径，数据会在下次启动时丢失——README 已更新文档指向新路径。
- **Codex skills 从 `_bundle` COPY 而非构建期 install**：与 Claude skills 策略一致（自包含构建、离线可用）。

**验证**：
- `bash -n` 通过；Python `py_compile` 通过；`git diff --check` clean
- `PYTHONPATH=src python3 -m unittest tests.test_cc_switch_runtime -v`：全通过
- 全量 unit test：521 OK, 15 skipped（无回归）

---

### 已知未完成 / 技术债（如实记录，不做为已完成）

- **密钥非唯一存储**：`claude-switch` 将 `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY` 写入 `.claude/settings.json`（env 块），与 `.aisc/secrets/api-keys` + `.cc-config/api-keys` 形成三处密钥副本。settings.json 写入是 Claude Code 运行依赖，但密钥明文落此文件是 P3 待处理的安全边界。
- **gitleaks 未闭合门禁**：`continue-on-error: true` + `docs/` 整体 allowlist。密扫运行但不阻断合并。
- **无 GUI / P3 计划**：v2.0.0-dev 不包含 GUI、TUI 重做或 P3 任何条目。

---

## v1.5.1 (2026-07-14) - 权限修复 + 简讯 URL 增强

### 变更
- **`entrypoint.sh`**：项目模式下对 `.claude` 目录追加 `sudo chown -R AISC:AISC`，解决挂载卷文件属主非 uid 1000 导致 `cs` 写 `settings.json` 时报 `EACCES: permission denied`。
- **`scripts/03_build_image.sh`**：临时构建上下文目录（`image/api_route_demo/`、`image/ai_brief/`）`mkdir -p` 前先 `rm -rf`，避免上次 `sudo` 构建残留 root 文件导致普通用户 `cp` 权限拒绝，`start.sh` 不再强制要求 sudo。
- **`ai_brief/brief.py`**：`--ai` 模式的素材和 prompt 增加原始链接 URL（`🔗`），LLM 输出每条简讯下方附带来源 URL，方便查看详情。

### 取舍
- **`.claude` chown 放在 entrypoint 而非构建期**：构建期 `USER AISC` 后 `chown` 对挂载卷无效（卷在运行时挂载）。entrypoint 启动时 `sudo chown` 自愈，利用 AISC 已在 sudoers NOPASSWD。

---

## v1.5.0 (2026-07-12) - AI 每日简讯注入启动头（TLDR + The Rundown）

### 动机
启动头那段「🚀 [Super Claude] 工作站初始化中... + 后端状态 + 分隔线」纯装饰、无信息量。把每日 AI 资讯（TLDR AI + The Rundown AI）抓取 + LLM 中文精选后注入启动头，每次进容器先看今日要闻；同时支持单独 CLI 输出。

### 变更
- **`ai_brief/` 新建**（项目根，与 `api_route_demo/` 平级）：
  - `brief.py`：**stdlib-only**（urllib + xml.etree + re），Py3.11（容器）/3.14（宿主）双端零安装。flags：`--date`/`--days`/`--top`/`--source`/`--ai`/`--save`/`--no-cache`/`--strict`。
  - `run.sh`：薄包装（`exec python3 brief.py`），绕 DrvFs 无 exec 位。
  - `README.md` + `.gitignore`（忽略 `cache/`）。
- **数据源**（curl 侦察确认）：
  - TLDR：RSS `tldr.tech/api/rss/ai` 拿期次 -> issue 页 `article.mt-3` 块解析（`a.font-bold` 链接 + `h3` 标题 + `div.newsletter-html` 摘要）。
  - Rundown：**无 RSS** -> `sitemap.xml` 过滤 `/p/` 按 `<lastmod>` 取最新 -> post 页（服务端渲染，964KB）解析 H1 头条 + 正文外链次要要闻。
- **规则筛选**：去赞助（blocklist：doubleclick/strandsagents/awscloud/videoask/typeform 等）+ 跨源去重（URL + 标题词集）+ 每源 Top N。Rundown 额外过滤裸域名/导航页/碎片锚文本。
- **`--ai` LLM 中文摘要**：读 cs 后端 env，urllib POST `/v1/messages` 精选 5 条 + 一句话中文。模型优先 `ANTHROPIC_DEFAULT_HAIKU_MODEL`（haiku/flash 档，快+省），回退 `ANTHROPIC_MODEL`。**兼容 GLM thinking 块**（遍历 content 取首个 `type:text`）；`max_tokens=4096`；失败回退规则英文输出。
- **终端渲染**：输出纯文本（编号 + 缩进 + emoji 段头 + 日期），无 `##`/`**` markdown 标记，终端直读；`--ai` 头带日期 `🤖 AI 精选简讯 · YYYY-MM-DD（N 条）`。
- **Dockerfile**：LiteLLM 层后新增 `COPY ai_brief/ -> /home/AISC/ai_brief/`（stdlib-only，无需 pip）。
- **entrypoint.sh**：mihomo 段（§3.5）后、启动菜单（§4）前新增 §3.6 - **有后端配置**（§3 算好的 `BASE_URL`+`AUTH`）才跑 `timeout 45 python3 /home/AISC/ai_brief/brief.py --ai --top 5`（中文精选）；**无后端**（临时作用域/cc/全新）-> 一行「简讯跳过」提示，不显示英文 fallback。BRIEF 空（timeout 杀/全失败）打印诊断行；绝不阻断启动。
- **构建脚本（`03_build_image.{sh,ps1}`）**：api_route_demo staging 旁加 `ai_brief`（brief.py + run.sh）临时进 `image/ai_brief/`，构建后清理。

### 取舍
- **stdlib-only 而非 bs4/requests**：换 Py3.11/3.14 双端零安装（契合 DrvFs/PEP 668/uvloop 约束）。正则解析规整 HTML，站点改版失效则优雅降级（空输出 + exit 0）。
- **启动头走 `--ai` 中文（haiku/flash 档）**：用户要中文；flash 模型控延迟/成本（~10s LLM + 6s 抓取 ≈ 15s）。后端未配/超时 -> 回退规则英文 + 提示；`timeout 45` 兜底（LLM 内部 30s 超时则回退）。实测 GLM-5.2[1m] 大模型 thinking 读超时，改 flash 后稳定。
- **无后端跳过简讯**：临时作用域读镜像出厂 settings.json（无 cs env），--ai 无 LLM 可用；§3.6 检测 `BASE_URL`+`AUTH`，无则一行跳过提示，不回退英文废话。
- **终端纯文本非 markdown**：启动头是终端输出，markdown 源码（`##`/`**`）不渲染显累赘；改纯文本编号+缩进直读。
- **每源独立 try + http_get 单次重试**：单源间歇失败不影响另一源，部分成功仍渲染；`--strict` 供调试非零退出。
- **`--rm` 容器缓存随容器销毁**：每次 `docker run` 重抓+LLM ≈ 15s；宿主单跑或同会话内重跑命中缓存。
- **日期取源站「最新已发刊」一期**：美 newsletter，北京早晨时当日刊未发（美早间=北京晚），故周二早显示周一 7.13 是正确的最新期，非 bug。

### 测试
- 宿主 `brief.py` 全 flag：双源/`--source`/`--top`/`--no-cache`/`--save`/缓存命中/`--ai`（haiku/flash 出中文 5 条 + 日期头）/断网静默 exit 0/`--strict` exit 1。
- 容器内（Python 3.11 + 容器网络）：双源抓取渲染 exit 0。
- **端到端重建**（`super-claude:latest`，项目挂载读 cs 后端）：启动头显示 `📰 今日 AI 简讯：🤖 AI 精选简讯 · 2026-07-13（5 条）` + 5 条中文一句话，纯文本无 markdown 标记；容器正常继续 exec（exit 0）。
- 全脚本 `bash -n` + `ast.parse` 通过。

### 其他
- entrypoint §3.6 注入点在 mihomo 之后（网络就绪）。
- 缓存默认开（`--no-cache` 关），非 `--cache` flag -- entrypoint 用 `--ai --top 5`。
- README 头版本号 v1.4.0 -> v1.5.0。

### v1.5.0 增量 — 多源扩展（5 源）+ 分类面板 TUI

在初版 TLDR+Rundown 双源基础上，curl 侦察见现存源偏向行业新闻（融资/诉讼/模型发布），用户要的是**工具+工作流+方法**。补 3 个 RSS/Atom 源并重做输出格式。

**新增数据源**（curl 验证存活+内容风味）：
- **Simon Willison**（`simonwillison.net/atom/everything/`，Atom）：LLM 实战工具 + 工作流，最贴合。
- **Changelog**（`changelog.com/news/feed`，RSS）：开发工具/开源/agent 工作流讨论。
- **HN Show HN**（`hnrss.org/show`，RSS）：新项目/工具火龙，加 AI/dev 关键词过滤（`ai/llm/agent/tool/cli/dev/claude/cursor/...`）。

**源码重组**（`ai_brief/brief.py` 大幅重写）：
- **源注册表**：`SOURCE_FETCHERS` dict + `SOURCE_GROUPS`（`all`/`tools`/`industry`/`workflow`），`--source` 支持组合（如 `tldr,simon`）。
- **通用 RSS 抓取**：`rss_fetch()` 兼容 RSS `<item>` + Atom `<entry>` + 命名空间（`{http://www.w3.org/2005/Atom}`，Simon feed 实测）。Atom `<link href="...">`（self-closing 有属性无文本）vs RSS `<link>url</link>`（文本值）两格式通吃。**Python 3.14 ElementTree 适配**：`el.find("link")` 对命名空间元素的行为变化，改为 namespace-aware 查找 + 独立 `if None` 检查（避 `or` 触 DeprecationWarning）。
- **HN 过滤**：`hn_filter()` 检查标题+URL 含白名单关键词，拉 3 倍条目再过滤，保证过滤后够 top 数。

**分类面板 TUI**：
- 3 分类：🛠️ 新工具 / 🔧 工作流/方法 / 📰 行业动态。
- 规则模式：按源分到预定义分类（`SOURCE_CATEGORIES`），每分类下子源分块，编号+缩进。
- `--ai` 模式：改 prompt 让 LLM **跨源按内容动态分类**（不按源），每类最多 4 条中文一句话，输出即用。实测深度求索 flash 中文分类质量好。
- 新 `--source` 快捷值：`all`（5 源）/ `tools` / `industry` / `workflow` / 逗号组合。

**取舍（增量）**：
- **Atom 命名空间兼容**：Simon 用 Atom（非 RSS），字段在 `{ns}title/link/summary` 下，通用 `rss_fetch` 同时兼容两格式（按 `els[0].tag` 检测 ns）。
- **分类不由源绑定**：规则模式按预定义表分，`--ai` 由 LLM 按内容分（更准）。
- **仅加 RSS 源不换掉 TLDR/Rundown**：用户选择保留（原说要中文 TLDR，后放宽；Rundown 虽无标准 feed 但因用户要求保留）。

### 测试（增量）
- 宿主：5 源各自单独拉（含 Atom 命名空间修复）、`--source all` 分类规则输出、`--ai` 分类中文（🛠️4 条/🔧4 条/📰4 条）、`--source tools/industry/tldr,simon` 组合。
- 容器端到端：因 Docker bridge 网络故障未重跑（宿主全量验证 + 先前端到端已证 entrypoint §3.6 调用链有效）。待 Docker 恢复后重建 + 验证启动头分类面板。

---

## v1.4.0 (2026-07-10) - LiteLLM 协议转换 + cc-switch-cli 集成

### 动机
TODO「claude code CLI外配置 cc-switch-cli」+ 汇报演示「Claude Code 接入 OpenAI 格式渠道的技术可行性」。内置 `cs` 只切 Anthropic 兼容后端（不改协议）；需 LiteLLM 做 Anthropic↔OpenAI 协议转换，并集成 cc-switch-cli（4.1k stars，多 AI CLI 管理）与 cs 共存。

### 变更
- **LiteLLM Demo（`api_route_demo/` 新建）**：
  - `config.yaml`：模型映射 `claude-3-7-sonnet-20250219`（Claude Code 强校验）-> `openai/gpt-4o`，占位 key。
  - `start_proxy.sh`：交互式输入 base_url + api_key，生成 `.config.runtime.yaml`（含 key 不入 git）；宿主/容器双环境（有 `run_proxy.py` 走 venv python，否则直接 `litellm`）。
  - `run_claude_demo.sh`：注入 `ANTHROPIC_BASE_URL=http://localhost:4000` + 起 claude。
  - `run_proxy.py`：宿主机 Python 3.14 绕 uvloop 不兼容（monkeypatch `ProxyInitializationHelpers._get_loop_type`）。
- **Dockerfile**：
  - LiteLLM 层（venv 后）：COPY demo + `pip install litellm[proxy]`（清华源，`USE_CN_MIRROR` 控制）+ `EXPOSE 4000`；demo 放 `/home/AISC/api_route_demo`（避开 app 挂载点）。
  - cc-switch-cli 层（litellm 后）：`ARG CC_SWITCH_VERSION=v5.9.0` + 下载 musl 二进制（复用 GH_PROXY 多镜像）-> `/usr/local/bin/cc-switch`；`USER root` 临时切 root 写再切回 AISC，**不破坏 litellm 缓存**。
- **构建脚本（`scripts/03_build_image.{sh,ps1}`）**：
  - 国内镜像源从单一 daocloud 改**多源 fallback**（daocloud -> nju -> 163）：优先本地缓存（`docker image inspect`），否则测 manifest 端点（仅 200/401 算通，403 排除），全不通回退官方源。
  - build 前把 demo 3 文件 cp 进 `image/api_route_demo/`（context=image/ 取不到项目根），build 后清理。
- **README**：版本 v1.2.2 -> v1.4.0；加「OpenAI 协议转换」+「cc-switch-cli」亮点与使用章节。

### 取舍
- **cc-switch 与 cs 共存**（非替代）：命令名 `cc-switch` vs `cs` 不冲突；cc-switch 功能全（多 AI CLI 管理），cs 轻量内置，按需选。
- **cc-switch 放 litellm 层后**：litellm pip 重型层缓存保留，重建仅 cc-switch 下载（~10s）；代价是 `USER root`/`USER AISC` 切换（比 sudo 干净）。
- **start_proxy.sh 生成运行时配置**（不覆盖原 config.yaml）：`.config.runtime.yaml` 含 key 加 `.gitignore`；非交互可预设 `OPENAI_API_BASE`/`OPENAI_API_KEY`。
- **构建脚本多源 fallback**：daocloud `/v2/` 通但 manifest TLS 超时、nju 403、Docker Hub 直连超时——多源 + 本地缓存优先是当前网络最稳方案；极端全不通才需配 daemon mirror。
- **宿主机 Python 3.14 兼容**：orjson 强制 3.11.9（litellm 钉 3.10.15 无 cp314 wheel）、uvloop monkeypatch（3.14 移除 `BaseDefaultEventLoopPolicy`）；容器 Python 3.11 无此问题。

### 测试
- 构建成功（`super-claude:latest`，2.55GB）：cc-switch `--version` -> `cc-switch 5.9.0`，ghfast.top 下载通。
- 容器内：`cs` + `cc-switch` 共存（`/usr/local/bin/`）；`/v1/models` 返回 `claude-3-7-sonnet-20250219`（owned_by: openai）；`/v1/messages` 带 placeholder_key 上游 401（config 无语法错误）。
- 宿主机回归：start_proxy.sh 改后仍走 run_proxy.py 分支，proxy 6s 就绪；交互式输入生成正确 YAML，`/health/readiness` 200。

### 其他
- TODO「cc-switch-cli」标完成。
- 发现 `docker rmi -f`（选 [2]）会清构建缓存，增量改动应选 [3] 新镜像名或保留镜像。

---

## v1.3.2 (2026-07-04) — 容器内 Python 运行时

### 动机
TODO「配置 docker 容器系统的 python」——容器内无 Python，Claude Code 无法跑 Python 脚本 / pip 装包。

### 变更
- **Dockerfile**：新增 Python apt 层（放 sed CRLF 之后，避免使 npm/claude 重型层缓存失效）——`python3 python3-pip python3-venv python-is-python3`（Debian 12 → Python 3.11）。
- **默认 venv**：`python3 -m venv /home/AISC/.venv`（USER AISC 后创建，AISC 可写）+ `ENV PATH="/home/AISC/.venv/bin:$PATH"`（venv 挂 PATH 头）。
- 绕过 Debian 12 PEP 668：系统 `pip install` 受限（externally-managed-environment），venv 内 `pip install` 直达，无需 `--break-system-packages`。

### 取舍
- **venv 在镜像内（`--rm` 每次重置）**：pip 装的包每次容器重启回到出厂（仅 pip 升级）。如需持久化包，加 requirements.txt + 启动安装脚本（未做，按需）。
- **Python 版本**：用系统 3.11（Debian 12 自带），不引入 pyenv/deadsnakes（够用）。
- **层位置**：python apt 放 sed CRLF 之后，npm/claude 重型层缓存命中，重建仅 ~30s。

### 测试
- 构建：python apt + venv 层新建，重型层 CACHED。
- 容器内：`which python` → `/home/AISC/.venv/bin/python`；`python --version` → 3.11.2；`pip install requests` → 成功（PEP 668 绕过）。

### 其他
- PLAN 文件从 `docs/TODO/` 移到 `docs/plans/`（与 TODO 分开）。
- TODO #3（启动器规范化）、#5（python）标完成。

---

## v1.3.1 (2026-07-04) — 项目目录重构（按职责分组）

### 动机

根目录 ~18 项混杂（Dockerfile/entrypoint/claude-switch/wrapper/_bundle/downloads/commands/启动器/文档/生成器…），违反高聚合。按职责分组到 `image/` / `scripts/` / `tools/` / `docs/`，根目录收敛到 7 项（入口 + README + 配置 + 锁文件）。

### 变更

- **`image/`**（新建，= 镜像构建上下文）：Dockerfile + entrypoint.sh + claude-switch + claude-wrapper + claude-settings.json + global-claude.md + mihomo-build-config.js + commands/ + _bundle/ + downloads/ 全部搬入。构建上下文从根改为 `image/`，**Dockerfile COPY 路径零改动**（全相对上下文）。
- **`tools/`**（新建）：stage-skills.sh + stage-mihomo.sh 搬入；`DST` 改为 `image/_bundle`、`image/downloads`（`$(dirname "$0")/..` 推导项目根）。
- **`docs/`**（新建）：devlog.md + TODO/ 搬入。
- **`scripts/03_build_image.{sh,ps1}`**：构建命令加 `-f $PROJECT_ROOT/image/Dockerfile` + 上下文改 `$PROJECT_ROOT/image`。
- **根目录**：仅留 README.md + .gitignore + .gitattributes + 3 个入口(.bat/.sh/.command) + skills-lock.json。
- **README**：项目结构章节重写；构建命令全部更新（`docker build -f image/Dockerfile ... image/`）；引用更新（stage-*.sh → tools/，downloads/ → image/downloads/，devlog.md → docs/devlog.md）。

### 取舍

- **构建上下文 = `image/`**：Dockerfile COPY 全相对上下文，搬入后零改动；额外收益——上下文从根（含 `.git/`/62MB 二进制/scripts/docs）缩到 `image/`，**传输更小、构建更快**。
- **`.gitattributes`/`.gitignore` 不动**：模式全局（`*.sh`/`*.ps1`/`claude-switch` 按文件名匹配子目录；`.claude/`/`.deploy/` 全局忽略），移动后仍生效。
- **宿主 `.claude/mihomo/` 留根**：02 写、04 挂载的代理配置是宿主运行时产物，非镜像输入。
- **`skills-lock.json` 留根**：未被构建/启动器引用，锁文件约定根。
- **版本号**：v1.3.0（模块化）已推送，本次续 v1.3.1（目录重构），不 force-push 重写历史。

### 测试

- `bash -n` 全 .sh；PS 语法全 .ps1。
- `docker build -f image/Dockerfile image/` 构建成功（验证上下文 + COPY）。
- e2e：启动器流水线（镜像存在→run）两平台通过。

---

## v1.3.0 (2026-07-04) — 启动器模块化重构（流水线 + 状态解耦）

### 动机

`launcher.ps1`（131 行）/ `启动_AI工作站.sh`（134 行）随 Mihomo TUN、API 配置等功能膨胀，构建/代理/运行逻辑耦合在单体脚本里，违反低耦合高聚合。拆为 4 个生命周期模块 + 薄流水线入口，模块间用状态文件解耦。

### 设计决策

- **D1 · 按平台 .sh + .ps1 平行**（已与用户确认）：bash/PowerShell 各平台自带，零宿主依赖（不选 Node.js 调度——宿主 Node 不可控，违反"开箱即用"）。代价：两套平行逻辑同步维护。
- **D2 · 状态文件解耦**：`.deploy/state.env`（KEY=value，gitignored）。只存简单值 `IMAGE`/`PROXY_ENABLED`/`CONTAINER_NAME`/`DO_RUN`；**路径不入状态**——各模块从 `$0`/`$PSScriptRoot` 推导 `PROJECT_ROOT`，避免空格/特殊字符破坏 `source`/解析。bash `source`/grep 读、PS 正则读；写用追加+去重。
- **D3 · 入口极薄**：根 `.sh`/`.bat` 只按序调 4 模块（pipeline）。
- **D4 · 行为保持**：根文件名 + 双击入口不变；代理 TUI/构建菜单/docker run 参数等价迁移。**API Key 仍在容器内 `cs`**、**作用域仍在 entrypoint**（不挪到宿主 02）。
- **D5 · 容器侧不动**：Dockerfile/entrypoint/mihomo-build-config.js/stage-mihomo.sh 全不变。

### 变更

- **scripts/ 流水线**（新增 12 文件，6 .sh + 6 .ps1）：
  - `run.*` 编排器：`state_init` + 写 `CONTAINER_NAME`/`IMAGE`/`DO_RUN`/`PROXY_ENABLED` 默认值 → 按序调 01-04，任一非零退出即中止。
  - `01_check_env.*`：`docker` 命令存在 + `docker info` daemon 运行；失败友好退出。
  - `02_config_wizard.*`：代理 TUI（y/N → 本地/URL → 下载/拷贝 → 非空校验）→ 写 `.claude/mihomo/config.yaml` + `state(PROXY_ENABLED)`。代理非阻断：失败/跳过 → `PROXY_ENABLED=0` 回退直连（匹配旧行为）。
  - `03_build_image.*`：镜像存在菜单（[1]运行/[2]重建/[3]新名）+ 构建（cache/镜像源提示）+ "立即运行?" → `state(IMAGE, DO_RUN)`。`DO_RUN=0`（选不运行）→ 04 跳过 docker run。
  - `04_launcher.*`：读 state → 清退出的旧容器 → 拼 `docker run`（`PROXY_ENABLED=1` 追加 `--cap-add=NET_ADMIN --device=/dev/net/tun` + 配置只读挂载）。
  - `_state.*`：`state_init`/`state_set`/`state_get`（bash）/ `Init-State`/`Set-State`/`Get-State`（PS）。PS 用 .NET `WriteAllText`（UTF-8 无 BOM + LF）避免 bash `source` 被 BOM/CR 破坏；bash `state_get` 末尾 `tr -d '\r'` 防御。
- **根入口改薄**：`启动_AI工作站.sh` → `exec bash scripts/run.sh`；`一键启动_AI工作站.bat`（ASCII）→ `powershell -File scripts/run.ps1`；`.command` 不变。
- **PS1 BOM**：所有 `scripts/*.ps1` UTF-8 BOM（PS5.1 按 BOM 识别中文）；`.gitattributes` `*.ps1 text eol=lf` 保证提交后 LF+BOM。
- **`.gitignore`**：加 `.deploy/`（运行时状态）。

### 取舍

- **PS 编排用子进程**：`run.ps1` 用 `& powershell -NoProfile -File` 调各模块（独立进程 + `$LASTEXITCODE`），而非 dot-source——dot-source 下模块 `exit 0` 会退出整个 run.ps1，破坏流水线。子进程有 ~1-2s 启动开销，可接受。bash 同理用 `bash scripts/0X.sh` 子进程。
- **DO_RUN 状态位**：03"构建后不运行"需干净中止 04。用 `DO_RUN` 状态位（0/1）而非特殊退出码，符合状态解耦原则。
- **两套平行逻辑**：改提示文案需同步 .sh + .ps1 两份（用户已接受）。

### 测试

- `bash -n` 全 .sh 通过；PS `[Parser]::ParseFile` 全 .ps1 通过。
- e2e 两平台 × 两路径（配/不配代理）全通过：4 模块按序、state.env 正确流转（`PROXY_ENABLED`/`DO_RUN`/`IMAGE`/`CONTAINER_NAME`）、docker run 拿到正确参数（代理路径含 `--cap-add=NET_ADMIN --device=/dev/net/tun` + 配置挂载）。

---

## v1.2.3 (2026-07-04) — 容器内建 Mihomo TUN 透明代理

### 动机

宿主机零代理场景下，让容器内 Claude Code 直连 Anthropic API。在容器内以 Mihomo (Clash Meta) TUN 模式接管全部出站，宿主无需开任何代理；TUI 引导用户完成配置，开箱即用。对应 TODO「clash翻墙配置（docker内部翻墙）」。

### 设计决策（与用户确认）

- **D1 · TUN 补丁容器内权威注入**：宿主启动器只下载/拷贝用户**原始**配置到 `.claude/mihomo/config.yaml`（不打补丁）；`entrypoint.sh` 用 Node 在可写副本上 strip+append。落盘文件保留原始配置，运行时强制含 TUN。理由：容器内 Node+工具必有、每次启动重打、手动丢配置也兜底；宿主环境不可控（Windows BAT 无 Node/awk）。
- **D2 · docker run 特权按需追加**：仅 TUI 选“需要代理”时追加 `--cap-add=NET_ADMIN --device /dev/net/tun` 与配置只读挂载；不配代理则零特权、零 tun 设备依赖，避免宿主缺 `/dev/net/tun` 时启动失败。

### 变更

- **Dockerfile**：apt 增加 `iptables iproute2 ca-certificates`（TUN auto-route 操纵 iptables/路由表、https 下载）；新增 mihomo 下载层（pin `MIHOMO_VERSION=v1.19.27`，arch 自适应）+ geodata 预置层（geoip.metadb/geosite.dat/country.mmdb → `/home/AISC/.mihomo`，单文件失败仅 warn 不阻断）。**下载加固**：优先用 `downloads/` 本地预置（离线/弱网）；否则多镜像轮询（ghfast.top 实测稳，依次 gh-proxy/github.moeyy/ghproxy.net/mirror.ghproxy）+ 强制 `--http1.1`（绕开 curl/GitHub CDN HTTP/2 流异常）+ 短 connect-timeout 快失败 + 直连兜底。
- **stage-mihomo.sh**（新增）：预下载 mihomo.gz + geodata 到 `downloads/`。镜像 `stage-skills.sh`+`_bundle` 自包含哲学；`downloads/` **已纳入 git** → `docker build` 完全不访问 GitHub（详见增量）。
- **entrypoint.sh**：新增 §3.5 — 若 `/etc/mihomo/config.yaml` 存在：Node 读 ro 源 → 通用顶层块剥离（`tun:`/`dns:`）→ 追加规范 `tun:` 块（+ 缺失时补最小 `dns:` 防 53 端口解析死循环）→ 写可写副本 → `sudo -b mihomo -d ~/.mihomo -f 副本` → sleep 2 → pgrep 健康检查 + `curl api.anthropic.com` 探测 → 极客日志。失败仅告警不阻断（便于进 bash 排障）。
- **启动_AI工作站.sh**：新增 `configure_proxy()`（本地文件/URL 二选一，curl 下载，base64 异常检测）+ `docker run` 数组化条件追加 `--cap-add=NET_ADMIN --device /dev/net/tun -v .../config.yaml:/etc/mihomo/config.yaml:ro`。
- **一键启动_AI工作站.bat**：降级为纯 ASCII 三行包装（`chcp 65001` + `powershell -File launcher.ps1`）；中文 UI 与全部逻辑移至 `launcher.ps1`（PowerShell 原生 Unicode）。cmd .bat 对中文有 DBCS 解析缺陷，无法在 .bat 内承载中文（详见增量「Windows 启动器中文化」）。
- **.gitignore**：显式忽略 `.claude/mihomo/`（订阅凭据敏感；`.claude/` 已覆盖，此处防御性显式）。
- **README / devlog**：新增“代理网络（容器内建 Mihomo TUN）”章节（原理图/使用/手动构建/已知限制）+ 数据模型补 `.claude/mihomo/`。

### 取舍

- **DNS 块**：用户 spec 仅列 `tun:`；实测 TUN `dns-hijack: any:53` 无解析器易形成解析死循环 → 仅在用户配置**无** `dns:` 顶层块时补一个最小 `dns:`（fake-ip + 国内外 nameserver/fallback），不覆盖用户已有 `dns:`。
- **mihomo 版本 pin**：v1.19.27（build-arg 可覆盖），换可复现构建；asset `mihomo-linux-<arch>-<ver>.gz` 已核验。
- **mihomo 以 root 启动**：`USER AISC` 无 `CAP_NET_ADMIN`，建 TUN + iptables 必须 root → `sudo`（NOPASSWD sudoers 已就绪）。后台 `sudo -b`，容器退出随 PID1 终止，`--rm` 自动清理。
- **geodata 失败降级**：不阻断构建（GEO 规则不可用，多数订阅仍可用 IP-CIDR/域名规则）。
- **ghproxy flaky**：`GH_PROXY` build-arg 可覆盖；下载逻辑代理→直连回退。

### v1.2.3 增量（多格式订阅自动转换 + 启动器中文化 + 构建下载加固）

- **下载加固（Dockerfile）**：mihomo/geodata 下载层重写——优先用 `downloads/` 本地预置（离线/弱网）；否则多镜像轮询（`ghfast.top` 实测稳，依次 gh-proxy / github.moeyy / ghproxy.net / mirror.ghproxy）+ 强制 `--http1.1`（绕开 curl/GitHub CDN HTTP/2 流异常）+ 短 connect-timeout 快失败 + 直连兜底。修复用户构建时 `mirror.ghproxy.com` SSL 失败 + GitHub HTTP/2 流异常导致下载失败。
- **stage-mihomo.sh（新增）**：预下载 mihomo.gz + geodata 到 `downloads/`。**已纳入 git**（同 `_bundle` 哲学）→ `docker build` 完全不访问 GitHub，国内网络无忧（消除用户提出的「构建期 GitHub 下载慢/失败」风险）。升级 mihomo：改 Dockerfile `MIHOMO_VERSION` 后重跑本脚本更新 `downloads/` 再提交。`downloads/` 为空时构建自动回退多镜像下载。
- **mihomo-build-config.js（新增）**：把原 entrypoint 内联 heredoc 抽成独立脚本（可测、清晰）。职责 = 原始订阅 → mihomo 配置：①格式识别（clash-yaml / base64订阅 / URI直链 / JSON(SIP008)），非 yaml 自动转最小 Clash 配置（proxies + url-test自动选最快 + select + MATCH,PROXY），节点协议支持 ss/vmess/trojan/vless/hysteria2(hy2)；②剥离已有 tun:/dns: 顶层块 → 追加规范 tun:（+ 缺失时补 dns:）。退出码：0 产出配置 / 1 硬失败（空 / 识别为订阅但 0 节点 / 读取失败）。
- **entrypoint.sh**：§3.5 改调 `node /usr/local/bin/mihomo-build-config.js`，去掉大段内联 heredoc。健康检查改用 **curl 探测作主信号**——初版用 `pgrep -x mihomo` 在 3s 时点曾误报「启动失败」（进程名/时序问题），但 mihomo 实际存活并处理了请求；改为 `curl -sS https://api.anthropic.com`（去 `-f`：无 auth 返 401/404，`-f` 会误判失败，任何 HTTP 响应都算可达）。sleep→4 给 url-test 初选时间。curl 失败时用 `pgrep -f 'mihomo -d'` 区分「进程退出 vs 仍在初选」。实测：用户 base64 订阅 → 31 节点 → TUN 接口 `Meta` UP → api.anthropic.com 经 hysteria2 节点可达（HTTP 404）。
- **启动器校验放宽**：`.sh`/`.bat` 去掉「必须含冒号」的 yaml 限制，改为非空即可——格式由容器内识别/转换。
- **Windows 启动器中文化（.bat → .ps1 拆分）**：cmd.exe 的 .bat 对中文有 DBCS 解析缺陷，三方案全败——① UTF-8 文件按 OEM(936/GBK)解析致 3 字节错切，中文片段被当命令执行（`'时多开...' is not recognized`）；② GBK 编码又撞 cmd 第二个 bug（GBK 尾字节落 ASCII 特殊字符区如 `|`/`{`，`if/goto` 上下文不当双字节处理 → `syntax incorrect`）；③ UTF-8 BOM 不被 cmd 识别（破坏 `@echo off`）。`chcp`/BOM 均改不了 .bat 解析码页（固定 OEM）。故 `.bat` 降级为纯 ASCII 三行包装（`chcp 65001` + `powershell -File launcher.ps1`），所有中文 UI 移到 `launcher.ps1`（PowerShell 原生 Unicode，UTF-8 BOM 解析无缺陷）。`launcher.ps1` 设 `[Console]::OutputEncoding=UTF8` + `.bat` 已 `chcp 65001` → 中文在任何 Windows 正常显示。docker 调用用数组 splatting（`& docker @args`）规避 PS 原生参数引号问题；`--device=/dev/net/tun` 用 `=` 形式避免 PS 对 `/` 前缀的处理。实测中文 UI 完美显示、无解析错误、两条路径（配/不配代理）均正确拼出 docker run。
- **多格式验证**：用户订阅 `https://103.14.76.98/sub/fsc/...`（base64，31 节点：trojan/vless/hysteria2）→ 转换后 `mihomo -t` 校验通过。

### 已知限制

- 自动转换生成最小配置（自动选最快节点 + 全流量走代理），不含原订阅分流规则/分组；需精细分流仍可提供 Clash YAML 直链（原样使用，仅注入 TUN）。节点协议暂支持 ss/vmess/trojan/vless/hysteria2，其余协议解析到 0 节点会明确报错。
- `/dev/net/tun` 依赖：Docker Desktop LinuxKit VM 内置；原生 Linux 需 tun 模块。仅启用代理时挂载。
- mihomo 日志在容器内 `/home/AISC/.mihomo/mihomo.log`。

---

## v1.2.2 (2026-07-01) — 非 root 运行（AISC 用户）

### 动机

Claude Code 在 root 下拒绝 `--dangerously-skip-permissions` 模式。容器全程改用非 root 用户 `AISC`（uid 1000），
让该模式可用；挂载点从 `/app` 移到 AISC 家目录 `/home/AISC/app`，所有运行态目录均在 AISC 可写范围内。

### 变更

- **Dockerfile**：`useradd -m -u 1000 AISC`；出厂 `.claude` 由 `/root/.claude` 改建 `/home/AISC/.claude`；
  `WORKDIR /home/AISC/app`；构建末尾 `chown -R AISC:AISC /home/AISC` 后 `USER AISC`。
- **entrypoint.sh**：`GLOBAL=/home/AISC/.claude`、`PROJECT=/home/AISC/app/.claude`、`CC_CONFIG=/home/AISC/app/.cc-config`；
  删除 root 专属的 `chown` 权限交还逻辑（AISC 直接读写挂载卷）；作用域导出改写 `~/.bashrc`，不再写 `/etc/profile.d`。
- **claude-wrapper / claude-switch**：fallback 与 `do_upgrade` 出厂源路径改 `/home/AISC/.claude`；
  `cs` KEY_DIR 解析路径改 `/home/AISC/app/.cc-config`；`do_upgrade` 删除 `chown` 交还块。
- **stage-skills.sh**：`IMG_HOME=/home/AISC/.claude`。
- **启动器（.sh / .bat）**：挂载目标 `:/app` → `:/home/AISC/app`（.bat 的 named volume 同步改 `/home/AISC/app/.claude`）。
- **README / devlog**：路径表与示例命令同步更新。

### 取舍

- 不做 UID 匹配（无 build-arg UID/GID）。Docker Desktop 下容器 uid 对宿主透明，AISC(1000) 写入即归宿主用户。
  原生 Linux Docker 若宿主 uid ≠ 1000，挂载卷可能写不动 —— 留待实际遇到再加 build-arg。
- 不保留旧 root 所有权文件的迁移修复：全新非 root 环境，旧 `/app/.claude` 若 root 所有权残留需手动删除重建。

### v1.2.2 增量（容器配置加固）

在非 root 运行基础上，补齐权限/安全/构建稳健性与 git 工作流。

- **AISC 用户密码 + sudoers**：`echo 'AISC:AISC' | chpasswd`；`/etc/sudoers.d/aisc` 写 `AISC ALL=(ALL) NOPASSWD:ALL`（440）。容器内 AISC 免密 sudo，便于权限修复与系统操作。
- **entrypoint.sh 自愈 `.cc-config` 所有权**：旧镜像曾以 root 运行，绑定挂载把 root 所有权持久化到宿主，导致 AISC 读不了 `root:600` 的 `api-keys` → `cs` 切换静默失败。改为 `sudo chown -R AISC:AISC "$CC_CONFIG_DIR"` 自愈（依赖前述 sudoers）。
- **claude-wrapper 默认 `--dangerously-skip-permissions`**：注入默认 flag 跳过权限确认（容器内自动流），用户手动传入则不重复追加，避免重复 flag 报错。前提是 `USER AISC`（root 下 Claude 拒绝此 flag）。
- **git 全局 `core.autocrlf=input`**：Dockerfile 内 `USER AISC` 后 `git config --global core.autocrlf input`。commit 时 CRLF→LF（仓库永远干净 LF），checkout 不转；跨平台(Win 宿主 + Linux 容器)避免 CRLF 噪音进历史，`.gitattributes` 优先于此。
- **`.gitattributes` 行尾规范化**：`git add --renormalize .` 一次性把 665 个 `_bundle` CRLF 噪音归零（纯行尾，无内容差异），分两个 commit（行尾规范化 + 源文件改动）入库。
- **启动器 `.bat` 加固**：
  - `:build` 开头检查 `%~dp0Dockerfile` 是否存在，缺失则报错退出（提示「请在有 Dockerfile 及其它资源的文件夹下进行 build 操作」）。
  - build 失败检测修正：`if` 块内 echo 去括号（修 "was unexpected at this time" 解析错误）；每个 `call :build` 后加 `if errorlevel 1 exit /b 1`（修 `exit /b` 从 call 返回不退出脚本、假报成功的问题）。
- **本项目 git 配置**：`user.name=Thomas Wang`、`user.email`、`credential.helper=store`（token 存 `.git-credentials`，600 权限，`.gitignore` 忽略），remote 走 HTTPS + PAT。

### 取舍（增量）

- `--dangerously-skip-permissions` 默认开：容器 `--rm` 隔离 + 绑定挂载仅 `app/`，风险可控；纯本地自动流场景值得。
- token 存仓库内 `.git-credentials`：随项目走但明文（600），比放 `~/.git-credentials` 风险略高，用户取舍。
- sudoers `NOPASSWD`：容器内便利 > 安全约束；容器即用即弃，影响域有限。

### v1.2.2 增量二（后端模型配置对齐 + xf 后端 + cs show 增强）

实测各代理可用模型后，对齐 `claude-switch` 配置。

- **新增 xf 后端**（讯飞 maas-coding）：`XF_BASE=https://maas-coding-api.cn-huabei-1.xf-yun.com/anthropic`，独立 `XF_KEY`。三档：OPUS=`xopglm52`（glm5.2，512k 无 1M）、SONNET=`xopdeepseekv4pro[1m]`、HAIKU/SUBAGENT=`xopdeepseekv4flash[1m]`；EFFORT=max、COMPACT=512000。
- **ark 低端两档换 deepseek**：SONNET 由 `glm-5.2[1m]` → `deepseek-v4-pro[1m]`，HAIKU/SUBAGENT 由 `glm-4.7` → `deepseek-v4-flash[1m]`；OPUS 保持 `glm-5.2[1m]`；EFFORT 开 max。
- **1y 配置实测对齐**：1y 仅 `glm-5.2` 可用（Claude 模型名全 503），全档改 `glm-5.2[1m]`。
- **duo-cc 配置实测对齐**：duo-cc Claude 模型名 `claude-sonnet-5`/`claude-opus-4.8`/`claude-haiku-4.5` 实测可用，MODEL 全设 `claude-sonnet-5[1m]`。
- **COMPACT 统一**：除 cc（清空设计）与 xf（512000）外，deepseek/ark/1y/duo-cc 全设 `1000000`，充分利用 1M 窗口、减少压缩损失。
- **`cs show` 增强**：不再只显示后端名，打印全部 11 个 settings.json env 变量（BASE/TOKEN/API_KEY/MODEL/OPUS/SONNET/HAIKU/SUBAGENT/EFFORT/COMPACT），敏感 token 截断显示（前 12 + 后 4）。

### 取舍（增量二）

- duo-cc/1y 设 COMPACT=1M 但模型未必真支持 1M：若实际窗口 <1M，到模型上限才报错而非提前压缩。duo-cc 充值后实测确认。
- xf OPUS `xopglm52` 不加 `[1m]`：glm5.2 在讯飞只有 512k，加后缀会错。

## v1.2.1 (2026-06-30) — README 手动构建/运行 文档完善

- **README 手动构建/运行部分重写**：拆分为构建/运行/常用变体三个小节，覆盖三平台命令。
  - 构建：明确 `USE_CN_MIRROR` 默认=1，新增 `--no-cache` 示例。
  - 运行：新增 Windows PowerShell/CMD 的 `-v` 语法，强调 `TERM=xterm-256color` 必要性。
  - 常用变体：`CLAUDE_SCOPE` 跳过菜单、`bash` 直接进 shell、`cs <后端>` 一键切换、`--name` 容器命名。

## v1.2.0 (2026-06-30) — 插件化重构 + 双作用域 + 跨平台修复

### 架构重构

- **临时 / 项目双作用域**：用 Claude CLI 原生 `CLAUDE_CONFIG_DIR` 驱动。
  临时 = 镜像内置 `/root/.claude`（即用即弃）；项目 = `/app/.claude`（从镜像完整复制，持久到宿主机卷）。
  entrypoint 交互菜单 / `CLAUDE_SCOPE` 环境变量选择，导出并写入 `.bashrc`/`profile.d`。
- **`.claude` 与 `.cc-config` 分离**：`.claude` 为 CLI 原生完整目录（skills/plugins/projects…）；
  `.cc-config` 仅存 cs 的 `api-keys`（密钥隔离，gitignore）。
- **插件机制集成 6 套技能**（离线可用，预置 cache + marketplaces + 注册表 + `enabledPlugins`）：
  caveman（SessionStart hook 默认激活）/ claude-hud（statusLine HUD）/ document-skills /
  superpowers / skill-creator + gstack（扁平文档，6 子技能 + 斜杠命令）。
  `skill-creator` 构建期从本地 marketplace 离线 install。
- **自包含构建**：插件包 `_bundle` 纳入 git（约 24M），`docker build` 不再依赖宿主机 `~/.claude`。
  `stage-skills.sh` 作为一次性生成器（裁剪 marketplace、cache 版本剪枝、gstack 仅 6 子技能）。
- **cs 实时切换**：env 块改写入 `.claude/settings.json`（Claude Code 原生读取），`!cs ds` 当场生效；
  `write_settings` 合并保留 `enabledPlugins/statusLine`。`cs cc` 允许留空清空所有配置。
- **cs upgrade + 出厂版本检测**：`.factory-version`（出厂内容哈希）；项目版本旧则提示升级；
  `cs upgrade` 叠加更新出厂部分、合并 settings（留 env）、保留运行态、孤项编号表格多选删除。

### 启动器增强（.sh / .bat / .command）

- 镜像不存在自动构建；已存在三选一（直接运行 / 删旧重建防悬空 / 新镜像名）。
- 构建前两问：是否用缓存（`--no-cache`）、是否用国内镜像源（`USE_CN_MIRROR` + daocloud 基础镜像）。
- 容器名唯一后缀（`$$` / `%RANDOM%`），仅清理已退出容器 → 项目+临时多开互不挤掉。

### 跨平台修复（Windows 重点）

- **`.bat` 改纯英文 ASCII**：UTF-8 中文被 cmd 按代码页解析断行报错（wt 同样），英文根治；`chcp 65001` 仅保障 claude 输出。
- **基础镜像 docker.io 超时**：国内镜像选项同时把 `NODE_IMAGE` 指向 daocloud，绕开 `auth.docker.io`。
- **HUD 不显示（多根因）**：① 强制 `TERM=xterm-256color`（Windows 容器 TERM 缺失致 statusLine 隐藏）；
  ② 符号链接（superpowers AGENTS.md）`cp -r` 在 grpcfuse 创建失败 + `set -e` 中断致 `.claude` 复制残缺 →
  镜像内解引用所有 symlink + entrypoint 完整性校验补拷 + `cp -rL`；
  ③ **插件自带 `.gitignore`（含 `dist/`）导致 claude-hud `dist/index.js` 漏提交** → 用户 clone 缺文件、
  statusLine `MODULE_NOT_FOUND`；stage-skills 删除嵌套 `.gitignore` + 补提交；
  ④ `installed_plugins.json` 路径写死 `/root` → CLI 误判项目副本 orphan 可能删 dist → 复制后重写路径为项目目录。
- **`.claude.json` 缺失**：新版 CLI 核心状态在 `.claude.json`，构建期写入 onboarding + 跑一次 CLI 补全运行字段。

### 网络 / 工具（前置工作）

- WSL → Windows Clash 代理（7890）走 SSH-over-443（`ssh.github.com`），9 仓库切 SSH remote。
- 主机 `claude-switch` 增加 `duo-cc` 后端。

## 修复：.bat WT 启动逻辑重做 (2026-06-29, bug4 后续)

### 🐛 no.4 修复后暴露的两个新问题

- **4a 重复开窗** — 已在 Windows Terminal 内运行 `.bat` 仍无条件再开一个 wt。
  根因：脚本只 `where wt` 判断系统是否装 wt，未判断**当前是否已在 wt 内**。
  修复：读环境变量 `WT_SESSION`，已在 wt 则 `goto run` 直接当前标签运行。
- **4b docker 丢参** — 新 wt 内报 `'docker run' requires at least 1 argument`（`%IMAGE%` 丢失）。
  根因：`wt ... cmd /k "...""%cd%:/app""...%IMAGE%"` 的嵌套双引号经 **wt tokenizer**（非 cmd）解析时被拆断，
  命令在 `-v` 后截断，`%IMAGE%` 落入 wt 的其它参数而丢失。
  修复：改为**自重启模式** — wt 仅以本脚本 `cmd /k ""%~f0""` 开新标签，
  `docker run` 在重启实例内**直接执行**，不再把命令串塞进 wt 解析器；`wt -d "%cd%"` 保留工作目录。
  结构用 `if defined WT_SESSION goto run` + `where wt` / `if errorlevel 1 goto run` + `:run` 标签，
  规避 `&&( ... )` 括号块的批处理解析坑。

### ⚠️ 验证

本机 Linux 无法执行 `.bat`，仅做静态校验（含 `WT_SESSION`/`wt -d`、docker run 参数完整、无嵌套 docker 串）。
**需 Windows + Windows Terminal 实测三场景**：① 已在 wt 标签内双击/运行 ② CMD/PowerShell 双击 ③ 未装 wt。

## 修复：容器运行时与 Windows 启动问题 (2026-06-29, no.3-5)

### 🐛 三项缺陷修复

- **no.5 中文乱码** — 容器内未配置 UTF-8 locale，`ls` 等输出八进制转义乱码。
  Dockerfile 注入 `ENV LANG=C.UTF-8 LC_ALL=C.UTF-8`（debian-slim/glibc 内置，无需 locale-gen），
  `entrypoint.sh` 追加 `export LANG/LC_ALL` 作运行期兜底。已在容器内验证 `locale`=`C.UTF-8`、中文文件名与渲染正常。
- **no.4 .bat 报错** — `一键启动_AI工作站.bat` 经 Windows Terminal 启动报 `参数格式不正确 - >nul`，
  根因为 `wt ... cmd /k "chcp 65001 ^>nul && ..."` 中 caret 转义的 `>nul` 被 wt 参数切分误判。
  去除该重定向（保留一行 `Active code page` 输出，无害）。
- **no.3 残留容器** — `docker run --rm` 无 `--name`，窗口被强制关闭时容器残留需手动删。
  启动脚本（`.bat` + `启动_AI工作站.sh`）改用固定 `--name super-claude-station`，
  并在每次启动前 `docker rm -f` 清理同名 stale 容器，保证不堆积。正常退出仍建议 `exit`。

### ✅ 验证

`docker build` 通过；容器内 `locale` 确认 `C.UTF-8`，`ls` 中文无乱码。
Windows `.bat` 的 no.4 需在 Windows + Windows Terminal 环境实测确认。

## v1.1.3 (2026-06-28)

### 🚀 启动体验与全局行为优化

**重大变更**：后端配置与 Key 统一持久化到项目挂载目录 `/app/.claude/`，并在 `entrypoint.sh` 与 `claude-wrapper` 中自动注入环境变量，解决配置后仍进入登录引导、首次进入 bash 后手动 `claude` 不生效等问题。

### ✨ 变更

| 项 | 说明 |
|----|------|
| 配置持久化 | `cs` 在 Docker 内优先写入 `/app/.claude/settings.json`，随项目挂载卷保留 |
| Key 持久化 | `cs` 在 Docker 内优先写入 `/app/.claude/api-keys`，容器重建不丢失 |
| `claude-wrapper` | 新增包装器：每次运行 `claude` 前读取 settings env，注入 `ANTHROPIC_*` / `CLAUDE_CODE_*` 后再执行 `claude-real` |
| 全局 `CLAUDE.md` | 新增 `global-claude.md`，构建时复制到 `/root/.claude/CLAUDE.md` |
| karpathy-flow 默认启用 | 将 Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution 写入全局 `CLAUDE.md` |
| Caveman 默认启用 | 全局默认 Caveman `full` 沟通风格，用户可用 `normal mode` / `stop caveman` 关闭 |
| 跨平台启动脚本 | 新增 Linux `启动_AI工作站.sh` 与 macOS `启动_AI工作站.command`，Windows `.bat` 更新为 v1.1.2 横幅并优先使用 Windows Terminal |
| README 启动说明 | 按 Windows / Linux / macOS 拆分，补充启动模式、单次运行、容器残留清理、终端乱码说明 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| 登录引导误触发 | `entrypoint.sh` 读取 settings 后真正 `export` env，避免只有配置文件但 Claude 进程无 token |
| 首次 bash 后手动 `claude` 不生效 | `claude-wrapper` 每次启动都重新注入 env，解决 `cs` 写入配置后当前 bash 环境未更新的问题 |
| 项目级 settings 覆盖全局 settings | `cs` 优先写 `/app/.claude/settings.json`，避免 `.claude/settings.json` 与 `~/.claude/settings.json` 不一致 |
| `/model` pin 冲突 | `cs` 写 settings 时删除 `model` 字段，让 `env.ANTHROPIC_MODEL` 接管当前后端 |
| 空 API Key 覆盖 Auth Token | env 注入时对空值执行 `unset`，避免 `ANTHROPIC_API_KEY=""` 干扰 `ANTHROPIC_AUTH_TOKEN` |
| 单次运行模式 | 验证 `docker run ... claude -p "..."` 可用，并写入 README |
| CMD 中文乱码 | `.bat` 优先使用 Windows Terminal；README 明确传统 CMD 可能乱码 |

### 📝 已知问题

- [ ] Termius SSH 配置文档未编写
- [ ] gstack 仅有技能描述，完整运行时安装方案待确认

---

## v1.1.2 (2026-06-27)

### 🔐 安全重构：API Key 与脚本分离

**重大变更**：`cs` 脚本不再硬编码 Key，改为从 `~/.claude/api-keys` 读取，无 Key 时交互式提示输入。

### ✨ 变更

| 项 | 说明 |
|----|------|
| Key Store | `~/.claude/api-keys`（chmod 600），`KEY_NAME=value` 格式，5 组 Key 独立存储 |
| `get_key()` | 新函数：先查 Key Store → 没有则提示用户输入 → 输入后自动保存 |
| `cs show` 增强 | 显示当前后端 + 各后端 Key 保存状态（✓/✗） |
| URL 保留 | 端点 URL 仍留在脚本中（非机密），仅 Key 走外部存储 |
| Dockerfile | 构建时不执行 `cs`，改为创建空 `api-keys` + 空 `settings.json` |
| entrypoint 引导 | 未配置时自动显示 `cs deepseek` / `cs ark` 等可用命令 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| 硬编码 Key | `claude-switch` 第 21-27 行移除全部默认 Key |
| 构建时依赖 Key | Dockerfile 不再 `RUN cs deepseek`，避免 build 阶段要求交互输入 |
| Key 注入 JS 字符串 | 改为 env var 传递（`export CS_AUTH_TOKEN`），消除 `'` `\` 等特殊字符引发的 SyntaxError |
| `get_key()` stdout 污染 | `echo` 提示文案全部改 `>&2`，`$()` 只捕获纯 Key 值 |
| CRLF 混入 Key | `grep` → `tr -d '\r'` 清洗 Windows 行尾 |
| 密钥路径 | Docker 容器内自动使用 `/app/.claude/api-keys`（随 `-v` 挂载） |
| entrypoint 重复提示 | Section 3 改为单行状态；Section 5 仅在拦截时显示一次性引导 |
| entrypoint 未配置拦截 | `claude` 命令在无后端时 `exec bash` 而非直接进 Claude Code |
| `.gitignore` | 新增 `api-keys` + `super-claude-v1.1.2.tar` 排除规则 |

### 📝 已知问题

- [ ] Termius SSH 配置文档未编写
- [x] ~~`cs` 脚本内 API Key 硬编码~~ → v1.1.2 修复

---

## v1.1.1 (2026-06-27)

### 🔄 切换脚本重构：`cs` 统一入口

**重大变更**：废弃交互式菜单方案，改用 `cs` 一键切换 + `~/.claude/settings.json` 持久化。

### ✨ 变更

| 项 | 说明 |
|----|------|
| `cs` 统一入口 | `cs` / `claude-switch` 指向同一脚本，写入 `~/.claude/settings.json` |
| 放弃菜单交互 | 旧版 `claude-switch` 菜单 + `.claude_keys` 方案全部移除 |
| 5 后端内嵌 Key | cc / deepseek / ark / 1y / duo-cc 的 API Key 内置脚本，切换即用 |
| `cs show` | 快速查看当前后端 |
| `SC_RESTART=1` | 切换后自动重启 Claude Code（Docker 直连模式） |
| 默认后端初始化 | Dockerfile 构建时 `RUN cs deepseek`，不再用 `ENV` 硬编码 |
| `ARG NODE_IMAGE` | 基础镜像可通过 `--build-arg` 替换，解决国内拉取问题 |
| `.gitignore` | 排除 `super-claude-v1.tar`、`.claude_keys` |
| 构建导出流程 | `docker build` + `docker save` → `super-claude-v1.tar` |

### 🔧 修复

| 项 | 说明 |
|----|------|
| CRLF 行尾 | `claude-switch` 从 CRLF 转为 LF，修复容器内 `bash\r` 错误 |
| DeepSeek 无 Key | 移除 Dockerfile 中 `ENV ANTHROPIC_BASE_URL`（有 URL 无 Token 导致 `ERR_BAD_REQUEST`） |
| entrypoint 横幅 | 改为从 `~/.claude/settings.json` 读取后端信息，不再依赖 Docker ENV |
| `claude` 包装器 | 简化为直接移交 `claude-real`，不再做 Key 检测（切换交给 `cs`） |
| cygpath 兼容 | `cs` 脚本自动识别 Windows/Linux 环境，Linux 容器内直接使用 POSIX 路径 |

### 📝 文档

- README.md 重写：`cs` 用法、平台详情表、构建导出流程
- 新增 `cs` 直连模式说明：`docker run ... cs ark`

### 🗑️ 移除

- 旧版交互式 `claude-switch` 菜单（Anthropic/DeepSeek/硅基流动/OpenRouter/智谱 5 选 1）
- `.claude_keys` Key 持久化文件（改为 `~/.claude/settings.json` 管理）
- `entrypoint.sh` 中无 Key 自动引导逻辑（不再需要）
- Dockerfile 中 7 行 `ENV` 硬编码 DeepSeek 变量

### 📂 当前项目结构

```
.
├── Dockerfile
├── entrypoint.sh
├── claude-switch                       # 同时是 cs 和 claude-switch 的源
├── 一键启动_AI工作站.bat
├── devlog.md
├── README.md
├── skills/
│   ├── claude.json
│   ├── karpathy-flow/
│   └── ... (20+ 技能)
├── .claude/
│   └── settings.local.json
├── .claude_keys                        (已废弃，不再使用)
└── todo/
    ├── todo.md
    └── 20260625/
        ├── claude-switch               (开发过程中的中间版本)
        └── setup-ssh-portproxy.ps1
```

### 已知问题

- [ ] Termius SSH 配置文档未编写
- [ ] `cs` 脚本内 API Key 硬编码，后续可改为环境变量覆盖 + 运行时输入

---

## v1.1.0 (2026-06-27)

### 🔄 架构重构：纯终端闭环

**重大决策**：彻底切断对第三方 GUI 黑盒工具的依赖，转向 100% 内部闭环的纯终端 CLI 工作流。

### ✨ 新增

| 项 | 说明 |
|----|------|
| `claude-switch` | 内置模型后端切换器 CLI，支持 5 大平台、15+ 模型 |
| 平台接入 | Anthropic 官方 / DeepSeek 官方 / 硅基流动 / OpenRouter / 智谱 Z.AI |
| 硅基流动子菜单 | 5 款国产模型可选（DeepSeek-V4-Pro、GLM-5.2、Nex-N2-Pro、MiniMax M3、Qwen3.6-35B） |
| OpenRouter 子菜单 | 6 款全球模型可选（Claude Opus 4.8、Sonnet 4.6、DeepSeek V3.2、GLM-5.2、Qwen3 Coder、Kimi K2.7） |
| 智谱 Z.AI 子菜单 | 3 款 GLM 模型可选（GLM-4.6、GLM-4.5、GLM-4.5-Air） |
| `一键启动_AI工作站.bat` | Windows 一键启动脚本，`chcp 65001` 防乱码，零参数开箱即用 |
| API Key 持久化 | `/app/.claude_keys`（chmod 600），5 组 Key 独立存储，容器重启不丢失 |
| `karpathy-flow` 技能 | Andrej Karpathy 编码规范 skill，自动化入容器 |
| `devlog.md` | 开发日志，提升至项目根目录 |
| entrypoint 自动引导 | 无 Key 时启动 `claude` 自动重定向到 `claude-switch` |
| `claude` 包装器 | 重命名原版为 `claude-real`，包装脚本统一拦截：有 Key → 原版，无 Key → `claude-switch` |
| `AUTH_METHOD` 双通道 | Anthropic 官方用 `ANTHROPIC_API_KEY`，第三方平台用 `ANTHROPIC_AUTH_TOKEN` + 清空 `API_KEY` |
| Claude Code 启动绕过 | 预置 `config.json`（`hasCompletedOnboarding: true`）跳过首次联网验证 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| Dockerfile — VPN 依赖 | 注入清华 apt 镜像源 + 淘宝 NPM 镜像源，国内网络无需 VPN 即可构建 |
| Dockerfile — `.claude/` 报错 | 不再 `COPY .claude/`（宿主机缺失时构建失败），改为镜像内生成默认 `settings.local.json` |
| entrypoint.sh — 覆盖风险 | 原逻辑缺文件就强覆盖，现改为仅首次运行注入，保护用户自定义配置 |
| entrypoint.sh — root 锁死 | 新增 `chown` 权限修复，自动检测宿主机 UID/GID 归还文件所有权 |
| entrypoint.sh — Shell | `#!/bin/sh` → `#!/bin/bash`，支持 `echo -e` 等特性 |
| Dockerfile — 工具链 | 补上 `sudo`、`tmux` |
| `claude-switch` — Anthropic 模型 | `claude-3-5-sonnet-20241022`（已退役）→ `claude-opus-4-8` |
| `claude-switch` — 硅基流动模型 | `Pro/deepseek-ai/DeepSeek-V3` → `Pro/deepseek-ai/DeepSeek-V4-Pro` |
| Claude Code — 国内无 VPN 无法启动 | 预置 `config.json` 跳过 onboarding + 第三方平台改用 `ANTHROPIC_AUTH_TOKEN` |
| `claude` 包装器 — 死循环 | 兼容 `ANTHROPIC_AUTH_TOKEN`，两个变量任非空即放行 |
| `claude-switch` — Anthropic 模型 | `claude-3-5-sonnet-20241022`（已退役）→ `claude-opus-4-8` |
| `claude-switch` — 硅基流动模型 | `Pro/deepseek-ai/DeepSeek-V3` → `Pro/deepseek-ai/DeepSeek-V4-Pro` |

### 📝 文档

- README.md 全面重写：5 大平台菜单、子菜单表格、claude-switch 详解

### 🗑️ 移除

- `docker_version/` 子目录清理，文件全部提升至项目根目录

### 📂 当前项目结构

```
.
├── Dockerfile
├── entrypoint.sh
├── claude-switch
├── 一键启动_AI工作站.bat
├── devlog.md
├── README.md
├── skills/
│   ├── claude.json
│   ├── karpathy-flow/SKILL.md     ← v1.1.0 新增
│   └── ... (20+ 技能)
├── .claude/
│   └── settings.local.json
├── .claude_keys                   (运行时生成)
└── todo/
    └── todo.md
```

---

## v1.0.0 (2026-06-25)

### 初始版本

- `node:20-slim` 基础镜像
- 全局安装 `@anthropic-ai/claude-code`
- 预配置 DeepSeek Anthropic 兼容 API（`ANTHROPIC_BASE_URL`、模型映射、effort）
- `claude.json` 全局配置（claude-hud + document-skills 插件）
- 20+ 预装技能库 → `/root/.claude/skills/`
- `entrypoint.sh` 入口脚本：自动注入项目级 `.claude/` 模板
- Windows SSH 端口代理配置（`setup-ssh-portproxy.ps1`）

### 已知问题

- [x] ~~无 VPN 时 `node:20-slim` apt/npm 安装失败~~ → v1.1.0 修复
- [x] ~~`.claude/` 缺失导致 Docker 构建报错~~ → v1.1.0 修复
- [x] ~~Skill 引入（andrej-karpathy-skills）~~ → v1.1.0 完成
- [x] ~~全局 claude-switch 命令~~ → v1.1.0 完成
- [ ] Termius SSH 配置文档未编写

## v2.1.1-dev (2026-07-23) - root 家目录挂载与运行时资源隔离

### 动机

Windows → WSL2 → Docker bind mount 场景下，宿主机工作区直接挂载到 `/root`，统一容器运行身份与文件权限模型，并避免挂载 `/root` 覆盖镜像内置 CLI 资源。

### 变更

- **Docker 挂载路径**：宿主工作区由 `/root/app` 改为直接挂载到 `/root`，容器默认工作目录同步改为 `/root`。
- **出厂资源隔离**：Claude/Codex 出厂配置与 skills/plugins 迁移到 `/opt/aisc/factory`，Python venv 迁移到 `/opt/aisc/venv`，Mihomo geodata 迁移到 `/opt/aisc/mihomo`。
- **项目配置路径**：项目作用域使用 `/root/.claude`、`/root/.codex` 和 `/root/.aisc`，首次启动从 `/opt/aisc/factory` 复制并持久化到宿主工作区。
- **临时作用域**：使用 `/tmp/aisc-home`，不把临时 Claude/Codex 配置写入宿主机工作区。
- **cc-switch 集成**：启动时自动拉起 daemon、初始化 Codex provider、启用 Claude/Codex 路由，并离线登记和同步 gstack skills。
- **Codex 权限**：默认启用 bypass approvals/sandbox 与 hook trust，等价于 Claude 容器 bypass 模式。
- **环境变量**：容器默认设置 `IS_SANDBOX=1`。

### 验证

- Docker 镜像 `aisc:v2.1.1-dev-root-home` 构建成功。
- 真实宿主目录 bind mount 到 `/root` 的项目/临时两种作用域均验证通过。
- cc-switch daemon、Codex provider、Claude/Codex 路由和 gstack skills 验证通过。
- 完整测试：189 项通过，1 项按既有条件跳过。
