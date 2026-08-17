# Stage 1 可观察性与测试

## 指标

输出：input/output bytes、batch size、queue depth、dropped/truncated bytes、render duration；生命周期：open/close/terminate/reap duration、active child、listener/timer count；状态：snapshot revision、stale、discarded event。

## 自动化与 soak

Vitest/组件测试验证 DOM mutation、focus/aria；Rust 集成测试验证 PTY/IPC/取消/隐藏窗口；Python contract tests 保证 CLI 不回归。固定 10 MiB ANSI/UTF-8 fixture，4 KiB 输入，重复 100 次；tab/session soak 30 分钟或等价样本，比较初末内存与 registry。

## 门禁

输入回显 p95≤100ms（标准机）；稳定输出不得无限 queue；关闭 hard deadline 内 child 全部 reap；a11y axe 无 P0/P1，关键流程键盘可达。实机记录 Windows ConPTY、Linux/macOS 适用项。
