# Stage 7 风险分析

| 风险 | 影响 | 缓解/门禁 |
|---|---|---|
| `%LOCALAPPDATA%` 不可用或被重定向 | 配置丢失或写入错误用户目录 | 使用 Windows Known Folder API；解析结果记录在 doctor；无权限时停止，不静默回退 workspace |
| 旧目录同时被两个进程迁移 | 数据损坏、重复写 | 全局 migration lock + workspace lock；manifest 状态机和原子 rename |
| 同名用户文件/目录 | 覆盖用户数据 | 只迁移已知 AISC-owned 文件；冲突进入 quarantine 并要求确认 |
| junction/symlink 越界 | 任意路径读写 | 逐段 containment 校验；拒绝 reparse point，除非明确允许且目标仍在 root |
| 路径过长/非 ASCII | 容器挂载或启动失败 | 使用长路径 API；中文、空格、emoji 和 260+ 路径 fixture |
| 磁盘不足/进程中断 | 半迁移状态 | 预估空间、临时目录、fsync/atomic replace、可重复 resume/rollback |
| 旧版本仍写 workspace | 新旧状态分叉 | 在旧入口留下只读 redirect/诊断；集成测试扫描 workspace 写入 |
| 多 workspace hash 碰撞 | 共享错误配置 | SHA-256 全量 canonical path，目录名带版本，碰撞测试和 manifest 校验 |
