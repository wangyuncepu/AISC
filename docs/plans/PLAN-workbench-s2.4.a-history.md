# Workbench S2.4.a - history 持久化 + 最近工作区

> 状态：提案
> 规范：02-startup-flow.md §九（history schema + 原子写 + 跨进程锁 + expected_revision）；03-lifecycle-contract.md §8.1（启动对账，完整版 S2.4.b）；06 §五 S2.4
> 编写日期：2026-08-07
> 分支：feature/workbench-phase2

## 1. 范围

S2.4 拆两子切片。**S2.4.a = history.rs 持久化基础 + 最近工作区列表**。立 history 文件 + 跨进程锁 + revision 机制（两窗口并发的地基），picker 显最近工作区。**不做**恢复布局/对账（S2.4.b）。

### 本切片做（IN）

- **history.rs**（Rust 新模块）：schema-versioned `history.json`（02 §九.2，subset：schema_version/revision/workspaces，window 几何留 b）。
  - `load(dir)`：缺失->空；corrupt JSON->隔离（rename `history.json.corrupt`）+ 返回空；unsupported schema->error 不覆盖（02 §九）。
  - `save(dir, expected_revision, patch)`：跨进程锁（`fs4` exclusive lock on `history.lock`，~5s 超时 fail-closed）-> 锁内 reload -> `revision != expected_revision` 返回 `Conflict{current_revision}`（调用方 reload/merge/有界重试）-> merge patch（upsert patch 的 workspace by path，保留其他）-> revision+1 -> 原子写（temp+fsync+rename，复用 settings.rs 模式）-> 返回新 revision。
  - 命令 `load_history(app) -> WorkbenchHistory`（只读）+ `save_history(app, expected_revision, patch) -> {revision}`（Conflict 为结构化 error）。
- **store**：`history`/`historyRevision`；启动 negotiate 后 `loadHistory`；`scheduleSave`（debounce 300ms）在 runtime ready / tab 开关 / workspace 选择 时持久化（记 path/last_used_at/last_agent/runtime ref/layout）；Conflict -> reload+merge+有界重试（3 次）。
- **picker 最近列表**：picker 显 `history.workspaces`（按 last_used_at desc，basename + 全路径 hover + last_agent），点击 -> 填 workspace + runPreflight。
- **Cargo.toml**：加 `fs4`（跨平台文件锁）。

### 本切片不做（OUT）

- **启动对账（runtime list 合并 history vs 实际）+ 恢复布局提示（恢复布局/空白打开）+ 为 tabs 创建新 session** -> S2.4.b（关「崩溃后发现 runtime」+「恢复布局」gate）。
- **孤儿 session 检测/处理（session list）** -> S2.4.b。
- **窗口几何 save/restore** -> S2.4.b（schema 留字段或 b 加）。
- **两窗口同 workspace 的细粒度合并** -> MVP last-write-wins on same path（revision 机制保护其他 workspace 不丢）。
- **history 损坏时的可恢复错误 UI** -> b（a 隔离文件 + 返回空，静默）。
- **provider/history secret scan** -> S3.2（history 不含 secret，仅 workspace/runtime_id/tab 元数据，02 §九 强制）。

## 2. 关键设计

### 2.1 schema（02 §九.2 subset）

```text
WorkbenchHistory
  schema_version: 1
  revision: u64
  workspaces: [WorkspaceRecord]
WorkspaceRecord
  path: canonical absolute
  last_used_at: ISO UTC
  pinned: bool
  last_agent: claude|codex|bash|cc-switch
  runtime: Option<RuntimeRef{runtime_id, image, network, scope}>
  layout: Option<Layout{active_tab_id: Option, tabs: [TabRecord{tab_id, agent, title, position}]}>
```
不含 session_id/PTY PID/scrollback/provider 密钥（02 §九 强制）。

### 2.2 跨进程锁 + revision（02 §九）

`save` 流程：lock `history.lock`（fs4 exclusive，~5s 超时）-> reload disk -> 校验 expected_revision -> merge patch（upsert by path，保留其他 workspace）-> revision+1 -> 原子写 -> unlock。Conflict（revision 不符）-> 调用方 reload + merge 自己 patch 进新 disk workspaces + 重试（≤3 次）。fail-closed：锁超时不开写。

### 2.3 save 触发（debounce）

store `scheduleSave()`：debounce 300ms 合并连续变更。触发点：runtime ready（initTabs 后，记 runtime ref + 初始 layout）、tab open/close/reopen（记 layout）、workspace 选中（picker，记 path/last_used/last_agent）。patch = 当前活动 workspace 记录。其他 workspace 由 disk 保留（merge）。

### 2.4 最近列表 UI

picker 输入框下方加「最近工作区」列表：`history.workspaces` 按 last_used desc，每项 basename + 全路径（title）+ last_agent。点击 -> `workspace = path` + `runPreflight`（跳过手输）。

## 3. 改动文件

### 后端
- `workbench/src-tauri/Cargo.toml`：`fs4 = "0.12"`（或最新）。
- `workbench/src-tauri/src/history.rs`（新）：schema structs + load（corrupt 隔离）+ save（锁+revision+merge+原子写）+ `load_history`/`save_history` 命令 + 单测（round-trip / corrupt 隔离 / revision conflict / merge 保留其他 workspace / schema 不匹配不覆盖）。
- `workbench/src-tauri/src/lib.rs`：`pub mod history;` + 注册 `load_history`/`save_history`。

### 前端
- `workbench/src/types/index.ts`：`WorkbenchHistory`/`WorkspaceRecord`/`RuntimeRef`/`Layout`/`TabRecord`。
- `workbench/src/lib/ipc.ts`：`loadHistory`/`saveHistory(expectedRevision, patch)`。
- `workbench/src/stores/runtime.ts`：`history`/`historyRevision` + `loadHistory`（startup）+ `scheduleSave`（debounce + conflict 重试）+ save 钩子。
- `workbench/src/App.vue`：picker 加最近列表。

## 4. 步骤与验证

1. Cargo.toml + history.rs + 命令 + 单测 -> verify: `cargo build` + `cargo test`（新 history 测试 + 58 不回归）。
2. types + ipc -> verify: typecheck。
3. store history + scheduleSave + 钩子 -> verify: typecheck。
4. picker 最近列表 + App.vue -> verify: `npm run build` 过。
5. 实机手测 -> verify:
   - 启动 dev -> picker 显最近工作区（首次为空）。
   - 选工作区 -> start runtime -> 开 tab -> 关 app。
   - 重启 dev -> picker 最近列表显该工作区（path + last_agent）-> 点击 -> 直接进 preflight。
   - `cat ~/.config/cn.aisc.workbench/history.json` 验证 schema/revision/workspaces 记录正确。
   - （两窗口并发可选测）开两 Workbench，各自选不同工作区 -> 两者 history 都保留（revision 机制）。

## 5. 验收（S2.4.a 局部）

- [ ] history.json schema-versioned 原子写，corrupt 隔离不覆盖。
- [ ] 跨进程锁 + expected_revision：Conflict 时有界重试，不丢其他 workspace。
- [ ] picker 显最近工作区，点击直接 preflight。
- [ ] runtime ready / tab 变更 / workspace 选中均持久化。
- [ ] `cargo test` + `npm run build` 零错误；58 测试不回归。
