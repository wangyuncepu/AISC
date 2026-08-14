# Stage 2 可观察性与测试

## 自动化矩阵

同一 contract runner 对 pip wheel、pipx venv、bundled sidecar、PATH CLI 运行：version、doctor、runtime inspect/stop、session open/terminate、invalid args、capability mismatch。断言 JSON deep equality（允许声明的 build metadata 差异）、退出码、stable code、stderr cap。

## 产物与安全

保存 wheel/sdist/sidecar manifest、SHA-256、架构、依赖锁、SBOM 和 clean-room 日志；doctor/diagnostic redaction fixture 以 token/key/cookie/prompt/env/scrollback 词表扫描。发布失败不得替换现有 sidecar。

## 性能门

pip install cold、CLI cold start、version JSON、discovery probe、sidecar spawn/terminate 记录 p50/p95/max；stdout 超 cap、协议超时、hash 不符、架构不符均为阻断。三平台执行适用 smoke，Windows 做真实 Workbench sidecar。
