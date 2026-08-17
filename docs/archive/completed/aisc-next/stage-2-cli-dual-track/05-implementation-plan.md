# Stage 2 实施计划

## S2.1～S2.2 包与协议

校验 pyproject entry points、wheel/sdist clean install；建立 v1 envelope/JSONL fixture、版本/错误码和 unknown/unsupported 测试。门：CLI-A01/A02。

## S2.3～S2.4 capability/discovery

实现 version capability 输出和 Rust discovery 优先级；source/version/probe error 可诊断，argv-only。门：CLI-A03/A04。

## S2.5 parity

contract runner 对 pip、pipx、sidecar 逐命令比对参数、退出码、JSON、timeout、redaction；差异自动阻断。门：CLI-A05/A06。

## S2.6～S2.7 产物与安全

补三平台 sidecar manifest/hash/回滚、clean-room smoke、SBOM、依赖审计和诊断导出清单；真实发布动作先获用户确认。门：CLI-A07/A08。

每个最小单元独立 commit；升级失败必须保留可启动旧版本；不改 CLI 默认 stop/terminate 语义。
