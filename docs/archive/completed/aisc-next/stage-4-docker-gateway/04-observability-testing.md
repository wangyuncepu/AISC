# Stage 4 可观测性与测试

## 指标

- operation/backend/phase/duration/outcome；
- SDK socket open/close、resize count、cancel deadline；
- CLI child spawn/exit、stdout/stderr bytes、timeout；
- daemon preflight latency、partial cleanup；
- Build event throughput、first event、cancel latency。

不记录 secrets、prompt 或完整 Docker env。

## 自动化

- Fake/SDK/CLI 三 backend contract matrix；
- result/error/timeout/cancel/daemon unavailable/permission/partial cleanup；
- operation cancellation 和 no-child/no-socket leak；
- argv safety、shell=True 静态检查；
- old CLI command JSON regression；
- recording/replay deterministic fixture。

## 真 Docker 手测

Windows Docker Desktop、Linux Docker Engine、macOS Docker Desktop：

- preflight/context；
- inspect/list/start/stop/remove；
- interactive input/output/resize/cancel；
- build event/cancel；
- daemon 重启、权限、网络失败；
- `auto|sdk|cli` 等价结果和耗时 p50/p95/max。

## 发布门

任何 backend 删除必须有至少两平台 real smoke、旧 CLI contract 全绿、回滚开关和 release note。