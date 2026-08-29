# AISC Next Follow-up 总览

> 状态：Accepted planning
> 基线：`f5a74e5`（`develop`）

## 目标

1. 统一 AISC 在 Windows 上的配置、状态、运行时文件、日志、缓存、artifact 和诊断目录，默认不再污染打开的 workspace 根目录；
2. 构建容器时选择 cc-switch 最新稳定版（排除 prerelease），同时让 Release/CI 保持可复现；
3. 将 cc-switch UI 放在容器内并嵌入 Workbench tab，和 cc-switch CLI 使用同一配置目录及 SQLite 数据库；
4. 修正并可验证 DeepSeek 官方配置，提供 Claude alias 到 flash/pro 的模型映射、`[1m]` 声明和用户覆盖；
5. 编写并实现一个 C# Windows-only、纯原生终端控件的功能等价 POC，与 Tauri + Vue 并行验证。

## 已接受的产品边界

- Workbench 后续开发面向 Windows；Python CLI 和容器保持跨平台；
- cc-switch tab 必须是 Workbench 内的 UI，不能打开宿主机桌面版，也不能弹出独立桌面窗口；
- Provider UI 首版只做列表、删除、修改、简易添加和自定义添加；密钥只写入受控存储，页面默认遮罩且不能回显完整值；
- 简易添加只需要 Provider 下拉框和 API key；自定义添加提供 base URL、API key、模型、wire API 等 cc-switch 官方字段；
- C# POC 复用现有 `aisc.cli/v1`、Workspace/Data Root 和 Provider UI protocol，不重写 Python CLI 或 DockerGateway。

## 明确非目标

- 不在容器中运行需要 X11/桌面窗口的 Linux cc-switch binary；
- 不使用宿主机已经安装的 cc-switch Desktop；
- 不通过解析 TUI 文本或 Workbench 直接写 SQLite；
- 不在本阶段做完整 IDE、模型市场、密钥同步服务、跨设备账号或自动覆盖用户 preset；
- 不因 C# POC 的存在立即删除 Tauri + Vue。

## 阶段编号

本计划承接已完成的 Stage 0–6，新增 Stage 7–9。每阶段目录沿用 `00-overview`、`01-risk-analysis`、`02-domain-contract`、`03-ux-flow`、`04-observability-testing`、`05-implementation-plan`、`acceptance`、`decisions` 规约；Stage 9 另含 C# 开发文档。

## 关键门禁

- Stage 7：新旧路径解析、迁移、锁、原子写入和回滚 fixture 全部通过；
- Stage 8：latest resolver、资产架构、checksum、preset refresh、Provider UI protocol 和 SQLite 并发测试通过；
- Stage 9：WinUI shell、runtime/session、原生 terminal、tab 和 Provider UI 的功能等价 POC 通过，性能和可维护性结论写入验收。

## 回滚原则

- Stage 7 的数据迁移以 manifest 为边界，失败只回滚本次目标写入，保留源文件和 quarantine；
- Stage 8 的镜像回滚使用已记录的精确 release manifest；Provider preset 回滚只恢复 preset-owned 字段，不覆盖用户字段；
- Stage 9 的 POC 通过删除/停用实验分支回滚，正式 Tauri + Vue 始终可独立发布；
- 任何 schema/protocol 不兼容都 fail closed，不以旧缓存或猜测值冒充成功。
