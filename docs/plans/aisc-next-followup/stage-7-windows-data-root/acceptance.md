# Stage 7 验收

| ID | 验收方法 | 结果 |
|---|---|---|
| A-DATA01 | fresh Windows workspace，启动 CLI/Workbench/container 后扫描根目录 | 待执行 |
| A-DATA02 | legacy fixture dry-run/apply，校验 manifest、hash、redirect 和源文件 | 待执行 |
| A-DATA03 | 中断迁移后 resume/rollback，模拟权限/磁盘不足 | 待执行 |
| A-DATA04 | 两个 session + provider 写入并发，检查 lock 和 SQLite/JSON 完整性 | 待执行 |
| A-DATA05 | 中文、emoji、长路径、junction、OneDrive 用户目录 | 待执行 |

证据模板：

```text
目标/验收 ID：
Commit：
OS/arch：
CLI/Workbench/Container 版本：
前置条件：
步骤：
期望：
结果：
测试名/日志（已脱敏）：
结论：PASS | FAIL
```
