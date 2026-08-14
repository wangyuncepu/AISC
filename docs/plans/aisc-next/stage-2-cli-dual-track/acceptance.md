# Stage 2 验收清单

> 所有证据记录目标/验收 ID、Commit、OS/arch、Workbench/CLI/Docker 版本、前置、步骤、期望、结果、p50/p95/max、产物 hash、测试/日志、结论。

| ID | 目标/风险/步骤 | 可执行验收与证据 |
|---|---|---|
| CLI-A01 | CLI-01/CLI-R01/S2.1 | clean venv 与 pipx 安装 wheel/sdist；入口运行 `version --format json`，版本/依赖/退出码正确；重复安装可恢复。 |
| CLI-A02 | CLI-02/CLI-R02/S2.2 | pip、sidecar、Rust/TS 对 v1 fixture deep-equal；unknown 字段不丢；未知版本和坏 JSON fail closed。 |
| CLI-A03 | CLI-03/CLI-R03/S2.3 | capability matrix 覆盖满足、缺失、旧版本；unsupported 返回稳定 code/action，不调用不支持业务。 |
| CLI-A04 | CLI-04/CLI-R04/S2.4 | 构造 explicit/saved/bundled/PATH/platform 五来源，结果严格按优先级；显示绝对路径/source/version，argv 无 shell。 |
| CLI-A05 | CLI-05/CLI-R05/S2.5 | 同一命令矩阵比较参数解析、默认值、退出码、stable error code、JSON envelope；差异自动 FAIL。 |
| CLI-A06 | CLI-05/CLI-R05/S2.5 | runtime/session/doctor 正常、非法、超时、stdout overflow、取消在 pip 与 sidecar 等价；默认 stop/terminate 语义不变。 |
| CLI-A07 | CLI-06/CLI-R06/S2.6 | 三平台适用 sidecar clean-room smoke；manifest hash/arch/version 正确；模拟升级失败后旧版本可启动并可回滚。 |
| CLI-A08 | CLI-07/CLI-R07/S2.7 | SBOM/依赖审计通过；redaction 扫描无 secret；pip/sidecar 不改 PATH、不写凭据；诊断导出有用户确认清单。 |

阶段结论：CLI-A01～CLI-A08 全 PASS，且用户明确确认后才允许发布/推送/打 tag。
