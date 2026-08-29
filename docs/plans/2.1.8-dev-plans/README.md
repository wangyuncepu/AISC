# v2.1.8 开发计划（Agent 对话 + Bash 体验）

> 状态：已审阅 · 2026-08-29
> 基线：develop `d7535b2`（v2.1.7-dev S9 全收）
> 主题：Agent 历史对话管理、Bash 体验增强、Codex 提示

## 文档索引

- [`01-design.md`](01-design.md) — 设计文档（已批准，方案 A 薄层直读）

## 阶段总览

| 阶段 | 主题 | 规模 |
|---|---|---|
| T1 | Picker 清理 + Codex AGENTS.md | 0.5h |
| T2 | Bash 工具（ble.sh/fzf/yazi/tmux/nvim/rg）+ HISTFILE + SQLite | 0.5 天 |
| T3 | CLI `session list`（JSONL 解析 → 结构化） | 0.5 天 |
| T4 | Rust IPC + 变更页双区 UI + 点击恢复 | 1 天 |
| T5 | 手测全矩阵 + CI + 收口 | 0.5 天 |
