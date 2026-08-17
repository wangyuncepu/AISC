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
