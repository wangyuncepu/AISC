# Workbench S2.3.b - Provider 状态 + P1 可观察性

> 状态：提案
> 规范：04-observability.md §二.P1/§四.2/§五（provider 刷新策略）；05-cli-gui-contract.md §七（provider current）；03 §十（get_provider_status）
> 编写日期：2026-08-07
> 分支：feature/workbench-phase2

## 1. 范围

S2.3.b 收尾 S2.3：活动 Agent 的 Provider/route/auth 显示 + 刷新。后端加 `get_provider_status` 命令（S0.4 CLI 已就绪），前端侧栏加 P1 区 + provider 轮询。

### 本切片做（IN）

- **后端**：`get_provider_status(app, workspace, runtime_id, agent) -> ProviderStatus`，包 `aisc provider current --runtime-id --agent <claude|codex> --workspace --format json`（run_control + envelope_error + parse，复用 S2.2.b 模式）。`ProviderStatus{runtime_id, agent, provider_id, provider_name, route_mode, auth_status, observed_at}`。agent 校验 claude|codex。lib.rs 注册。
- **store**：`providerStatuses: Record<"claude"|"codex", ProviderStatus|null>` 缓存（per-agent，04 §四.2「不存在全局 Provider」）+ `providerError` + `loadProviderStatus(agent)`；runtime 切换/停止时清缓存。
- **provider 轮询 composable** `useProviderPolling`：活动 tab 为 claude/codex 且 runtime running 时，切换 tab 立即查 + 15s（聚焦）/60s（失焦）/隐藏暂停（04 §五）；bash/cc-switch 或非 running 不查。
- **侧栏 P1 区**：活动 agent 的 provider_name / route_mode（official-direct|cc-switch-proxy|unknown）/ auth_status（configured|login_required|not_configured|unknown）。bash/cc-switch 显「不适用」。capability 缺失（`!provider_status`）显「Unknown · 需升级 CLI」（04 §八）。

### 本切片不做（OUT）

- **cc-switch 退出后失效 Claude/Codex provider 缓存并立即刷新活动 Agent**（04 §五 末句边缘规则）-> 后续（需 cc-switch tab 退出联动，S2.4 tab 生命周期细化时一起）。
- **provider 查询的 revision/request_seq 抗乱序硬化** -> S3.1。
- **P2 runtime 详情面板 / aria-live 播报** -> S3.3。
- **provider GUI 编辑器** -> 永不（MVP 不做，06 §十.6）。

## 2. CLI 契约（已确认）

`aisc provider current --runtime-id <id> --agent <claude|codex> --workspace <ws> --format json` -> envelope data = `{runtime_id, agent, provider_id, provider_name, route_mode, auth_status, observed_at}`。agent 仅 claude|codex。错误码 `AISC_ERR_PROVIDER_STATUS_FAILED`（error.rs map_aisc 已映射）。capability `aisc.provider-status/v1`（S0.4，已协商进 CapabilityReport.provider_status）。

## 3. 关键设计

### 3.1 per-agent 缓存，非全局

`providerStatuses` 按 agent 分别缓存（claude/codex 各一份）。活动 tab 切换 -> 读对应 agent 缓存；若无/旧 -> 查。不互相覆盖（04 §四.2「不存在当前 Runtime 的全局 Provider」）。

### 3.2 刷新策略（04 §五）

- 活动 tab 切换到 claude/codex -> 立即查（若缓存无/旧）。
- 聚焦 15s / 失焦 60s / 隐藏暂停 周期查活动 agent。
- 仅 runtime running 时调度；stopped/not_found 不查（保留 last 缓存标 stale 或显「—」）。
- 复用 `document.hidden`/`hasFocus` + jitter 模式（同 useRuntimePolling）。

### 3.3 capability gate

`store.capability?.provider_status === false` -> 侧栏 P1 显「Provider: Unknown · 需升级 CLI」，不发查询。

## 4. 改动文件

### 后端
- `workbench/src-tauri/src/runtime.rs`：`ProviderStatus` struct + `provider_current_argv(runtime_id, agent, workspace)` 纯函数 + `get_provider_status` 命令 + 单测（argv + parse）。
- `workbench/src-tauri/src/lib.rs`：注册 `get_provider_status`。

### 前端
- `workbench/src/types/index.ts`：`ProviderStatus` + `RouteMode`/`AuthStatus` 字符串字面量类型（可选）。
- `workbench/src/lib/ipc.ts`：`getProviderStatus(workspace, runtimeId, agent)`。
- `workbench/src/stores/runtime.ts`：`providerStatuses`/`providerError` + `loadProviderStatus(agent)` + `clearProviderStatuses`（runtime 切换/停止时）。
- `workbench/src/composables/useProviderPolling.ts`（新）：活动 agent 感知的 provider 轮询。
- `workbench/src/features/workspace/RuntimeSidebar.vue`：P1 区（provider/route/auth + 不适用/capability gate/加载态）。
- `workbench/src/App.vue`：mount `useProviderPolling`（ready 时）。

## 5. 步骤与验证

1. 后端 ProviderStatus + get_provider_status + argv 测试 -> verify: `cargo build` + `cargo test`（新 argv/parse 测试 + 55 不回归）。
2. types + ipc -> verify: typecheck。
3. store provider 缓存 + loadProviderStatus -> verify: typecheck。
4. useProviderPolling composable -> verify: typecheck。
5. 侧栏 P1 区 + App.vue mount -> verify: `npm run build` 过。
6. 实机手测 -> verify:
   - 开 claude tab -> 侧栏显 provider_name/route_mode/auth_status（或 login_required/not_configured）。
   - 切 codex tab -> 显 codex 的 provider（独立缓存）。
   - 切 bash/cc-switch tab -> 显「不适用」。
   - ~15s 后 provider 自动刷新（observed 更新）。
   - runtime stop -> 不再查 provider（保留 last 或显「—」）。
   - capability gate：若 CLI 不支持 providerStatus（模拟）-> 显「需升级 CLI」（可选测，难造）。

## 6. 验收（S2.3.b 局部）

- [ ] 活动 claude/codex tab 侧栏显 provider/route/auth；bash/cc-switch 显「不适用」。
- [ ] claude/codex provider 分别缓存，切换 tab 不互相覆盖。
- [ ] provider 15s 周期刷新；runtime 非 running 时不查。
- [ ] capability 缺失显「需升级 CLI」。
- [ ] `cargo test` + `npm run build` 零错误；55 测试不回归。
