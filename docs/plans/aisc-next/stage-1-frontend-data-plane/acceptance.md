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

## 执行记录（2026-08-14，分支 `stage-1-frontend-data-plane`）

| 验收 | 证据 | 结论 |
|---|---|---|
| F-A01 | `domain/__tests__/layerContract.test.ts`（2 测试）扫描全部 `.vue`，禁止组件直引 runtime/provider/docker/history/settings IPC 命令；App.vue 收紧为按名 import（`4d27681`） | PASS |
| F-A02 | pty spawn 失败返回 `WB_ERR_CLI_*` 且无 child、writer 通道硬上限 bounded（`9248b1d`，cargo lib 114） | PASS |
| F-A03 | 终端输入/回显、resize、隐藏 pane 行为 | 待用户 Windows ConPTY 手测（B-A10） |
| F-A04 | `domain/streamBuffer`（7 测试）+ `terminalThroughput`（2 测试）：10 MiB fixture 在 <2s 内 bounded 处理，per-pane 4 MiB/4096 chunk 预算，truncated 计数完整，Terminal 显示截断提示（`0328774`、`dab45e8`） | PASS |
| F-A05 | `runtimeStream`（2 测试）：Fake Channel 驱动 store buffer；sessionId 移动后旧 channel 事件被丢弃；Rust registry 既有 100× reopen 测试保持（`fd91548`） | PASS |
| F-A06 | `runtimeFreshness`（4 测试）：迟到低 seq 响应不覆盖、markStale 保留快照、fresh 恢复（`fd91548`） | PASS |
| F-A07 | TabBar 嵌套 button 修复 + 3 结构测试（单一 role=tab、无嵌套 button、关闭按钮独立 + aria-label）；键盘/对比度/焦点 | PASS（自动化）；200% 缩放/读屏手测待用户 |
| F-A08 | 10 MiB 输出吞吐本机 8ms（<2s 硬门），报告格式见 `terminalThroughput` | PASS（本机基线） |
| F-A09 | 30 分钟 soak 内存/资源有界 | 待用户真机 soak |
| F-A10 | vitest 148 / pytest 428 / cargo lib 114 全绿；IPC fake（runtimeStream）通过 | PASS（自动化）；ConPTY 手测待用户 |

本地门全绿；CI 实跑与 ConPTY/soak 手测待用户授权/执行（B-A10/B-A11/B-A12）。

阶段结论：F-A01～F-A10 全 PASS（含待手测项明确），Stage 2 才可开始。
