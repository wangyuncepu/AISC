# Stage 4 风险分析

| ID | 风险 | 缓解 |
|---|---|---|
| R4-01 | SDK/CLI 状态语义不同 | backend contract matrix，领域结果统一 |
| R4-02 | Docker Desktop named pipe/context 差异 | Windows 实机矩阵，保留 CLI fallback |
| R4-03 | SDK socket/stream 未清理 | operation owner、cancel/close/wait finally |
| R4-04 | BuildKit 输出/取消回归 | Build 暂留 CLI，固定 benchmark 和 fallback |
| R4-05 | daemon 不可用/权限/超时 | 稳定 error code、deadline、可重试 |
| R4-06 | application 感知 backend 导致分叉 | Gateway Protocol 注入，backend 只在 adapter |
| R4-07 | Fake 过度理想化 | recording + fault injection + real smoke |
| R4-08 | 重命名破坏外部调用者 | `DockerExecutor = DockerGateway` 兼容周期 |
| R4-09 | 并发 stop/remove/exec 资源泄漏 | ownership table、partial cleanup 证据 |
| R4-10 | SDK 依赖升级破坏 Python 支持矩阵 | lock/constraints、contract CI |

残余风险：Docker Desktop 版本、BuildKit plugin 和平台 daemon 行为不完全同质；CLI fallback 保留到下一次发布周期后再评估。