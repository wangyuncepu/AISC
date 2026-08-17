# Stage 2 领域契约

## 1. CLI 公共面

命令协议固定 `aisc.cli/v1`。同名命令必须在 pip CLI、bundled sidecar、容器内调用保持参数、默认值、退出码、stable error code、JSON envelope 和 JSONL event 等价。人类输出只是展示，不是 Workbench 输入。

## 2. capability

`aisc version --format json` 返回版本、protocol、capabilities、build/runtime metadata；capability 是显式集合。请求缺失或版本不支持时返回 `CAPABILITY_UNSUPPORTED`，不猜测、不静默降级到破坏性路径；未知字段忽略并保留可 round-trip 字段。

## 3. discovery

顺序固定 `explicit > saved pin > bundled sidecar > PATH > platform discovery`。每次结果保存 source、absolute path、version、protocol、capabilities、probe error；Rust 构造 argv 数组，禁止 shell 字符串和任意 executable/args。

## 4. 发布与回滚

wheel/sdist、sidecar、manifest 都有版本、平台、架构、hash；安装和替换原子化，失败恢复上一版本。pip 安装不改用户 PATH、不读取/写入凭据。sidecar discovery 与 pip 环境隔离但使用相同 contract fixtures。

## 5. 安全

stdout/stderr 有 cap，doctor/diagnostics redaction 后才能进入日志或导出；不持久化 API key、OAuth、cookie、prompt、完整环境变量和 PTY scrollback。Docker 调用仍由 Python adapter 所有，CLI 不开放任意 shell。
