# v2.1.8 开发计划（Agent 历史对话 + Bash 体验）

> 状态：设计 v3 待审阅 · 2026-08-29
> 基线：develop `3153269`（v2.1.7-dev S9 全收）
> 主题：Agent 历史对话管理、Bash 体验增强、Codex 提示

## 文档索引

- [`01-design.md`](01-design.md) — 设计 v3（探针冻结 + 审阅 v1/v2 全部阻塞项已回应）

## 阶段总览（v3）

| 阶段 | 内容 | 依赖 |
|---|---|---|
| T0 | 探针 fixture 冻结（Claude/Codex 真实 JSONL 脱敏入 tests/fixtures/；含标题/单引号 cwd/>10MB/resume 失败用例锚点） | 无 |
| T1 | Picker agent 标签清理 + AGENTS.md 可选模板注入 | 无 |
| T2 | Bash 全套：Dockerfile 工具（ble.sh/fzf/yazi/nvim/rg，版本 pin+sha256）+ rcfile 链（wrapper --rcfile + /root/.bashrc shim）+ HISTFILE + SQLite（Python helper 参数化） | T0 |
| T3 | CLI `conversation list`（JSONL 解析 + §1e 过滤/标注 + fixture 测试） | T0 |
| T4 | wrapper `--resume-id` + Rust `conversation_list/resume` IPC + 变更页第五分组 UI（失败不建 tab） | T3 |
| T5 | 手测全矩阵 + CI + 收口 | T2+T4 |
