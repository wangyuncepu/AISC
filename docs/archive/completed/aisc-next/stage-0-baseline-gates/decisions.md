# Stage 0 决策记录

> 仅记录本阶段已接受决定；具体字段和命令以 `00-overview.md`、`01-cross-stage-contracts.md`、`02-domain-contract.md` 为准。

| ID | 决定 | 理由/影响 |
|---|---|---|
| B-D01 | 以 `d2bdcd9` 为唯一规划基线 | 防止归档旧计划与现行契约混用；所有差异显式记录。 |
| B-D02 | 先门禁、后功能 | 高频数据面和协议若无基准，后续性能/兼容结论不可审计。 |
| B-D03 | 共享 versioned fixture，不共享实现 | Python/Rust/TS 可独立实现但必须证明语义一致。 |
| B-D04 | 资源预算是硬门而非建议 | 无界 queue/child/listener 会造成死锁和泄密，overflow 必须可观察。 |
| B-D05 | 持久化失败 fail safe | 保留旧文件、隔离损坏、拒绝覆盖优于静默默认值。 |
| B-D06 | 每阶段串行、每步最小 commit、用户确认合并 | 继承旧 GUI fine-tune 的可审计治理，避免跨阶段状态链竞态。 |
| B-D07 | 性能使用 p50/p95/max 与 hard deadline | 平均值掩盖尾延迟；不在无 benchmark 时承诺 SLA。 |
| B-D08 | 不把诊断内容等同于事实 | operation error、snapshot、overflow 和 stale 必须分离。 |
