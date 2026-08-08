# Workbench S3.2 - 安全硬化

> 状态：提案
> 规范：06-implementation-plan.md §六 S3.2；02-startup-flow.md §九（history 不含 secret）；05-cli-gui-contract.md §9.2（粘贴 cap）
> 编写日期：2026-08-08
> 分支：feature/workbench-phase3

## 1. 范围

S3.2 安全硬化：Tauri CSP + 最小攻击面（移除未用 opener）+ 破坏性操作确认 + secret/scrollback/边界验证清单。

### 本切片做（IN）

- **CSP**：`tauri.conf.json` `app.security.csp` 设显式 CSP（现为 null 宽松）：
  `default-src 'self'; connect-src ipc: http://ipc.localhost ws://localhost:1420 http://localhost:1420; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; script-src 'self'`
  （`ws://localhost:1420`/`http://localhost:1420` 为 vite dev HMR；xterm 需 `'unsafe-inline'` style；IPC 需 `ipc: http://ipc.localhost`）。dev 实测 HMR/终端/样式，若破调整。
- **移除未用 opener**：前端零调用 `openUrl`/`openPath`（grep 确认）。`Cargo.toml` 移除 `tauri-plugin-opener`、`lib.rs` 移除 plugin init、`capabilities` 移除 `opener:default`。最小攻击面。
- **破坏性操作确认**（dialog `confirm`，复用 S2.2.b import）：
  - `stopConflictRuntime`：confirm「停止 Runtime <id 前 8 位>？」。
  - `removeConflictRuntime`：confirm「移除 Runtime <id 前 8 位>？容器与元数据将永久删除」（force 移除运行中则文案加「运行中强制移除」）。
  - 侧栏 `stopRuntime`：confirm「有 N 个活动会话，停止将结束它们并停止 Runtime。继续？」（N=运行中/启动中 tab 数，02 §7.2）。
  - 取消则不执行。
- **安全验证清单**：`docs/security-checklist.md` 建检查清单（勾选 + 验证命令）：
  - history.json/settings.json 无 secret/scrollback（schema 审查 + `grep` 验证写入内容）。
  - PTY scrollback 不持久化（仅 xterm 内存，Terminal 无 history 写入）。
  - 粘贴 1MB cap（S1.3 `MAX_WRITE_BYTES`，验证）。
  - workspace 只读预检、start 才写入（S2.1.a，验证）。
  - CSP/opener 移除生效（dev 验证）。

### 本切片不做（OUT）

- **完整日志/crash report 通道**：当前无应用日志文件/crash report 通道（无持久化日志）。若有 -> 届时 secret scan。本切片验证「无日志持久化」。
- **macOS 签名/公证/Windows 签名** -> S4 发布门。
- **Provider 密钥读取**：MVP 从不读（S0.4 secret-free 契约）。无代码。
- **URL 打开功能**：opener 移除后无 URL 打开面（终端内 URL 由 agent 处理，不在 Workbench）。

## 2. 关键设计

### 2.1 CSP（tauri.conf.json）

现 `"csp": null`。设为显式 CSP（见上）。dev 模式 Tauri 同样应用 CSP；`ws://localhost:1420`（HMR）+ `http://localhost:1420`（devUrl self）加进 connect-src。xterm 的 css 是 external（`style-src 'self'` 够），但 Vue scoped style 运行时注入 `<style>` 需 `'unsafe-inline'`。`script-src 'self'`（vite 打包/模块，无 inline script）。实机 dev 验证：HMR 热更、xterm 终端渲染、侧栏样式正常。

### 2.2 opener 移除

三处：Cargo.toml（依赖 + lock）、lib.rs（`.plugin(tauri_plugin_opener::init())` 移除）、capabilities（`opener:default` 移除）。opener 插件无任何前端调用，移除后无功能损失（Workbench 不打开外部 URL；终端内 URL 由容器内 agent 处理）。

### 2.3 破坏性操作确认

store `stopRuntime`/`stopConflictRuntime`/`removeConflictRuntime` 开头加 `confirm`（@tauri-apps/plugin-dialog 已 import）。confirm 是原生对话框，取消返回 false -> 不执行。文案含操作对象（runtime id 前 8 位 / 活动 session 数）。

## 3. 改动文件

- `workbench/src-tauri/tauri.conf.json`：`csp` 设置。
- `workbench/src-tauri/Cargo.toml` + `Cargo.lock`：移除 `tauri-plugin-opener`。
- `workbench/src-tauri/src/lib.rs`：移除 opener plugin init + import。
- `workbench/src-tauri/capabilities/default.json`：移除 `opener:default`。
- `workbench/src/stores/runtime.ts`：stopRuntime/stopConflictRuntime/removeConflictRuntime 加 confirm。
- `docs/security-checklist.md`（新）：安全验证清单。

## 4. 步骤与验证

1. CSP + opener 移除 -> verify: `cargo build`（无 opener 依赖）+ `npm run build`；`cargo test` 67 不回归。
2. store confirm -> verify: typecheck。
3. `docs/security-checklist.md` -> verify: 逐项勾选。
4. 实机手测 -> verify:
   - dev 启动：HMR 热更正常（CSP 不破）、xterm 终端渲染、侧栏样式正常。
   - ConflictManager 点 stop/remove -> 弹确认 -> 取消不执行 / 确认执行。
   - 侧栏「停止 Runtime」-> 弹确认（含活动 session 数）-> 确认后正常停止。
   - 常规流程回归（picker -> start -> tab -> stop）。
   - `grep` 验证 history.json 无 secret 形状（如 `sk-`、`token=`）。

## 5. 验收（S3.2 局部）

- [ ] 显式 CSP 生效（dev 不破 HMR/终端/样式）。
- [ ] opener 插件/权限移除（无调用面）。
- [ ] 所有破坏性操作（stop/remove/force-remove）有确认，取消不执行。
- [ ] security-checklist 逐项验证：history 无 secret/scrollback、粘贴 1MB cap、workspace 只读预检。
- [ ] `cargo test` + `npm run build` 零错误；67 测试不回归。
