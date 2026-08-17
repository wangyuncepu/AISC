# Stage 0：基线与门禁总览

> 基线：`d2bdcd9`。前置规范：`../00-overview.md`、`../01-cross-stage-contracts.md`。本文件是本阶段范围 SSOT。

## 1. 目的与完成状态

Stage 0 不交付终端新功能，而是把后续开发所需的可重复基线、协议 fixture、质量门、资源预算和证据治理固定下来。阶段完成必须满足本目录 `acceptance.md` 的 B-A01～B-A12 全部 PASS；不得以“文档完成”替代自动化和手测证据。

## 2. 目标台账

| 目标 | 可交付结果 | 主文件/目录 | 风险 | Step | 验收 |
|---|---|---|---|---|---|
| B-01 | 基线清单、环境探针、可重复命令和 golden 结果 | `scripts/`, `.github/workflows/`, `docs/` | B-R01 | S0.1 | B-A01/B-A02 |
| B-02 | `aisc.cli/v1`、IPC envelope、JSONL fixture 与兼容断言 | `src/aisc/`, `workbench/src-tauri/`, `tests/fixtures/` | B-R02 | S0.2 | B-A03 |
| B-03 | Python/Rust/Vue/打包 CI 触发及全绿门 | `.github/workflows/`, `workbench/package.json` | B-R03 | S0.3 | B-A04 |
| B-04 | PTY、事件、队列、子进程、watcher 的 per-resource/global budget | Rust runner、stores、测试 fixture | B-R04 | S0.4 | B-A05/B-A06 |
| B-05 | settings/history/fixture 的 schema、原子写、锁、redaction 基线 | Rust persistence、Python diagnostics | B-R05 | S0.5 | B-A07/B-A08 |
| B-06 | 分支、commit、手测、CI、证据和发布停线规约 | `devlog`、阶段文档 | B-R06 | S0.6 | B-A09～B-A12 |

## 3. 关键文件与修改边界

- 关键代码：`src/aisc/cli/`、`src/aisc/application/`、`workbench/src/`、`workbench/src-tauri/src/`。
- 关键测试：`tests/`、`workbench/src/**/*.test.*`、`workbench/src-tauri/tests/`、`tests/fixtures/`。
- 关键配置：`workbench/package.json`、`package-lock.json`、`.github/workflows/*`、`pyproject.toml`、Cargo manifest。
- 本阶段不得修改 Stage 3～6 目录的实现计划，不得引入新的业务功能或重写 Python domain。

## 4. Non-goals

不做 CLI pip 发布、sidecar 发现重构、Workspace Explorer、Artifact Contract、DockerGateway SDK、安装器向导、完整视觉改版；不建立常驻 daemon；不把性能目标写成无证据的绝对 SLA。

## 5. 执行纪律

从最新 `develop` 创建 `stage-0-baseline-gates`，阶段内按 S0.1～S0.6 子步骤，每个最小单元独立 commit，commit 必须包含 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。每个子步骤先执行自动化，再由用户按手测清单验证；阶段完成需本地全绿、CI 全绿、手测 PASS、`acceptance.md` 证据完整、用户确认后才允许 `merge --no-ff` 回 `develop` 并 push。

## 6. 性能与质量门

基线命令必须可重复；关键门包括：构建无 warning 预算增长、JSON fixture round-trip 100%、PTY/队列无界分配为 0、单 Runtime 资源上限可观测、持久化故障不覆盖旧文件、redaction fixture 不含 token/key/cookie/prompt/scrollback。性能数字必须记录 p50/p95/max 与硬超时，不能只写平均值。
