# Stage 4 实施计划

1. `4a-contract`: DockerGateway Protocol、result/error model、兼容 alias、fixture。
2. `4b-query`: SDK preflight/inspect/list，CLI backend 对照与 Fake。
3. `4c-lifecycle`: start/stop/remove/wait、deadline、partial cleanup。
4. `4d-interactive`: 统一 exec socket/resize/cancel/reap，保留 CLI fallback。
5. `4e-build-benchmark`: Build CLI baseline、SDK spike 仅实验，输出迁移决策。
6. `4f-release`: backend flag、recording/fault tests、跨平台 smoke、旧行为回归。

关键文件：`src/aisc/adapters/docker_.py`、`src/aisc/application/{runtime,session,provider}.py`、CLI commands、tests。每步独立 commit；只有 4f 完成后才能删除重复实现。