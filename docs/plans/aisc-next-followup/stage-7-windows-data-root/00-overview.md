# Stage 7：Windows Data Root

> 状态：Planned
> 前置：已完成 Stage 0–6

## 目标

让 AISC 初始化和运行产生的配置、状态、runtime、日志、缓存、artifact、诊断和迁移文件集中在 `%LOCALAPPDATA%\AISC\data`，不再散落到 workspace 根目录。Python CLI、Workbench 和容器必须使用同一份路径解析合同。

## 验收目标

| ID | 目标 |
|---|---|
| DATA-01 | fresh install 不在 workspace 自动创建 `.aisc`、`.claude`、`.codex`、`.cc-switch` 等 AISC-owned 目录 |
| DATA-02 | 旧布局可 dry-run、迁移、校验、回滚；用户文件不被覆盖 |
| DATA-03 | 多进程/多 workspace 并发安全，路径越界和 symlink/junction 被拒绝 |
| DATA-04 | Workbench、CLI、container mount 和 diagnostics 都显示同一 canonical root |
| DATA-05 | upgrade、权限不足、磁盘不足、损坏和取消都 fail closed 且可恢复 |
