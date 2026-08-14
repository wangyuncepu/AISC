# Stage 4 验收台账

- `A-DG01-1` 新旧 Protocol/alias 注入和 Fake API 兼容。
- `A-DG02-1` operation/result/error/timeout/cancel/cleanup 字段稳定。
- `A-DG03-1` query/lifecycle SDK 与 CLI 结果等价。
- `A-DG04-1` interactive resize/input/output/cancel/reap 无资源泄漏。
- `A-DG05-1` Build CLI baseline 有 p50/p95/max；SDK 迁移有明确 GO/NO-GO。
- `A-DG06-1` application 不感知 backend；auto/sdk/cli flag 可回滚。
- `A-DG07-1` Fake/recording/fault injection 覆盖 daemon/permission/timeout/partial cleanup。
- `A-DG08-1` Windows/Linux/macOS smoke、旧 CLI 回归、删除重复代码前用户确认。

每项记录 commit、平台/版本、步骤、结果、耗时和日志；无真实 Docker 环境不得宣称跨平台 PASS。