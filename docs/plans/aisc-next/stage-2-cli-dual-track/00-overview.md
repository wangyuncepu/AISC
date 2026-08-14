# Stage 2：CLI 双轨总览

> 基线：`d2bdcd9`。依赖：Stage 0、Stage 1 accepted。遵循 `../00-overview.md`、`../01-cross-stage-contracts.md`。

## 1. 目的

把 Python CLI 作为独立 pip/pipx 产品，同时保留 Workbench frozen sidecar；两条轨道共享 `aisc.cli/v1` 的命令、参数、退出码、错误码、JSON envelope 和 capability 语义。GUI 只依赖结构化能力，不解析人类输出。

## 2. 目标台账

| 目标 | 可交付结果 | 关键文件/目录 | 风险 | Step | 验收 |
|---|---|---|---|---|---|
| CLI-01 | pyproject、wheel/sdist、可重现 pip 安装 | `pyproject.toml`, `src/aisc/` | CLI-R01 | S2.1 | CLI-A01 |
| CLI-02 | versioned JSON envelope/JSONL events 及未知字段策略 | `src/aisc/protocol/`, fixtures | CLI-R02 | S2.2 | CLI-A02 |
| CLI-03 | capability 命令、版本协商、unsupported 行为 | `src/aisc/cli/`, Rust runner | CLI-R03 | S2.3 | CLI-A03 |
| CLI-04 | explicit > saved pin > bundled > PATH > platform discovery | Rust discovery、settings | CLI-R04 | S2.4 | CLI-A04 |
| CLI-05 | pip CLI 与 sidecar 参数/错误/结果 parity | contract tests、fake CLI | CLI-R05 | S2.5 | CLI-A05/A06 |
| CLI-06 | sidecar 构建、升级、回滚、三平台发布矩阵 | scripts/workflows/bundle | CLI-R06 | S2.6 | CLI-A07 |
| CLI-07 | 供应链、敏感数据 redaction、诊断和兼容退化 | packaging、doctor、SBOM | CLI-R07 | S2.7 | CLI-A08 |

## 3. 关键边界

Python domain 继续拥有 Runtime、Session、Provider、DockerGateway；Rust 只 spawn/cancel/timeout/size-limit/decode/error-map，并不复制领域规则。sidecar 不是 pip 环境的隐式替代；discovery 结果必须展示来源、版本和 capability。`shell=True` 永久禁止。

## 4. Non-goals

不重写 Python domain 为 Rust，不让 GUI 直连 Docker/registry/Provider，不在本阶段交付 DockerGateway SDK、Artifact 命令或安装器首次向导，不把人类 stdout 作为协议，不承诺不同版本之间的任意 schema 自动迁移。

## 5. 分支与发布门

从 Stage 1 accepted 的 `develop` 创建 `stage-2-cli-dual-track`，按 S2.1～S2.7 串行，每最小单元独立 commit 且包含 Claude trailer。涉及发布、push、tag、PyPI 或真实安装器的外发动作必须用户明确确认。阶段完成需 pip/pipx、sidecar、Workbench 集成、Windows/Linux/macOS 适用矩阵和回滚证据全部通过，用户确认后 `merge --no-ff`。

## 6. 性能与质量门

CLI cold start、JSON 输出、sidecar discovery、spawn/terminate 设 p50/p95/max；stdout/stderr/JSON 最大字节数有 cap；未知 capability fail closed；pip 安装不可写入用户 PATH 或凭据；发布产物由 hash、版本、架构和 clean-room smoke 证明。
