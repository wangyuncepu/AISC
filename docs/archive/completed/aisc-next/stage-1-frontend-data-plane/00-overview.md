# Stage 1：前端结构与数据面总览

> 基线：`d2bdcd9`。依赖：Stage 0 accepted。遵循 `../00-overview.md`、`../01-cross-stage-contracts.md`。

## 1. 目的

将前端从单体协调器拆为可测试的 domain/store/view 投影，并建立 Rust PTY/IPC 到 Vue 的有界高频数据面。目标是行为等价、资源有界、状态事实与操作错误分离，再承载后续 Workspace/Artifact 工作。

## 2. 目标台账

| 目标 | 可交付结果 | 关键文件/目录 | 风险 | Step | 验收 |
|---|---|---|---|---|---|
| F-01 | runtime/session/tab/pane domain 与 view model 分层 | `workbench/src/domain/`, `stores/`, `components/` | F-R01 | S1.1 | F-A01 |
| F-02 | PTY resize/write/read、取消、reap 的统一数据面 | `workbench/src-tauri/src/pty/`, IPC commands | F-R02 | S1.2 | F-A02/F-A03 |
| F-03 | 输出批处理、背压、丢弃/截断可观察 | Rust channels、Vue terminal adapter | F-R03 | S1.3 | F-A04 |
| F-04 | SessionRegistry、generation、自然退出和恢复状态机 | Rust registry、Pinia stores | F-R04 | S1.4 | F-A05 |
| F-05 | snapshot/error reducer、stale/unknown 和最小更新 | `stores/runtime.ts`, sidebar views | F-R05 | S1.5 | F-A06 |
| F-06 | 键盘、焦点、aria-live、对比度等 a11y P0 | components、test utilities | F-R06 | S1.6 | F-A07 |
| F-07 | 首帧、输入回显、输出吞吐、切换和内存预算 | benchmark scripts、CI artifacts | F-R07 | S1.7 | F-A08/F-A09 |
| F-08 | 前端/Rust 集成测试 harness 与 soak | `workbench/tests/`, fixtures | F-R08 | S1.8 | F-A10 |

## 3. 关键文件与数据边界

Vue/Pinia 只持有短期 UI 和事实快照投影；Rust 持有 PTY、SessionRegistry、IPC、宿主路径和清理责任；Python 继续拥有 Runtime/Session/Provider 业务。高频字节不得逐 chunk 写入深响应式树；terminal adapter 只能接收批次和统计。

## 4. Non-goals

不做 Explorer、Artifact index、Docker 直连、CLI pip 发布、分屏产品化、主题市场、IDE/Git/编辑器，也不恢复旧 PTY、PID 或 scrollback。不得以拆组件为名改变 `aisc.cli/v1` 行为。

## 5. 分支、步骤与门

从已接受的 Stage 0 基线创建 `stage-1-frontend-data-plane`，按 S1.1～S1.8 串行推进；每步独立 commit 并带 Claude trailer。每步自动化和用户手测完成后汇报；阶段门为本地测试、CI、Windows ConPTY 适用手测、性能样本、a11y P0 和证据全部 PASS，用户确认后 `merge --no-ff` 回 `develop`。

## 6. 门禁指标

输出处理必须有 per-session/global bytes、event queue、render batch 和时间预算；overflow/truncation 产生稳定 operation/event，不得标完整。输入回显、resize、切 tab 和退出均记录 p50/p95/max；标准 fixture 下不得出现无限增长或未回收 listener/timer/child。
