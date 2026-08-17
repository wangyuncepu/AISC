# 待办与门禁

## 想法 / Ideas

### IDEA-1 Tab 新建 UX（Windows Terminal 式，2026-08-17 用户提出）

- **内容**：设置页增加「默认新 tab」选项；点 `+` 立即建默认 tab；`+` 旁加 `↓`
  展开完整列表选择（拆分按钮）；设置页本身改为一种 tab 类型。
- **现状**：仅记录，**未实现**。`+` 菜单被 tabbar 滚动容器裁剪的 bug 已单独修复
  （Teleport + zoom 补偿；Stage 6 UX-02 回归，非 Stage 7 范围）。
- **归属**：Stage 7 合并后的独立 UI 小阶段——涉及 settings schema 新字段（含 REL-03
  round-trip 用例）、TabBar 拆分按钮、设置页 tab 化（现 tab 模型绑定 agent session，
  设置 tab 是无 session 的新类别，需验收 ID + vitest/i18n 同步）。
- **附带**：KI-1（向导 Docker 就绪检测）与 KI-2（向导界面复检）仍在归档
  `aisc-next/todo.md` 挂账，建议与 IDEA-1 同一轮手测一并处理。

## 进入 Stage 7 前

- [x] 确认归档 `aisc-next` 的最终提交和迁移说明（最终提交 `f5a74e5`；目录随 followup 计划入库整体移入 `docs/archive/completed/`）；
- [x] 记录现有 workspace 根目录中会被迁移的文件清单（fresh 初始化实测，见 `stage-7-windows-data-root/02-domain-contract.md` Legacy layout 实测清单）；
- [ ] 定义 `AISC_DATA_ROOT` 的开发/测试覆盖和权限策略（7a-contract 实现内容）。

## Stage 7

- [ ] Windows path resolver、workspace hash、lock、atomic replace；
- [ ] legacy scan、迁移 manifest、dry-run、rollback 和损坏隔离；
- [ ] CLI、Workbench、container mount 全部改用 resolver；
- [ ] fresh/upgrade/multi-instance/long-path/disk-full 真机验收。

## Stage 8

- [ ] 预研最新 stable cc-switch 的 daemon/API 和数据库锁行为；
- [ ] 实现 stable latest resolver、资产架构校验、SHA-256 和 image labels；
- [ ] 从官方 DeepSeek 文档生成 fixture，确认字段、模型 ID、endpoint 和 `[1m]`；
- [ ] 冻结 Provider UI protocol，完成 list/add/edit/delete 和 secrets redaction；
- [ ] 验证 UI/CLI 同库、并发写、preset refresh 用户覆盖和升级迁移。

## Stage 9

- [ ] 创建 `experiment/workbench-winui3`；
- [ ] 搭建 WinUI shell、native terminal control、session/tab 和 CLI bridge；
- [ ] 用同一 contract fixture 实现 Provider tab；
- [ ] 完成等价验收、性能/崩溃/高输出报告和替代决策建议。
