# v2.1.8 设计文档：Agent 历史对话管理 + Bash 体验增强

> 日期：2026-08-29 · 状态：待审阅（v2，补齐契约后重写）
> 方案 A（薄层直读）· 审阅 v1 的 P0/P1/P2 已逐项回应

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
| resume argv | `claude --resume <session-id>` | `codex resume <session-id>` |
| max_file_size | 10MB（超限跳过，标 `resumable:false`） | 10MB（同左） |
| malformed 行策略 | 跳过不完整 JSON 行；零可解析行 → 排除出列表 | 同左 |

### 1b. CLI 命令（冻结）

```bash
# 列表（只读，不碰 Docker）
aisc conversation list --workspace <path> [--format json|text]

# 恢复（需要运行中的容器）
aisc conversation resume --workspace <path> --conversation-id <id> --agent <claude|codex> [--format json]
```

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
      "resumable": true
    }
  ]
}
```

**resume 输出**：信封 `{terminal_session_id: "<new-uuid>", agent, conversation_id}` 或错误。

### 1c. ID 分离（冻结）

| 字段 | 含义 | 生成方 |
|---|---|---|
| `conversation_id` | provider 原生会话 ID（Claude/Codex 的 UUID） | provider CLI 写入 JSONL 文件名 |
| `terminal_session_id` | Workbench PTY 生命周期 UUID（新生成） | Rust `uuid()` |

恢复流程：
1. 前端调 IPC `conversation_resume(workspace, conversation_id, agent)`
2. Rust 生成新 `terminal_session_id = uuid()`
3. Rust 走现有 `open_session` 路径，wrapper 传 `--resume <conversation_id>` 作为 agent 额外参数
4. wrapper 对 claude 执行 `claude --resume <id>`；对 codex 执行 `codex resume <id>`
5. 返回 `{terminal_session_id, conversation_id, agent}` — 前端用 terminal_session_id 管理新页签

### 1d. 标题提取（脱敏规范）

1. **优先级**：provider 原生 title/summary 字段（当前均无）→ 首条用户消息
2. **提取**：取消息内容文本；`message.content` 为列表时取首个 `type='text'` 块
3. **清洗**：
   - 删除换行符、ANSI escape、控制字符（`\x00-\x1f`）
   - 截断至 80 Unicode scalar values（不是字节）
4. **脱敏**：匹配 `sk-[a-zA-Z0-9]{20,}` / `Bearer\s+\S+` / `api[_-]?key.*['\"]\s*\w{16,}` → 替换为 `[REDACTED]`
5. **降级**：提取失败 → `"(无法读取)"`；单文件失败不阻断列表（该行标 `resumable:false`）

### 1e. 过滤规则（替代 message_count < 2）

- **排除条件**：零条可解析的用户消息（`type=user` 且 `message.role=user` 且有非空内容）
- **保留单条用户消息**的会话，标 `resumable: true`（claude/codex 均可恢复）
- **排除条件**：文件 > 10MB（性能护栏，标 `resumable:false` 而非静默丢弃）

### 1f. Rust IPC（冻结）

```rust
#[tauri::command]
pub async fn conversation_list(workspace: String) -> Result<ConversationListResult, WorkbenchError>;

#[tauri::command]
pub async fn conversation_resume(
    workspace: String, conversation_id: String, agent: String
) -> Result<ConversationResumeResult, WorkbenchError>;
```

TS 侧对应类型：
```typescript
interface ConversationSummary {
  conversation_id: string;
  agent: "claude" | "codex";
  title: string;
  started_at: string | null;
  last_at: string | null;
  message_count: number;
  resumable: boolean;
}
```

## 2. wrapper 扩展

`aisc-session-wrapper open` 增加可选 `--resume-id <conversation_id>` 参数：

```python
# wrapper 内部
if args.resume_id:
    if agent == "claude":
        argv = ["claude", "--resume", args.resume_id]
    elif agent == "codex":
        argv = ["codex", "resume", args.resume_id]
else:
    argv = AGENT_BINARIES[agent]  # 现有路径
```

Rust `open_session` 增加可选 `resume_conversation_id` 参数 → 透传 wrapper。

**容错**：resume 失败（会话不存在/provider 版本不支持）→ wrapper 退出码非零 → 现有 session-exit 流程报错 → 前端显示失败 tab（与普通 agent 启动失败一致）。

## 3. Bash 体验增强

### 3a. 容器路径契约（runtime context 扩展）

宿主 `start_runtime` 在 runtime-context.json 中新增：
```json
{
  "workspace_state_dir": "/root/.aisc-state"
}
```

entrypoint 将该路径同步导出为环境变量：
```bash
export AISC_WORKSPACE_STATE_DIR="$(jq -r '.workspace_state_dir' /run/aisc/runtime-context.json 2>/dev/null || echo '')"
export AISC_BASH_HISTORY_FILE="${AISC_WORKSPACE_STATE_DIR}/runtime/.bash_history"
export AISC_BASH_HISTORY_DB="${AISC_WORKSPACE_STATE_DIR}/runtime/bash_history.db"
```

**挂载方式**：`workspaces/<hash>/runtime/` 已是 bind mount（容器内 `/root/.aisc-state/runtime/`）——project scope 通过 data-root 挂载链已有；temporary scope 无挂载（HISTFILE 退化为容器内存，SQLite 跳过）。

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

# 5. SQLite history append (fail-open)
if [ -n "$AISC_BASH_HISTORY_DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  _aisc_prev_cmd=""
  _aisc_log_history() {
    local cmd
    cmd="$(history 1 | sed 's/^ *[0-9]* *//')"
    [ -z "$cmd" ] && return
    [ "$cmd" = "$_aisc_prev_cmd" ] && return  # dedupe consecutive
    _aisc_prev_cmd="$cmd"
    sqlite3 "$AISC_BASH_HISTORY_DB" "
      INSERT INTO history (workspace_hash, terminal_session_id, cmd, cwd, started_at, exit_code, source)
      VALUES ('${AISC_WORKSPACE_HASH:-}', '${AISC_TERMINAL_SESSION_ID:-}', 
              '\''$(echo "$cmd" | sed "s/'/'\\\\''/g")'\'',
              '$PWD', datetime('now'), $?, 'terminal');
    " 2>/dev/null || true
  }
  # Append to existing PROMPT_COMMAND, don't overwrite
  PROMPT_COMMAND="_aisc_log_history;${PROMPT_COMMAND}"
fi
```

**边界**：
- 非交互 bash（`bash -c`）：不加载 rcfile（`--rcfile` 仅 interactive），不写历史
- tmux 子 shell：tmux 启动新 shell → 新 bash 进程 → 需 `$TERM` 且 interactive 才走 rcfile；tmux 的默认 shell 不会自动 source（用户可在 tmux 配置中手动 source）
- 用户自定义 `~/.bashrc`：rcfile 先 source 它，AISC 追加在后（优先级不冲突）
- ble.sh / fzf 初始化失败：不阻断 bash 启动（`|| true` 保护）
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
- 多终端并发：WAL 允许并发读 + 串行写；sqlite3 CLI 每次调用独立连接（auto-commit）
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
  message_count: number;
  resumable: boolean;
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

### 4d. 恢复中状态

- 恢复按钮点击 → loading → 成功：跳转新终端页签 / 失败：行内错误提示（不弹窗）
- 重复点击防抖：恢复进行中禁用所有对话行的点击

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
| 恢复不存在的 conversation_id | 错误信封，无 tab 创建 |
| resume 会话文件损坏 | 错误信封 |
| 无运行时容器时调 resume | 明确错误码 |
| 重复点击恢复 | 第二次被防抖拦截 |

### Bash（entrypoint + wrapper）

| 用例 | 期望 |
|---|---|
| wrapper 用 --rcfile 启动 bash | rcfile 加载链生效 |
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
- AISC 侧 codex 提示注入（先试 AGENTS.md prompt 工程）
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
