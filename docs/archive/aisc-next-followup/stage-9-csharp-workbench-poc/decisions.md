# Stage 9 决策

| ID | 决策 | 说明 |
|---|---|---|
| D9-01 | C# 只做 Windows-only 功能等价 POC | 先验证技术和维护收益，避免无证据全量重写 |
| D9-02 | 分支为 `experiment/workbench-winui3` | 与正式 Tauri + Vue 主线隔离，可并行开发 |
| D9-03 | 使用原生 terminal control 优先 | 用户要求纯原生终端控件；自制 emulator 是高风险非目标 |
| D9-04 | 复用 `aisc.cli/v1` 和 Provider protocol | 保证 Python/container 事实只有一个所有者 |
| D9-05 | 以任务等价和证据决定后续路线 | 不以视觉重写完成度或单项 benchmark 直接替代 |
