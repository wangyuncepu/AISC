# Stage 7 决策

| ID | 决策 | 说明 |
|---|---|---|
| D7-01 | 默认使用 `%LOCALAPPDATA%\AISC\data` | Windows 用户数据语义；不把配置放在 workspace |
| D7-02 | workspace 隔离目录使用 versioned SHA-256 | 稳定、不可读出原始路径、避免碰撞 |
| D7-03 | 迁移只处理 known-owned allowlist | 保护用户自有 `.claude` 或同名文件；未知项 quarantine |
| D7-04 | 冲突和损坏 fail closed | 宁可要求用户决策，不自动覆盖或删除 |
| D7-05 | CLI、Rust、container 共用 resolver 契约 | 防止每层产生不同 root 和状态分叉 |
