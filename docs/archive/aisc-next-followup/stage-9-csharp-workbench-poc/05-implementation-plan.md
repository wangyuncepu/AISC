# Stage 9 实施顺序

1. `9a-spike`：评估 native terminal control 候选、许可证、ANSI/IME/resize 和高输出；输出 GO/NO-GO；
2. `9b-solution`：建立 .NET/WinUI solution、Core/Protocol/Windows 分层、CI 和签名/打包占位；
3. `9c-shell`：实现 DataRoot/readiness、窗口、导航、operation/error 和设置投影；
4. `9d-runtime`：实现 CLI sidecar discovery、JSONL、session registry、job object、PTY/terminal host；
5. `9e-tabs`：实现 terminal/cc-switch TUI tab、resize、close/reopen、bounded output；
6. `9f-provider`：复用 Stage 8 protocol，完成 `cc-switch-ui` Provider list/add/edit/delete；
7. `9g-equivalence`：运行 contract fixture、golden transcript、soak、a11y 和 Tauri 对比；
8. `9h-handoff`：写出替代/并行/停止建议，保持正式主线不变。

每一步保持独立提交。若 `9a-spike` NO-GO，保留协议和研究文档即可，不引入自制 terminal emulator。POC 任一阶段失败时只停用实验分支，不能影响 Tauri 发布链；协议 fixture 和性能报告保留供后续重启。
