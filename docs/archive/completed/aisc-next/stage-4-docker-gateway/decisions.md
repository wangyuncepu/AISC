# Stage 4 决策

- `D4-01` DockerGateway 是 Python 内部接口，不是 Rust API。
- `D4-02` `DockerExecutor` 保留兼容别名至少一个 release。
- `D4-03` interactive exec 继续 SDK-first。
- `D4-04` query/lifecycle 小步 SDK 化，CLI fallback 保留。
- `D4-05` Build 未经 benchmark 不迁移。
- `D4-06` backend 选择不泄漏到 application/domain。
- `D4-07` 所有 backend 统一错误、deadline、cleanup 和 observed state。
- `D4-08` 真实 Docker 跨平台证据缺失时不得删除 CLI 路径。
