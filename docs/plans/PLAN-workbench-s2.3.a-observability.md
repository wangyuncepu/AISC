# Workbench S2.3.a - 轮询对账 + P0 可观察性侧栏

> 状态：提案
> 规范：04-observability.md §二/§四.1/§五/§六；06 §五 S2.3；03 §8.2
> 编写日期：2026-08-07
> 分支：feature/workbench-phase2

## 1. 范围

S2.3 拆两子切片。**S2.3.a = 轮询对账 + P0 侧栏**，纯前端（复用 S2.2.b `runtime_inspect(workspace)`，后端零改）。关 Phase 2 gate「GUI 外 stop/remove 在轮询周期内显示真实状态」。

### 本切片做（IN）

- **轮询对账**：runtime ready 时周期 `runtime inspect` -> `applyRuntimeSnapshot`（S2.2.b observed_at 守卫），检测外部 stop/remove。
  - 可见性感知（04 §五）：窗口聚焦 5s / 失焦 15s / 最小化隐藏暂停；恢复时先标 stale 再立即 inspect。
  - 去重（in-flight 跳过）+ ±10% jitter；控制操作后不额外触发（S2.2.b 已 op->inspect）。
- **新鲜度**（04 §六.1 简化）：成功 inspect -> fresh；失败/resume -> stale；无 snapshot -> unknown。「observed Xs ago」相对时间显示。
- **P0 侧栏**（常驻 ready 视图）：workspace、runtime state + freshness + observed 相对时间、活动 agent、network/scope（config 免费可得）、精确 runtime_id/container_name、session 列表（tabs + 状态）、Stop Runtime + 手动 Refresh。

### 本切片不做（OUT）

- **provider status（claude/codex 的 provider/route/auth）+ 刷新** -> S2.3.b（P1）。
- **freshness fresh/stale/unknown 全 revision/request_seq 抗乱序硬化** -> S3.1（S2.2.b 已有 observed_at 简单守卫）。
- **runtime_stop session reason 精修 / stopped 状态保留 tabs 供 restart** -> S2.4（本切片外部 stop 时 session 经 PTY 自终为 disconnected，sidebar 显 stopped；不做自动 restart）。
- **history / 启动 list 对账 / 孤儿 session 检测** -> S2.4。
- **P2 runtime 详情面板（last_operation_error/启动诊断折叠）** -> 后续；本切片侧栏含基础信息。
- **aria-live 节流播报等完整 a11y** -> S3.3（本切片仅基础 aria-label）。
- CPU/内存图表（永不）。

## 2. 关键设计

### 2.1 轮询 composable

`composables/useRuntimePolling.ts`，App.vue `watch(store.status)`：ready -> start，离开 -> stop。

- `tick()`：`if (!runtimeId || !workspace || inFlight) skip`；`inFlight=true`；`runtimeInspect(workspace, runtimeId)` -> `applyRuntimeSnapshot`（fresh）；catch -> `markObservationFailed`（stale）；finally `inFlight=false; scheduleNext()`。
- `scheduleNext()`：`document.hidden` -> 暂停（不调度，等 visibility 恢复）；聚焦 `document.hasFocus()` -> 5s ±10% jitter；失焦 -> 15s ±10%。`setTimeout` 递归。
- visibility/focus listener：`hidden->visible` 或 blur->focus -> `markStale()` + 立即 `tick()`。
- `stop()`：clear timer + remove listeners + `freshness=unknown`。

### 2.2 新鲜度（store）

- `freshness: Ref<"fresh"|"stale"|"unknown">`、`lastReceivedAt: number`。
- `applyRuntimeSnapshot`：成功 -> `freshness="fresh"`、`lastReceivedAt=Date.now()`。
- `markObservationFailed()`：`freshness="stale"`（保留 last snapshot，标 stale）。
- 无 snapshot -> `unknown`。sidebar 用 `runtimeSnapshot.observed_at` + 本地 1s timer 显「observed Xs ago」。

### 2.3 侧栏布局

ready 视图改：`topbar + [sidebar | (TabBar + terminal)]`。原 toolbar（workspace/runtime/stop）内容并入侧栏，Stop 按钮移侧栏底部。

侧栏内容（自上而下）：
- **Workspace**：basename + full path（title）
- **Runtime**：state 徽章（Running/Stopped/Not found/Unknown，文本+色，不只靠色）+ freshness（fresh/stale/unknown）+ observed Xs ago + runtime_id（短，title 全）+ container_name
- **Config**：image / network / scope（runtimeSnapshot.config）
- **Active agent**：活动 tab title 或「No session」
- **Sessions**：tabs 列表（title + state 指示）
- **Actions**：「刷新」（手动 tick）+「停止 Runtime」

### 2.4 外部 stop/remove 的 UI 表现

轮询检测 runtime state -> stopped（外部 stop）或 not_found（外部 remove）。session 经 PTY 自终（disconnected，S2.2.a exit 事件）。sidebar 显真实 state；用户可「停止 Runtime」回 picker（重进经 discovery restart）。**只显示，不自动恢复**（gate = 显示真实状态）。

## 3. 改动文件（全前端）

- `workbench/src/composables/useRuntimePolling.ts`（新）：轮询循环 + 可见性/jitter/去重。
- `workbench/src/features/workspace/RuntimeSidebar.vue`（新）：P0 侧栏。
- `workbench/src/stores/runtime.ts`：`freshness`/`lastReceivedAt` + `markObservationFailed`/`markStale`；`applyRuntimeSnapshot` 更新 freshness；离开 ready 重置。
- `workbench/src/types/index.ts`：`Freshness` 类型。
- `workbench/src/App.vue`：ready 视图 sidebar 布局 + mount 轮询 composable（watch status）。

后端零改。

## 4. 步骤与验证

1. types 加 Freshness -> verify: typecheck。
2. store freshness 字段 + markObservationFailed/applyRuntimeSnapshot 更新 -> verify: typecheck。
3. useRuntimePolling composable -> verify: typecheck。
4. RuntimeSidebar.vue + App.vue 布局 + mount 轮询 -> verify: `npm run build` 过；`cargo build` 零改零错。
5. 实机手测 -> verify:
   - ready 侧栏显 workspace/runtime Running·fresh/agent/network/scope/IDs/sessions。
   - 外部 `./aisc runtime stop --runtime-id <id> --workspace <ws>` -> 轮询周期内（~5s）sidebar 显 Stopped·stale，session 转 disconnected。
   - 外部 `./aisc runtime remove --runtime-id <id> --workspace <ws>` -> 显 Not found。
   - 失焦/最小化后恢复 -> 立即刷新（stale->fresh）。
   - 手动「刷新」按钮触发 inspect。

## 5. 验收（S2.3.a 局部）

- [ ] ready 视图常驻侧栏显 workspace/runtime state+freshness/活动 agent/network/scope/IDs/sessions。
- [ ] 外部 stop/remove 在一个稳定轮询周期（~5s 聚焦 / ~15s 失焦）内反映真实 state。
- [ ] 失焦/最小化暂停；恢复先标 stale 再立即刷新。
- [ ] `npm run build` + `cargo build` 零错误。
