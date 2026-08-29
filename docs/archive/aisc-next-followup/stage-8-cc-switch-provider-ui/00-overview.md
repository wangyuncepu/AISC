# Stage 8：cc-switch 最新版与 Provider UI

> 状态：Planned
> 前置：Stage 7 path contract

## 目标

1. 构建默认使用 cc-switch 最新 stable release，排除 prerelease/draft，并保留 Release 可复现信息；
2. 更新 DeepSeek preset，严格以官方文档字段和 fixture 为准；
3. 为 Claude 提供默认 flash、opus -> pro、其它 alias -> flash 的 `[1m]` 映射，用户 override 优先；
4. 在容器内运行 cc-switch UI backend/adapter，在 Workbench 内嵌 `cc-switch-ui` tab，不打开独立桌面窗口；
5. UI 与 cc-switch CLI 共享同一 `cc-switch.db`，并提供最小 Provider 管理闭环。

## 验收目标

| ID | 目标 |
|---|---|
| CS-01 | `latest` 只解析 stable 且下载目标架构资产；显式版本可复现 |
| CS-02 | 镜像 label/manifest 记录 tag、commit、URL、arch、SHA-256 |
| CS-03 | DeepSeek endpoint、字段、模型和 `[1m]` fixture 与官方文档一致 |
| CS-04 | Claude alias 映射默认正确，用户覆盖在 preset refresh 后仍存在 |
| CS-05 | `cc-switch-ui` 为 Workbench 内嵌 tab，容器内 UI/CLI 同库并发安全 |
| CS-06 | list/add/edit/delete、简易/自定义添加和 secret redaction E2E 通过 |
