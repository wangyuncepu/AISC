# Stage 2 UX/流程

## 用户路径

1. pip 用户在 clean venv 执行安装并运行 `aisc version --format json`；输出 protocol/capability。
2. Workbench 启动 discovery，按固定优先级探测；显示来源、版本、错误和下一步，不展示完整环境变量。
3. capability 满足时执行结构化命令；不满足时显示升级/选择其他来源，禁止隐式 fallback。
4. sidecar 升级先校验 manifest/hash/架构，再原子替换；失败保留旧版本并提供回滚。
5. 诊断导出前展示文件清单和 redaction 摘要，用户确认后写出。

CLI 原始 stdout 不直接作为 GUI 文案；稳定错误码配本地化 action。所有按钮可键盘触发，安装失败不诱导用户输入凭据。
