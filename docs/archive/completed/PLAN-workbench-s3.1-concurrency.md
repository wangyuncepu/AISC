# Workbench S3.1 - 并发与异常硬化

> 状态：提案
> 规范：03-lifecycle-contract.md §九（并发与顺序）；04-observability.md §六.2（reducer 排序）；06 §六 S3.1
> 编写日期：2026-08-08
> 分支：feature/workbench-phase3

## 1. 范围

S3.1 硬化状态机并发 + 异常路径。Phase 2 已有：observed_at 简单守卫（S2.2.b）、轮询检测外部变化（S2.3.a）、history 跨进程锁（S2.4.a）、cancel 流程（S2.1.a）。S3.1 补：per-runtime op mutex + request_seq 抗乱序 + cleanup 审计。

### 本切片做（IN）

- **per-runtime operation mutex（Tauri）**：`OpMutexes` managed state（`HashMap<runtime_id, Arc<tokio::sync::Mutex<()>>>`）。`stop_runtime`/`runtime_restart`/`remove_runtime` 在 run_control 前acquire 该 runtime_id 的 mutex（`lock_owned`），同 runtime 串行、不同 runtime 并发（03 §九.1/§九.6）。`start_runtime` 仍用 StartOp 全局单 start token（已串行），不改。lib.rs `.manage(OpMutexes::default())`。
- **request_seq/revision reducer（store，04 §六.2）**：替换 `applyRuntimeSnapshot` 的 observed_at 简单守卫为 **request_seq 单调守卫**。`requestSeq` 计数器：`refreshRuntime`（轮询）每次 `++requestSeq` 赋值，`applyRuntimeSnapshot(snap, seq)` 仅当 `seq >= lastAppliedSeq` 才 apply（旧 poll 响应不覆盖新状态）。控制操作（restart）也走 seq（`++requestSeq`），apply 后 `lastAppliedSeq = seq`；start/reuse 无 snapshot，op 后设 `lastAppliedSeq = ++requestSeq`（代际边界，拒绝在途旧 poll）。`revision` 每次 apply 递增（单调，供未来对账）。observed_at 仍用于 freshness 显示（不用于排序）。
- **cleanup 审计**：核对所有 timer/listener/channel 确定性清理--useRuntimePolling/useProviderPolling `stop()`（timer+listeners，已做）、Terminal `onBeforeUnmount`（PTY+resize timer+ResizeObserver+window listener，已做）、store `startTimer`/`saveTimer`。修发现的缺口（如 useProviderPolling 的 `watch` 未 unlisten--App 根组件生命周期内可接受，文档注明；若发现真泄漏则修）。
- **Rust 单测**：OpMutexes 序列化（同 id 二次 acquire 阻塞、不同 id 并发）。

### 本切片不做（OUT）

- **operation_id for control ops**：cancel 流程（cancelRuntimeStart + handleCancelledStart，S2.1.a）已处理 start 取消；当前 UI 单 op（按钮禁用）无并发控制 op 竞态。operation_id 是更通用抽象，但当前无需求 -> 后续若多 op 并发再 加。
- **两窗口 runtime state 竞态细粒度**：CLI registry/workspace 跨进程锁（S0.2）+ 轮询（S2.3.a）已覆盖；Tauri op mutex 处理本进程排序（本切片）。完整两窗口 runtime state merge -> 后续。
- **Docker daemon 重启 / runtime OOM 特殊处理**：轮询已检测（runtime -> unknown/stopped，session 经 PTY 自终）。无额外代码（CLI inspect 返回 unknown）。
- **8h/10 session/高输出 内存增长压测** -> S3.2（scrollback 不持久化）+ 真机长测（release gate）。

## 2. 关键设计

### 2.1 OpMutexes（runtime.rs）

```rust
#[derive(Default, Clone)]
pub struct OpMutexes(pub Arc<std::sync::Mutex<HashMap<String, Arc<tokio::sync::Mutex<()>>>>>);

async fn acquire_op_lock(m: &OpMutexes, runtime_id: &str) -> tokio::sync::OwnedMutexGuard<()> {
    let arc = {
        let mut g = m.0.lock().unwrap();
        g.entry(runtime_id.to_string()).or_insert_with(|| Arc::new(tokio::sync::Mutex::new(()))).clone()
    };
    arc.lock_owned().await
}
```
stop/restart/remove 命令开头 `let _guard = acquire_op_lock(&app.state::<OpMutexes>().inner().clone(), &runtime_id).await;`。guard drop 释放（命令结束）。同 runtime_id 的 op 排队；不同 id 并发。

### 2.2 request_seq reducer（store）

- `requestSeq: Ref<number>`、`lastAppliedSeq: Ref<number>`、`revision: Ref<number>`（内部，不必暴露 UI）。
- `refreshRuntime`：`const seq = ++requestSeq.value; ... applyRuntimeSnapshot(snap, seq);`
- `applyRuntimeSnapshot(snap, seq)`：`if (seq < lastAppliedSeq.value) return;`（stale poll，丢弃）-> apply snapshot + `lastAppliedSeq.value = seq; revision.value++;` + freshness= fresh。
- 控制操作：restart `const seq = ++requestSeq.value; const snap = await runtimeRestart(...); applyRuntimeSnapshot(snap, seq);`；start/reuse 后 `lastAppliedSeq.value = ++requestSeq.value; revision.value++;`（代际边界，在途旧 poll 被拒）。
- 移除旧 observed_at 排序守卫（seq 单调更可靠；observed_at 留 freshness 显示）。

### 2.3 cleanup 审计

核对清单（已做，验证 + 文档）：
- useRuntimePolling：start 加 visibility/focus/blur listeners + timer；stop 清 timer + remove listeners。App.vue `watch(status)` + `onBeforeUnmount` 调 stop。✓
- useProviderPolling：同 + `watch(activeTabId, runtimeState)`（App 根生命周期，不 unlisten，可接受）。✓
- Terminal：onBeforeUnmount closePty + clear resize timer + disconnect ResizeObserver + remove window resize listener。✓
- store：startTimer（stopTimer 清）、saveTimer（debounce，模块级，app 生命周内 OK）。
- 修：若审计发现缺口（如某 listener 未清）则修；否则仅文档。

## 3. 改动文件

- `workbench/src-tauri/src/runtime.rs`：`OpMutexes` + `acquire_op_lock` + stop/restart/remove 加锁 + 单测。
- `workbench/src-tauri/src/lib.rs`：`.manage(OpMutexes::default())`。
- `workbench/src/stores/runtime.ts`：`requestSeq`/`lastAppliedSeq`/`revision` + `applyRuntimeSnapshot(snap, seq)` 改 seq 守卫 + `refreshRuntime` 赋 seq + 控制操作（ensureRuntime）赋 seq/代际边界。移除 observed_at 排序守卫。

## 4. 步骤与验证

1. 后端 OpMutexes + 加锁 + 单测 -> verify: `cargo build` + `cargo test`（新 mutex 序列化测试 + 65 不回归）。
2. store request_seq reducer -> verify: typecheck。
3. cleanup 审计 -> verify: 代码核对（listened/timer 清理点）。
4. 实机手测 -> verify:
   - 常规流程不破：picker -> start -> 多 tab -> stop -> 重进 reuse/restart -> 恢复布局。
   - 轮询抗乱序：快速切焦点触发多次 refresh -> 不出错（stale poll 被丢弃，状态不闪回）。
   - 同 runtime 并发 op：快速点 stop 后立即点 remove（若 UI 允许）-> 不出错（mutex 序列化）；或控制台无 panic。
5. `npm run build` + `cargo build` 零错误。

## 5. 验收（S3.1 局部）

- [ ] 同 runtime 的 stop/restart/remove 被 mutex 串行（不同 runtime 并发）。
- [ ] 轮询 stale 响应（低 seq）不覆盖新状态（高 seq）。
- [ ] 所有 timer/listener 有确定性清理证据（审计文档/代码）。
- [ ] `cargo test` + `npm run build` 零错误；65 测试不回归。
