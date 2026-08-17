# Stage 9：C# Workbench 功能等价 POC

> 状态：Planned / 独立实验分支
> 分支：`experiment/workbench-winui3`
> 前置：Stage 7 accepted、Stage 8a Provider protocol accepted

## 目标

验证 Windows-only 的 C# + WinUI 原生 Workbench 是否能在不复制 Python 业务的前提下，达到当前 Tauri + Vue Workbench 的核心功能等价：启动、runtime readiness、session/tab、原生 terminal、结构化 CLI 调用、cc-switch Provider UI 和诊断。

## POC 边界

- Tauri + Vue 继续正式发布和维护；
- Python CLI、DockerGateway、container wrapper 和 Provider schema 是复用对象；
- POC 不做全量视觉迁移、插件市场、完整 IDE 或跨平台支持；
- POC 通过后只输出替代/并行/停止建议，不自动切换产品主线。

## 验收目标

| ID | 目标 |
|---|---|
| CSPOC-01 | WinUI shell 和生命周期可安装、启动、关闭、恢复 |
| CSPOC-02 | session/tab/PTY 输出、输入、resize、取消和清理与 Tauri 等价 |
| CSPOC-03 | 原生 terminal 通过 ANSI、中文、emoji、方向键、鼠标、超长输出测试 |
| CSPOC-04 | 复用 `aisc.cli/v1` 完成 runtime、build、diagnostics、Provider UI 操作 |
| CSPOC-05 | 在 Workbench tab 内完成 cc-switch list/simple/custom/edit/delete |
| CSPOC-06 | 与 Tauri 对比的性能、可靠性、无障碍和维护成本报告完成 |
