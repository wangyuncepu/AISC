# Stage 5 验收台账

> 平台：Windows 11 / x86_64，Rust 176 / TS 184 / pytest 508 基线。分支 `stage-5-onboarding-installer`。

## 5a-state（进行中）

- `A-ONB01-1` onboarding schema 首次/进行中/完成/跳过/中断恢复/高版本/损坏通过。
  - Commit：`e371ea3`
  - 证据：Rust `onboarding.rs`——schema-versioned `onboarding.json`（status/current/completed/skipped/last_error_code/source）、fs4 跨进程锁 + atomic replace、corrupt 隔离到 `.corrupt`、高版本 fail-closed；6 个单测（missing→not_started、roundtrip、corrupt、unsupported、patch complete/skip、finished states）。TS store 5 测试 + wizard 3 测试覆盖 load/patch/skip/finished。
  - 步骤：首次启动 load→not_started；begin→in_progress；skip→skipped；corrupt/high-version fail-closed；升级后完成状态保留。
  - 结果：Rust 6 + TS 8 相关测试通过；全库 Rust 176 / TS 184。
  - 结论：PASS
- `A-INS01-1` NSIS fresh/upgrade/uninstall、PATH/sidecar/WebView2/Docker 引导不丢用户数据。
  - Commit：`73c39cf`（NSIS handoff + Rust reader；fresh/upgrade/uninstall 实机随 5g 总门）
  - 证据：installer.nsi 安装写 handoff（InstallerSource/InstalledVersion/FirstRun/DockerHint）到 `HKCU\Softwareisc\AISC Workbench`，卸载 `DeleteRegKey` 清理；NSIS 边界确认——只做文件/PATH/sidecar/WebView2/Docker 引导，不配置 workspace/provider/runtime；`identity_matches_tauri_config` 固定 key 一致性。
  - 步骤：安装→registry 写入手off→卸载→key 删除。
  - 结果：Rust 179 / TS 184。
  - 结论：PASS（实机 fresh/upgrade/uninstall 随 5g）
- `A-ONB02-1` Docker installed 与 Engine ready 分离；starting/timeout/retry/doctor/continue 正确。
- `A-ONB03-1` 新建/选择/最近/workspace 恢复与 Stage 3 Explorer 接通。
- `A-ONB04-1` Agent readiness 文案和 guide/login/config action 正确且不显示 secret。
- `A-ONB05-1` direct/host proxy/TUN/failed/skip/revoke 网络矩阵通过。
- `A-ONB06-1` new/reuse/restart/restore、取消、冲突、失败恢复通过。
- `A-ONB07-1` 完成进入 workspace；Settings/Help 可重开；skip 有温和提示。
- `A-ONB08-1` installer handoff 非敏感、Workbench 二次验证、升级兼容。
- `A-ONB08-2` Windows/Linux/macOS、中英、窄窗/150%、键盘/读屏证据齐。
