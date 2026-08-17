# 决策记录

> 状态：Accepted（2026-08-17）
> 基线：`f5a74e5`

| ID | 决策 | 理由 |
|---|---|---|
| D-16 | 新计划使用独立目录 `aisc-next-followup`，不修改已完成的 `aisc-next` | 旧计划即将归档，避免把新需求混入已验收范围 |
| D-17 | Windows Workbench 默认使用 `%LOCALAPPDATA%\AISC\data` | 不污染 workspace；符合 Windows 用户数据目录语义 |
| D-18 | 提供旧布局一次性迁移、回滚和显式 legacy 诊断 | 现有用户不能因升级丢失配置或 runtime 状态 |
| D-19 | cc-switch 默认追踪最新 stable，Release 记录精确版本和 SHA-256 | 兼顾开发便利与发布可复现；排除 prerelease/draft |
| D-20 | cc-switch UI 在容器内提供数据面，在 Workbench 内嵌 tab 渲染 | 不依赖宿主 Desktop，不弹独立窗口，UI/CLI 共享数据库 |
| D-21 | 优先使用 cc-switch machine-readable API/daemon；无稳定 API 才实现 adapter | 不解析 TUI，不让 GUI 直写 SQLite，同时保留可落地性 |
| D-22 | Provider UI 支持简易添加和自定义添加，密钥不可回显 | 覆盖常用场景且降低误操作和泄露风险 |
| D-23 | DeepSeek endpoint/model 以官方文档 fixture 为 SSOT，Claude alias 为 flash/pro 并默认 `[1m]` | 避免固定错误 base URL/模型；允许官方变更和用户 override |
| D-24 | 后续 Workbench 开发 Windows-only；Python CLI/container 继续跨平台 | C#、原生 terminal 和 Docker 适配需要明确平台边界 |
| D-25 | C# 使用独立 `experiment/workbench-winui3` 分支做功能等价 POC | 与 Tauri + Vue 并行验证，不提前承担全量重写成本 |
| D-26 | C# POC 优先验证原生 terminal control 的 ANSI、中文、emoji、方向键、resize 和高输出 | 这是 Windows 原生重构的最大技术不确定性 |

## 待门禁后决定

- 最新 cc-switch 是否提供可维护的 daemon/API；若没有，adapter 的最小权限边界和升级策略；
- 官方 DeepSeek 文档在实施时的具体模型 ID 和 Anthropic endpoint；
- native terminal control 的最终组件及许可证、分发和无障碍表现；
- C# POC 是否达到替代 Tauri 的性能、稳定性和维护收益门槛。
