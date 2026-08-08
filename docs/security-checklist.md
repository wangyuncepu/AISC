# AISC Workbench 安全验证清单

> 状态：Phase 3 S3.2
> 目的：Preview 发布前逐项验证的安全基线。每项含验证方式；未通过不得进入 S4 发布门。

## 1. Tauri 配置

- [x] **显式 CSP**：`tauri.conf.json` `app.security.csp` 已设（`default-src 'self'` + `ipc:` + dev 端口 + `style-src 'unsafe-inline'`）。验证：dev 启动 HMR 热更/终端渲染/样式正常；`csp: null` 已移除。
- [x] **最小攻击面**：`tauri-plugin-opener` 已移除（前端零调用 `openUrl`/`openPath`）。验证：`Cargo.toml`/`Cargo.lock`/`lib.rs`/`capabilities` 无 opener 引用；`package.json` 无 `@tauri-apps/plugin-opener`。
- [x] **capabilities 最小权限**：仅 `core:default` + `dialog:default` + `core:window:allow-destroy`（退出确认需要）。验证：`capabilities/default.json` 无多余权限。

## 2. 破坏性操作边界

- [x] **stop/remove 确认**：`stopRuntime`（侧栏，含活动 session 数）、`stopConflictRuntime`、`removeConflictRuntime`（含 force 文案）均有 `confirm` 对话框，取消不执行。验证：实机点各按钮 -> 弹确认 -> 取消无副作用。
- [x] **退出确认**：`onCloseRequested` 有活动 session 时 confirm，确认才 destroy（S2.2.b）。
- [x] **workspace 只读预检**：`runtime preflight` 只读无副作用；写入仅在用户确认 Start 后（S2.1.a）。验证：`aisc runtime preflight` 后无 `.aisc/`/容器创建。

## 3. Secret 与敏感数据

- [x] **history/settings 无 secret**：schema 仅 workspace/runtime_id/tab 元数据（02 §九 强制）；不含 session_id/PTY PID/scrollback/Provider 密钥。验证：`cat ~/.config/cn.aisc.workbench/history.json` grep 无 `sk-`/`token=`/`api_key` 形状。
- [x] **PTY scrollback 不持久化**：xterm 缓冲仅驻留内存（05 §9.2），Terminal 组件无 history/日志写入。验证：代码审查 + `~/.config/cn.aisc.workbench/` 无 scrollback 文件。
- [x] **粘贴 cap**：`write_session` 1MB 上限（S1.3 `MAX_WRITE_BYTES`，05 §9.2）。验证：Rust 单测 + 大粘贴实测不 OOM。
- [x] **错误 detail 脱敏**：`redact()` 过滤 `sk-`/`key=`/`token=` 形状（S1.2）。验证：Rust 单测（env secret/截断）。

## 4. 进程与资源

- [x] **无孤儿进程**：session close terminate -> wait/reap（S1.3）；op mutex 串行同 runtime 破坏操作（S3.1）。验证：50 次开关 session 无残留（Phase 1 门清单）。
- [x] **无持久化日志通道**：应用无日志文件/crash report 写入（仅终端缓冲 + 错误 detail 内存）。验证：`~/.config/cn.aisc.workbench/` 仅 settings.json/history.json。

## 5. 已知未做（defer）

- macOS 签名/公证、Windows 代码签名 -> S4 发布门。
- Provider 密钥读取：MVP 从不读（S0.4 secret-free 契约，无代码面）。
- 完整日志/crash report 通道：无持久化日志；若未来增加，需先定义脱敏/大小/权限契约（04 §七）。
