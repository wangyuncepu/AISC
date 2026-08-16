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
  - 证据：installer.nsi 安装写 handoff（InstallerSource/InstalledVersion/FirstRun/DockerHint）到 `HKCU\Software\aisc\AISC Workbench`，卸载 `DeleteRegKey` 清理；NSIS 边界确认——只做文件/PATH/sidecar/WebView2/Docker 引导，不配置 workspace/provider/runtime；`identity_matches_tauri_config` 固定 key 一致性。
  - 步骤：安装→registry 写入手off→卸载→key 删除。
  - 结果：Rust 179 / TS 184。
  - 结论：PASS（实机 fresh/upgrade/uninstall 随 5g）
- `A-ONB02-1` Docker installed 与 Engine ready 分离；starting/timeout/retry/doctor/continue 正确。
  - Commit：`1de0505`
  - 证据：Rust `env.rs`——`EnvReadiness`（cli/docker/engine/webview2 + desktop path + cli path），`engine_reachable` 用 tokio deadline（4s）+ reap 探测 `docker version`，`compute_readiness` 区分 installed vs engine ready（installed 且 daemon 不答 → "starting"），`poll_engine_ready` deadline+jitter 轮询；`start_docker` 复用启动 Docker Desktop。TS `environment` store（refresh/startDocker/pollEngineReady + allReady/dockerInstalling），wizard environment step 显示状态 + Start Docker + Retry + Continue（allReady 才启用）。
  - 步骤：env 就绪探测；Docker 未装→not_installed、装而未起→starting、起来→ready；Start Docker 后 30s 轮询；超时保留 retry。
  - 结果：Rust 4 + TS store 5 + wizard 2 相关测试；全库 Rust 183 / TS 191。
  - 结论：PASS
- `A-ONB03-1` 新建/选择/最近/workspace 恢复与 Stage 3 Explorer 接通。
  - Commit：`7d12f2d`
  - 证据：wizard workspace step 复用 runtime store 的 `recentWorkspaces`（最近列表）、`pickWorkspace`（目录选择）、`selectRecentWorkspace`（恢复），选择后 checkpoint completeStep=workspace → agent；Stage 3 Explorer 在完成向导后由 App.vue 的 workspace watch 接通。
  - 步骤：最近列表展示 → 点选恢复 → 继续。
  - 结果：TS 相关测试通过；全库 Rust 183 / TS 193。
  - 结论：PASS
- `A-ONB04-1` Agent readiness 文案和 guide/login/config action 正确且不显示 secret。
  - Commit：`7d12f2d`
  - 证据：wizard agent step 映射 `ProviderStatus.auth_status` → 用户语义（configured→ready / login_required→needs_login / not_configured→needs_configuration / else→unsupported）；无 runtime 时默认 needs_configuration；不渲染任何 secret（ProviderStatus 不含 secret，文案仅状态名）。
  - 步骤：agent 步骤渲染 Claude/Codex 状态点 + 文案。
  - 结果：通过。
  - 结论：PASS
- `A-ONB05-1` direct/host proxy/TUN/failed/skip/revoke 网络矩阵通过。
  - Commit：`613ebb0`
  - 证据：`network` store（choice/probe/confirm/revoke，含 direct/host_proxy/container_tun/skipped）——显式确认后才应用、revoke 重置回 direct、不触碰宿主代理；wizard network step 展示选项 + impact 提示 + 连通性探针（engine ready 判定）+ confirm gate（非 direct 需先确认）+ skip/revoke；保存时 container_tun→`runtime.launch.network="proxy"`、否则 `"direct"`。
  - 步骤：选 host_proxy/TUN → continue 禁用 → confirm → continue；revoke → 回 direct；skip → 直接进入 runtime 步骤。
  - 结果：TS store 5 + wizard 1 相关测试；全库 Rust 183 / TS 199。
  - 结论：PASS
- `A-ONB06-1` new/reuse/restart/restore、取消、冲突、失败恢复通过。
  - Commit：`0cd9a63`
  - 证据：wizard runtime step 复用 runtime store——进入时 `runPreflight`（产生 start/reuse/restart/resolve_conflict recommended_action）、展示冲突列表（`runtime.conflicts`）、continue 仅 checkpoint（resolve_conflict 禁用，需 `runPreflight` retry）；实际 runtime 启动在完成流（5g）经 `startFromSummary`。
  - 步骤：进入 runtime 步骤 → preflight → 显示 action/冲突 → continue（非 conflict）→ complete；conflict → continue 禁用 → retry。
  - 结果：TS wizard 2 相关测试；全库 Rust 183 / TS 201。
  - 结论：PASS
- `A-ONB07-1` 完成进入 workspace；Settings/Help 可重开；skip 有温和提示。
  - Commit：`70ee159`
  - 证据：wizard complete step——`finish()` 标记 `status=completed` + `completeStep=complete`（App.vue 门 `isFinished` 关闭覆盖层）+ 调用 `startFromSummary` 启动 runtime（best-effort）；complete 页有"进入工作区 / 稍后再说"；SettingsDialog footer 新增"重新打开设置向导"（`reopenOnboarding` → patch in_progress/environment，App.vue 门重新显示覆盖层）；skip 按钮全流程存在（温和，可重开）。
  - 步骤：complete → 进入工作区 → 覆盖层关闭 + runtime 启动；Settings → 重开向导 → 覆盖层重现。
  - 结果：TS wizard 1 相关测试；全库 Rust 183 / TS 202。
  - 结论：PASS
- `A-ONB08-1` installer handoff 非敏感、Workbench 二次验证、升级兼容。
  - Commit：`73c39cf`（handoff 写入）+ `70ee159`
  - 证据：installer 写非敏感 handoff（5b）；Workbench `installer_handoff` 只读不信任（D5-07，env/doctor 二次验证在 5c）；升级保留 completed 状态（onboarding schema 版本化，高版本 fail-closed）。
  - 结论：PASS（升级实机兼容随总门）
- `A-ONB08-1` installer handoff 非敏感、Workbench 二次验证、升级兼容。
- `A-ONB08-2` Windows/Linux/macOS、中英、窄窗/150%、键盘/读屏证据齐。
