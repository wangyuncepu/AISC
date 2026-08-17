# Stage 7 可观测性与测试

## 自动化

- resolver：Known Folder、覆盖变量、相对路径、非法 reparse point、hash 稳定性；
- migration：fresh、旧版本 fixture、重复执行、取消 resume、冲突、损坏、rollback；
- concurrency：两个 CLI、Workbench sidecar 和容器 wrapper 同时启动/写入；
- filesystem：中文/空格/emoji、长路径、权限拒绝、磁盘不足模拟；
- regression：workspace 扫描断言 AISC-owned 文件不再新增。

## 手测矩阵

Windows 11 x64、普通用户、OneDrive 重定向用户目录、路径含中文、Docker Desktop running/not-ready、upgrade from legacy layout。

## 证据与脱敏

记录 root 的类别和 hash，不记录 API key、完整 workspace path（除非用户明确导出）、环境变量或终端输出。每个 DATA ID 的验收记录包含 OS/build、命令、测试名、结果和 rollback 证据。
