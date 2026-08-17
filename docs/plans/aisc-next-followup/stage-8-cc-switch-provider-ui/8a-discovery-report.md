# Stage 8a 技术预研报告（API discovery gate）

> 调研日期：2026-08-17 · 方法：真实 release metadata（GitHub API）+ Linux musl 二进制
> 黑盒实跑（python:3.12-slim 容器，隔离 `CC_SWITCH_CONFIG_DIR`）+ DeepSeek 官方文档
> 逐页取证。**未依赖任何旧版本猜测。** fixture：`container/lib/deepseek-official-facts.json`。

## 1. Release / resolver 事实（CS-01/CS-02）

| 项 | 事实 |
|---|---|
| 上游 | `github.com/saladday/cc-switch-cli`（farion1231/cc-switch 的 CLI fork，MIT，Rust/Tauri） |
| latest stable（2026-08-17） | **v5.10.1**（2026-08-06 发布；近 10 个 release 均为 `prerelease=false, draft=false`） |
| 资产命名 | `cc-switch-cli-{v}-linux-{x64|arm64}[-musl].tar.gz`；**arch 是 `x64` 不是 `amd64`**；musl 为默认静态构建，glibc 为无后缀变体（`latest.json` 里嵌套 `variants.glibc`） |
| 版本化 vs 未版本化 | 每个 release 同时带 `cc-switch-cli-linux-x64-musl.tar.gz`（未版本化）与带 `vX.Y.Z` 的版本化资产；**resolver 应选版本化资产**（可复现） |
| 校验和 | **GitHub Releases API 每个 asset 自带权威 `digest`（sha256）**；实测下载 musl tarball 的 sha256 与 API digest 完全一致（`be6836eb…0790`）。release 另附 `checksums.txt`（双保险）与 `latest.json`（Tauri updater 清单，含 minisign 签名） |
| 网络 | TUN 代理下 GitHub 直连下载超时；`ghfast.top` 镜像实测可用（与 Dockerfile 现有镜像链一致） |
| v5.9.0 → v5.10.1 | **DB schema 保持 v16，无迁移**；新增 usage 面板/会话历史/Codex Anthropic 兼容/MCP 等 |

## 2. CLI / daemon / DB 事实（CS-05/CS-06）

- **无 HTTP API**。`daemon` 是 proxy worker 的 supervisor（`start [--detach]/stop/status/logs`），
  经 Unix socket 通信（无 daemon 时 `daemon status` 报 "not reachable: No such file"）。
  **Provider CRUD 不依赖 daemon**。
- **无任何 `--json` 输出**：`provider list` 渲染 unicode 表格、`provider current` 人类文本。
- Provider CRUD 表面（`-a claude|codex|…`）：
  - `provider add` **非交互**：`--template/--name/--id/--base-url/--api-key/--model/
    --haiku-model/--sonnet-model/--opus-model/--fable-model/--subagent-model/
    --config/--config-file/--website-url/--notes`。角色模型旗标的帮助文本即官方
    `[1M]` 语义（"append [1M] to enable 1M context"、"Haiku does not support it"）。
    ⚠️ `--api-key` 走 argv（违反我方 secret 协议）；`--config-file /dev/stdin` **实测可用**
    （settings_config JSON 从 stdin 进入，argv 无 secret）。
  - `provider edit <id>` **TUI-only**（非 tty stdin patch 实测 exit=1）→ adapter 的 edit =
    快照合并 → `switch` 换走 → `delete` → 同 `--id` 重 add。
  - `provider delete` 非交互 ✓，但**拒绝删除 current provider**；`provider switch` 非交互 ✓
    （目标 provider 配置为空时非 tty 会 prompt 失败——换走目标必须是有实际配置的）。
  - **add 会把新 provider 置为 current**（field-mode 实测）→ delete 前必须 switch 走。
  - ⚠️ **add 成功输出明文回显 API Key**（"API Key: sk-…"）→ adapter 必须把 cc-switch CLI
    的全部 stdout 视为不可信、经 redaction 后才能进 UI/日志/诊断（A-CS07 实锤）。
  - claude `settings_config` 形状 `{"env":{…}}`；只给 `ANTHROPIC_MODEL` 时上游会**自动把
    DEFAULT_HAIKU/SONNET/OPUS 外溢为同值**——preset 必须显式写全官方角色变量，防止错误外溢。
  - `--template deepseek` **不适用于 claude**；`--template dds` = `https://www.ddshub.cc`
    三方中转（**非 DeepSeek 官方**）。上游无 DeepSeek 官方 claude 模板 → 我方 preset 保留。
- DB：`CC_SWITCH_CONFIG_DIR/cc-switch.db`（SQLite，首次运行建库并注入 180 条模型定价）；
  18 张表；`providers` 列含 `settings_config`(JSON text)/`is_current`/`app_type`/`category`/
  `provider_type`/`meta`…；伴随锁文件 `cc-switch.db.init.lock`、`cc-switch.db.session-usage.lock`；
  schema v16（v5.9→v5.10 稳定）。

## 3. DeepSeek 官方 fixture（CS-03/CS-04）

来源四页（retrieved 2026-08-17，全文取证）：

- `quick_start/agent_integrations/claude_code`（**官方逐字环境变量集**）
- `guides/anthropic_api`（base URL、服务端映射、兼容性矩阵）
- `quick_start/pricing`（模型/上下文/弃用）
- `news/news260424`（V4 发布、1M 标配）

核心事实（全量见 fixture JSON）：

```text
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=<key>                        # 官方用 AUTH_TOKEN（非 API_KEY）
ANTHROPIC_MODEL=deepseek-v4-pro[1m]
ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]
ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]   # ← 官方 sonnet 推荐 pro
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash      # 无 [1m]
CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash
CLAUDE_CODE_EFFORT_LEVEL=max
```

- 模型官方 ID：`deepseek-v4-flash` / `deepseek-v4-pro`；`deepseek-chat`/`deepseek-reasoner`
  **2026-07-24 已弃用**；两模型原生 1M 上下文 / 最大输出 384K。
- 服务端兜底映射：`claude-opus*`→pro、`claude-haiku*/claude-sonnet*`→flash、
  未知模型名→flash（`anthropic-beta` header 被忽略）。

## 4. 与既有规划的差异（需按 D8-06 以 fixture 为准修正）

| 规划原文（02-domain-contract） | 官方事实 | 处置 |
|---|---|---|
| default/sonnet/haiku/其它 → flash；opus → pro | **sonnet 与 default 主力位 → `deepseek-v4-pro[1m]`**（Claude Code 主用 sonnet 位，官方推荐 pro）；仅 haiku/subagent → flash | 8c 按官方集实现；服务端映射作为不设 env 时的兜底 |
| "`[1m]` 只能按官方文档规定附加" | 官方 Claude Code 页**逐字**使用 `[1m]` 后缀（MODEL/OPUS/SONNET 带、HAIKU/SUBAGENT 不带） | `[1m]` 为官方语法，preset 原样保留 |
| 现 preset：`deepseek-v4-pro` 默认 + 仅 ANTHROPIC_MODEL 等 | 缺 SONNET→pro[1m]、HAIKU→flash、SUBAGENT、EFFORT_LEVEL=max、AUTH_TOKEN 完整集 | 8c 重写为官方 7+1 变量集 |

## 5. 结论：实现路径 = **Path B（受控 adapter）**

无官方 HTTP/IPC API（Path A 不存在）。adapter 设计基线：

1. **写**：一律走官方非交互 CLI；secret 经 `--config-file /dev/stdin`（argv 零 secret）；
   edit = 快照合并 + switch-away→delete→re-add（同 id）；处理 current 守卫。
2. **读**：容器内 adapter 对 `cc-switch.db` 只读连接取快照（schema v16 已固化进测试）；
   Workbench 永不直连 DB。
3. **redaction**：cc-switch CLI stdout 全部视为含 secret 的不可信文本，脱敏后才可外露。
4. 并发：adapter 是唯一 writer 入口（`provider add/delete/switch` 子进程 + BEGIN IMMEDIATE
   由上游事务承担）；快照读带 busy timeout。
