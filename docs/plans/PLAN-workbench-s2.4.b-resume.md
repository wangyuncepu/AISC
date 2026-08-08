# Workbench S2.4.b - 恢复布局（resume layout）

> 状态：提案
> 规范：02-startup-flow.md §2.3（Resume Layout）+ §九；03-lifecycle-contract.md §六（Tab 契约）/§8.1
> 编写日期：2026-08-08
> 分支：feature/workbench-phase2

## 1. 范围

S2.4.b 收尾 Phase 2：**恢复布局**（关「恢复布局」gate）。崩溃/关闭后重进已知工作区，可恢复上次的 tab 布局（开新 session，不续接 PTY）。「崩溃后发现 runtime」gate 已被 S2.4.a recents + S2.2.b discovery 覆盖（preflight 显 reuse/restart，不自动 stop/remove）。

### 本切片做（IN）

- **history layout 只记 open tabs**：`buildPatch` 过滤 `sessionState !== "idle"` 的 tab（之前记全部 4 个），使 layout 反映「上次实际开着的 tab」。
- **恢复布局按钮**：LaunchSummary 在 preflight `reuse`/`restart`（runtime 存在）且 history 该 workspace 有 open tabs 时，显「恢复布局」按钮 + 文案「恢复标签布局会启动新的 Agent 会话，不会续接上次终端内容」（02 §2.3）。`Start` 仍走单 tab 路径（空白打开）。
- **resumeLayout action**：复用 `ensureRuntime()`（抽出 start/reuse/restart 逻辑）+ `initTabs(historyOpenAgents, historyActiveAgent)` 为每个历史 open tab 开新 session（新 session_id，不续接 PTY）。
- **initTabs 重构**：`initTabs(agentsToOpen[], activeAgent?)`--为指定 agents 各开 session，设 active。startFromSummary 调 `initTabs([launch.agent], launch.agent)`；resumeLayout 调 `initTabs(historyAgents, historyActive)`。

### 本切片不做（OUT）

- **孤儿 session 检测/处理**（`session list` 找无 PTY 的 session -> 结束/忽略，03 §8.1）-> S3.1/后续（需 `session list` Tauri 命令 + 诊断 UI；非 gate）。
- **窗口几何 save/restore**（02 §九.2 `window` 字段）-> 后续（schema 已可扩；非 gate）。
- **history 损坏可恢复错误 UI** -> 后续（S2.4.a 已静默隔离）。
- **恢复布局专用 resume prompt 视图**（02 §2.3 的独立屏 [恢复布局]/[空白打开]/[选择其他工作区]）-> 本切片用 summary 内按钮等效实现（Start=空白打开，Cancel=选择其他工作区，恢复布局=恢复）；独立屏留后续打磨。

## 2. 关键设计

### 2.1 layout 只记 open tabs

`buildPatch`：`tabs.value.filter(t => t.sessionState !== "idle").map(...)`。`active_tab_id` 仅在活动 tab 非 idle 时记。这样 history layout = 上次开着的 tab 集合，resume 据此恢复。

### 2.2 ensureRuntime 抽取

`startFromSummary` 和 `resumeLayout` 共用 start/reuse/restart 逻辑：抽 `ensureRuntime(): Promise<boolean>`（按 preflight.recommended_action 走 start/reuse/restart，设 runtimeState/runtimeReady；resolve_conflict 返回 false）。`startFromSummary` = ensureRuntime + initTabs([launch.agent])。`resumeLayout` = ensureRuntime + initTabs(historyAgents, historyActive)。

### 2.3 initTabs(agentsToOpen, activeAgent?)

建 4 固定 tab（idle）-> 对 `agentsToOpen` 各调 `openTab`（开新 session）-> 设 activeTabId 为 `activeAgent`（或首个）。正常 start 开 1 个；resume 开历史 open tabs（多个），各新 session_id，**不续接 PTY**（03 §六 placeholder->session，新 session_id）。

### 2.4 restorableLayout computed

`{agents, activeAgent} | null`：preflight 为 reuse/restart + history 该 workspace layout.tabs 非空时返回。LaunchSummary 据此显「恢复布局」按钮。

## 3. 改动文件（全前端，无后端）

- `workbench/src/stores/runtime.ts`：`buildPatch` 过滤 idle tab；抽 `ensureRuntime`；`initTabs(agentsToOpen, activeAgent?)` 重构；`resumeLayout()`；`restorableLayout` computed；`startFromSummary` 改用 ensureRuntime + initTabs。
- `workbench/src/features/startup/LaunchSummary.vue`：「恢复布局」按钮 + 文案（`v-if="store.restorableLayout"`）。

## 4. 步骤与验证

1. store: buildPatch 过滤 + ensureRuntime 抽取 + initTabs 重构 + resumeLayout + restorableLayout -> verify: typecheck（startFromSummary 不破）。
2. LaunchSummary 恢复布局按钮 + 文案 -> verify: `npm run build` 过；`cargo build` 零改零错。
3. 实机手测 -> verify:
   - 选工作区 start -> 开 claude + bash 两 tab -> 关 app。
   - 重启 -> picker 点该工作区 -> selectRecentWorkspace 恢复配置 -> preflight 显 reuse/restart -> summary 显「恢复布局」按钮 + 文案。
   - 点「恢复布局」-> runtime reuse/restart + 自动开 claude + bash 两 tab（新 session，各独立）-> active 为上次的。
   - 点「Start」（空白打开）-> 只开 launch.agent 1 个 tab。
   - 关 app 重启 -> 恢复布局仍可用（history layout 持久）。

## 5. 验收（S2.4.b 局部 + Phase 2 收尾）

- [ ] 已知工作区（有 history layout + runtime）summary 显「恢复布局」+ 文案。
- [ ] 恢复布局开历史 open tabs（新 session，不续接 PTY）；Start 走单 tab。
- [ ] history layout 只记 open tabs。
- [ ] `npm run build` + `cargo build` 零错误。
- [ ] Phase 2 验收门：恢复布局通过；崩溃后重启发现 runtime（S2.4.a 已覆盖）；两窗口 history（S2.4.a lock/revision）。
