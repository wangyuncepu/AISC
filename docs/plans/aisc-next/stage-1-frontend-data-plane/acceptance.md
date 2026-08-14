# Stage 1 验收清单

> 每项记录目标/验收 ID、Commit、OS/arch、版本、前置、步骤、期望、结果、p50/p95/max（适用时）、测试名/截图/日志、PASS/FAIL。

| ID | 目标/风险/步骤 | 可执行验收与证据 |
|---|---|---|
| F-A01 | F-01/F-R01/S1.1 | domain/store/view 依赖检查通过；组件不直接拥有 Runtime/Provider/Docker 事实；reducer fixture 与旧行为一致。 |
| F-A02 | F-02/F-R02/S1.2 | open/resize/write/cancel/close 并发测试通过；argv/IPC 参数完整；所有 child 在正常与失败路径 reap。 |
| F-A03 | F-02/F-R02/S1.2 | 终端输入回显、resize 去重、隐藏 pane 不发零尺寸；记录 p50/p95/max，超时返回稳定错误。 |
| F-A04 | F-03/F-R03/S1.3 | 10 MiB 4KiB fixture 下 batch/queue/buffer 均受预算；注入 overflow 后 UI 显示截断和计数，不伪造 complete。 |
| F-A05 | F-04/F-R04/S1.4 | 自然退出/reopen 100 次无旧 generation 回写、registry 有界；ack/TTL 和重复 close 结果幂等。 |
| F-A06 | F-05/F-R05/S1.5 | stale/unknown/fresh reducer 保留事实与错误分离；迟到 response 被丢弃；无语义变化期间用户层 DOM mutation=0。 |
| F-A07 | F-06/F-R06/S1.6 | 键盘完成 tab/pane/错误/重试流程；axe 无 P0/P1；200% 缩放、对比度、focus ring 和 aria-live 手测通过。 |
| F-A08 | F-07/F-R07/S1.7 | 固定机器与 fixture 测量首帧、输入、输出、tab 切换 p50/p95/max；报告冷/热和样本数。 |
| F-A09 | F-07/F-R07/S1.7 | 30 分钟或等价 soak 前后内存、listener、timer、registry、child 有界；失败给出 dump 而非隐藏。 |
| F-A10 | F-08/F-R08/S1.8 | Vitest、cargo、Python contract、IPC fake 和 Windows ConPTY 手测全绿；Linux/macOS 适用项明确并留证。 |

阶段结论：F-A01～F-A10 全 PASS，Stage 2 才可开始。
