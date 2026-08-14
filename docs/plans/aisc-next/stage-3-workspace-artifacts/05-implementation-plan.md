# Stage 3 实施计划

> 分支：`stage-3-workspace-artifacts`

## 子步骤

1. `3a-contract`: schema fixture、CLI parser、redaction、路径策略，先写失败测试。
2. `3b-index`: Rust artifact index、revision/lock/atomic recovery、IPC。
3. `3c-explorer`: lazy tree、open/reveal/preview/copy；首版只读。
4. `3d-watcher`: debounce、overflow、bounded rescan、unattributed projection。
5. `3e-skill`: 内置 Skill、容器同步、Claude/Codex/Bash smoke。
6. `3f-polish`: keyboard/a11y、长路径、大目录、恢复和跨平台手测。

## 代码落点

- Python：`src/aisc/application/artifact.py`、`src/aisc/cli/commands/artifact.py`、`src/aisc/domain/artifacts.py`、fixtures/tests。
- Rust：`workbench/src-tauri/src/artifact.rs`、`workspace.rs`、`watcher.rs`、`lib.rs` commands。
- Frontend：`workbench/src/features/workspace-explorer/`、artifact store、types、ipc。
- Skill/container：`container/cc-switch-skills/`、`entrypoint.sh`、bundle revision。

## Commit/回滚

每个 3a–3f 独立提交；schema 先兼容只读，index 写入在 fixture 通过后启用。任何高版本 schema 保持只读，不覆盖原文件；watcher 可关闭并退回手动刷新。

## 阶段完成

A-ART/A-WX 全部 PASS，Python/Rust/Vue/CLI 测试、真机打开/Reveal/路径安全、overflow recovery 和用户确认完成后再合并。
