# Stage 8 实施顺序

1. `8a-discovery`：锁定 latest stable、API/daemon 能力、数据库 schema/lock 和 DeepSeek 官方 fixture；
2. `8b-version-resolver`：实现 release metadata resolver、asset/checksum 校验、manifest/labels 和 build args；
3. `8c-preset`：重写 preset ownership、Claude alias 映射、`[1m]`、用户 override 和 migration fixture；
4. `8d-provider-adapter`：实现 `aisc.cc-switch-provider/v1`、secret channel、事务、redaction 和 concurrency tests；
5. `8e-workbench-tab`：新增 `cc-switch-ui` agent/tab、list/simple/custom/edit/delete flows、错误和恢复状态；
6. `8f-e2e-release`：容器 fresh/upgrade、CLI/UI 同库、latest/reproducible build、Windows tab、安全扫描和发布证据。

任何 API discovery gate 失败都不得以 TUI scraping 代替；应先记录阻断和可接受的 adapter 方案。发布回滚使用已签名/校验的旧 manifest；preset 回滚只恢复 preset-owned 字段，Provider 数据库迁移必须提供 previous-schema fixture。
