# Stage 9 可观测性与测试

## 自动化

- Protocol：JSON envelope、未知 schema、超时、非零退出、过大输出和取消；
- Core：session state machine、tab close/reopen、operation retry/cancel；
- Windows：process tree/job object 清理、PTY/pipe backpressure、resize、DPI、路径和权限；
- Terminal golden：ANSI color/style, cursor, alternate screen, Unicode combining/emoji, CJK/IME, bracketed paste, arrows, mouse and 100MB output；
- Provider：复用 Stage 8 protocol fixture 和 secret scan；
- soak：8 小时多 tab 高输出、重复启动/关闭、sleep/resume 和 Docker restart。

## 对比指标

与当前 Tauri 版本在同一 Windows VM 测量启动 p50/p95、首字节延迟、PTY 输出吞吐、内存、句柄、CPU、tab 切换和崩溃恢复。报告必须注明测试版本、机器和 workload，不用单一指标决定替代。

## 手测

Windows 11 x64、普通用户、DPI 100/150/200%、中英文输入法、暗/亮主题、键盘-only、screen reader smoke、Docker ready/not-ready 和网络断开。
