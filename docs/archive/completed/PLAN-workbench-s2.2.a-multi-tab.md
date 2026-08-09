# Workbench S2.2.a — 多标签 + Session 状态机

> 状态：提案
> 规范：03-lifecycle-contract.md §五/§六/§七.1；06-implementation-plan.md §五 S2.2
> 编写日期：2026-08-07
> 分支：feature/workbench-phase2

## 1. 范围

S2.2 拆为两个子切片。本切片 **S2.2.a = 多标签 + Session 状态机**，**纯前端**（后端 S1.3 的 `open_session`/`close_session` registry 已是多 session 能力，无需改动）。

### 本切片做（IN）

- Claude/Codex/Bash/cc-switch **4 个固定 agent 标签**，共享同一个 runtime（03 §二.3/§六）。
- 每标签独立 Session 生命周期：`starting → running → exited/disconnected/failed`（03 §五），合并重复终止事件为单一 `SessionExit`。
- 切换标签 = 切换可见 Terminal 视图；隐藏标签的 PTY 继续运行（03 §六.8 关闭 Tab 才结束 Session）。
- 关闭 Session（标签 ×）：terminate 该 session，标签转 `exited`，可“重新打开”（新 session_id）。
- 停止 Runtime：关闭所有运行中标签的 session + `stop_runtime`，回 picker（沿用现有行为）。

### 本切片不做（OUT，明确 deferral）

- **runtime 状态机 / observed_at / revision / freshness / 轮询对账** → S2.2.b
- **list / remove / force-remove 管理 UI、冲突复用/停止替换** → S2.2.b（解决“不兼容 runtime 阻塞”痛点）
- **退出 Workbench 确认 + Tauri 关闭拦截** → S2.2.b（需状态机判定活动 session）
- **history 持久化 / 恢复布局 / 崩溃对账 / placeholder 恢复** → S2.4
- **Provider/auth Warning、P0/P1 可观察性侧栏** → S2.3
- runtime stop 时 session 退出 reason 精修为 `runtime_stop`（当前为 transport_error/disconnected）→ S2.2.b 状态机关联

## 2. 关键设计决策

### 2.1 4 固定标签 vs 任意新增

采用 **4 固定 agent 标签**（匹配 06 §五“实现 Claude/Codex/Bash/cc-switch 标签”与 02 §九.2 history tabs 语义）。每标签状态：`idle`（未开）/ `opening` / `running` / `closing` / `exited` / `failed`。不做任意新增/删除/重复 agent 标签（MVP 不需要，省去 dedup 与 position 管理）。

### 2.2 多 Terminal 实例

渲染每个非 idle 标签各一个 `<Terminal>`，`v-show` 仅活动标签可见（保留 DOM，PTY 持续输出到隐藏 xterm buffer）。Terminal 组件**重构为 tab-scoped**：props `tabId`，从 store 读该 tab 的 `sessionId`/`agent`，自管 PTY 生命周期。可见性变化时主动 `fit`（补 ResizeObserver 对 display 切换不触发的缺口）。

### 2.3 Session 状态机（store reducer）

每标签持有 `sessionId: string | null`、`sessionState`、`exit?: SessionExit`。事件来源：
- `open_session` Ok → `running`；reject → `failed`。
- PTY Channel `exit` 事件（reason=process_exit → `exited`；transport_error → `disconnected`）→ 单一权威来源，per-tab `closed` 标志防重复应用。
- 用户关标签 → `closing` → `close_session` 返回 → `exited`(reason=user_close)。
- 已 `exited`/`failed` 的标签点“重新打开”→ 新 session_id → `opening`。

后端 `session.rs` observer + `close_session` 已合并终止事件（S1.3），前端不再自行猜测最终原因（03 §五.2 末句）。

### 2.4 启动衔接

`startFromSummary` runtime ready 后：为 `launch.agent` 创建初始 tab 并开 session（`opening→running`），其余 3 tab 为 `idle`，`activeTabId = 初始 tab`，`status=ready`。

## 3. 改动文件

### 前端（全部）
- `workbench/src/types/index.ts`：新增 `Tab`、`TabSessionState`、`TabBinding`（或用 sessionId/exit 派生）；复用现有 `SessionState`/`SessionExit`。
- `workbench/src/stores/runtime.ts`：`tabs: Ref<Tab[]>`、`activeTabId`；actions `openTab(agent)`/`activateTab(tabId)`/`closeTab(tabId)`/`reopenTab(tabId)`/`onTabSessionExit(tabId, exit)`；改写 `openSessionForCurrent`→建初始 tab；`stopRuntime` 迭代关所有 running tab。移除单一 `sessionId`（改为 `activeTab.sessionId` 派生，保留 `runtimeId`/`runtimeReady`）。
- `workbench/src/features/terminal/Terminal.vue`：重构为 props `tabId`；scoped PTY；`visible` prop/watch → fit；exit 回调 `store.onTabSessionExit`。
- `workbench/src/features/workspace/TabBar.vue`（新）：4 agent 标签 + 状态指示 + 关闭/重新打开按钮。
- `workbench/src/App.vue`：`status=ready` 视图改 TabBar + 多 Terminal 容器（v-show）；移除单 Terminal 直接引用。
- `workbench/src/lib/ipc.ts`：无改动（open/close/write/resize 已就绪）。

### 后端
- 无改动。复用 `open_session`/`write_session`/`resize_session`/`close_session`。

## 4. 步骤与验证

1. types 加 Tab/状态枚举 → verify: `npm run build`（vue-tsc）过。
2. store 改 tabs 模型 + actions → verify: typecheck 过；现有 startup 流程不破（negotiate/preflight/summary/start 仍通）。
3. Terminal 重构 tab-scoped + visible fit → verify: typecheck 过；单标签仍能开 bash（回归）。
4. TabBar 组件 + App.vue ready 视图接线 → verify: `npm run build` 过；`cargo build` 过（无后端改动，仅确认未误改）。
5. 实机手测 → verify:
   - 开 claude 初始 tab + 点 Bash tab 开 bash，两 tab 各自独立输出，切换不丢历史。
   - 关闭运行中 tab → exited 显示退出码 → 重新打开成新 session。
   - 停止 Runtime → 所有 tab session 结束 → 回 picker。
   - resize 隐藏 tab 切回可见后正确 fit。

## 5. 验收（S2.2.a 局部）

- [ ] 4 agent 标签可独立开/关/重开，共享同一 runtime。
- [ ] 切换标签不丢 PTY 历史；隐藏标签继续运行。
- [ ] 关闭标签 terminate session（宿主+容器无孤儿，复用 S1.3 close 语义）。
- [ ] 停止 Runtime 关闭所有 session 后回 picker。
- [ ] `npm run build` + `cargo build` 零错误。
