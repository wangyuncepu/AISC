# Stage 0 验收台账

> 证据格式沿用 `../00-overview.md`：目标/验收 ID、Commit、OS/arch、Workbench/CLI/Docker 版本、前置条件、步骤、期望、结果、耗时 p50/p95/max、截图/日志/测试名、结论。

## 执行记录（2026-08-14，分支 `stage-0-baseline-gates`）

| 验收 | 证据 | 结论 |
|---|---|---|
| B-A01 | `tests/test_baseline.py` determinism 测试 + 真实探针两次运行仅 `generated_at` 不同（in-process 断言 `deterministic: True`） | PASS |
| B-A02 | Windows 11 手测 `complete`（用户执行，git `0dfb473`、python 3.14.5 / node 22.23.2 / npm 12.0.2 / rustc 1.97.1 / cargo 1.97.1 / docker 29.6.2）；WSL fail-closed：缺 node/npm/rustc/cargo → `--strict` exit 1、不生成 latest.json（用户执行） | PASS |
| B-A03 | 共享 `tests/fixtures/cli` 被三端消费：Python `test_cli_fixtures.py` 9 通过、Rust `tests/cli_fixtures.rs` 7 通过、TS `cliFixtures.test.ts` 6 通过；unknown-field round-trip 与 unsupported-protocol 负例均验证 | PASS |
| B-A04 | `test_workflow_contract.py` 9 通过：path filters 覆盖 workbench/src、package、src-tauri、src/aisc 及新增 `scripts/baseline`、`tests/fixtures`；workbench-ci cli job 含 baseline `--strict` 与 artifact 上传 | PASS（CI 实跑见下方 B-A11） |
| B-A05 | Rust `read_capped` truncation（cap+truncated flag）、`control_plane_budget_is_stable`（MAX_STDOUT 8MB / MAX_STDERR 64KB 冻结） | PASS |
| B-A06 | `scripts/soak/soak.py` + `test_soak.py` 8 通过（p50/p95/max、deadline 超出计数、报告形状）；真实样本 `python -m pytest tests/test_baseline.py -q` ×3 → min 431ms / p50 456ms / p95 479ms / max 481ms，deadline 10s 内 | PASS |
| B-A07 | 现有 `storage.rs` atomic replace（创建/覆盖/失败保留原文件）、`history.rs` lock/revision/corrupt/unknown-field 测试保持通过；Rust lib 全量 112 通过 | PASS |
| B-A08 | `tests/fixtures/redaction/denylist.txt` 被 Rust `redact_denylist_fixture_never_leaks` 消费；新增 Bearer `<jwt>` OAuth redact；Python 冒烟断言 `aisc version --format json` 无 secret 形状 | PASS |

## B-A09 ~ B-A12（收口门）

| 验收 | 状态 |
|---|---|
| B-A09 每个最小单元独立 commit + trailer | PASS — 本阶段 9 个 commit（0dfb473→48fb6b4），全部含 `Co-Authored-By`，信息关联 B-*/B-R* |
| B-A10 用户手测清单执行 | PASS — Windows 11 `complete`（用户执行）+ WSL fail-closed（用户执行），见下方清单 |
| B-A11 本地全绿 + CI 全绿 | PASS — 本地 pytest 428 / vitest 128 / cargo lib 112；CI run `31799032346` 三 job 全绿（frontend build+tests / rust cargo test / cli pytest + Unix baseline probe + artifact） |
| B-A12 用户确认后才 merge | PASS — 用户 2026-08-14 授权“push + CI 绿后自动合并”；合并 `--no-ff` 回 develop 执行中 |

## 用户手测清单（B-A10）

1. Windows 11（已完成，用户执行 `run_baseline.py --strict` → `complete`，latest.json 已展示）。
2. WSL/Linux（已完成 fail-closed 分支：缺 node/npm/rustc/cargo → `--strict` exit 1、无 latest.json）。
3. 提交审计：`git log --oneline stage-0-baseline-gates` 应有 9 个本阶段 commit，工作区干净。

## 阶段结论

B-A01～B-A12 全 PASS。CI 全绿（含 Unix baseline probe 与 artifact），用户已确认合并，进入 Stage 1。
