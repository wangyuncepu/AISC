# v2.1.8 设计文档：Agent 历史对话管理 + Bash 体验增强

> 日期：2026-08-29 · 状态：已审阅 · 方案 A（薄层直读）

## 1. 目标

1. 「变更」页双区：工作区文件变更 + Agent 历史对话（可点击恢复）
2. 内建 bash：fish 式幽灵补全（ble.sh）+ Ctrl+R 模糊搜索（fzf）+ HISTFILE 持久化 + SQLite 追写
3. 内建 bash 增加常用工具：yazi / tmux / neovim / ripgrep
4. Codex 下一步提示（AGENTS.md prompt 工程）
5. Picker 历史行移除 agent 标签

## 2. Agent 历史对话管理

### 数据流

```
Claude:  workspaces/<hash>/claude/projects/<dir>/*.jsonl
Codex:   workspaces/<hash>/codex/sessions/*.jsonl (路径实探)
                    ↓
CLI:     aisc session list --workspace <path> --format json
         → [{session_id, agent, title, started_at, last_at, message_count}]
                    ↓
Rust:    session_list(workspace) → Vec<SessionSummary> (IPC)
                    ↓
Vue:     变更页 "Agent 对话" 可收拢分组，每行 [agent图标] 标题 · 时间
```

### 恢复动作

- 点击行 → 前端 `session_resume(workspace, session_id, agent)` IPC
- Rust 走现有 `open_session` + `--resume <id>` (claude) / codex 等效命令（实探后定）
- 新终端页签自动激活

### 标题提取

JSONL 首条 `type=human` 消息文本前 60 字符；无则 `(无标题)` + 时间戳。

### 排序与上限

`last_at` 降序；显示前 20 条 + 展开全部。

### 边界

- 仅 project-scope 工作区（temporary 无持久对话）
- codex 会话文件格式待实探（可能非 JSONL，需适配层）
- 过滤空对话（message_count < 2）

## 3. Bash 体验增强

### 3a. ble.sh（fish 式幽灵提示）

镜像 Dockerfile 安装 ble.sh nightly → `source` 进 `/etc/bash.bashrc`。
纯 bash 实现，无外部依赖；读 bash 内存历史（HISTFILE 加载后）。

### 3b. fzf（Ctrl+R 模糊搜索）

apt 安装；`source /usr/share/doc/fzf/examples/key-bindings.bash` 进 bashrc。

### 3c. HISTFILE 持久化

entrypoint 设置：
```bash
HISTFILE="<workspace-state>/runtime/.bash_history"
HISTSIZE=10000
HISTCONTROL=ignoredups:erasedups
shopt -s histappend
```

### 3d. SQLite 追写

PROMPT_COMMAND + `history 1` 读最后命令（避免引号注入），追写：
```sql
CREATE TABLE IF NOT EXISTS history(
  id INTEGER PRIMARY KEY, cmd TEXT, ts REAL, cwd TEXT
);
```
DB 路径：`<workspace-state>/runtime/bash_history.db`。
**终端侧不消费 SQLite**（ble.sh 读 HISTFILE）；SQLite 仅供 Workbench 后续查询。

### 3e. 工具安装

| 工具 | 方式 | 用途 |
|---|---|---|
| fzf | apt | 模糊搜索 |
| tmux | apt | 终端复用 |
| neovim | apt | 编辑器 |
| ripgrep | apt | 快速搜索 |
| yazi | GitHub release 静态二进制 | 文件管理器 |

## 4. Codex 下一步提示

镜像 `/root/AGENTS.md` 或 codex 全局指令文件注入：
> 任务完成后，在回复末尾用简洁的中文列出 2-3 个逻辑下一步建议。

纯 prompt 工程；效果依赖模型遵循度；不可靠则挂账（AISC 侧追加方案复杂度高）。

## 5. Picker 清理

删 `WorkspacePicker.vue` 历史行末尾 agent 标签（`picker.recentAgent` 键 + 渲染代码）。i18n 两语言。

## 6. 测试策略

| 层 | 覆盖 |
|---|---|
| CLI | `session list` 解析 JSONL fixture → 结构化输出 |
| Rust | `session_list` / `session_resume` IPC 信封测试 |
| Vue | 变更页双分组 + 对话行渲染 + 点击恢复 mock |
| Dockerfile | 工具安装冒烟（CI Bundle 路径已有） |
| entrypoint | HISTFILE / PROMPT_COMMAND shellcheck |

## 7. 不做

- 对话内容预览/浏览（下周期 B 方案增量）
- Workbench 侧命令搜索 UI（SQLite 已就位，消费下周期）
- AISC 侧 codex 提示注入（先试 prompt 工程）
- cross-workspace 全局命令历史索引
