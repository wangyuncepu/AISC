# Stage 3：Workspace Explorer 与 Agent Artifact

> 状态：Accepted planning
> 代码基线：`d2bdcd9`
> 分支：`stage-3-workspace-artifacts`

## 目标

| ID | 目标 | 优先级 | 验收前缀 |
|---|---|---|---|
| ART-01 | 冻结 `aisc.artifact/v1` | P0 | `A-ART01-*` |
| ART-02 | `aisc artifact record/list/inspect/clear-session` | P0 | `A-ART02-*` |
| ART-03 | 内置 Artifact Skill，提供语义约束 | P1 | `A-ART03-*` |
| ART-04 | session-scoped registry，不污染 workspace | P0 | `A-ART04-*` |
| ART-05 | Rust 路径 containment 与 secret policy | P0 | `A-ART05-*` |
| ART-06 | versioned artifact index 安全持久化 | P0 | `A-ART06-*` |
| WX-01 | lazy、只读 Workspace tree | P1 | `A-WX01-*` |
| WX-02 | 打开、Reveal、复制路径、适用预览 | P1 | `A-WX02-*` |
| WX-03 | watcher 兜底与 bounded rescan | P1 | `A-WX03-*` |
| WX-04 | Artifact 分类与未归因变化 | P1 | `A-WX04-*` |
| WX-05 | 大仓库、响应式、键盘和错误体验 | P1 | `A-WX05-*` |

## 不变量

- Skill 提供标题、分类和打开建议，不是事实数据库。
- `aisc.artifact/v1` 的显式登记是 authoritative fact。
- watcher 只报告文件变化；不得猜测 Agent provenance。
- Agent 只提交 workspace-relative path；宿主绝对路径由 Rust 校验后解析。
- Explorer 首版只读，不交付完整编辑器、删除、重命名或全盘索引。
- Agent Artifact 与发行 `packaging artifact` 使用不同 schema 和命名空间。

## 完成定义

目标全部有自动化和真机证据；恶意路径/secret/overflow 被拒绝；大 workspace 可用；Claude/Codex/shell 产物工作流 E2E 通过；重启后 index 可恢复且不污染 Git 状态。