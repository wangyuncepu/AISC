# Stage 7 验收

| ID | 验收方法 | 结果 |
|---|---|---|
| A-DATA01 | fresh Windows workspace，启动 CLI/Workbench/container 后扫描根目录 | 待执行 |
| A-DATA02 | legacy fixture dry-run/apply，校验 manifest、hash、redirect 和源文件 | 待执行 |
| A-DATA03 | 中断迁移后 resume/rollback，模拟权限/磁盘不足 | 待执行 |
| A-DATA04 | 两个 session + provider 写入并发，检查 lock 和 SQLite/JSON 完整性 | 待执行 |
| A-DATA05 | 中文、emoji、长路径、junction、OneDrive 用户目录 | 待执行 |

## 子步骤证据

### 7a-contract — DataRootResolver + schema + workspace hash + fixtures（2026-08-17）

- 目标/验收 ID：DATA-01..04 契约层（resolver 行为由 7e 全量接线后在各 A-DATA 门复验）
- Commit：`729c300`（Python resolver + fixture）、`fa432ec`（Rust mirror + 共享向量）
- OS/arch：Windows 11 Pro 10.0.26200 / x64
- CLI/Workbench/Container 版本：2.1.5-dev（resolver 尚未接线，不影响现行为）
- 步骤：`python -m pytest tests/test_data_root.py -q`；`cargo test --offline data_root`
- 期望：Known Folder 默认根、override 绝对路径/空白拒绝、workspace 双向 overlap 拒绝、
  reparse segment 拒绝（Windows 经 junction 真实执行）、hash 稳定且版本化、
  目录名无 `:`、Python/Rust 共享向量一致、resolve 只读（不创建目录）
- 结果：**PASS** — Python 17 passed + 8 subtests（junction 回退生效，无 skip）；
  Rust 8 passed（含共享向量与 mklink /J reparse 用例）
- 测试名/日志（已脱敏）：`tests/test_data_root.py`、`workbench/src-tauri/src/data_root.rs`
  （内联 tests）、fixture `tests/fixtures/data-root/hash-vectors.json`（含 CJK/emoji/UNC 向量）
- 回归：全量 `python -m unittest discover` 572 OK（61 skipped 为既有 Docker/CLI 集成跳过）；
  `cargo test --offline` 181+7×3 全过
- 结论：**PASS**

### 7b-storage — 统一目录/锁/原子写 API（2026-08-17）

- 目标/验收 ID：DATA-03/DATA-05 存储层（lock/atomic/corruption 原语；全量并发与故障注入门在 7f）
- Commit：`72d1bfd`
- OS/arch：Windows 11 Pro 10.0.26200 / x64
- 步骤：`python -m pytest tests/test_data_root_store.py -q`
- 期望：prepare 幂等创建契约骨架（含 `state/locks`）；rel 路径逃逸（`..`/绝对/反斜杠）拒绝；
  JSON 双 scope 原子读写、无临时文件残留、覆盖即替换；损坏 JSON 隔离为 `*.corrupt` 且
  fail closed（读取返回 None，原字节保留）；跨进程锁互斥 + 有界超时 + 稳定错误码
  `AISC_ERR_DATA_ROOT_LOCK_TIMEOUT`，持有者退出后可重新获取；workspace 域锁带 hash 前缀
- 结果：**PASS** — 12 passed（含真实子进程持锁的超时/释放用例）；合计 data-root 测试
  29 passed + 14 subtests
- 回归：全量 `python -m unittest discover` 584 OK（61 skipped 同前）
- 结论：**PASS**

### 7c-legacy-scan — 只读扫描 + allowlist + manifest（2026-08-17）

- 目标/验收 ID：DATA-02 契约层（扫描/分类/manifest；dry-run/apply/rollback 执行在 7d）
- Commit：`abd855e`
- OS/arch：Windows 11 Pro 10.0.26200 / x64
- 步骤：`python -m pytest tests/test_legacy_scan.py -q`；真实 workspace 只读实扫
- 期望：合成 legacy 全形状分类正确（owned 22 / transient 7，含 `.aisc→runtime/`、
  agent 目录→`workspaces/<h>/{claude,codex,cc-switch}/` 映射、db+wal+shm 成组 owned）；
  namespace 内未知文件→unknown；无 AISC 标记的同名目录→foreign（只报告不迁移）；
  目标同 hash→仍 owned、异 hash→conflict fail closed；扫描全程只读（目录快照不变）；
  manifest to_dict/from_dict 往返一致、错误 schema/version/state/classification 拒绝
- 结果：**PASS** — 11 passed + 18 subtests；data-root 组合计 40 passed + 32 subtests
- 真实实扫（用户提供的标准初始化 workspace，只读）：**owned 3127 / transient 8 /
  unknown 0 / conflict 0**，五命名空间全判 AISC 态；`workspace_hash` 与现行
  `.aisc/workspace-locks/<同 hex>` 一致（sha256-v1 前缀化不改变摘要）。实扫并反哺
  allowlist 两处修正：`.claude/{.claude.json,.factory-version}`（隐藏文件）入列；
  `daemon.sock`（Windows AF_UNIX reparse）按 transient 处理
- 回归：全量 `python -m unittest discover` 595 OK（61 skipped 同前）
- 结论：**PASS**

### 7d-migration — 执行层 + CLI doctor/migrate/rollback（2026-08-17）

- 目标/验收 ID：DATA-02/05 执行层（A-DATA02/A-DATA03 自动化部分；真机故障注入与并发门在 7f）
- Commit：`3118a02`（executor）、`34811cf`（CLI）
- OS/arch：Windows 11 Pro 10.0.26200 / x64
- 步骤：`python -m pytest tests/test_data_migration_exec.py tests/test_cli_data_root.py -q`
- 期望：commit 后源文件不动、瞬态原地、全迁移命名空间落 `.aisc-migrated` 标记；重复 apply 幂等
  （copied=0/skipped=N）；取消保留 prepared manifest、重跑 resume；迁移中源变更/冲突/
  空间不足/损坏复制 fail closed（稳定 `AISC_ERR_DATA_MIGRATION_*`）；unknown 未经
  `--quarantine-unknown` 非零退出、consent 后 copy→verify→删源；rollback 只删 manifest 内
  且 hash 未变的目标（用户改过的保留）、恢复 quarantine、移除标记；doctor/dry-run 全程
  只读；CLI 信封 `aisc.cli/v1`、doctor 载荷不含原始 workspace 路径
- 结果：**PASS** — executor 13 passed + CLI 5 passed
- 真实 workspace CLI dry-run（只读）：copy_count **3127** / skip 8 / **62,187,538 bytes**，
  conflicts=0、unknowns=0 —— 该 workspace 满足直接迁移条件
- 回归：全量 `python -m unittest discover` 613 OK（61 skipped 同前）
- 结论：**PASS**

### 7e-wiring — CLI/Rust/容器接线到 data root（2026-08-17）

- 目标/验收 ID：DATA-01/04 生效（真机容器全链路在 7f）
- Commit：`1da1ecb`（7e-1 状态写入）、`ae20673`（7e-2 config 层）、`92387e4`（7e-3 artifact
  统一）、`b9c4b9d`（7e-4 Workbench）、`321ff0a`（7e-5 容器 + DATA-01 回归门）
- OS/arch：Windows 11 Pro 10.0.26200 / x64
- 步骤：全量 `python -m unittest discover`；`cargo test --offline`；hermetic 污染复查
- 期望与结果：
  - **7e-1** registry/state 适配器语义改为「root=state 目录」，六处边界经
    `workspace_state_dir` 解析（fresh workspace 零写入断言通过）；legacy
    containers.json/state.env 首用收养（不覆盖、源保留）；`_resolve_root` 消除
    stop/ps 读 `<aisc-root>/.aisc` vs run 写 `<workspace>/.aisc` 的旧双轨
  - **7e-2** workspace config 层 canonical 优先 + legacy 只读回退（fresh→canonical /
    legacy-only→legacy / both→canonical 矩阵断言通过）
  - **7e-3** artifact 注册表 canonical `<data-root>/artifacts`，双侧（Python/Rust）legacy
    读回退，`AISC_ARTIFACT_DATA_ROOT` 覆盖保留
  - **7e-4** Workbench 三处 `config_dir` 收敛到 `app_state_dir`（legacy Roaming 收养 +
    不可校验回退）；DiagnosticBundle 增脱敏 `dataRoot` 区块（TS 类型同步）
  - **7e-5** docker argv 增四个 data-root 挂载（claude/codex/cc-switch/runtime→daemon
    态），宿主预建挂载目标、resolver 失败即停；entrypoint project 态挂载优先、旧宿主
    回退 `/root/app` 布局；DATA-01 回归门：plan_run 挂载断言 + workspace 零新增断言
  - 测试封闭性：7 个测试模块注入 hermetic `AISC_DATA_ROOT`（此前向真实
    `%LOCALAPPDATA%` 写入——含一处 `addCleanup(pop)` 误清注入值的 bug）
- 回归：全量 620 OK（61 skipped）；cargo 183+7×3；污染复查 workspaces=0
- 待 7f 真机：Docker Desktop 实跑 project/temporary 双作用域、旧宿主回退布局、
  cc-switch daemon 持久化
- 结论：**PASS**

证据模板：

```text
目标/验收 ID：
Commit：
OS/arch：
CLI/Workbench/Container 版本：
前置条件：
步骤：
期望：
结果：
测试名/日志（已脱敏）：
结论：PASS | FAIL
```
