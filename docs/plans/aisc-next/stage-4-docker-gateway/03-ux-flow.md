# Stage 4 Operator Flow

## 自动 backend

```text
aisc runtime/session/build
  → application 注入 DockerGateway
  → Auto 选择 SDK 或 CLI
  → operation_id/phase 可观测
  → 结果语义与旧版本相同
```

## 失败与 fallback

- SDK 不可用：Auto 可退 CLI；若显式 `sdk` 则返回可操作错误。
- daemon 未运行：显示 Docker unavailable/start Docker/retry，不伪造 stopped。
- timeout：到 deadline 后 cancel，再 bounded cleanup；展示 retry。
- partial cleanup：返回 observed state + cleanup incomplete，不静默成功。

## 交互 Session

```text
exec_create → exec_start(socket) → initial resize → input/output
 → resize watcher → cancel/close → exec_inspect → dispose socket/watcher
```

## Build

暂时维持 CLI streaming；用户看到结构化 build events。SDK build 只有在独立 benchmark 和跨平台 smoke 通过后才进入决策。