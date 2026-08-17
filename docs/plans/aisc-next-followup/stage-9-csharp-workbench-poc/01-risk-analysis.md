# Stage 9 风险分析

| 风险 | 影响 | 缓解/门禁 |
|---|---|---|
| 原生 terminal control 不成熟或许可不合适 | POC 无法达到终端体验 | 先做独立 spike；比较 Microsoft/Windows Terminal 原生控件及许可证；无法满足则停止，不手写完整 terminal emulator |
| ANSI/IME/中文/emoji/resize 差异 | 用户输入和输出错误 | 与 Tauri 共享 golden transcript 和交互矩阵；固定 cell size、DPI、字体和 resize 事件 |
| C# 复制 Python/Rust 领域逻辑 | 行为漂移、双倍维护 | 只调用 `aisc.cli/v1`；协议模型生成/fixture；禁止 Docker/SQLite 直连 |
| PTY/pipe child 泄漏 | 卡死、句柄增长 | cancellation token、job object、bounded channel、关闭序列和 soak gate |
| WinUI/Windows SDK 版本碎片 | 安装或运行失败 | 固定最低 Windows build、SDK、.NET/WinAppSDK；CI + clean VM 安装测试 |
| POC 视觉与 Tauri 不一致 | 无法比较功能效率 | 以任务和 contract fixture 为主，先不追求像素一致；记录差异和迁移成本 |
| Web/Provider session 权限扩大 | 密钥泄露 | 复用 Stage 8 protocol、短期 token、secret redaction 和 tab scope |
