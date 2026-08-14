# Stage 1 实施计划

## S1.1 分层

盘点 `workbench/src` 的 runtime/session/tab 依赖，抽 typed domain、Pinia reducer、view model；保留旧入口做回归。门：F-A01。

## S1.2～S1.4 数据面和生命周期

统一 Rust PTY command、bounded channel、resize/write/cancel；实现 generation、Reserved/Closing、ack/TTL 和恢复。门：F-A02～F-A05。

## S1.5 状态投影

实现 snapshot/error 分离、freshness reducer、最小更新 key 和 stale/unknown 文案。门：F-A06。

## S1.6～S1.8 a11y、性能、harness

补键盘/aria/contrast 测试，固定输出 benchmark 与 soak，接入 IPC/ConPTY fake+实机 harness；门：F-A07～F-A10。

每步先写测试再实现；任何预算变更记录理由和新 p50/p95/max。不得把 Stage 2 CLI 工作混入本分支。
