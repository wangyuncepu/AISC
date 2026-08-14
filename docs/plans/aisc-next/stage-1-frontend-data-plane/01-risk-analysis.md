# Stage 1 风险分析

> 风险编号仅本阶段使用：F-R01～F-R08。每项必须在实现步骤和验收台账闭环。

| 风险 | 触发与影响 | 缓解/阻断门 | 关联 |
|---|---|---|---|
| F-R01 拆分改变事实所有权 | 组件复制 Runtime/Provider 规则，状态互相覆盖 | domain/store/view 单向依赖图、reducer contract test、禁止组件调用 Docker | F-01→S1.1→F-A01 |
| F-R02 PTY 生命周期竞态 | resize/write/close 并发，child 或 channel 泄漏 | Rust single owner、Reserved/Closing、cancel token、wait/reap；并发测试 | F-02→S1.2→F-A02/F-A03 |
| F-R03 高频输出拖垮 UI | 逐 chunk 响应式更新、队列爆满、静默截断 | byte/event budget、批次 render、背压、overflow/truncated 可观察 | F-03→S1.3→F-A04 |
| F-R04 迟到事件污染新 Session | 旧 generation 回写新 pane，恢复重复启动 | session_id+generation 校验、ack/TTL、有界 registry | F-04→S1.4→F-A05 |
| F-R05 stale 被当 fresh | poll error 覆盖有效事实或错误覆盖 snapshot | snapshot/error 分离、fresh/stale/unknown reducer、revision 丢弃旧响应 | F-05→S1.5→F-A06 |
| F-R06 a11y 回归 | 颜色承载状态、焦点丢失、屏幕阅读器噪音 | axe/键盘/焦点/对比度测试；aria-live 只播报语义变化 | F-06→S1.6→F-A07 |
| F-R07 性能基线虚假 | 只测平均、机器差异遮盖 p95，内存随 tab 增长 | 固定 fixture、冷/热分开、p50/p95/max、soak 和泄漏快照 | F-07→S1.7→F-A08/F-A09 |
| F-R08 测试 harness 与实机脱节 | fake 通过但 ConPTY/隐藏 tab deadlock | fake+IPC 集成+Windows 手测；平台不适用项明确 | F-08→S1.8→F-A10 |
