# Stage 0 可观察性与测试

## 自动化

- Python：pytest 覆盖 manifest、命令回归、redaction、错误 envelope。
- Rust：cargo test 覆盖 lock/revision/atomic replace、bounded channel、cleanup、argv。
- Vue：npm test 覆盖 reducer、fixture decode、无深响应式 chunk。
- CI：`npm ci; npm run build; npm test -- --run; cargo test; python -m pytest`；YAML path filter 静态断言。

## 观测字段

每个 operation 记录 operation_id、source、phase、duration_ms、outcome、stable_error_code、retryable、action、redacted detail；资源记录 queue bytes/items、overflow、child state、dispose/reap 结果。

## 性能门

固定 fixture、冷/热分组，记录 p50/p95/max、样本数和硬 deadline；任何 overflow、未回收 child、redaction 命中或 schema 覆盖均 FAIL。手测使用统一证据格式。
