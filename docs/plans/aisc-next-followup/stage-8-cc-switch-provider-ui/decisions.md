# Stage 8 决策

| ID | 决策 | 说明 |
|---|---|---|
| D8-01 | 默认 `stable/latest`，发布锁定精确版本和 SHA-256 | latest 解决开发摩擦，manifest 保证可复现 |
| D8-02 | resolver 在构建前执行，Dockerfile 消费解析结果 | 避免 Dockerfile 隐式联网和版本漂移 |
| D8-03 | UI tab 不运行桌面窗口 | 容器没有宿主显示环境，且用户明确要求不得独立窗口 |
| D8-04 | 优先官方 API/daemon，无 API 才受控 adapter | 绝不解析 TUI 或让 GUI 直写数据库 |
| D8-05 | UI/CLI 共用一个 SQLite 和写入 adapter | 保证 provider 事实一致、并发可控 |
| D8-06 | DeepSeek 具体模型 ID 来自官方 fixture | 官方文档变更时可审计、可更新，不固化猜测 |
| D8-07 | preset refresh 尊重 user-owned fields | 用户覆盖优先于默认 preset |
