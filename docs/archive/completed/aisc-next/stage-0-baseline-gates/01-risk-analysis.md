# Stage 0 风险分析

> 风险编号仅本阶段使用：B-R01～B-R06。关闭条件：缓解已实现，且 `acceptance.md` 有自动化/手测证据。

| 风险 | 触发与影响 | 缓解与证据 | 关联 |
|---|---|---|---|
| B-R01 基线不可复现 | 依赖、OS、Docker、代理或 fixture 漂移，结果无法比较 | 锁文件、环境探针、版本清单、固定 fixture hash；失败打印差异而非覆盖基线 | B-01→S0.1→B-A01/B-A02 |
| B-R02 协议漂移 | CLI/IPC envelope 字段、版本、错误码不一致，GUI 误判事实 | golden JSON/JSONL、unknown-field round-trip、unsupported fail-closed、跨语言 contract test | B-02→S0.2→B-A03 |
| B-R03 CI 漏触发或只测单层 | 前端/Rust/Python/打包改动未触发对应工作流 | path filter 静态测试；PR 必跑 build/test/cargo/pytest；产物留存 | B-03→S0.3→B-A04 |
| B-R04 高频资源无界 | PTY 输出、队列、timer、listener、child 堆积，造成卡顿/deadlock | per-resource/global budget、背压、overflow event、dispose/reap 断言和 soak | B-04→S0.4→B-A05/B-A06 |
| B-R05 持久化破坏或泄密 | 并发写丢字段、损坏覆盖、诊断包含 secret | lock+revision、tmp/fsync/atomic replace/recovery、redaction denylist fixture | B-05→S0.5→B-A07/B-A08 |
| B-R06 证据治理失效 | 只改文档/只跑本地，未记录手测和用户确认 | 子步骤验收先行、最小 commit、统一证据格式、阶段停线 | B-06→S0.6→B-A09～B-A12 |

高优先级门：B-R02/B-R04/B-R05；任一未关闭不得开始 Stage 1。所有日志禁止 token、API key、OAuth、cookie、prompt、完整环境变量和 PTY scrollback。
