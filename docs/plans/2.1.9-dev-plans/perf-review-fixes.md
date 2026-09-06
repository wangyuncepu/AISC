# PERF 批次审查修复计划（D-13）

- 范围：`ffc6564..c9dd941`（PERF P1-P9）
- 性质：代码审查后续修复，不新增性能目标；以“语义等价 + 失败路径可恢复”为唯一验收标准。
- 状态：已完成（2026-09-06）

## 背景

D-13 审查确认 Python/Rust/Vitest/vue-tsc 回归基线均为绿色，但发现两类会静默改变语义的问题，以及若干契约测试缺口。本文档作为修复计划与验收清单。

## 修复项

### R1. P6a light-poll 降级契约（Blocker）

**问题**：`docker_api.rs::poll_light()` 把 raw transport 失败折叠成 `Ok(unknown + stale)`；前端只在 `runtimePollLight()` reject 时才回退完整 CLI。结果 named pipe 不可用时不会触发预期降级，可能长期停留 unknown/stale。

**修复**：

1. transport / HTTP 非 200 / 超时统一返回 `Err`。
2. `refreshRuntimeLight()` 的 catch 继续回退 `runtimeStatus()`。
3. Rust 单测注入失败 engine getter，断言 `poll_light` 返回 `Err` 而不是 `Ok(unknown)`。

### R2. P4 SDK exec 流语义（Blocker）

**问题**：SDK `exec_start()` 未开启 `demux`，stdout/stderr 被合并且 stderr 恒空；`timeout` 与 `input_text` 参数被忽略，CLI executor 的隔离和超时语义丢失。

**修复**：

1. `exec_start(..., demux=True)`，分别映射 stdout/stderr。
2. mapped hot path 仅支持无 timeout、无 input 的 plain exec；出现任一参数立即回退 CLI。
3. 测试覆盖 stdout JSON + stderr warning、timeout fallback、input fallback。

### R3. P4 ps 模板与 Names 语义（High）

**问题**：

- 未知模板 token（如 `{{.CreatedAt}}`）不触发 fallback，而是字面输出。
- CLI `{{.Names}}` 是逗号连接的全部 name；SDK 渲染只取第一个。

**修复**：

1. 渲染前先校验模板只包含已支持 token；未知 `{{.Field}}` 与带空格的 `{{ .Field }}` 都回退 CLI。
2. `Names` 按 CLI 语义输出 `name1,name2`。
3. `containers.list(..., sparse=True)` 保持单次 `/containers/json` 请求，避免默认 list 对每行容器追加 inspect；renderer 读取 list payload 的字符串 `State`、顶层 `Labels`/`Image`，同时防御 inspect-like shape。测试 pin 多容器名、未知 token fallback 与 `sparse=True`。

### R4. P4 零 CLI 泄漏断言（High）

**问题**：fake client 成功 mapped 路径没有断言内层 CLI executor 零调用，无法防止 fake 缺属性后静默穿透真实 CLI。

**修复**：对 ps/exec/inspect/preflight 的 mapped 成功路径分别 mock 内层 CLI 方法，断言零 CLI 调用；ps 测试同时断言使用 `sparse=True`，避免默认 list 的逐容器 inspect。

### R5. P8 memory 数据层校验（Medium）

**问题**：Rust 校验允许 `3gg`、`3bg` 等多个 suffix 字符；CLI `--max-memory` 缺少等价校验。

**修复**：

1. Rust 严格校验：纯数字，或数字 + 单个 `b/k/m/g`。
2. Python runtime/CLI 数据层使用同一格式校验，非法值在入口拒绝，而不是传给 Docker。
3. 增加非法样本测试。

### R6. P9 `--agent all` 部分失败语义（Medium）

**问题**：`--agent all` 逐 agent 提交；第一个成功、第二个失败时返回 1，但已成功 agent 的状态不回滚。

**处置**：先明确该聚合路径是 sequential best-effort，不承诺原子性；在实现与 entrypoint 注释中写明，并在测试中 pin 部分失败输出。若后续要求原子性，再另行设计两阶段提交/备份恢复，不在本次修复中引入数据库快照回滚的额外风险。

### R7. P3 历史 spool 丢失窗口文档化（Low）

**问题**：20 条/60s/exit flush 的 accepted loss window 未在代码注释中明示，容易误解为强持久化。

**修复**：在 bash/zsh hook 与 helper 注释中明确 SIGKILL/强停/宿主崩溃可能丢失未 flush 命令。

## 不修改项

- P5b 锁互操作：双向互斥、心跳语义、时间戳格式与逃生舱已审查通过。
- P2 EOF 退出语义：exec-specific inspect、5s 保底、legacy 逃生舱均通过。
- P7 退避叠加：当前策略无 120s 叠加问题。
- `.wslconfig` auto 保键合并与确认文案：当前实现通过审查。

## 验收

1. `python -m pytest tests/ -q`
2. `cargo test --manifest-path workbench/src-tauri/Cargo.toml`
3. `pnpm -C workbench test` 或项目当前实际包管理器等价命令
4. `pnpm -C workbench exec vue-tsc --noEmit` 或等价命令
5. `container/` 有改动后必须刷新 vendor/checksums 并确认 bundle 同步。

## 实施结果（2026-09-06）

| 验收项 | 结果 |
|---|---|
| Python 全量 | `1146 passed, 70 skipped, 1 warning, 126 subtests passed`（warning 为既有 GBK decode 线程警告） |
| Rust 全量 | lib `305 passed`；integration tests 全绿（cli_fixtures 7、cli_runner 7、lock_interop 2、pty_supervisor 7、web_services 4） |
| Vitest | 56 个文件、434 个测试通过 |
| vue-tsc | `node node_modules\vue-tsc\bin\vue-tsc.js --noEmit` 通过 |
| vendor verify | `1514 verified, 0 missing, 0 checksum mismatch, 0 malformed`（⚠ 后证为 CRLF 假绿，见下） |

## 热修（2026-09-06 晚，`fe28d75`）

b49ed0f 的 container/ 四文件（aisc-bashrc / aisc-zshrc / aisc_bash_history.py / cc_switch_preset_providers.py）编辑时被写成 CRLF：vendor-refresh 对有改动文件按工作区字节取哈希 → CRLF 哈希进 checksums，CI（eol=lf 检出）Bundle/NSIS verify 炸 4 mismatch；本地 verify 对 CRLF 验 CRLF 假绿；bundle 三副本同步的也是 CRLF 版。修复：工作区字节级归一 LF（哈希与 CI 期望逐一相符）+ 重刷 vendor + bundle 重同步。git blob 侧因 .gitattributes 归一化本就正确。教训：Windows 上 vendor-refresh 须 `PATH="/tmp/py3shim:$PATH"`（WindowsApps python3 stub rc=49 杀 step 3）；编辑 container/ 文本文件后必查 CRLF。
| bundle 同步 | `aisc-bashrc`、`aisc-zshrc`、`entrypoint.sh`、`lib/aisc_bash_history.py`、`lib/cc_switch_preset_providers.py` 在 container / NSIS bundle / debug bundle 三处 SHA256 一致 |
