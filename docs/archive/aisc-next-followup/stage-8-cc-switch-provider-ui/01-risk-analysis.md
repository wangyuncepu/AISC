# Stage 8 风险分析

| 风险 | 影响 | 缓解/门禁 |
|---|---|---|
| GitHub latest 变化或 API 限流 | 不可复现、构建失败 | resolver 缓存 metadata；Release 固定 manifest；限流时只允许显式版本，不静默使用旧资产 |
| prerelease/draft/无资产 release | 安装错误版本或构建中断 | 使用 `prerelease=false,draft=false`，校验 semver、平台、架构和 checksum |
| 上游资产命名/签名变化 | Dockerfile 下载失败 | resolver 解析 release assets，不硬编码单一文件名；无匹配资产 fail closed |
| cc-switch 无稳定 daemon/API | 被迫解析 TUI或直写 DB | Stage 8a 技术预研；无 API 时实现最小 adapter，禁止 TUI scraping |
| UI/CLI 并发 SQLite 写入 | 数据损坏/丢失 | 统一 writer、BEGIN IMMEDIATE、busy timeout、schema check、进程锁和 contract tests |
| API key 出现在 argv/log/诊断 | 密钥泄露 | stdin/受控 IPC、redaction、禁止回显、secret fixture 扫描 |
| preset 覆盖用户配置 | 用户配置丢失 | field ownership、revision marker、显式 override 层和回归测试 |
| DeepSeek 文档模型变更 | 生成错误请求 | 官方文档 fixture 带日期/revision；实施前门禁和更新说明 |
| 桌面 UI 在容器无显示服务器 | 无法启动/弹窗 | 不运行窗口 binary；Workbench tab 只消费 HTTP/IPC 数据面 |
