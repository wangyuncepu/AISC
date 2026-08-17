# AISC Next Follow-up

> 状态：Accepted planning
> 代码基线：`f5a74e5`
> 规划日期：2026-08-17

这是 `aisc-next` 计划（已归档至 `docs/archive/completed/aisc-next/`）完成后的后续计划。本目录只覆盖新的 Windows 数据布局、容器内 cc-switch Provider UI、最新版 cc-switch 构建以及 C# Workbench 功能等价 POC。

阅读顺序：

1. `00-overview.md`：范围、阶段目标和非目标；
2. `01-cross-stage-contracts.md`：路径、CLI、Provider、构建和安全不变量；
3. `02-dependency-map.md`：阶段门和允许的并行关系；
4. `decisions.md`：已经确认的产品与架构选择；
5. 对应 `stage-*` 目录：风险、契约、UX、测试、实施和验收。

## 阶段

| 阶段 | 目录 | 目标 | 前置 |
|---|---|---|---|
| 7 | `stage-7-windows-data-root/` | 把初始化配置、运行时状态、日志、缓存和诊断统一收纳到 Windows 数据根目录，并提供旧布局迁移 | 已完成 `aisc-next` |
| 8 | `stage-8-cc-switch-provider-ui/` | 最新稳定版 cc-switch、可复现版本记录、官方 DeepSeek preset、容器内 Provider UI 和共享数据库 | Stage 7 路径契约 |
| 9 | `stage-9-csharp-workbench-poc/` | 在独立分支用 C# + 原生 Windows terminal control 实现功能等价 POC；Tauri + Vue 继续正式主线 | Stage 7；复用 Stage 8 契约 |

Stage 9 的实现可以在 Stage 8 的协议冻结后与 Stage 8 的剩余实现并行，但不得复制 Docker、Provider 或 Python CLI 业务逻辑。

## 总体交付门

- 每个阶段都有自动化测试、Windows 真机手测、证据记录和回滚说明；
- API key、OAuth、cookie、完整环境变量和终端 scrollback 不进入日志、artifact、history 或诊断包；
- 本地开发默认 `latest stable`，Release/CI 必须记录解析后的精确版本、commit/tag 和 SHA-256；
- UI 只能通过版本化 `aisc` CLI/Provider UI protocol 操作容器，不能直连 Docker 或 SQLite；
- 用户明确修改过的 Provider 配置在 preset 刷新时不得被覆盖；
- C# POC 通过功能等价验收后，才讨论是否替代 Tauri，不在本计划中直接替换正式前端。
