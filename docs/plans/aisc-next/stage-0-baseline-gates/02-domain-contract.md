# Stage 0 领域契约

## 1. 基线对象

`BaselineManifest` 包含 `schema_version=1`、代码 commit、OS/arch、Python/Node/Rust/CLI/Docker 版本、命令、环境变量白名单、fixture SHA-256 和生成时间。manifest 不记录凭据和终端内容。

## 2. 协议与错误

所有 envelope 为 `meta.protocol=aisc.cli/v1`，至少含 `command`、`request_id`、`outcome`、`exit_code`；事件为 JSONL，单行有界，未知字段必须保留或忽略而不崩溃。unsupported version/capability 必须 fail closed，返回稳定错误码和 action。

## 3. 资源预算

每个 PTY/session、全局 queue、stdout/stderr、diagnostic bundle 都定义 bytes/items/time 上限；超过上限只能产生 `overflow/truncated`，不得继续标记 complete。所有 child、PTY、timer、listener、channel、lock、watcher 有 owner 和 cleanup outcome。

## 4. 持久化

settings/history fixture 具有 schema/revision；保存需 expected revision、跨进程 lock、unknown-field round-trip、tmp+fsync+atomic replace、backup recovery、corrupt isolation、migration rollback。redaction 发生在导出和日志边界，原始 secret 不进入 fixture。

## 5. 性能记录

每项 benchmark 记录 warm/cold、样本数、p50/p95/max、硬 deadline、机器和版本；不存在可比样本时标记 BLOCKED，不用估算值替代。
