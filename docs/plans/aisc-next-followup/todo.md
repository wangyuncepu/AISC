# 待办与门禁

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
