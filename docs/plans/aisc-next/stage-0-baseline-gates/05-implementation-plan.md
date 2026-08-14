# Stage 0 实施计划

## S0.1 基线清单

编写环境探针、锁定命令和 fixture manifest；提交基线失败样例，再修复可重复生成。关键文件：`scripts/`、`tests/fixtures/`、CI artifact 配置。门：B-A01/B-A02。

## S0.2 契约 fixture

冻结 envelope、JSONL、错误码、unknown/unsupported 负例；Python/Rust/TS 各自消费同一 fixture。门：B-A03。

## S0.3 CI

补 workflow path filters、build/test/cargo/pytest 和 YAML 静态测试；门：B-A04。

## S0.4 资源基线

建立 bounded channel、stdout cap、cleanup instrumentation、soak harness；门：B-A05/B-A06。

## S0.5 持久化与 redaction

补 settings/history 原子写、锁、revision、损坏隔离、redaction denylist；门：B-A07/B-A08。

## S0.6 治理

写 devlog/手测表、证据模板和阶段报告；用户确认后才合并。每步最小 commit，禁止 squash 丢证据。
