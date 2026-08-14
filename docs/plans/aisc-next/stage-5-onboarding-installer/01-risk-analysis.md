# Stage 5 风险分析

| ID | 风险 | 缓解 |
|---|---|---|
| R5-01 | NSIS 过度承载业务 | 严格 installer/Workbench 边界与 handoff fixture |
| R5-02 | Docker 安装后 Engine 尚未 ready | readiness 状态机、重试/超时/诊断/稍后继续 |
| R5-03 | WSL/许可/重启中断 | 将 blocking 原因具体化，可回到环境页 |
| R5-04 | 首次向导不可恢复 | schema version、checkpoint、resume/skip/reopen 测试 |
| R5-05 | Provider/API key 泄露 | 只显示 Ready/Needs login/configuration，不读密钥 |
| R5-06 | TUN 改写用户网络 | 明示影响、用户确认、探针验证、可跳过/回滚 |
| R5-07 | 重复运行误删 Runtime/history | onboarding 只调用现有 preflight/reuse/restore contract |
| R5-08 | 中英/窄窗/高 DPI 溢出 | i18n、320/600/800/150% 矩阵和键盘测试 |
| R5-09 | 安装升级丢 settings/history | migration/rollback/backup smoke |
| R5-10 | 安装器和 GUI 状态漂移 | handoff 只传事实，Workbench 再验证，不信任标记 |

残余风险：Docker Desktop 首次启动行为受平台和用户许可影响；向导必须允许不完成安装并正常退出。