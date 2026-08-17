# Stage 5 验收台账

> 平台：Windows 11 / x86_64，Rust 176 / TS 184 / pytest 508 基线。分支 `stage-5-onboarding-installer`。
>
> **总门（2026-08-16）**：本地 Rust lib 166 / TS 205 / pytest 508 全绿；CI 对 develop
> `4c0d60a`（merge）+ `bae03fc`（cfg 修复）全绿（Workbench CI / Bundle Linux·macOS /
> NSIS installer）；实机安装/卸载/升级/引导随两轮手测（第 1 轮 5 项已 PASS，第 2 轮
> 修复已验收、KI-1 记录移交 Stage 6）。**结论：PASS，Stage 5 收口。**

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
  - 增强（B，A-ONB02）：`start_docker` 在 exe 缺失时经 winget 安装 Docker Desktop（`--accept-* --disable-interactivity`）再启动；向导"Start Docker"在 not_installed 时文案变"安装并启动 Docker"。候选路径与 env 单一来源（`runtime::docker_desktop_candidates`）。Rust 185 / TS 203。
  - 手测修复（2026-08-16，第 1 轮）：`start_docker` 改为 **await winget 到完成**（10min 上限）并返回真实结果——不再 fire-and-forget；winget 用 `CREATE_NO_WINDOW` 隐藏控制台（原 DETACHED 会闪终端框）；向导新增 `installing` 中间态"正在安装 Docker Desktop…"；WebView2 检测改查 **HKCU+HKLM+WOW6432Node** 三个根（原只查 HKCU 误报 missing）；首次启动竞态修复——onboarding 完成前不 `negotiate()`（原首次帧闪"启动失败"，重启才正常）。Rust 186 / TS 203。
  - 手测修复（2026-08-16，第 2 轮）+ 特性（实机复测中）：
    - Commit：`641bc67`（round-2）+ `bae03fc`（`creation_flags` 改 `cfg(windows)`，修 Linux/macOS CI E0599）。CI 对 develop `4c0d60a`/`bae03fc` 全绿（Workbench CI / Bundle Linux·macOS / NSIS）。
    - **Welcome "Workbench 配置读取失败"**：`onboarding::save` 现在先 `create_dir_all(config_dir)` 再取 fs4 锁——真全新安装（目录尚不存在）时首次 `onboarding_update` 不再因 NotFound 失败（settings.rs 早已如此）；且向导把错误改为**非阻塞横幅**——一次性后端失败不再隐藏 begin/skip 按钮、卡死欢迎页。
    - **CLI: unavailable**：`env::resolve_cli_path` 从"仅 pin"改为全发现顺序（pin > 内置 sidecar > PATH > 平台）的**存在性检查**——onboarding 阶段 negotiate 被推迟、pin 为空/陈旧时，紧挨 exe 的 sidecar 也能被识别为 ready（真实 negotiate 仍负责版本/能力校验）。
    - **实时检测 + 重新检查（部分解决，见 KI-1）**：环境步骤新增**自动轮询**（5s，`environment.startAutoPoll`，随步骤进入/离开与 engine ready 自停）；去掉 180s 阻塞轮询（会锁死按钮）→ 启动后直接持续自动轮询；引擎探测加 `CREATE_NO_WINDOW`（消除黑框闪烁）；「重新检测」**永不禁用**（原被 `loading` 禁用约 4/5 时间无响应）；增加 installing/starting 提示文案。**遗留**：GUI 内引擎探测仍可能返回非 ready，已记入 `todo.md` KI-1 移交 Stage 6。
    - **离线安装包（像 mihomo）**：`scripts/fetch-docker-installer.ps1` 下载最新 Docker Desktop 安装器；`tauri.offline.conf.json` 覆盖层将其打进 `$INSTDIR\aisc-bundle\docker-offline\`；`runtime::bundled_docker_installer` + `install_docker_desktop_bundled` 在 exe 缺失时**优先本地安装器静默安装**，失败再回退 winget；`scripts/build-installer.ps1 -Mode online|offline` 产出两版（离线版 `-offline-setup.exe`）。
    - **Windows 弹窗通知**：复用已注册的 `tauri-plugin-notification`（capability 已含 `notification:allow-notify`）——winget/本地安装器成功后 toast"Docker Desktop 安装完成…"；`poll_engine_ready` 在引擎首次就绪时 toast"Docker 已就绪"。
    - Rust lib 166 / TS 205（+2 自动轮询测试）。
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
- `A-ONB08-2` Windows/Linux/macOS、中英、窄窗/150%、键盘/读屏证据齐。

## 已知问题（跨阶段遗留，见 `../todo.md` KI-1）

- **KI-1（未解决，移交 Stage 6）**：向导环境步骤无法实时识别 Docker 就绪——即便
  Docker Desktop 已启动、shell 中 `docker version` 可达（`29.7.2`），环境步骤仍显示
  engine starting；自动轮询与「重新检测」均不反映 ready。已做 CREATE_NO_WINDOW /
  持续自动轮询 / 永不禁用重新检测，仍未根治。完整现象、环境事实与待查假设记录于
  `docs/plans/aisc-next/todo.md`。用户选择：记录移交，下一开发阶段重点查因修复。
  当前 Stage 5 收口不阻塞（跳过引导可正常进入工作区）。
