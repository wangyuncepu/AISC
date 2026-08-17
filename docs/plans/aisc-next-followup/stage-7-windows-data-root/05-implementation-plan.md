# Stage 7 实施顺序

1. `7a-contract`：实现 `DataRootResolver`、schema、workspace hash 和 path fixture；
2. `7b-storage`：统一 state/config/artifact/diagnostic writer 的目录和 lock/atomic API；
3. `7c-legacy-scan`：实现只读 scan、allowlist、冲突报告和 migration manifest；
4. `7d-migration`：实现 prepare/commit/resume/rollback/quarantine 及 CLI doctor；
5. `7e-wiring`：接入 Python CLI、Rust Workbench、container mount、session wrapper 和 diagnostics；
6. `7f-gate`：运行自动化、Windows 真机、升级/故障手测，更新 acceptance 和 devlog。

每个子步骤独立提交。任何 workspace 写入回归、迁移覆盖用户文件或 rollback 失败都阻断 Stage 8。
