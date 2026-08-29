# v2.1.8 开发计划（Agent 历史对话 + Bash 体验）

> 状态：设计 v5 待审阅 · 2026-08-29
> 基线：develop HEAD（v2.1.7-dev S9 全收）
> 主题：Agent 历史对话管理、Bash 体验增强、Codex 提示

## 文档索引

- [`01-design.md`](01-design.md) — 设计 v5（审阅 v4：P0-1 去 export 守卫、P0-3 sidecar captured preflight + 精确 ID 匹配、P1 1-4 全修）

## 阶段总览（v5）

| 阶段 | 内容 | 依赖 |
|---|---|---|
| T0 | 探针 fixture 冻结（Claude/Codex 真实 JSONL 脱敏入 tests/fixtures/） | 无（**可先行**） |
| T1 | Picker agent 标签清理 + AGENTS.md 可选模板注入 | 无 |
| T2 | Bash 全套（含 runtime.py 新增 `-e AISC_WORKSPACE_HASH` 实装任务） | T0 + P0 修正过审 |
| T3 | CLI `conversation list` + `conversation resume`（含 sidecar preflight） | T0 + P0 修正过审 |
| T4 | wrapper `--resume-id` + Rust `conversation_list/resume` IPC + 变更页 UI | T3 |
| T5 | 手测全矩阵 + CI + 收口 | T2+T4 |
