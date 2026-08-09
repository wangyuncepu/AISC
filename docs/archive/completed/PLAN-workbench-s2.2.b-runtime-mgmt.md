# Workbench S2.2.b - Runtime 状态机 + 管理 UI + 退出确认

> 状态：提案
> 规范：03-lifecycle-contract.md §四（runtime 状态机）/§七.2-3（停止/退出）/§十（domain API）；04-observability.md §四.1/§六（observation/reducer）；02-startup-flow.md §七.3（退出）
> 编写日期：2026-08-07
> 分支：feature/workbench-phase2

## 1. 范围

S2.2.b 收尾 S2.2：runtime 状态机（op 驱动）+ 管理 UI（冲突解决 list/stop/remove）+ 退出 Workbench 确认。解决用户之前踩的「不兼容 runtime 阻塞启动」「stop 没真正清理」痛点。

### 本切片做（IN）

- **后端契约修复 + 新命令**：`RuntimeSnapshot` 对齐 CLI `to_dict()`（修 inspect 解析失败 bug）；新增 `list_runtimes`/`remove_runtime`；`inspect`/`stop`/`restart`/`remove` 全部透传 `--workspace`（registry 定位 + config 回填）。
- **Runtime 状态模型**（store，op 驱动）：`runtimeState`（unknown/not_found/starting/running/stopping/stopped/removing）+ 完整 snapshot + `applyRuntimeSnapshot` reducer（observed_at 守卫，旧观察不覆盖新）。控制操作后立即 inspect 收尾（04 §六.2 末句）。
- **冲突解决 UI**：preflight `resolve_conflict` 时不再粗暴报错 -> `list_runtimes(workspace, workbench)` 列出工作区已有 runtime（state + 配置）-> 逐个 Stop/Remove（force）-> re-preflight。解决「不兼容 runtime 阻塞」。
- **退出 Workbench**：Tauri `onCloseRequested` 拦截 -> 有活动 session 则 `confirm` -> 结束本窗口 session（保留 runtime，02 §七.3 MVP 默认）-> destroy；无活动 session 直接退出。

### 本切片不做（OUT，明确 deferral）

- **轮询对账 / 外部 stop-remove 周期检测** -> S2.3（observability 轮询）。本切片状态机仅 op 驱动（start/stop/restart/remove 后 inspect）。
- **freshness fresh/stale/unknown + revision/request_seq 抗乱序硬化** -> S3.1（异常与并发）。本切片用 observed_at 简单守卫。
- **stopped 状态「保留 tabs 供 restart」richer UX** -> S2.4（history）。本切片 stop 仍回 picker（重进经 preflight restart 路径）。
- **runtime_stop session reason 精修**（现为 transport_error）-> S2.4（tabs 保留时才有意义；本切片 stop 清 tabs）。
- **Provider/auth + P0/P1 可观察性侧栏** -> S2.3。
- **history 持久化 / 启动 list 对账 / 崩溃恢复** -> S2.4。

## 2. CLI 契约（已勘查确认）

- `runtime list --workspace <ws> --owner workbench --format json` -> `{runtimes:[snapshot...], observed_at}`。per-workspace registry（`ws/.aisc/`），按 workspace_key + owner 过滤。
- `runtime inspect --runtime-id <id> --workspace <ws> --format json` -> snapshot。
- `runtime stop/restart --runtime-id <id> --workspace <ws> --format json` -> snapshot。
- `runtime remove --runtime-id <id> --workspace <ws> --force --format json` -> snapshot。
- snapshot = `{runtime_id, state, config:{workspace,image,network,scope}, owner, config_fingerprint, container_name, container_id, registry_state, observed_at, stale, [label/created_at/started_at/last_operation_error]}`。state ∈ unknown/not_found/starting/running/stopping/stopped/removing。
- `start` 返回 `RuntimeStartResult`（**含 `ready`**，与 snapshot 不同形状，当前 Rust 正确）。

## 3. 关键设计决策

### 3.1 状态机 op 驱动（非轮询）

store 持 `runtimeState` + `runtimeSnapshot`。转换由操作结果 + 操作后 inspect 驱动：start Ok -> inspect -> running；stop -> inspect -> stopped；restart -> inspect -> running；remove -> inspect/list -> not_found。无后台轮询（S2.3）。`applyRuntimeSnapshot(snap)`：仅当 `snap.observed_at >= 当前 observed_at` 才应用（简单守卫，防慢操作覆盖新状态；全 revision 硬化留 S3.1）。

### 3.2 冲突解决视图（非 error）

`startFromSummary` 遇 `resolve_conflict` 不再置 error -> 置新状态 `conflict` + 调 `list_runtimes` -> `ConflictManager.vue` 列出 runtime（runtime_id 缩写/state/image/scope）+ Stop（running/stopped）/Remove（force）按钮 -> 操作后 re-preflight（recommended_action 变 reuse/restart）。

### 3.3 workspace 透传

`runtime_inspect`/`stop_runtime`/`runtime_restart`/`remove_runtime`/`list_runtimes` 全部加 `workspace: String` 参数 -> argv 加 `--workspace`。store 调用时传 `store.workspace`。修 S2.1.a 遗留：inspect 不带 workspace 致 registry_state=missing + config 空 + `ready` 解析失败。

### 3.4 退出确认

前端 `getCurrentWindow().onCloseRequested`：`event.preventDefault()` -> 若有 running/starting tab -> `confirm("有 N 个活动会话，退出将结束它们（Runtime 保留运行）。继续？")` -> 确认则 `closeSession` 全部 live tab（best-effort）-> `await window.destroy()`；取消则什么都不做。无活动 session 直接 destroy。需 capabilities 加 window destroy 权限（验证 core:default 是否覆盖，否则补 `core:window:allow-destroy`）。

## 4. 改动文件

### 后端（Rust）
- `workbench/src-tauri/src/runtime.rs`：
  - `RuntimeSnapshot` 对齐 CLI（drop `ready`，加 `config: RuntimeConfig`/`owner`/`observed_at`/`stale`/`registry_state`/`container_id`，optional 字段 `#[serde(default)]`）。
  - `runtime_inspect`/`stop_runtime`/`runtime_restart` 加 `workspace: String` -> argv `--workspace`。
  - 新 `list_runtimes(app, workspace, owner) -> {runtimes: Vec<RuntimeSnapshot>, observed_at}` + `remove_runtime(app, workspace, runtime_id, force) -> RuntimeSnapshot`。
- `workbench/src-tauri/src/lib.rs`：注册 `list_runtimes`/`remove_runtime`。
- `capabilities/default.json`：补 window destroy 权限（若 core:default 不覆盖）。

### 前端
- `workbench/src/types/index.ts`：扩 `RuntimeSnapshot`（config/owner/observed_at/stale/registry_state）；`RuntimeState` 补 stopping/stopped/removing；`RuntimeListResult`。
- `workbench/src/lib/ipc.ts`：`runtimeInspect`/`stopRuntime`/`runtimeRestart` 加 workspace 参数；新 `listRuntimes(workspace, owner)`/`removeRuntime(workspace, runtimeId, force)`。
- `workbench/src/stores/runtime.ts`：`runtimeState`/`runtimeSnapshot` + `applyRuntimeSnapshot`；`startFromSummary` resolve_conflict -> `conflict` 状态 + `loadConflicts`；`stopRuntime`/`restartRuntime`/`removeRuntime` actions（op 后 inspect）；`stopRuntime`（ready 视图）op 后 inspect 确认 stopped；`confirmExit`（close 拦截）；新 `WorkbenchStatus="conflict"`。
- `workbench/src/features/startup/ConflictManager.vue`（新）：列出 runtime + Stop/Remove + re-preflight。
- `workbench/src/App.vue`：`conflict` 视图 -> ConflictManager；mount 时注册 `onCloseRequested`。
- `workbench/src/main.ts`（或 App.vue onMounted）：注册 close 拦截。

### 测试
- Rust 单测：`list_runtimes` argv（--workspace/--owner）、`remove_runtime` argv（--force）、`runtime_inspect` argv（--workspace）、`RuntimeSnapshot` 反序列化（无 ready 字段 OK）。
- 现有 47 测试不回归。

## 5. 步骤与验证

1. 后端 RuntimeSnapshot 对齐 + workspace 透传 + list/remove 命令 + 注册 -> verify: `cargo build` + `cargo test`（新增 argv/parse 测试 + 47 不回归）。
2. types + ipc 加新形状/wrappers -> verify: typecheck。
3. store 状态模型 + 冲突/管理 actions + 退出确认 -> verify: typecheck。
4. ConflictManager.vue + App.vue conflict 视图 + close 拦截 -> verify: `npm run build` 过。
5. 实机手测 -> verify:
   - 制造冲突（外部起一个不兼容 runtime）-> preflight -> 冲突视图列出 -> Stop/Remove -> re-preflight -> reuse/restart -> Start 成功。
   - ready 视图停止 Runtime -> inspect 确认 stopped -> 回 picker -> 重进 preflight 显示 restart。
   - 有活动 session 时关窗 -> 弹确认 -> 确认 -> session 结束、窗口关、runtime 仍运行（`docker ps`）；无活动 session 直接关。

## 6. 验收（S2.2.b 局部）

- [ ] 不兼容 runtime 不再阻塞：可从冲突视图 stop/remove 后继续启动。
- [ ] stop/restart/remove 后 inspect 反映真实 state（stopped/not_found/running）。
- [ ] 退出 Workbench 有活动 session 时确认；确认后结束 session、保留 runtime。
- [ ] `cargo test` + `npm run build` 零错误；47 测试不回归。
