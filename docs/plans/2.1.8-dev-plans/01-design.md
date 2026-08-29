# v2.1.8 设计文档：Agent 历史对话管理 + Bash 体验增强

> 日期：2026-08-29 · 状态：待审阅（v7，审阅 v6：前端编排 + CLI resume 冻结为删除）
> 方案 A（薄层直读）

## 0. 审阅回应摘要

| 审阅项 | 回应 |
|---|---|
| P0-1 session list 语义冲突 | ✅ 新增独立 `conversation` 命令命名空间，不复用 session |
| P0-2 resume 无可执行契约 | ✅ 探针完成，resume argv 冻结；conversation_id 与 terminal_session_id 分离 |
| P0-3 历史格式未验证 | ✅ Claude/Codex 双探针完成，§1 冻结格式表 |
| P1-4 Bash 路径未接入容器契约 | ✅ runtime context 增 `workspace_state_dir` 字段 |
| P1-5 SQLite 并发不完整 | ✅ §3d 完整 schema + WAL + busy timeout + retention |
| P1-6 rcfile 初始化不确定 | ✅ §3c 冻结 wrapper `--rcfile` 链路 |
| P1-7 工具缺可复现性 | ✅ §3e 版本 pin + sha256 + arch 矩阵 |
| P1-8 标题提取风险 | ✅ §1d 脱敏规范 |
| P1-9 UI 位置不清 | ✅ §4 冻结前端数据模型 + 面板位置 |
| P1-10 测试不足 | ✅ §6 扩展矩阵 |
| P2-11 message_count 武断 | ✅ 改为「无有效用户消息即排除」+ resumable 标记 |
| P2-12 AGENTS.md 边界 | ✅ §5 可选注入层，不覆盖用户文件 |

## 1. Agent 历史对话管理

### 1a. 探针结果（冻结）

| 字段 | Claude | Codex |
|---|---|---|
| source_root | `workspaces/<hash>/claude/projects/` | `workspaces/<hash>/codex/sessions/` |
| file_pattern | 递归 glob `**/*.jsonl` | 递归 glob `**/*.jsonl`（YYYY/MM/DD/ 嵌套） |
| 一文件=一会话 | 是（文件名 = session_id） | 是（文件名含 session_id） |
| id_source | 文件名 stem（UUID） | 文件名中 `rollout-<ts>-<uuid>.jsonl` 提取 UUID |
| 行类型 | `queue-operation` / `user` / `assistant` / `attachment` / `system` | `session_meta` / `event_msg` / `response_item` / `world_state` / `turn_context` |
| 用户消息判定 | `type=='user'` 且 `message.role=='user'` | `type=='response_item'` 且 `payload.type=='message'` 且 `payload.role=='user'` |
| 消息内容路径 | `message.content`（string 或 `[{type:'text',text}]` 列表） | `payload.content`（`[{type:'input_text',text}]` 列表） |
| timestamp 字段 | 每行 `timestamp`（ISO 8601） | 每行 `timestamp`（ISO 8601） |
| 原生 title | 无 | 无 |
| resume argv | `claude --resume <conversation_id>` | `codex resume <conversation_id>` |
| max_file_size | 10MB（超限**不全文解析**：头部 200 行扫描出 title/time，返回占位 summary，`resumable:false` + `unavailable_reason=file_too_large`，`message_count:null`——详见 §1e） | 同左 |
| malformed 行策略 | 跳过不完整 JSON 行；零可解析行 → 排除出列表 | 同左 |

### 1b. CLI 命令（冻结）

```bash
# 列表（只读，不碰 Docker）
aisc conversation list --workspace <path> [--format json|text]

# 预校验（captured、非交互、纯 JSON envelope）
aisc conversation preflight --workspace <path> --conversation-id <id> --agent <claude|codex> [--format json]
```

**`conversation resume` 不作为公共 CLI 命令存在**（方案 B 冻结）：恢复动作
是 Workbench Rust IPC 的两步编排（preflight + open_session --resume-id），
完整流程依赖 PTY Channel 与 pane 生命周期，拆出独立 CLI 命令无使用场景且
与 captured/interactive 边界冲突。§1b 仅暴露 `list` 与 `preflight`。

**list 输出 schema**：
```json
{
  "schema_version": 1,
  "conversations": [
    {
      "conversation_id": "24b70882-2d45-4cec-a9e2-66f8c012481f",
      "agent": "claude",
      "title": "帮我写一个排序算法",
      "started_at": "2026-08-29T10:00:00Z",
      "last_at": "2026-08-29T10:05:00Z",
      "message_count": 12,
      "file_size": 81920,
      "resumable": true
    }
  ]
}
```

`unavailable_reason?: "file_too_large" | "malformed" | "unsupported"`（resumable=false 时必有）。

**resume 输出**：信封 `{terminal_session_id: "<new-uuid>", agent, conversation_id}` 或错误。

### 1c. ID 分离（冻结）

| 字段 | 含义 | 生成方 |
|---|---|---|
| `conversation_id` | provider 原生会话 ID（Claude/Codex 的 UUID） | provider CLI 写入 JSONL 文件名 |
| `terminal_session_id` | Workbench PTY 生命周期 UUID（新生成） | Rust `uuid()` |

恢复流程（v6：Rust 编排两步——captured preflight + interactive open）：
1. 前端调 IPC `conversation_resume(runtime_id, workspace, conversation_id, agent, on_event)`（签名同 §1f）
2. **Rust 第一步**：`run_control`（captured）执行 `aisc conversation preflight --workspace <path> --conversation-id <id> --agent <agent>`
   → 失败：envelope 错误 → IPC 返回 `WorkbenchError` → **不建 tab**，行内提示
   → 成功：进入第二步
3. **Rust 第二步**：生成新 `terminal_session_id = uuid()` → 调现有 `open_session` 路径（含 `on_event` Channel），sidecar argv 追加 `--resume-id <conversation_id>`
4. wrapper 内部转换 provider argv：
   - claude → `claude --resume <conversation_id>`
   - codex  → `codex resume <conversation_id>`
5. 返回 `{terminal_session_id, conversation_id, agent}` — 前端用 terminal_session_id 管理新页签

**两步边界（冻结）**：preflight 是独立 CLI 子命令 `aisc conversation preflight`（非交互、纯 JSON envelope 输出），与 `open_session` 的交互 PTY 路径完全解耦——不引入 token、不共用 I/O 模式。Rust `conversation_resume` 编排两步的调用顺序。

### 1d. 标题提取（脱敏规范）

1. **优先级**：provider 原生 title/summary 字段（当前均无）→ 首条用户消息
2. **提取（按 provider 分派，与 §1a 格式表一一对应）**：
   - **Claude**：`message.content` 为 string → 直接用；为 list → 取首个
     `type == "text"` 块的 `text`
   - **Codex**：`payload.content` 为 list → 取首个 `type == "input_text"` 块的 `text`
3. **清洗**：
   - 删除换行符、ANSI escape、控制字符（`\x00-\x1f`）
   - 截断至 80 Unicode scalar values（不是字节）
4. **脱敏**：匹配 `sk-[a-zA-Z0-9]{20,}` / `Bearer\s+\S+` / `api[_-]?key.*['\"]\s*\w{16,}` → 替换为 `[REDACTED]`
5. **降级**：提取失败 → `"(无法读取)"`；单文件失败不阻断列表（按 §1e 标注）
6. **测试**：Codex fixture 的 title 断言 == 真实用户输入文本（非仅「不崩溃」）

### 1e. 过滤与不可恢复标注（替代 message_count < 2）

- **排除出列表**（不返回）：零条可解析的用户消息；零可解析行（完全 malformed）
- **保留并标注**（返回 summary，`resumable:false` + `unavailable_reason`）：
  - `file_too_large`（>10MB）：仍返回记录；title/time 从**前 200 个可解析行**（流式
    头部扫描）提取，`message_count: null`；`file_size` 照实
  - `malformed`：部分行损坏但存在可解析用户消息 → 正常 title，`resumable:false`
  - `unsupported`：agent 非 claude/codex（防御，当前不可达）
- **保留单条用户消息**的会话：`resumable: true`（claude/codex 均可恢复）

**schema 增补**（list 输出与 TS 类型同步）：
```json
{
  "file_size": 81920,
  "unavailable_reason": "file_too_large",   // 可缺省；resumable=false 时必有
  "message_count": 12                        // file_too_large 时为 null
}
```

### 1f. Rust IPC（v6 冻结：resume 接管 PTY + sidecar preflight 编排）

```rust
#[tauri::command]
pub async fn conversation_list(
    workspace: String,
) -> Result<ConversationListResult, WorkbenchError>;

// 方案 A（冻结）：resume = Rust 编排两步——
//   1) run_control captured: aisc conversation preflight（§2 代码草案）
//   2) open_session(..., --resume-id, on_event)（现有 PTY 事件模型）
// runtime_id 由前端传入；on_event 是标准 PtyEvent Channel。
#[tauri::command]
pub async fn conversation_resume(
    app: AppHandle,
    runtime_id: String,
    workspace: String,
    conversation_id: String,
    agent: String,
    on_event: Channel<PtyEvent>,
) -> Result<ConversationResumeResult, WorkbenchError>;
```

内部实现 = `open_session` 复用：Rust `session_open_argv` 在有
`resume_conversation_id` 时为 wrapper argv 追加 `--resume-id`；其余
（reserve/spawn/事件）完全同现有路径。**无两阶段 token**（方案 B 否决：
token 生命周期/清理/超时是净增复杂度，收益为零）。

TS 侧对应类型：
```typescript
interface ConversationSummary {
  conversation_id: string;
  agent: "claude" | "codex";
  title: string;
  started_at: string | null;
  last_at: string | null;
  message_count: number | null;   // file_too_large 时 null
  file_size: number;
  resumable: boolean;
  unavailable_reason?: "file_too_large" | "malformed" | "unsupported";
}
```

## 2. wrapper 扩展

`aisc-session-wrapper open` 增加可选 `--resume-id <conversation_id>`（唯一命名，
全文一致；provider 专属形态只在 wrapper 内部出现）：

```python
# wrapper argv（冻结）
# open --session-id <terminal_session_id> --runtime-id <runtime_id>
#      --agent <agent> [--resume-id <conversation_id>]

if args.resume_id:
    if agent == "claude":
        argv = ["claude", "--resume", args.resume_id]
    elif agent == "codex":
        argv = ["codex", "resume", args.resume_id]
    else:
        raise UnsupportedResume(agent)  # bash/cc-switch 不支持 --resume-id
else:
    argv = AGENT_BINARIES[agent]  # 现有路径

# per-PTY 环境注入（SQLite 链用，见 §3c）
os.environ["AISC_TERMINAL_SESSION_ID"] = args.session_id
```

Rust `open_session` 增加可选 `resume_conversation_id` 参数 → 透传 wrapper。

**失败模型（v4 混合冻结——同步预校验 vs 异步 provider 失败分开处理）**：

| 阶段 | 失败类型 | 行为 |
|---|---|---|
| PTY spawn **前**（sidecar captured preflight，见 §2 代码草案） | conversation 文件不存在（精确 ID 匹配）/ conversation_id 非 UUID v4 / agent 不支持 resume | sidecar `conversation preflight` CliError → **现有 envelope 协议**（`errors[0].code`）→ Rust `map_aisc` → IPC 返回 `WorkbenchError` → **前端不建 tab**，对话行内提示。全程 captured 模式，无 PTY 泄漏 |
| PTY spawn **后**（provider 内部） | 会话文件损坏、provider 版本不支持该 id、resume 后立即崩溃 | 走**现有 session-exit 生命周期**：tab 已建（PTY 在），agent 退出事件照常上屏——与普通 agent 启动失败完全一致（用户看到退出信息，可关 tab） |

理由：open_session 的 reserve→spawn→返回 是既有原子路径（session.rs:347-483），
「spawn 后不建 tab」需要新握手协议，净增复杂度买不到体验；预校验把可同步判定
的失败（占绝大多数：点错/已删）拦在 spawn 前，剩余长尾沿用成熟失败 UX。

**预校验实现（v5 重构：sidecar 层 captured preflight，不在 wrapper 内）**

v4 的 wrapper 内预校验否决——`open_interactive` 是交互 PTY 路径，wrapper 的
stderr 直接进终端，**无结构化控制面**供 sidecar 解析。v5 起预校验是独立
子命令 `aisc conversation preflight`（captured 模式，纯 JSON envelope）：

```python
# src/aisc/cli/commands/conversation.py
def cmd_conversation_preflight(args, emitter, effective_format):
    """独立子命令：aisc conversation preflight（captured、非交互、纯 JSON）。"""
    ws_key = workspace_key_for(args.workspace)
    state = DataRootResolver().resolve(Path(args.workspace))
    conv_id = args.conversation_id

    # 精确 ID 校验（拒绝非 UUID 输入，不做 glob 子串匹配）
    if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}"
                        r"-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}", conv_id):
        raise CliError(message=f"Invalid conversation ID: {conv_id}",
                       exit_code=2, error_code="AISC_ERR_CONVERSATION_INVALID_ID")

    # provider-specific 精确文件匹配（非 rglob 子串）
    if args.agent == "claude":
        base = state.workspace_dir / "claude" / "projects"
        # Claude: 文件名 = <conversation_id>.jsonl，精确 stem 匹配
        hit = any(
            p.is_file() and p.stem == conv_id
            for p in base.rglob("*.jsonl")
        )
    elif args.agent == "codex":
        base = state.workspace_dir / "codex" / "sessions"
        # Codex: rollout-<timestamp>-<uuid>.jsonl，解析文件名尾段 UUID
        pat = re.compile(
            r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-"
            r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}"
            r"-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})\.jsonl$")
        hit = any(
            p.is_file() and (m := pat.match(p.name)) and m.group(1).lower() == conv_id.lower()
            for p in base.rglob("*.jsonl")
        )
    else:
        raise CliError(message=f"Unsupported agent for resume: {args.agent}",
                       exit_code=2, error_code="AISC_ERR_CONVERSATION_INVALID_AGENT")

    if not hit:
        raise CliError(
            message=f"Conversation {conv_id} not found for agent {args.agent}",
            exit_code=3, error_code="AISC_ERR_CONVERSATION_UNRESUMABLE")

    # preflight 通过 → 返回成功 envelope（Rust 接着调 open_session + --resume-id）
    return {"preflight_ok": True, "conversation_id": conv_id, "agent": args.agent}, 0, []
```

**错误传递链（冻结）**：preflight `CliError` → sidecar 统一 envelope
`errors[0].code = AISC_ERR_CONVERSATION_UNRESUMABLE / _INVALID_ID / _INVALID_AGENT`
→ Rust `map_aisc()` 新增三条中文映射 → `conversation_resume` IPC 返回
`WorkbenchError` → 前端行内提示。**全程走现有 envelope 协议**，不新增通道。

**wrapper 侧改动降为纯透传**：wrapper 只新增 `--resume-id` 参数 + provider argv
转换 + `AISC_TERMINAL_SESSION_ID` 环境注入。**不做文件校验**（preflight 已在
sidecar 层完成）。wrapper 内 `_fail` 签名不动。

## 3. Bash 体验增强

### 3a. 容器路径契约（v3 修正：复用现有挂载，不新建）

**实际挂载（runtime.py:1184 已有，不改）**：
```
<workspace_state_dir>/runtime  →  /root/.local/state/cc-switch
```

**裁决：选项 2** —— Bash runtime 数据复用该挂载。目录名 `cc-switch` 是历史遗产，
v3 起其定位扩展为「工作区 runtime 持久化目录」（承载 cc-switch 状态 + Bash 历史）；
data-root 契约文档同步注记，不改挂载目标（改挂载会破坏存量卷）。

**宿主内路径**：`workspaces/<hash>/runtime/`
**容器内路径**：`/root/.local/state/cc-switch/`

### 3a-i. 完整传递链（冻结）

```
start_runtime (Python, runtime.py)
  └─ docker create 追加 env：
       -e AISC_WORKSPACE_HASH=<workspace_key>  # = workspace_key_for() 原始
         # SHA-256 hex（区别于 data-root 目录名 sha256-v1-<hex>；后者仅用于
         # 定位目录，SQLite 字段与诊断日志一律用原始 hex
         # ⚠ T2 实装任务：当前 runtime.py:1139-1145 尚未传此 env——T2 需在
         # docker create 的 -e 列表中新增（与 CLI_SCOPE 并列），非已有实现
       （scope 沿用现有 -e CLI_SCOPE=project|temporary，runtime.py:1139——
         不新造 AISC_SCOPE；bashrc 经 entrypoint 的 SCOPE 间接可得，不直接消费）

entrypoint.sh（idle 分支，runtime-context 写入处）
  ├─ export AISC_BASH_HISTORY_DIR=/root/.local/state/cc-switch  # 挂载点常量
  ├─ export AISC_BASH_HISTORY_FILE=$AISC_BASH_HISTORY_DIR/.bash_history
  ├─ export AISC_BASH_HISTORY_DB=$AISC_BASH_HISTORY_DIR/bash_history.db
  └─ runtime-context.json 增字段：bash_history_file / bash_history_db

aisc-session-wrapper open（每个 PTY 一次）
  └─ exec 前导出：AISC_TERMINAL_SESSION_ID=<args.session_id>
     （per-PTY 正确性：docker exec 每次新进程，wrapper 从自身 --session-id 注入）

bash --rcfile /usr/local/share/aisc/bashrc
  └─ 读 AISC_BASH_HISTORY_FILE / _DB / _WORKSPACE_HASH / _TERMINAL_SESSION_ID
```

**作用域差异**：
- `project`：挂载存在 → HISTFILE + SQLite 均持久（宿主 data root）
- `temporary`：同路径落在容器层（无挂载）→ 容器删除即失；代码不分支（临时工作区
  本无持久承诺）

**权限**：挂载目录 root 属主（容器 root 运行，天然可写）。

### 3b. ble.sh + fzf 安装（可复现）

**版本 pin**：

| 工具 | 版本 | 来源 | 安装方式 |
|---|---|---|---|
| ble.sh | `nightly-20250829`（冻结 commit） | GitHub release tar.xz | 解压至 `/usr/local/share/ble.sh/` |
| fzf | apt（Debian 12 版本） | apt 源 | `apt-get install -y fzf` |
| neovim | apt | apt 源 | `apt-get install -y neovim` |
| ripgrep | apt | apt 源 | `apt-get install -y ripgrep` |
| yazi | `25.2.26`（冻结） | GitHub release zip | 静态二进制 + sha256 校验 |
| tmux | 已有 | — | — |

**ble.sh 下载**：复用现有 CN mirror 链（ghfast.top 等）。**yazi**：同左；amd64 资产 `yazi-x86_64-unknown-linux-musl.zip`，arm64 资产 `yazi-aarch64-unknown-linux-musl.zip`。两者均 sha256 校验（Dockerfile ARG 注入）。

### 3c. rcfile 初始化链路（冻结）

镜像内置 `/usr/local/share/aisc/bashrc`，wrapper 对 bash agent 使用：

```python
# aisc-session-wrapper
if agent == "bash":
    argv = ["bash", "--rcfile", "/usr/local/share/aisc/bashrc"]
```

bashrc 内容：
```bash
# /usr/local/share/aisc/bashrc — AISC-managed bash initialization
# 0. RECURSION GUARD (P0)：wrapper --rcfile 与 /root/.bashrc shim 互指
#    （rcfile source ~/.bashrc → shim source rcfile）。守卫保证只加载一次。
if [ "${AISC_BASHRC_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
AISC_BASHRC_LOADED=1   # 故意不 export：tmux 子 shell 不继承 → 可完整初始化

# 1. Source user/system rc if present (non-blocking)
[ -f /etc/bash.bashrc ] && source /etc/bash.bashrc
[ -f ~/.bashrc ] && source ~/.bashrc

# 2. HISTFILE persistence
if [ -n "$AISC_BASH_HISTORY_FILE" ]; then
  export HISTFILE="$AISC_BASH_HISTORY_FILE"
  export HISTSIZE=10000
  export HISTCONTROL=ignoredups:erasedups
  shopt -s histappend
fi

# 3. ble.sh (fish-style ghost text; fail-open)
if [ -f /usr/local/share/ble.sh/ble.sh ] && [[ $- == *i* ]]; then
  source /usr/local/share/ble.sh/ble.sh --noattach
fi

# 4. fzf key bindings (Ctrl+R; fail-open)
if [ -f /usr/share/doc/fzf/examples/key-bindings.bash ]; then
  source /usr/share/doc/fzf/examples/key-bindings.bash
fi

# 5. SQLite append via Python helper (参数化 API——shell 不拼 SQL，
#    免疫引号/换行/Unicode; fail-open)
if [ -n "$AISC_BASH_HISTORY_DB" ] && [ -n "$AISC_WORKSPACE_HASH" ]; then
  _aisc_prev_cmd=""
  _aisc_log_history() {
    local _aisc_exit=$?                        # FIRST line: capture BEFORE anything
    local cmd
    cmd="$(history 1 | sed 's/^ *[0-9]* *//')"
    if [ -z "$cmd" ] || [ "$cmd" = "$_aisc_prev_cmd" ]; then
      return "$_aisc_exit"                     # dedupe/empty still preserves code
    fi
    _aisc_prev_cmd="$cmd"
    AISC_HIST_DB="$AISC_BASH_HISTORY_DB" \
    AISC_HIST_WS_HASH="$AISC_WORKSPACE_HASH" \
    AISC_HIST_SESSION_ID="$AISC_TERMINAL_SESSION_ID" \
    AISC_HIST_CMD="$cmd" AISC_HIST_CWD="$PWD" \
    AISC_HIST_EXIT="$_aisc_exit" \
    python3 /usr/local/bin/lib/aisc_bash_history.py append 2>/dev/null
    return "$_aisc_exit"                       # LAST: restore original code
  }
  # Append to existing PROMPT_COMMAND, don't overwrite; the guard above
  # makes double-source impossible, so no double-append.
  # 注：仅支持字符串形式 PROMPT_COMMAND；Bash 数组形式（PROMPT_COMMAND=(a b)）
  # 本期不兼容——rcfile 在用户 rc 之后 source，数组 hook 罕见于交互 shell；
  # 如用户确用数组形式，AISC hook 不追加（无损降级，HISTFILE/ble.sh 不受影响）。
  case ";${PROMPT_COMMAND};" in
    *;_aisc_log_history;*) ;;                      # already present
    *) PROMPT_COMMAND="_aisc_log_history;${PROMPT_COMMAND}" ;;
  esac
fi

helper（镜像新增 /usr/local/bin/lib/aisc_bash_history.py；子命令冻结）：

```python
# init    : 幂等建库（CREATE TABLE/INDEX IF NOT EXISTS + WAL + busy_timeout）
# append  : 若表缺失先隐式 init（同事务内，幂等）→ 参数化 INSERT
# retain  : 保留最近 10000 条（entrypoint 启动时调用一次）

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS history ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " workspace_hash TEXT NOT NULL, terminal_session_id TEXT,"
    " cmd TEXT NOT NULL, cwd TEXT, started_at TEXT,"
    " exit_code INTEGER, source TEXT NOT NULL DEFAULT 'terminal');"
    "CREATE INDEX IF NOT EXISTS idx_history_ts ON history(started_at DESC);"
    "CREATE INDEX IF NOT EXISTS idx_history_cmd ON history(cmd);"
)

def _connect(db):
    conn = sqlite3.connect(db, timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")   # 幂等
    conn.executescript(_SCHEMA)               # IF NOT EXISTS → 幂等
    return conn

# append: _connect → INSERT(?) 参数化 → commit
# retain: DELETE FROM history WHERE id NOT IN
#         (SELECT id FROM history ORDER BY id DESC LIMIT 10000)
```

**初始化责任（冻结）**：`append` 首次调用即幂等初始化（不依赖 init 先行）；
`init` 仅供显式预热/诊断；`retain` 由 entrypoint 启动时调用一次。

**env 注入链（补 §3a-i）**：
- `AISC_WORKSPACE_HASH`：start_runtime docker create 时 `-e` 注入（容器级，全 PTY 共享）
- `AISC_TERMINAL_SESSION_ID`：wrapper 每个 PTY exec 前导出（per-PTY 正确）；
  `aisc shell` 直连路径无 wrapper → 无此变量 → helper 跳过写库（HISTFILE 仍生效）
```

**tmux 闭环（v3）**：镜像 **拥有** `/root/.bashrc`（容器 root fs，非用户工作区文件；
entrypoint「不改用户 bashrc」的约束针对挂载进来的工作区文件）。镜像层在该文件追加
受保护 shim（标记块，幂等）：

```bash
# >>> aisc managed >>>
if [ -f /usr/local/share/aisc/bashrc ] && [[ $- == *i* ]]; then
    source /usr/local/share/aisc/bashrc
fi
# <<< aisc managed <<<
```

效果：tmux 新 pane 起交互 bash → 读 `/root/.bashrc` → shim source AISC rcfile →
**ble.sh / Ctrl+R / HISTFILE / SQLite hook 全部继承**（HISTFILE 经 tmux 环境继承 +
rcfile 重导出双保险）。wrapper `--rcfile` 与 shim 同源幂等不冲突；用户自有内容写在
shim 之后不受影响。

**其余边界**：
- 非交互 bash（`bash -c`）：不加载 rcfile/shim（`[[ $- == *i* ]]` 守卫），不写历史
- 用户自定义：wrapper 场景 rcfile 先 source `/etc/bash.bashrc` + `~/.bashrc`；
  shim 场景 AISC 块在前、用户内容在后
- ble.sh / fzf 初始化失败：不阻断 bash 启动（守卫 + `|| true`）
- `bash --rcfile` 跳过 `/etc/profile`：rcfile 内显式 source `/etc/bash.bashrc` 弥补

### 3d. SQLite Schema（冻结）

```sql
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_hash TEXT NOT NULL,
  terminal_session_id TEXT,
  cmd TEXT NOT NULL,
  cwd TEXT,
  started_at TEXT,        -- ISO 8601
  exit_code INTEGER,
  source TEXT NOT NULL DEFAULT 'terminal'
);
CREATE INDEX IF NOT EXISTS idx_history_ts ON history(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_cmd ON history(cmd);
```

**并发策略**：
- WAL 模式：`PRAGMA journal_mode=WAL`（初始化时设置一次）
- busy timeout：`PRAGMA busy_timeout=5000`（每连接）
- 多终端并发：Python helper 每次独立连接；WAL 允许并发读 + 串行写 +
  busy_timeout=5000 兜底
- HISTFILE 并发：`histappend` 模式下 bash 以 O_APPEND 追加，行级原子性由内核保证

**Retention**：保留最近 10000 条（entrypoint 启动时 `DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 10000)`）。

**敏感命令**：不脱敏存储（终端本身可见明文）；Workbench 侧查询时脱敏展示。

### 3e. 工具版本矩阵

| 工具 | amd64 资产 | arm64 资产 | sha256 校验 |
|---|---|---|---|
| ble.sh | `ble-nightly-<commit>.tar.xz` | 同左 | ARG 注入 |
| yazi | `yazi-x86_64-unknown-linux-musl.zip` | `yazi-aarch64-unknown-linux-musl.zip` | ARG 注入 |

Dockerfile ARG：
```dockerfile
ARG BLE_SH_VERSION=nightly-20250829
ARG BLE_SH_SHA256=<hash>
ARG YAZI_VERSION=25.2.26
ARG YAZI_SHA256_X86=<hash>
ARG YAZI_SHA256_ARM64=<hash>
```

下载失败策略：CN mirror 链 → 直连 → 构建失败（fail-closed，不装残缺工具）。

## 4. UI 设计（冻结）

### 4a. 位置

「变更」面板（activeKind='artifacts'）新增**第五个分组**「Agent 对话」，排在现有四组（可交付/源码变更/生成输出/未归因变更）之后。分组可收拢（同现有 collapsible groups）。

### 4b. 前端数据模型

```typescript
// stores/conversationHistory.ts（新建，不入 workspaceExplorer store）
interface ConversationSummary {
  conversation_id: string;
  agent: "claude" | "codex";
  title: string;
  started_at: string | null;
  last_at: string | null;
  message_count: number | null;   // file_too_large 时 null
  file_size: number;
  resumable: boolean;
  unavailable_reason?: "file_too_large" | "malformed" | "unsupported";
}
```

### 4c. 交互

- 每行：`[agent 图标] 标题 · 相对时间`（如 `claude 帮我写排序 · 5 分钟前`）
- 点击可恢复行 → 调 `conversation_resume` → 新终端页签 → 自动激活
- 点击不可恢复行 → 行内提示「此对话无法恢复」（不弹窗）
- 搜索：变更页顶部搜索框**同时搜索对话标题**（matcher 复用）
- 分组按 `last_at` 降序混合排列（不按 agent 分组——用户关心时间线）
- 显示前 20 条 + 「展开全部」
- 空状态：「暂无历史对话」
- 加载状态：现有 artifacts-panel 的 loading 复用
- 刷新：进入变更页时刷新（现有 `refreshArtifacts` 时机）+ 手动刷新按钮

### 4d. 恢复编排（v7：preflight 成功前不建 tab/pane/channel）

当前 `openPane` 是「先建 pane/session_id/Channel → 再调 IPC」（workspaceRuntime.ts:1110-1157）。
conversation_resume 不能走这条路径（preflight 失败时 pane 已存在）。**前端编排冻结**：

```
对话行点击
  → 设置 conversationResumePending = conversation_id（行内 spinner，全局禁点）
  → 调 Rust IPC conversation_resume(runtime_id, workspace, conversation_id, agent, on_event)
      │
      ├─ Rust 内部第一步：run_control preflight 失败
      │    → IPC 返回 WorkbenchError
      │    → 前端：清 pending，行内错误提示；tab/pane/Channel 均未创建
      │
      └─ preflight 成功 → Rust 第二步 open_session
           → 前端在 on_event 首次收到事件前：
             ① 调 store.createTab(agent) 生成 tab/pane（现有路径，pane.sessionState=starting）
             ② 用返回的 terminal_session_id 绑定 pane
             ③ Channel 在 Rust 侧已创建并传入——前端不预建 Channel
           → agent 输出流经 on_event → pane 渲染
           → open_session 失败（provider 层）：tab 已建，走现有 session-exit 失败 UX
```

**关键规则**：Channel 由 Rust `conversation_resume` 参数携带（前端传入的是
空 Channel 框架，Tauri 绑定后事件自动回流）——前端不预建任何 PTY 基础设施，
也不需要「未提交 Channel 的释放」逻辑。pane/tab 创建发生在 IPC 调用**之后**
（前端 `await` 返回或首个事件到达时），preflight 失败自然零残留。

- 重复点击防抖：`conversationResumePending !== null` 时禁用所有对话行点击

### 4e. 工作区切换

- 切换工作区时清空 conversationHistory store
- 不取消进行中的 IPC 请求（结果丢弃即可，不显示旧数据）

## 5. Codex 下一步提示（AGENTS.md）

**不覆盖用户文件**。镜像在 `/usr/local/share/aisc/agent-instructions.md` 放 AISC 管理的指令模板；entrypoint 启动时：

1. 检查 `/root/AGENTS.md` 是否存在
2. 若不存在 → 复制 AISC 模板
3. 若存在 → **不修改**（用户自主）

模板内容：
```markdown
# AISC Agent Guidelines

## Response Format
After completing a task, suggest 2-3 logical next steps in concise Chinese.
```

**用户可控**：`AISC_AGENT_INSTRUCTIONS=off` 环境变量禁用注入。

## 6. 测试矩阵（扩展）

### 历史解析（CLI）

| 用例 | 期望 |
|---|---|
| Claude 正常 fixture（含 user/assistant/attachment） | 正确提取 title/timestamp/count |
| Codex 正常 fixture（含 session_meta/response_item） | 同上 |
| 空文件（0 字节） | 排除出列表 |
| 仅 queue-operation 行（无用户消息） | 排除出列表 |
| 单条用户消息 | 保留，resumable=true |
| 多文件混合 | 按时间排序正确 |
| 损坏 JSON 行（半写入尾部） | 跳过该行，不崩溃 |
| 超大文件（>10MB） | resumable=false |
| 标题含 API key 模式 | 脱敏为 [REDACTED] |
| 标题含换行/ANSI | 清除后显示 |
| 非 UTF-8 字节 | 跳过该行 |
| 缺失 timestamp | last_at=null |

### 恢复（CLI + Rust + wrapper）

| 用例 | 期望 |
|---|---|
| Claude resume argv 生成 | `claude --resume <id>` |
| Codex resume argv 生成 | `codex resume <id>` |
| conversation_id ≠ terminal_session_id | 新 UUID 生成，原 ID 保留 |
| 恢复不存在的 conversation_id（精确 stem/UUID 匹配失败） | preflight 拦截：`AISC_ERR_CONVERSATION_UNRESUMABLE` 信封；**不调用 open_session、不 spawn PTY、不建 tab**；行内提示 |
| preflight 成功后 open_session 正常 | open_session 调用恰一次；`--resume-id` 透传 wrapper；`on_event` 收到 provider 输出 |
| preflight 通过但 provider 启动失败 | tab 已建；走 session-exit UX |
| conversation_id 非 UUID 格式 | preflight `AISC_ERR_CONVERSATION_INVALID_ID`（exit 2） |
| conversation_id 是另一会话的子串 | 精确匹配拒绝（不做子串命中） |
| agent=bash 传 --resume-id | preflight `AISC_ERR_CONVERSATION_INVALID_AGENT` |
| resume 后 provider 立即失败（损坏会话） | tab 已建，走现有 session-exit 失败 UX |
| resume 会话文件损坏 | 错误信封 |
| 无运行时容器时调 resume | 明确错误码 |
| 重复点击恢复 | 第二次被防抖拦截 |

### Bash（entrypoint + wrapper）

| 用例 | 期望 |
|---|---|
| wrapper 用 --rcfile 启动 bash | rcfile 加载链生效 |
| 同一 bash 重复 source（wrapper+shim 双路径） | 守卫拦截：不递归、PROMPT_COMMAND 恰好一个 AISC hook |
| tmux 新 pane（继承已设 AISC_BASHRC_LOADED=1？） | 守卫未 export → 新 shell 完整初始化（ble/fzf/PROMPT_COMMAND 均生效） |
| HISTFILE 持久化 | 命令写入后容器重启可读 |
| SQLite 表结构 | 字段齐全 + WAL 启用 |
| 多行命令写入 | 整条保存（含换行） |
| 含引号命令写入 | SQLite 转义正确 |
| ble.sh 缺失时启动 bash | 正常启动（fail-open） |
| fzf 缺失时 Ctrl+R | 原生 bash 行为 |
| PROMPT_COMMAND 已有 hook | AISC hook 追加不覆盖 |
| 临时工作区 | HISTFILE 退化为内存（不报错） |

## 7. 不做（本期）

- 对话内容预览/浏览（下周期）
- Workbench 侧命令搜索 UI（SQLite 数据已就位，消费下周期）
- AISC 侧**运行时动态 prompt 注入**（本期仅做 §5 的镜像级可选 AGENTS.md 模板注入）
- cross-workspace 全局命令历史
- Claude/Codex 对话合并去重

## 8. 阶段重排

| 阶段 | 内容 | 依赖 |
|---|---|---|
| T0 | 探针 fixture 冻结（真实 JSONL 脱敏入 tests/fixtures/） | 无 |
| T1 | Picker 清理 + AGENTS.md（P2 快修） | 无 |
| T2 | Bash 全套（Dockerfile 工具 + rcfile + HISTFILE + SQLite） | T0 |
| T3 | CLI `conversation list`（JSONL 解析 + fixture 测试） | T0 |
| T4 | wrapper `--resume-id` + Rust IPC + 变更页 UI | T3 |
| T5 | 手测全矩阵 + CI + 收口 | T2+T4 |
