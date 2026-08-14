# Stage 0 验收清单

> 证据格式沿用 `../00-overview.md`：目标/验收 ID、Commit、OS/arch、Workbench/CLI/Docker 版本、前置条件、步骤、期望、结果、耗时 p50/p95/max、截图/日志/测试名、结论。

| ID | 目标/风险/步骤 | 可执行验收与证据 |
|---|---|---|
| B-A01 | B-01/B-R01/S0.1 | 在 clean checkout 生成两次 manifest；commit、版本、fixture hash 相同，差异仅允许时间字段；记录命令和日志。 |
| B-A02 | B-01/B-R01/S0.1 | 在 Windows 11 及至少一个适用 Unix 环境运行基线；缺依赖时 fail closed 且不覆盖上次 PASS。 |
| B-A03 | B-02/B-R02/S0.2 | Python/Rust/TS 对同一 v1 JSON/JSONL fixture 解析一致；unknown field round-trip；unsupported version 稳定拒绝、零业务副作用。 |
| B-A04 | B-03/B-R03/S0.3 | YAML 静态测试证明 workbench/src、package、src-tauri、src/aisc 变更命中工作流；PR 命令全绿并保存 artifact。 |
| B-A05 | B-04/B-R04/S0.4 | 固定高频 fixture 下 per-resource/global queue 不越界；overflow/truncated 可见；无 child/channel/timer/listener 泄漏。 |
| B-A06 | B-04/B-R04/S0.4 | soak 运行固定样本，记录 p50/p95/max 和 hard deadline；取消、超时、关闭均完成 cleanup，不发生 deadlock。 |
| B-A07 | B-05/B-R05/S0.5 | settings/history 并发写、unknown field、corrupt、replace 失败 fixture 通过；旧文件可恢复，禁止空文件窗口。 |
| B-A08 | B-05/B-R05/S0.5 | redaction fixture 扫描 token/key/cookie/OAuth/prompt/env/scrollback；日志和诊断包均无命中。 |
| B-A09 | B-06/B-R06/S0.6 | 每个最小单元有独立 commit、Claude trailer、关联目标/风险/验收；工作树状态和 devlog 可审计。 |
| B-A10 | B-06/B-R06/S0.6 | 用户按 Windows/适用平台手测清单执行，记录 OS、版本、步骤、结果、日志/截图和性能样本。 |
| B-A11 | B-06/B-R06/S0.6 | 本地测试全绿、CI 全绿；任一 FAIL 或 BLOCKED 不得写阶段 PASS。 |
| B-A12 | B-06/B-R06/S0.6 | 用户确认后才 `merge --no-ff` 回 develop；未获确认不 push、不删分支。 |

阶段结论：B-A01～B-A12 全 PASS，且证据完整，才允许 Stage 1 开始。
