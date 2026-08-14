# Stage 4：Python DockerGateway

> 状态：Accepted planning
> 基线：`d2bdcd9`
> 分支：`stage-4-docker-gateway`

## 目标台账

| ID | 目标 | 验收 |
|---|---|---|
| DG-01 | `DockerExecutor` 演进为 `DockerGateway`，保留兼容别名 | A-DG01 |
| DG-02 | 统一 operation/result/error/timeout/cancel/cleanup | A-DG02 |
| DG-03 | inspect/list/start/stop/remove/wait 渐进 SDK backend | A-DG03 |
| DG-04 | interactive exec/resize SDK 生命周期统一 | A-DG04 |
| DG-05 | Build 保持 CLI，先 benchmark 再决定 | A-DG05 |
| DG-06 | `auto|sdk|cli` 只在 adapter 内部选择 | A-DG06 |
| DG-07 | Fake/recording/fault injection contract matrix | A-DG07 |
| DG-08 | 只有等价性和跨平台证据齐全才移除重复 CLI | A-DG08 |

## 范围

Python 继续拥有 Docker domain；Rust 只消费结构化 CLI。所有 backend 禁止 `shell=True`，业务层不感知 SDK/CLI。