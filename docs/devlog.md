# AISC — 开发日志

> 记录规则：版本按发布时间从新到旧排列。版本内只记录已经进入对应标签或当前发布提交的内容；计划、未提交实验和后续修复不提前归入旧版本。

# v2.1.9-dev (2026-08-20 ~) — 四挂账清偿 · nairong 根因链 · 构建韧性 · 优化批次（分支 develop）

> 规划入口：`docs/plans/2.1.9-dev-plans/`（README 阶段表 + decisions.md D-1..D-11 +
> opt-batch-spec.md + f1-f2-design.md）。VERSION 冻结前保持 2.1.8.dev0。

- **T1-T6（四挂账统一清偿）**：#53 隔离测试钉第二 tempdir；#50 ble.sh 移除（vendor +
  门控 + D-1 修订）；#3 归因全量修复（R1 容器登记桥 / R2 env 兜底 / R3 呈现层按 D-6
  降级）；#28 VM 闪烁主攻（fit 遥测 + 振荡自诊断浮层 + sticky cell 冷却）；T5 全矩阵
  回归收口；T6 变更页朴素化（归因呈现降级，D-6）。
- **nairong #61 三轮根因链（hotfix）**：bash 零输出退出 → HOTFIX1（fit 方向，证伪回滚）
  → HOTFIX2（传输异常捕获 + stderr 可见性——本轮回溯发现了真凶）→ HOTFIX3 **根因**：
  zh-CN 下 docker-py `from_env()` 读 docker context `meta.json` 不带 encoding → GBK
  UnicodeDecodeError → sidecar 崩溃 exit 1 零输出。三层修复：`docker.from_env` 安全
  工厂（任意异常回退 npipe 默认端点，docker_.py + docker_gateway.py 双侧）、pty.rs
  stderr 改 piped 并作为 Output 事件入流（真实 TTY 交错语义）、session 生命周期落
  时间线（session_exit info/error）。`lib.rs` `ensure_sidecar_utf8()`（PYTHONUTF8=1）
  进程级兜底。用户 VM 中文用户名路径复现 PASS 确认（2026-09-01 前）。
- **T7（D-8）**：zsh 换默认 shell 后 help 教学引导缺失 → aisc-zshrc §7 help() 以
  `__AISC_TUTORIAL_EOF__` heredoc 逐字节复刻 tutorial.py `_TUTORIAL`（SSOT 防漂移测试
  三连：zshrc help 存在 / heredoc==_TUTORIAL / bash env 回退）。
- **T8（D-9）构建网络韧性硬化**：Dockerfile 全动作审查出 CN 网络五个无兜底点。修复：
  apt 重试×3 循环、pip 清华源兜底、npm 三坑落地（`npm i -g file.tgz` 同名平台包冲突 /
  `npm cache add`+`--offline`=ENOTCACHED 无 packument / 终局=file: manifest + alias key
  装进 /opt/aisc/npm + symlink——**离线重装实证通过**）、yazi 预设经 ghproxy 链、
  geodata 下载清理；宿主侧 `stage-npm.sh`（PY 探针绕 WindowsApps stub、多架构、
  `npm:` alias spec 解析、skip-if-current）+ `_ensure_base_image` 镜像链预拉
  （本地命中跳过 → 三镜像链 600s → tag 本地名，失败给 registry-mirrors 三段指引）。
  中毒链演练 + 离线全量重装验证。CI Windows Docker 冷启动竞态 → 就绪门（30×10s，
  `b4dd1e8` 后四 lane 稳定绿）。
- **F1/F2 设计定稿（D-10，未实施）**：F2 宿主工具 MCP（streamable-http + 白名单 +
  只读筛，streamable-http 是 Rust 侧第一个本地监听服务；P0 通道 PoC 待实测）先于
  F1 SSH 双向同步（mutagen，影子目录=真工作区→身份链 11 触点零改动）。裁决表 +
  安全模型 + 待决问题五项全档 `f1-f2-design.md`。用户裁定：**优化批次优先于新功能**。
- **优化批次规格冻结（D-11）**：三路只读探针（前端流/渲染/分屏 · provider 链/daemon ·
  性能旋钮/缓存/冷启动）+ 用户五条报障 + 五点裁决 → `opt-batch-spec.md` O1-O9 合并
  规格 + §G 八条实施红线。关键实证：分屏 × 与滚动条 z11 同 stacking context 6px 重叠带、
  渲染路径零遥测、外层 30s < 内层串行舞步可超 30s、daemon 无 watchdog 被 OOM 即静默躺平、
  build cache 6.7GB 无 UI 入口、冷启动 70s 中全量复制占 29s。
- **O1（`ee62b07`）分屏 × z 序修复**：`.pane-close` right 4→18px 让出 xterm 滚动条带 +
  z 2→--z-overlay(20) 恒可点；截断角标 right 10→48px 错位。几何契约钉进
  paneCloseHit.test.ts（源码契约扫描 + 真挂载点击双范式——jsdom 无布局，几何断言沿
  tokens.test.ts 源码扫描范式）。
- **O3（`e664208`）渲染路径三态遥测**：mountWebgl 成功/构造失败/context-loss 经 store
  choke point `logRendererEvent` 落共享时间线（组件不直接 import logUiEvent，沿
  logTerminalResizeError 层契约）；事件带 WEBGL_debug_renderer_info 摘要 + 软渲染判定
  （SwiftShader/llvmpipe 低配信号）；fit 遥测行补 renderer 字段。
- **O9（`7fd6111`）取消懒布局**：用户直接下令。重开工作区全量恢复——initTabs 删 lazy
  分支 + wakeDormantTab、activateTab 删唤醒路径、TabSessionState 删 "dormant" 枚举、
  TabBar/i18n 双语同步收缩；layoutLazyRestore.test.ts 改写 layoutRestore.test.ts
  （全量恢复语义：每 tab 立即开 session、重激活不双开）。
- **O2（`8ca2423`）输出截断 → 磁盘 spool**：用户裁决"难道就非截断不可吗"的终局答案。
  Rust：PtyEvent::Output 带全局 raw offset（stdout/stderr 双泵共享 SpoolWriter 互斥
  推进）；`<数据根>/sessions/<sid>.spool` 追加写（unix 0600），写失败降级内存-only +
  一次性时间线事件；offset/committed 分离防半写错位回放；新 ipc `session_read_spool`
  （≤2MiB/页）；spool 随 entry 生命周期删除（ack/close/TTL sweep）+ 启动清扫 24h 残留。
  TS：streamBuffer offsets 平行数组（headOffset 锚点）；常驻截断角标改"加载更早"按钮
  （活会话限定）——clear + spool 段 64KiB 分块 + 窗口全量重放，consumed 重置到 cursor
  活流无缝续接；eof/失败禁用。三不变式（streamCursor 单调/每帧单响应式替换/服务端阻塞
  背压）全保持。**顺手修存量 bug**：session.rs `snapshot_serializes_camel_case` 缺
  闭合 `}` 致其后 5 个测试被吞成嵌套函数从未运行（复活首跑即暴露
  shutdown_request 的 JSON 转义存量错，一并修复）。
- **本地门（每项独立 commit 前）**：vitest 422 / vue-tsc 干净 / cargo 262+25 集成 /
  pytest 全量绿。O5-O8 待实施；外部证据待收：8G 笔记本 doctor 导出（O5）、长对话
  恢复复现样本（独立 bug）。
- **手测反馈批次（`1775fe2`，2026-09-02 八条反馈）**：O1（×可点 + Ctrl+Shift+W）、
  O3（renderer_mount 33 次落时间线，Intel Arc D3D11 硬渲）手测 PASS；三项行为修正：
  **O9 r2**（用户裁决升级——重开工作区不恢复布局，恒全新默认单 bash tab，r1 全量
  恢复被否）；**#4** 新建 agent 分屏"加载动画"感 = B-05 首帧 resize veil（全新 term
  无 stale grid 可盖 → 删首帧 veil，re-show 保留）；**#5c** narrowTui 去 bash 豁免
  （bash 内嵌 claude/codex TUI 同样乱码，<60 列一律 overlay）。诊断定性三条：#5b
  "分屏后长间隔自动重绘"= claude 自身 TUI 空闲点重绘（上游行为）；#6"反复输出"
  图中为 Claude Code 后台 agent 正常进度块（各仅一次）；日志实证 O6 铁证——
  aisc.log 单文件 `cli_exit` 555 / `op` 540（轮询链海量 spawn）。待用户裁决：
  #5a bash 内唤起 agent 的 scrollback 混看（语义/产品题）、#8 变更页"⇄ 移动"
  类型标签去留。
- **两项用户裁决落地（`49dc539`）**：**#8 误报根治**（用户指认该文件实为 claude
  新生成）——agent 原子写 = 写临时文件 → rename 成正式名，notify 的 From(temp)
  半边被 is_temp_file 过滤吞掉、孤儿 To 被判 renamed → 新文件误标"⇄ 移动"；
  TempRenameTracker 让 1s 窗内配对的 To 判 created（真 mv 语义不变，watcher
  +3 单测）。**#5a 滚动回看指示器**（裁决：不唤起清屏）——视口位于活尾部之上
  时左上角 chip"已上滚 N 行（正在查看历史输出）"+ 一键回到底部，挂
  .xterm-viewport 原生 scroll 事件。本地门：vitest 421 / vue-tsc / cargo 265。

# Stage 7 (2026-08-17) — Windows Data Root（AISC Next Follow-up，分支 stage-7-windows-data-root）

> 规划入口：`docs/plans/aisc-next-followup/stage-7-windows-data-root/`。把初始化/运行产生的配置、状态、runtime、日志、缓存、artifact、诊断和迁移文件统一收纳到 `%LOCALAPPDATA%\AISC\data`，workspace 只留用户文件；提供旧布局迁移。证据台账：`stage-7-windows-data-root/acceptance.md`。
> **总门 PASS（2026-08-17）**：A-DATA01..05 真机全过 + 用户 Workbench 手测确认。

- **7a contract**：`aisc.data-root/v1` 纯域契约 + 只读 `DataRootResolver`（Python SSOT
  `src/aisc/{domain,application}/data_root.py`，Rust mirror `workbench/src-tauri/src/data_root.rs`）：
  平台默认根（Win `%LOCALAPPDATA%\AISC\data`，跨平台 XDG）、`AISC_DATA_ROOT` override
  校验（绝对路径/无空白/与 workspace 双向不重叠，fail closed）、reparse segment 拒绝、
  `sha256-v1` 全量 workspace hash（目录名冒号→连字符，Windows 合法）、契约布局目录映射；
  Python/Rust 共享向量 fixture `tests/fixtures/data-root/hash-vectors.json`（CJK/emoji/UNC）。
  未接线——现行为不变（接线在 7e）。本地门：pytest 17+8 subtests / cargo data_root 8 /
  全量 572 OK + 181+7×3。
- **7b storage**：`adapters/data_root_store.py` 统一存储 API：幂等 `prepare` 契约骨架、
  跨进程 fail-closed `file_lock`（msvcrt/fcntl，error_code 可参数化以便 7e 保留
  STATE_LOCK_TIMEOUT 语义）、rel 路径校验（artifacts validator）、原子 UTF-8 写
  （同目录 temp + fsync + replace）、损坏隔离 `*.corrupt`、写前 reparse 链复检（TOCTOU
  防御）；稳定错误码下沉 domain。未改现有 writer（7e）。本地门：store 12 passed
  （含子进程持锁超时用例）/ 全量 584 OK。
- **7c legacy-scan**：`domain/data_migration.py`（known-owned allowlist + 瞬态集 +
  目标映射 + `aisc.data-migration/v1` manifest，from_dict 对错误
  schema/version/state/classification fail closed）+ `application/legacy_scan.py`
  只读 walker：owned/unknown 计算 sha256、冲突按 hash 比较（同字节仍 owned、异字节
  conflict）、无 AISC 初始化标记的同名目录判 foreign（只报告不迁移）、symlink/junction
  不穿透、AF_UNIX socket（reparse tag）计瞬态。真实 workspace 实扫 **3127 owned /
  8 transient / 0 unknown / 0 conflict**，实扫反哺 allowlist（补
  `.claude/{.claude.json,.factory-version}` 与 daemon.sock 处理）。执行/回滚在 7d。
  本地门：legacy 11 passed + 18 subtests / 全量 595 OK。
- **7d migration**：`application/data_migration.py` 两阶段执行器（staging 复制 + SHA-256
  校验 → 同卷原子 `os.replace` 提交；manifest `migrations/<ws>.json` 先落 prepared、
  逐条推进、崩溃可 resume；取消保留可恢复 manifest；全迁移命名空间写只读
  `.aisc-migrated` 重定向标记；rollback 只删 manifest 内且 hash 未变的目标、恢复
  quarantine、清标记；unknown 仅在显式 `--quarantine-unknown` 下 copy→verify→删源）+
  CLI `aisc data-root doctor|migrate --dry-run|--apply|rollback`（冲突/未同意 unknown/
  空间不足/源变更均稳定错误码非零退出）。真实 workspace dry-run：3127 文件/~62MB、
  零冲突零 unknown。本地门：executor 13 + CLI 5 passed / 全量 613 OK。
- **7e wiring**：五步接线——(1) registry/state 适配器改「root=state 目录」，
  `workspace_state_dir` 边界 + legacy 首用收养 + `_resolve_root` 消除 stop/ps 与 run
  的注册表双轨；(2) config workspace 层 canonical 优先 + legacy 回退；(3) artifact
  注册表统一到 `<data-root>/artifacts`（Python/Rust 双侧 legacy 读回退）；
  (4) Workbench `config_dir`→`app_state_dir`（Roaming 收养/回退）+ 诊断包 `dataRoot`；
  (5) 容器 project 态四个 data-root 挂载（entrypoint 挂载优先、旧宿主回退
  `/root/app`），宿主预建目标、fail closed；DATA-01 回归门（挂载 argv + workspace
  零新增）。修测试封闭性：7 模块注入 hermetic data root（此前真实 LOCALAPPDATA 被
  写入）。本地门：全量 620 OK / cargo 183+7×3 / workspaces 污染 0。
- **7f gate（真机）**：A-DATA01..05 全 PASS——fresh workspace 经 CLI+60 并发注册+**真实
  容器跑**（super-claude:latest + 新 entrypoint/wrapper bind-mount + 四 data-root 挂载）
  保持零新增，data root 收全量（claude 2171/codex 479/cc-switch 479+db+daemon 态）；
  用户实际 legacy workspace 副本 3127 文件迁移/幂等/回滚全链路；并发 60 写入零丢失；
  CJK/emoji/空格/359 字符长路径迁移 PASS、junction 拒绝。**根因修复**：镜像内旧
  cc-switch wrapper 硬编码 `HOME=/root/app` 回写 workspace → 改 `/proc/mounts` 挂载
  检测推导 HOME（`586aa24`，含显式 `--apply` flag）。发布前提：release 镜像重建烧入
  新 entrypoint+wrapper。本地全量门：Python 621 / cargo 183+7×3 / vitest 213 /
  vue-tsc 干净。
- **7f 手测期间的三个连环修复**：① 泄漏测试写进真实 `%LOCALAPPDATA%\AISC\data\config`
  的垃圾 onboarding 文件触发 `UnsupportedSchema` 死锁向导 → 无 schema_version 的文件
  按损坏隔离+空态（`5899a8c`）；② `+` 新建 tab 菜单被 tabbar 滚动容器裁剪（Stage 6
  UX-02 回归，非 Stage 7）→ Teleport + zoom 补偿（`aa10cd0`）；③ 镜像重建后仍污染 →
  覆盖桥挂了陈旧 `target/debug/aisc-bundle` 暂存把新镜像降级 → **移除覆盖桥、镜像为
  容器脚本唯一事实源**（`aa7ca34`），并用真实 sidecar 完整流程（start→session→stop）
  对新镜像复验全净。**用户手测 PASS 确认（2026-08-17）**。
- **启动序列**：followup 计划入库（`5ec13bb`）；`aisc-next` 整体归档
  `docs/archive/completed/aisc-next`（`e0af206`）；实测 fresh 初始化 workspace 清单
  （`.aisc/.claude/.codex/.cc-switch/.local`，~3130 文件/~69MB）入 02-domain-contract。

# Stage 6 (2026-08-16) — UI / a11y / 可观测性 / 发布收口（AISC Next，分支 stage-6-ui-release-convergence）

> 规划入口：`docs/plans/aisc-next/stage-6-ui-release-convergence/`。在新增工作流稳定后统一
> 视觉/响应式/a11y/诊断并完成跨阶段发布门。证据台账：`stage-6-ui-release-convergence/acceptance.md`。
> **此为上一步之后的 aisc-next 七阶段收尾阶段。**

- **6a KI-1 查因**：`engine_reachable` 改经 Docker Desktop 自带 CLI 路径（ProgramFiles/
  LOCALAPPDATA `resources\bin`）解析，回退 PATH；失败返回 redacted `engineDetail`，
  向导就地显示"引擎探测详情"（不再静默 starting）。
- **6b tokens（UX-01）**：`--space-*/--font-*/--radius-*/--shadow-*/--z-*/--duration-*`
  设计 token 集 + 状态色；全组件精确迁移（零视觉变化）；`tokens.test.ts` 门禁。
- **6c responsive（UX-02）**：Compact<640/Standard/Wide>1100 按有效 box 宽度
  （viewport/zoom）；`data-tier` 驱动 compact 规则；TabBar 横向滚动。
- **6d a11y（UX-03）**：`useDialogA11y` focus trap + opener restore；全局
  prefers-reduced-motion + xterm smooth-scroll 归零；右键菜单 Menu/Shift+F10 键盘开启。
- **6e i18n（UX-04/05）**：顶栏 status + sidebar sessionState 裸 enum → i18n 映射；
  CSS zoom rem 迁移 **NO-GO**（D6-09，保留 zoom）。
- **6f observability（REL-01）**：有界 op 耗时环（run_control/env/start_docker 喂入）+
  `op_traces`；`diagnostic_bundle` allowlist 脱敏包（导出前展示清单）；DoctorDialog 最近
  操作 + 导出按钮。
- **6g migration（REL-03）**：settings/onboarding/artifact previous-version fixture
  测试；history v1→v2 已有覆盖；unsupported schema fail-closed。
- **遗留**：KI-1（Docker ready 检测，待用户最终确认探测详情）、KI-2（初始化引导界面需
  重新手测，暂不处理）、ISO-1（离线安装包做 ISO，未实现）——见 `aisc-next/todo.md`。
- **本地门**：pytest 508 / cargo 194 / vitest 213 / vue-tsc 干净；CI 对 `e8cb233`（`--no-ff`
  合并）全绿（Workbench CI / Bundle Linux·macOS / NSIS）。

# Stage 5 (2026-08-16) — Installer 与首次启动引导（AISC Next，分支 stage-5-onboarding-installer）

> 规划入口：`docs/plans/aisc-next/stage-5-onboarding-installer/`。专业、简洁、失败可恢复的首次使用体验：NSIS 安装器 + schema 版本化的 Tauri 首次向导（环境/工作区/Agent/可选网络/Runtime/完成）。证据台账：`stage-5-onboarding-installer/acceptance.md`。

- **5a onboarding state（ONB-01）**：`onboarding.json`（status/current/completed/skipped/last_error_code/source）跨进程锁 + atomic replace；corrupt 隔离、高版本 fail-closed、升级保留完成态。
- **5b NSIS handoff（INS-01）**：安装器只做文件/PATH/sidecar/WebView2/Docker 引导，写非敏感 handoff（`InstallerSource/InstalledVersion/FirstRun/DockerHint`），不配置 workspace/provider/runtime。
- **5c 环境就绪（ONB-02）**：CLI / Docker installed / Engine ready 分离；Docker 缺失时向导一键 winget 安装（await 完成 + 真实错误 + `CREATE_NO_WINDOW`）；WebView2 三根注册表探测；`env_readiness`/`env_poll_engine`。
- **5d workspace/agent（ONB-03/04）**：新建/选择/最近恢复 + Agent readiness 语义映射（不暴露 secret）。
- **5e 网络（ONB-05）**：direct/host proxy/container TUN + 显式确认 + skip/revoke。
- **5f runtime（ONB-06）**：preflight/冲突审查/可恢复。
- **5g 完成 + 重开（ONB-07/08）**：完成进入工作区；Settings 可重开向导；handoff 非事实（Workbench 二次验证）。
- **两轮手测修复**：`3383dbb`（第 1 轮：Docker 安装 UX/WebView2 检测/首启竞态）+ `641bc67`/`bae03fc`（第 2 轮：欢迎页配置读取恢复、CLI 全发现、实时轮询、**离线安装包**（内置 Docker Desktop 安装器，mihomo 式）、**Windows toast**（安装完成/引擎就绪））。
- **遗留 KI-1**：向导环境步骤仍可能无法实时识别 Docker ready（引擎可达却显示 starting）→ 记录 `aisc-next/todo.md`，Stage 6 优先查因（已加探测详情诊断）。
- **本地门**：pytest 508 / vitest 205 / cargo 186 全绿；CI 对 develop `4c0d60a`/`bae03fc` 全绿（Workbench CI / Bundle / NSIS）。

# Stage 4 (2026-08-16) — Python DockerGateway（AISC Next，分支 stage-4-docker-gateway）

> 规划入口：`docs/plans/aisc-next/stage-4-docker-gateway/`。在不改变 Python 控制面所有权的前提下统一 Docker 结果、错误与 backend，逐步减少 subprocess 文本解析。证据台账：`stage-4-docker-gateway/acceptance.md`。

- **4a 契约（DG-01/02）**：`DockerGateway` runtime Protocol + `domain/gateway.py` operation envelope（operation_id/backend/exit_code/duration/stable error/cleanup/timed_out）+ 8 个类型化结果；`DockerExecutor = DockerGateway` 兼容别名（D4-02）；`create_docker_gateway('auto'|'sdk'|'cli')` 工厂。
- **4b/4c query+lifecycle SDK 化（DG-03/07）**：Fake docker-py client（recording + fault injection）驱动 `SdkGateway` 的 preflight/inspect/list/start/stop/remove/wait；`wait_container` 修复 `requests.ReadTimeout`（非 `DockerException`）逃逸 → 稳定 `DOCKER_ERR_TIMEOUT`；remove 已不存在容器幂等。
- **4d interactive（DG-04）**：`open_interactive` 从委托改为自持完整 SDK 生命周期（exec_create→start→AISC_RESIZE_FILE 初始+轮询 resize→原始流→inspect→join 收尾），无资源泄漏。
- **4e Build 基准 + NO-GO（DG-05）**：`scripts/bench/build-bench.py` 真实 daemon 离线基准——CLI p50 578/p95 1192/max 1260 vs SDK p50 92/p95 1844/max 2039；SDK 中位数优势来自缓存层复用、尾部更差 → **Build 保持 CLI backend**（决策文档 `build-benchmark-decision.md`）。
- **4f release gates（DG-06/08）**：auto/sdk/cli flag 可回滚、application 不感知 backend（backend 仅存诊断 envelope）；全库回归 508 passed；D4-08 未满足（无三平台实机 + 未删除重复实现）前保留 CLI backend，30 处 `RealDockerExecutor` 调用点零改动。
- **本地门**：pytest 508 / vitest 176 / cargo 170 全绿；CI 对 `989f297`（`--no-ff` 合并）全绿（Workbench CI / Bundle / NSIS / cli-sidecar）。

# Stage 3 (2026-08-15 ~ 2026-08-16) — Workspace Explorer 与 Agent Artifact（AISC Next，分支 stage-3-workspace-artifacts）

> 规划入口：`docs/plans/aisc-next/stage-3-workspace-artifacts/`。让用户能浏览当前工作区，并可靠发现、打开、Reveal、复制 Agent 交付物路径。证据台账：`stage-3-workspace-artifacts/acceptance.md`。

- **3a `aisc.artifact/v1`（ART-01/02）**：Python domain schema + `aisc artifact record/list/inspect/clear-session`；session-scoped JSONL registry 在宿主数据目录（`%LOCALAPPDATA%/aisc/artifacts`），不污染 workspace（A-ART04）；relative/create/modify/delete/rename/missing/duplicate 矩阵。
- **3b Rust 索引与 containment（ART-05/06）**：`artifact.rs` versioned index（revision/lock/atomic replace/corrupt isolation）、`workspace.rs` canonical containment（symlink/junction/UNC/case 越界拒绝）、preview budget 与 secret redaction；IPC `workspace_list/open/preview/reveal/copy`。
- **3c lazy 树 + Artifact 面板（WX-01/02/04）**：懒加载树（分页 200、dirs-first、ignore 默认集）、文件动作、Artifacts 面板按 Deliverable/Source change/Generated/Unattributed 分组。
- **3d watcher（WX-03）**：notify 递归 watch + debounce/coalesce/overflow→bounded rescan；只报告 unattributed 投影，不伪造 Agent provenance。
- **3e Artifact Skill（ART-03）**：内置 Skill 约束分类、登记、最终人类可读清单；明确"不是事实数据库"；Agent 只提交 workspace-relative path。
- **3f 键盘/APG（WX-05）**：递归可见树 + Arrow/Home/End/Enter/Space/Shift+F10 roving 键盘。
- **手测修复轮**：
  - `c390b1a` watcher 噪音忽略（任意层级 node_modules/target）、实时树、文件夹右键、初始化竞态、Skill 相对路径。
  - `dce222a` overlay drawer（不挤压终端）、artifact_refresh 修复（面板长期为空）、分页计算修正、watcher 携带 kind、容器绝对路径归一化、Tauri 剪贴板右键。
  - `8b4c9f1` **右键菜单在 `ui.font_scale≠1`（CSS zoom）下移出视口的根因修复**（除以 live .app zoom）；`.claude/.codex/.cc-switch/.local/tmp` 默认排除 + `ui.explorer_ignore` 设置贯穿 Rust listing/watcher/前端；临时文件（`foo.tmp.1234`/`file~`/`.swp` 等）三层过滤；空目录不进产物面板；同名 basename（created+modified / 不同路径 / manifest×unattributed）显示相对路径；产物行去按钮（单击预览/双击打开/右键菜单）。
- **本地门**：pytest 463 / vitest 176 / cargo 170 全绿；Windows 实机手测 PASS（右键/排除/临时文件/同名路径）。
- **注意**：容器内不安装 `aisc`（拒绝嵌套）；容器侧靠 watcher 的 unattributed 投影兜底，manifest 事实来源是宿主侧 `aisc artifact record`。

# Stage 1 (2026-08-14) — Frontend Data Plane（AISC Next，分支 stage-1-frontend-data-plane）

> 规划入口：`docs/plans/aisc-next/stage-1-frontend-data-plane/`。将前端从单体协调器拆为可测投影，建立有界高频终端数据面。

- **S1.1 分层（F-01）**：`domain/__tests__/layerContract` 依赖边界契约（组件禁引 runtime/provider/docker/history/settings IPC）；App.vue 收紧为按名 import。
- **S1.2 PTY 数据面（F-02）**：pty spawn 失败返回结构化错误且无 child 泄漏；writer 通道硬上限 bounded（cargo lib 114）。
- **S1.3 输出批处理（F-03）**：`domain/streamBuffer`（appendWithBudget，4 MiB/4096 chunk 预算，截断终态）+ 非响应式 pending 队列 + rAF 批量 flush（单次数组替换）；Terminal 显示“输出已截断”提示。
- **S1.4 生命周期（F-04）**：openPane channel 事件按 sessionId 归属校验，reopen 后旧 channel 迟到事件丢弃。
- **S1.5 状态投影（F-05）**：runtimeFreshness 测试（迟到低 seq 丢弃、stale 保留快照、fresh 恢复）。
- **S1.6 a11y（F-06）**：TabBar 嵌套 button 修复（tab 容器 + 单一 role=tab 激活按钮 + 独立关闭/重开按钮）+ 3 结构测试。
- **S1.7 基准（F-07）**：10 MiB 输出 fixture 吞吐（本机 8ms < 2s 硬门）、字节/chunk 预算、逐字节计数完整。
- **S1.8 harness（F-08）**：Fake Channel 驱动 store 的 channel→pending→rAF→paneStreams 链路 + sessionId guard（runtimeStream）。
- **本地门**：vitest 148 / pytest 428 / cargo lib 114 全绿。ConPTY/soak 手测与 CI 实跑待用户（B-A10/B-A11/B-A12）。

# Stage 0 (2026-08-14) — Baseline Gates（AISC Next，分支 stage-0-baseline-gates）

> 规划入口：`docs/plans/aisc-next/`。本阶段固定可重复基线、契约 fixture、CI 触发、资源预算和 redaction 门禁，不交付终端新功能。

- **S0.1 基线清单（B-01）**：`scripts/baseline/`（probe/manifest/run_baseline）——确定性 BaselineManifest（仅 `generated_at` 可变）、fixture SHA-256、`--strict` fail-closed 不覆盖上次 PASS；`tests/test_baseline.py` 10 通过。Windows 11 手测 `complete`（python/node/npm/rustc/cargo/docker/git 全绿）；WSL fail-closed 验证（缺关键工具 exit 1、无 latest.json）。
- **S0.2 契约 fixture（B-02）**：`tests/fixtures/cli/` 7 个 `aisc.cli/v1` 共享 fixture（envelope 正例/错误/JSONL/unknown/unsupported/错误码清单），Python(9)/Rust(7)/TS(6) 三端消费同一文件。
- **S0.3 CI 门禁（B-03）**：workbench-ci cli job 增加 Unix baseline `--strict` + artifact 上传；path filters 覆盖 `scripts/baseline`、`tests/fixtures`、契约测试；`test_workflow_contract.py` 9 通过。
- **S0.4 资源基线（B-04）**：`scripts/soak/soak.py`（p50/p95/max + hard deadline，可注入 runner）与 8 个测试；Rust `read_capped` truncation + 控制面预算冻结（stdout 8MB / stderr 64KB）。
- **S0.5 redaction（B-05）**：`tests/fixtures/redaction/denylist.txt` denylist 矩阵（Rust 不泄漏 + marker 存在）；redact 新增 `Bearer <jwt>` OAuth 形状；Python 冒烟断言 CLI 输出无 secret。
- **本地门**：pytest 428 / vitest 128 / cargo lib 112 全绿。CI 实跑与 merge 待用户确认（B-A11/B-A12）。

# v2.1.5-dev (2026-08-09 ~ 2026-08-10) — GUI Fine-Tune：G-01..G-18 全部完成

> **阶段总结（2026-08-09 ~ 2026-08-10）**：GUI Fine-Tune 18 个目标（G-01..G-18）全部完成并合并回 develop。覆盖：契约/测试基础设施（A-INFRA）、sidecar 入 PATH、停止/关闭/退出性能、typed settings、i18n、动态多 tab、终端渲染升级、设置页交付、侧边栏分层 + Provider 引导、Resize 根因修复、窗口记忆、终端基础 + 右键菜单、一键诊断、构建通知、动态标题、托盘、Tab 内分屏、明暗主题。
> 每步均按 06-implementation-plan 拆子步骤 → 验收清单（A-*）→ 自动化 + 手动测试 → 汇报；CI 全绿；已知遗留（分屏键盘导航等）记录于 `docs/todo.md`。

## Step 0 验收清单（契约与测试基础设施 A-INFRA-1..5，分支 step-0-*）

> 规范入口：`docs/archive/completed/gui-fine-tune-planning/`（00-06 + decisions）。Step 0 按 06-implementation-plan §0.1-0.4 执行。

### Step 0 实施（2026-08-09，提交 32811b1/c0f6ede/056194a/f020460/efcfc5e/49ddd2a）

- **Canonical workspace 链（A-INFRA-3）**：`open_session` 在 spawn 前 canonicalize（Rust 唯一生产者），`SessionEntry` 保存 canonical 值，open/terminate argv 均带 `--workspace`；失败映射 `AISC_ERR_WORKSPACE_INVALID`；store 从 `config.workspace` 回写 canonical 值并作为 history key。
- **SessionRegistry 所有权（A-INFRA-2）**：spawn 前 `Reserved` 原子插入、重复 ID 前置拒绝、spawn/注册失败 kill+reap 回滚、并发 close 共享 completion（`plan_close` 单元测试覆盖 Gone/Terminal/Run/Wait）、自然退出幂等 `ack_session_exit`、终端条目 60s TTL + 每 Runtime 32 条上限惰性清扫、`generation` 单调计数。
- **`shutdown_workbench` 协调器（03 §4.3 骨架）**：拒绝新 Session → 并发 bounded close（Reserved/Running/Closing 全接管）→ force-reap 遗留 → flush settings → `ShutdownReport`；App.vue 仅当 `unreaped_session_ids` 为空才 destroy，否则显示可恢复错误。预算收紧属 Step 2（G-07）。
- **安全原子替换（A-INFRA-5）**：新 `storage::atomic_replace`（tmp+fsync+`target→backup`→`tmp→target`→失败恢复 backup，禁 delete-first），settings/history 共用；history 四层（root/workspace/layout/tab）serde-flatten unknown fields round-trip，save 合并时深合并 on-disk unknown 字段与省略字段。
- **前端测试设施（§0.2）**：vitest + @vue/test-utils + jsdom，`npm test`/`test:watch`；新纯模块 `tabLayout.ts`。
- **逐 TabRecord 恢复（A-INFRA-1）**：`tabsFromRecords` 保留重复 Session type 与顺序 + saved→new tab_id 映射；旧 `.find(agent)` 去重缺陷以 7 条 vitest 固定为回归门。
- **CI（A-INFRA-4）**：新 `workbench-ci.yml`（push/PR：npm ci/build/test + cargo test + pytest）；bundle-linux-macos/nsis-installer 补前端/package path filters；bundle 产物在非 checkout cwd 验证 sidecar 权限/架构/`version --format json`/aisc-bundle 资源；`tests/test_workflow_contract.py` 静态断言 path filters（PyYAML 加入 dev extras）。
- **本地验证（Windows 11 + Docker Desktop 29.6.2 + aisc 2.1.5-dev + super-claude:latest runtime）**：Rust 76 单测 + cli_runner 7（含真实 aisc negotiate）+ pty_supervisor 4（含真实容器内 `aisc session open`，3× 稳定）+ vitest 7 + 契约测试 6 全绿；`npm run build` 通过。
- **测试环境修复**：`pty_supervisor` 模拟终端应答 `ESC[6n` 光标查询（bash/msys sh 启动即查询并阻塞），`SH` 环境变量提供 sh 绝对路径（ConPTY 后端不做 PATH 解析），real-aisc 截止 20s（冷容器 docker exec 延迟）。本地验证需 `PATH` 前置 `/tmp/pyshim`（python3 桩，Store 版 python3 不可用）。
- **手动测试（2026-08-09，Windows 11 + Docker Desktop 29.6.2 + aisc 2.1.5-dev，`npm run tauri dev`）**：启动/negotiate/picker ✅；选工作区 preflight→summary ✅；Start 后会话 opening→running ✅；`echo hello` 回显 ✅；tab 切换回来历史消失 → 修复（xterm 重新显示不重绘，`refresh(0, rows-1)` + 隐藏时跳过 fit）后恢复 ✅；× 关闭会话 → exited ✅；↔ 重开 ✅；关窗确认 → 关闭 ✅；任务管理器无 aisc/python/docker exec 残留 ✅（Docker Desktop 保持运行，符合退出保留 Runtime 语义）；`%APPDATA%\cn.aisc.workbench\` settings.json + history.json 存在 ✅。
- **CI（2026-08-09）**：Workbench CI 三 job 全绿（frontend npm build+vitest 7/7 / rust cargo test / cli pytest 427 过 1 修复）；Bundle Linux/macOS 全绿（含非 checkout cwd sidecar 权限/架构/version/resource 验证）；NSIS installer 全绿；cli-sidecar 全绿。修复项：vitest 4.1 forks worker 在 Node 20 失败 → CI 用 Node 22；rust job 补 GTK/webkit 系统依赖；tauri-build 需 externalBin/resource 存在 → 测试 job stage 占位；`docs/releases/v2.1.5-dev.md` 缺失 → 补发布说明。
- **Step 0 结论**：A-INFRA-1..5 门禁证据齐（A-INFRA-2 的 100× reopen 集成测试随 Step 2 registry 预算重构补齐，已确认）。

## Step 1 验收清单（G-18 sidecar 入用户 PATH，分支 step-1-g18-path）

> 规范：05-cli-gui-contract.md §五（PATH 安全算法）、06 §二；门禁 A-G18-1..4。

- [ ] **1a-1** PATH helper：目录项规范化（trim/去引号/尾斜杠/大小写）、冲突探测（展开 %VAR% 后查 `\aisc.exe`，跳过空项/UNC）、`WM_SETTINGCHANGE("Environment")` 广播。
- [ ] **1a-2** 安装：只改 `HKCU\Environment\Path` 单目录项；`$INSTDIR` 已存在不重复追加；marker `PathEntryOwned=1` + `PathEntry="$INSTDIR"`；首个命中非 `$INSTDIR` 时不覆盖不追加（交互提示/静默日志）；安装目录变化且旧 marker owned 时先移除旧精确项。
- [ ] **1a-3** 卸载：仅当 marker owned 且 marker 路径规范化相等才删除精确项；`/UPDATE` 跳过 ownership 清理；不删其他目录/其他 aisc。
- [ ] **1a-4** 注册表类型：原 REG_EXPAND_SZ 保留；`%VAR%` 不无故展开。
- [ ] **1a-5** 身份：`tauri.conf.json bundle.publisher=aisc`；Rust 常量 MANUFACTURER/PRODUCT_NAME + 一致性测试（解析 tauri.conf.json 与常量断言）。
- [ ] **1b-1** 移除 CheckPython/CheckWinget/PageDepsCheck/Section Dependencies 及 DEP_* 文案；保留 Docker 检测/启动链（finish 页启动 Docker 属宿主集成，保留）。
- [x] **1c-1** nsis-installer.yml smoke：从新 PowerShell 进程经 PATH 执行 `aisc version --format json`；重复安装 entry 恰好一次；卸载后 PATH 逐项相等。（smoke 已重写覆盖冲突/EXPAND_SZ/新进程解析/卸载保留，待 CI 验证）
- [x] **1c-2** 手动测试（Windows 11 实机，2026-08-09）：静默安装 → 新 PowerShell `Get-Command aisc` = `$INSTDIR\aisc.exe` ✅ + `aisc version` exit 0 ✅；重复安装 entry 恰好 1 ✅；类型 ExpandString 保留 ✅；静默卸载 owned entry 精确删除、其它条目不动 ✅。冲突场景（sentinel aisc）由 CI smoke 覆盖。
- [x] 模板 rebase 记录：模板来源 Tauri 2.11.5（tauri-bundler installer.nsi），结构 diff = 默认模板 + G-18 PATH + S4.2 保留逻辑，无其他偏离。
- **实机验证发现并修复 3 个真实 bug**（提交 40678d9）：(1) `CharLowerBuffW(w .r3)` 输出-only 导致输入丢失 → normalize 返回空 → 安装误判"已在 PATH"；(2) `PathRead` 用 System::Call `.r1-.r5` 破坏调用方寄存器 → 卸载 RemovePathEntryExact 比较全失败；(3) 测试方法坑：`cmd /c` 对 GUI 卸载器异步返回，需 `Start-Process -Wait`。附带修复：`\a` 序列经 handlebars 渲染变 bell（调试路径避开）。
- **CI 冒烟抓出并修复 4 个问题**（05ca3b0/983cd6e + smoke 修复 3e37abc/f04164c/056bd2b/988dd4e）：(1) PathNormalizeDir 只保护 $1/$2，CharLowerBuffW 用 $3 破坏扫描循环 → 冲突探测永远不命中（sentinel 场景 INSTDIR 被追加）；(2) smoke 的 `Count-InstDirEntries $x -ne 1` 被 PowerShell 解析为函数参数 → 断言恒真；(3) `RegQueryValueExW` 带大小指针(NULL 数据) 返回 ERROR_MORE_DATA → PathType 恒 1 → WriteRegStr 展开 `%USERPROFILE%`；(4) smoke 用 GetEnvironmentVariable（自动展开 EXPAND_SZ）匹配字面 `%USERPROFILE%` → 恒失败，改 DoNotExpandEnvironmentNames 读原始值；另接受 runner 系统 PATH 已有 pip aisc 的真实遮蔽语义（05 §5.2.5 不覆盖）。
- **Step 1 结论（2026-08-09）**：NSIS installer / Workbench CI / Bundle Linux-macOS 三 workflow 全绿；本地实机安装/重复安装/卸载/冲突全链 PASS。A-G18-1..4 证据齐。

### 补记：安装器 Docker Desktop 宿主集成（分支 step-18-docker-installer，2026-08-10）

用户反馈 G-18 移除依赖检测页后，安装器启动 Workbench 前不再处理 Docker。补上三分支宿主集成（`workbench/src-tauri/nsis/installer.nsi`）：

- **`Section Docker`**（INSTFILES 页，`Section Install` 之后）：交互式 GUI 安装（`${Silent}` / `$PassiveMode` guard）检测 Docker 缺失时用 winget 安装 `Docker.DockerDesktop`；winget 输出经随安装器打包的 `wg-transcode.ps1`（`bundle.resources`）把 UTF-8 流式转码为系统 ANSI 代码页，Details 面板实时显示可读进度（winget 非 TTY 无百分比条，仅文本状态行；转码避免 zh-CN 下 mojibake——2026-08-10 用户反馈"winget 日志乱码"后修复）；`$DockerWingetExit` 先存再 `CheckDocker`（修复旧 `Section Dependencies` 中 $0 被 clobber 的 latent bug）。失败不中止安装，由 Workbench 首次启动 preflight 报告真实引擎状态。
- **`RunFinishApp` 重写**：`CheckDocker` → 已装则 `StartDockerDesktop`（`FindProcessCurrentUser` + `FindProcess` 判运行，0=运行；未运行则 `ExecShell open` 静默启动）→ 未装则 MessageBox 询问打开 Docker 下载页（仍启动 Workbench）；然后 `RunAsUser` 启动 Workbench。
- **`.onInstSuccess` `/R` 路径**：silent/passive 自动启动前 `Call CheckDocker` + `StartDockerDesktop`（CI 不传 `/R`，无 Docker runner 上 no-op 无 MessageBox）。
- **新增**：`CheckDocker`（exe 存在 + 卸载注册表 InstallLocation 回退，`800715c` 逐字恢复）/ `CheckWinget`（`where winget`）/ `StartDockerDesktop`；`DOCKER_INSTALLING/INSTALL_OK/INSTALL_FAIL/NO_WINGET/MISSING_LAUNCH` 中英文 LangString。
- **silent/passive 安全**：`Section Docker` 被 `${Silent}`/`$PassiveMode` guard，CI smoke（`/S` 安装/升级/卸载）永不触发 winget；README/CI workflow 头部注释同步，防后人"简化"掉 guard。
- **验证**：`npm run tauri build -- --bundles nsis` 全绿，渲染 installer.nsi 含全部新符号；`check-deps-test.nsi` 更新为 `CheckDocker`+`CheckWinget`（去掉已删的 `CheckPython`），makensis 编译 + `/S` 实跑：本机 `docker_installed=0`（Docker Desktop 当前未安装）、`winget_installed=1` ✅。手测矩阵 a–g 待用户实机（见计划）。

## Step 2 验收清单（G-07 停止/关闭/退出性能，分支 step-2-g07-perf）

> 规范：03-lifecycle-contract.md §4.2/§4.3、06-implementation-plan §0.5；门禁 A-G07-1..4。目标：终止 Runtime / 关窗退出 / 会话回收三条路径的感知延迟与预算。

- [x] **2a-1** CLI `runtime stop --grace`（1..600 校验，超时=grace）：`stop_runtime` → `executor.stop_container(timeout=grace)`；`session terminate` grace 校验（有限 0..600），超时 grace+1.0；transport 预算 15s。测试：`test_runtime_lifecycle.py`（grace 传递/非法值）+ `test_session_commands.py`（terminate 超时）。
- [x] **2b-1** Rust 预算：TERMINATE_TIMEOUT 5s / CLOSE_WAIT 4s / CLOSE_FORCE_WAIT 2s；`session_open_argv` 带 `--workspace` + `--grace 3`；`runtime_stop_argv` 带 `--grace 3`；reopen 25 周期孤儿泄漏测试（A-INFRA-2 补全，`reopen_25_cycles_leaves_no_orphan_sessions`）。
- [x] **2c-1** `shutdown_workbench` 协调器（03 §4.3）：共享 6s graceful 窗口并发 close → 共享 2s force-reap → flush settings → `ShutdownReport`（graceful/force/timed_out/unreaped/flush_errors）；`stopRuntime` 分段式（400ms race 并发 close → stop → inspect 确认 stopped/not_found）。
- [x] **2c-2** 性能证据（`perf_runtime_stop_with_eight_sessions`，2026-08-09 实机）：0 会话 stop ~3.47s，8 会话 stop 0.73s（grace 3 快速路径），reopen 25 周期 ~1s/cycle 无孤儿。
- [x] **2d-1** 手动测试（Windows 11 实机，2026-08-09/10）：终止 Runtime 2-3 会话快速结束 ✅（首次失败 `unrecognized arguments: --grace 3` = 陈旧 sidecar，重建 + 双拷贝后修复，sidecar 同步要求记入 memory）；关窗瞬间隐藏 + 后台清理 + 进程 ~10s 内退出 + 容器保留 ✅；恢复布局回归 ✅。
- **手测发现并修复 4 个真实 bug**：
  - (1) 恢复布局消失（路径匹配脆弱 + 空 tabs 覆盖）：`restorableLayout` 精确字符串匹配，重输路径（正斜杠/尾斜杠/大小写）即失配 → 新增 `normalizePath/sameWorkspace`（win: `/`→`\`、去尾分隔符、大小写不敏感；posix: 去尾 `/`、区分大小写），恢复查找与 history key 统一归一化；`buildPatch` 空 tabs 时保留已有布局（stop/start reset 清空数组，单 tab 关闭不清空）——preflight 的 scheduleSave 不再抹掉磁盘布局（f210eca）。
  - (2) 关窗等待慢（前端 `await hide()` 挂起）：确认后 handler 死在 `await getCurrentWindow().hide()`（close-request 挂起期间该 Tauri 版本 hide IPC 不返回）→ shutdown 从未调用、窗口永不关、无日志（c9033a5：hide 与 shutdown 全部 fire-and-forget + 失败兜底 destroy；82a9bdd：改 Rust 侧 `app.get_webview_window("main").hide()` 直接 win32 隐藏——前端 hide IPC 在 close-request 挂起时不可靠）。stale/fresh 交替为原生确认框 focus/blur 触发轮询 markStale→tick 的正常现象，非 bug。
- **Step 2 结论（2026-08-10）**：CLI grace 链 + Rust 预算 + 分段 stop + 后台关闭全链 PASS；cargo session 19 绿 / vitest 9 绿（4 新增路径归一化）/ npm build 零错。A-G07-1..4 证据齐。

## Step 3 验收清单（typed settings 基础设施，分支 step-3-typed-settings）

> 规范：02-startup-flow.md §三.4（字段/默认/边界）+ §九（保存协议）；门禁 A-G01-1。

- [x] **3a-1** Rust typed settings：`ui/terminal/window` 三区全字段边界校验（语言/字号/主题/字体/行高/字距/回滚/渲染器/平滑滚动/窗口记忆/关闭行为/geometry schema），字段级非法回退 + validation issue，默认值只在 Rust。
- [x] **3a-2** 保存协议：独立 settings.lock + expected-revision 冲突 replay（≤3，Rust 侧）；unknown 字段（顶层/嵌套）深合并保留（A-INFRA-5）；pin 写复用锁不破坏 GUI 字段；corrupt 隔离 `.corrupt` 仅 reset 写默认；高版本 schema 只读拒写。命令 `load_settings/save_settings/reset_gui_settings`（reset 保 pin + unknown）。
- [x] **3b-1** 设置对话框骨架：键盘可达 modal（Esc/初始焦点/Tab）、每字段 label/错误/生效标记（即时/重建 Terminal/下次启动）、脏标记「未保存更改」（内存≠磁盘，A-G01-5）、保存失败可重试、readOnly/corrupt 警告条；重置从后端重载默认（前端无第二份默认）。
- [x] **3c-1** 手动测试（2026-08-09/10）：打开/编辑/保存/重启保持、非法值字段报错、corrupt 隔离、重置保 pin 均通过（字号实时生效属 Step 6/7 接线，已在手测中澄清范围）。
- **Step 3 结论（2026-08-10）**：cargo 13 新测试 + vitest 9 新测试全绿；A-G01-1 证据齐。

## Step 4 验收清单（G-09 UI i18n，分支 step-3-typed-settings）

> 规范：02 §三.1/§三.2/§三.3、06 §五；门禁 A-G09-1..4。

- [x] **4a-1** Rust locale 解析（`locale.rs`）：显式 `ui.language` > 安装器（`HKCU\Software\aisc\AISC Workbench\Installer Language`，1033→en-US/2052→zh-CN，字符串或 DWORD）> 系统（sys-locale）> zh-CN；`resolve_locale` 命令异步不阻塞 CLI 协商。6 纯函数矩阵测试。
- [x] **4b-1** vue-i18n 接入：zh-CN/en-US 全量字典（key 集完全一致，parity/空值/占位符/缺失 key 报错测试，A-G09-2）；启动并行解析应用；设置改语言保存后即时切换（A-G09-3）。
- [x] **4c-1** 全前端硬编码扫描替换（12 文件）：blocked/picker/summary/build/conflict/ready/error/侧栏/tab/设置/终端欢迎与 Session error/exit 辅助文本入字典（A-G09-4 原始 PTY 字节不动）；allowlist：raw 代码、路径、技术 token（id/ctr/image/network/scope/route/auth）、稳定错误码、后端错误消息。
- [x] **4c-2** 手动测试（2026-08-10）：en-US 切换全局即时生效 ✅；重启保持 ✅；auto 回中文 ✅；侧栏区标签本地化（手测反馈补 8 键）✅；终端欢迎/退出文本随语言 ✅。字号实时生效澄清为 Step 6/7 接线范围。
- **sidecar staging 二次事故（2026-08-10）**：`--grace 3` 复发。根因：tauri externalBin staging 源 `workbench/src-tauri/binaries/` 是旧 CLI，每次 cargo build 自动覆盖 `target/debug/aisc.exe`（pin 目标）。修复：重建 sidecar 同步 binaries/ + target/debug + 安装目录；同步清单记入 memory。
- **Step 4 结论（2026-08-10）**：cargo 6 新 + vitest 14 新测试全绿；A-G09-1..4 证据齐。

## Step 5 验收清单（G-08 动态多 tab，分支 step-5-g08-tabs）

> 规范：06 §六、02 §2.3；门禁 A-G08-1/2/3/6/7/8（pane 树相关 A-G08-4/5 属 G-17 分屏）。

- [x] **5a-1** Store 动态化：固定四 tab → `createTab(agent)` 动态数组（重复类型允许，A-INFRA-1）；每 Runtime 8 叶上限（A-G08-8，第 9 拒绝）；`removeTab`（× 移除整个 tab，运行中会话 best-effort 关闭，active 落右邻→左邻→空态，A-G08-6）；Start 仅开 1 Bash（A-G08-1）；LaunchSummary 移除初始 Agent 选择；Ctrl/Cmd+1..9 动态映射（10+ 用 tablist 方向键）；history 保存超 8 截断 + warning（A-G08-3）。
- [x] **5b-1** TabBar UI：`+` 弹出菜单（4 agent，aria-haspopup/expanded，方向键/Enter/Esc/点击外部关闭，键盘可达）；空态「新建标签」焦点目标；× = removeTab；「重开」保留。
- [x] **5c-1** Provider guide 最小流程（A-G08-2）：+ 选 claude/codex → 按 type 去重 Provider query → `not_configured` → guide 态（不调 open_session，无 PTY）+ GuidePane（重试：配置后即开会话；「打开 cc-switch」激活或创建）；bash/cc-switch 立即开。login_required（如 codex 默认 OpenAI Official 路由）直接开会话终端内登录 —— 2026-08-10 用户决策保留数据驱动，代码 TODO + todo.md 双记录。
- [x] **5d-1** 手动测试（2026-08-10）：Start 单 Bash、+ 多开/重复类型、guide 流程、× 移除与邻位、Ctrl+1..9、空态、8 上限、恢复布局（重复类型）、停止/退出无残留，全部通过。
- **Step 5 结论（2026-08-10）**：vitest 32 绿（9 新增 runtimeTabs）；A-G08-1/2/3/6/7/8 证据齐。

## Step 6 验收清单（G-06 终端渲染升级，分支 step-6-g06-render）

> 规范：06 §七、03 A-G06-1..5。

- [x] **6a-1** WebGL 渲染：`@xterm/addon-webgl`；renderer 枚举（auto|default|webgl）作为 Workbench 加载/释放策略（`resolveRenderer` 纯函数），不写入 term.options；构造 try/catch + context loss dispose 回落 DOM renderer（A-G06-1/2）。
- [x] **6a-2** 设置驱动：Terminal 创建读 typed settings（字体栈/字号/行高/字距/回滚/平滑滚动，默认值只在 Rust，未加载时用 xterm 原生默认）；即时选项（字号/行高/字距/回滚/平滑滚动）deep-watch 实时生效（对话框编辑即预览、取消即回滚）；renderer/font_family 变化原地重建视图——session_id/PTY/channel 不动，旧实例与 addons dispose 无泄漏（A-G06-3）。
- [x] **6a-3** 主题 token：暗色 palette（VS Code 默认）集中到 TERMINAL_THEME；正文/selection 对比度 ≥4.5:1（WCAG AA 断言测试，A-G06-5）。
- [x] **6a-4** 固定输出基准（A-G06-4）：仓库内确定性 10 MiB UTF-8/ANSI 混合 fixture（SHA-256 pin `0d1a8564...`），4 KiB chunks 连续写入；DOM 解析路径 0.01s total / max chunk 0.1ms（jsdom 无法跑 WebGL，WebGL 耗时以实机手测为准，未设虚假 FPS）。
- [x] **6b-1** 手动测试（2026-08-10）：终端字号 14/行高 1.2/平滑滚动生效；设置字号即时变大、取消回滚；renderer 切 webgl 重建视图会话不重开；配色/字体 fallback 目视正常；WebGL 无黑屏。全部通过。
- **Step 6 结论（2026-08-10）**：vitest 38 绿（renderer 6 + 基准 1 新增）；A-G06-1..5 证据齐。UI 字体缩放（ui.font_scale）接线归 Step 7（G-01）。

## Step 7 验收清单（G-01 设置页交付，分支 step-7-g01-settings）

> 规范：06 §八、02 A-G01-1..5。Step 3 已交付对话框骨架/校验/Reset 隔离/保存失败恢复（A-G01-1/2/4/5）；本步补齐生效边界（A-G01-3）与 UI scale。

- [x] **7a-1** `ui.font_scale` 接线：CSS zoom 作用于 UI chrome（顶栏/picker/摘要/侧栏/tab/对话框），终端区反缩放保持 1:1（终端文字由 terminal.font_size 管辖）；即时生效 + 对话框编辑预览/取消回滚。
- [x] **7a-2** 手测修复 2 个真实 bug：(1) zoom 影响布局——100vh 根被缩成 80vh，侧栏按钮/终端区脱离底边 → 盒子尺寸补偿 `calc(100vh/scale) × calc(100vw/scale)` + body 背景对齐；(2) 小窗口 1.5 缩放裁剪 → 有效缩放按窗口自适应 `min(用户值, 1.5, w/800, h/600)`（800×600 默认窗口为设计基线），resize 实时更新，设置值保留仅应用值收敛。
- [x] **7a-3** 生效边界完备性（A-G01-3）：语言/UI scale/字号/行高/字距/回滚/平滑滚动即时；renderer/font_family 仅重建 Terminal 视图不重开 Session（Step 6）；Reset 只恢复 GUI 设置（Step 3）。
- [x] **7b-1** 手动测试（2026-08-10）：1.25/1.5/0.8 各档布局正常、与终端字号独立并存、保存重启保持、取消回滚、小窗口自适应无裁剪。全部通过。
- **Step 7 结论（2026-08-10）**：vitest 38 绿 / build 零错；A-G01-1..5 证据齐。

## Step 8 验收清单（G-05 侧边栏分层 + G-12 Provider 引导，分支 step-8-sidebar-guide）

> 规范：04-observability.md（分层/ticker/引导规则）、06 §九；门禁 A-G05-1..4、A-G12-1/2。

- [x] **8a-1** 去 1 秒 ticker：观察时间按 snapshot 缓存、详情展开/手动刷新才重算；语义视图 key（runtime/provider/sessions）——key 不变 DOM 子树不动（A-G05-1，12s 零突变测试）。
- [x] **8a-2** 分层 UI：用户层（工作区/运行状态含 stale「上次已知」样式/Provider 名（无伪造 model）/Auth 标签+未配置行动/会话计数可点激活）+ 开发者详情折叠（原生 details：全部原始字段 + 复制，A-G05-3 字段清单测试）；刷新按钮「刷新中」仅手动点击显示（轮询不翻转，用户反馈修复）。
- [x] **8a-3** G-12 banner 移到 tab 顶部（非侧栏）：not_configured/login_required/unknown 分文案；动作重试/打开 cc-switch/官方账号登录（进 TUI）；provider 配置后 banner 转「已配置 + 启动会话」；unknown 不误报未配置（A-G12-1/2）。
- [x] **8a-4** 行为变更（04 §三 规则表）：login_required/unknown 也进引导态（取代 2026-08-10 的 login_required 直开决定）；恢复布局路径同样过 provider gate（A-G08-3 修复：未配置 codex 不再直进 TUI）。
- [x] **8b-1** 手测修复：guide tab 无 ×（canClose 加 guide）；引导文案不随 UI scale（反缩放只包 xterm 本体）；新建 tab 需点击才能输入（activeTabId watcher 统一聚焦 + guide→starting 迁移聚焦）。
- [x] **8c-1** 手动测试（2026-08-10）：侧栏分层/详情/复制/双语、banner 三动作、cc-switch 配置后启动会话、官方登录进 TUI 可直输、恢复布局 gate、外部 stop stale 样式。全部通过。
- **Step 8 结论（2026-08-10）**：vitest 44 绿（sidebar 5 + restore-gate 1 新增）；A-G05-1..4、A-G12-1/2 证据齐。

## Step 9 验收清单（G-02 Resize 根因定位与修复，分支 step-9-resize）

> 规范：06 §十（先诊断后修改）、05 A-G02-1..4。

- [x] **9a-1** 诊断链路测试（A-G02-1/2）：`resize_chain_stty_probe_three_sizes_20_reps` — 80×24/120×40/60×20 × 20 次，容器内 `stty size` 探针。
- [x] **9a-2** 根因记录（A-G02-2，提交 62cb985）：`docker exec -it` 的 exec pty 创建时定尺寸，docker CLI 无 resize 命令 → ConPTY resize 到不了容器（stty 恒为 spawn 尺寸）。
- [x] **9a-3** CLI 修复（A-G02-3）：交互会话改走 Docker SDK（`open_interactive`：exec_create(tty) + exec_start(socket) + 尺寸 watcher → `exec_resize`）；docker-py 成为首个运行时依赖。Windows 特有问题三连：os.read 在两种 console 模式都丢 CR/LF（cooked 等 Enter 吃 CR、raw 丢终止符）→ 改 `ReadConsoleInputW` 读 KEY_EVENT（Enter 自带 CR），resize 风暴期控制台 API 瞬断重试 ~1s；`os.get_terminal_size` 对输入句柄失败 → stdout `GetConsoleScreenBufferInfo`；exec 初始 0×0 → watcher 首轮即 resize。
- [x] **9a-4** 端到端（A-G02-4）：外部探针（`stty size < /proc/<agent-pid>/fd/0`，与会话 stdin 解耦——ConPTY 在 resize 风暴下周期性丢输入事件属平台限制，已在测试注释记录）3 尺寸 × 20 次全过；输入路径单测 echo 验证。
- [x] **9a-5** TUI 输出编码修复（SDK 切换回归，2026-08-10 手测暴露）：cc-switch TUI 全屏乱码（`鈹?` = GBK 解 UTF-8 的 `─`，`E2 94 80` 中 `80` 作 GBK lead byte 还吞掉后续 `ESC` -> ANSI 转义也断）。根因：SDK 路径 drain 线程 `os.write(1, chunk)` 写容器 UTF-8 裸字节到 ConPTY，而 zh-CN Windows ConPTY 输出代码页默认 GBK（CP936）；`pty.rs` reader 读 raw bytes -> base64 -> 前端，无编码转换，乱码发生在 ConPTY 内部。`entrypoint.py` `_configure_frozen_io()` 只管 Python 文本模式 `print()`，管不到 `os.write` 裸字节。**第一版修复** `SetConsoleOutputCP(65001)` 手测仍乱码--ConPTY 不可靠地尊重运行时代码页变更。**最终修复**：drain 线程 Windows 改用 `WriteConsoleW`（直接写 Unicode WCHAR，完全绕过代码页）+ 增量 UTF-8 解码器（`codecs.getincrementaldecoder`，处理跨 recv chunk 的多字节序列拆分）+ `GetConsoleMode` 检测非 console 句柄时回退 `os.write`；`SetConsoleOutputCP(65001)` 保留作 baseline。输入路径不受影响（`ReadConsoleInputW` 返回 Unicode WCHAR，与代码页无关）。sidecar 重建 + 三处同步（dist/binaries/target/debug）。
- [x] **9b-1** 手动测试（通过，2026-08-10）：cc-switch TUI 连续 20 次 resize 无残留旧区域、光标可见；应用内窗口拖拽 resize 终端跟随；cc-switch/任意 TUI 无乱码（9a-6 管道方案）。用户确认"体验上基本没有问题，20 次 resize 没发现明显问题"。
- [x] **9a-6** 管道方案（ConPTY 彻底绕过，2026-08-10 手测通过）：9a-5 的 `WriteConsoleW`/转码/`SetConsoleMode` 路径虽修好编码，但 ConPTY 层引入多个不可调和问题：(1) `WriteConsoleW` 用 Unicode 宽度表，zh-CN 下 box-drawing = 2 列 -> 错位；(2) `ENABLE_PROCESSED_OUTPUT` 设了才能认 ESC（VT 序列），但会把 `\n` 翻译成 `\r\n` -> 错位；清了则 VT 碎裂；(3) ConPTY 固定 GBK codepage，`SetConsoleOutputCP(65001)` 被忽略；(4) `os.write`+GBK 转码丢失非 GBK 字符（emoji -> `?`）；(5) ConPTY 从屏幕缓冲区重新生成 VT -> 可见从上到下刷新；(6) console 模型开销 -> 响应慢。**根治**：`spawn_pipe_session`（pty.rs）用 `std::process::Command` + `Stdio::piped()` 替代 ConPTY；`PtySession` 结构改为支持 pipe 模式（`master: Option`、`kill_fn` 闭包、`resize_file: Option<PathBuf>`）；resize 通过临时文件传递（Rust 写 `<cols> <rows>` -> `AISC_RESIZE_FILE` env var -> sidecar 100ms 轮询 -> `exec_resize`）。docker_.py `open_interactive` 从 ~200 行 console API 简化为 ~90 行裸 `os.read`/`os.write`，删除全部 console 代码（WriteConsoleW、SetConsoleOutputCP、SetConsoleMode、transcoding、ReadConsoleInputW、GetConsoleScreenBufferInfo、`terminal_size()`、`_forward_console_input()`）。数据流：容器 UTF-8/VT -> SDK socket -> sidecar `os.write` -> pipe -> Rust base64 -> xterm.js，零 console 处理。手测：显示正常、无乱码/`?`、无错位、方向键可用、响应快、无可见刷新。Rust 91 + Python 53 绿。
- **Step 9 结论（2026-08-10）**：python 绿 + Rust 91 绿；A-G02-1..4 证据齐 + 9a-5 编码修复 + 9a-6 管道方案（手测通过）；9b-1 手测通过（20 次 resize 无明显问题）。**Step 9 完成。**

## Step 10 验收清单（G-10 窗口尺寸/位置记忆，分支 step-10-geometry）

> 规范：06 §十一、02 §A-G10-1..5。

- [x] **10a-1** Rust 命令（A-G10-1/2/3）：`window.rs` 新模块：`restore_window_geometry`（启动时读 `window.geometry`，clamp 到显示器至少 64×64 可见、最小 800×600，应用位置/尺寸/最大化）+ `capture_window_geometry`（写当前 logical 位置/尺寸/最大化到 settings，`save_with_replay` 冲突安全；跳过 fullscreen/minimized）。physical->logical 转换 via scale_factor。离屏检测回退 OS 默认。
- [x] **10a-2** 生命周期接线（A-G10-5）：`lib.rs` setup hook 启动时调 restore（窗口显示前）；`App.vue` 窗口 resize 后 300ms 防抖调 capture；关闭前 `onCloseRequested` 中 `shutdownWorkbench` 之前 flush。
- [x] **10b-1** 手动测试（通过，2026-08-10）：NSIS 安装器实测--移动/调整窗口大小 -> 关闭 -> 重开 -> 位置/尺寸恢复；最大化 -> 关闭 -> 重开 -> 恢复最大化；`remember_geometry=false` 不记忆。用户确认"没有问题，测试通过"。
- **Step 10 结论（2026-08-10）**：Rust 91 绿 + vue-tsc + vite build 零错误；settings schema（`window.geometry`）Step 3 已定义，Step 10 只加命令 + 生命周期钩子。**Step 10 完成。**

## Step 11 验收清单（G-03 终端基础体验 + G-11 右键菜单，分支 step-11-terminal）

> 规范：06 §十二、03 §七 A-G03-1..4 / A-G11-1..4。

- [x] **11a-1** 搜索（A-G03-1/A-G11-2）：`@xterm/addon-search` 每 pane 独立加载/dispose；Ctrl/Cmd+F + 右键入口打开搜索条；上下结果、大小写切换、无结果提示、Esc 关闭；tab 切换不串查询。按键经 `attachCustomKeyEventHandler` 拦截（容器 DOM keydown 被 xterm 内部 textarea 吞掉不触发，2026-08-10 手测修复）。
- [x] **11a-2** 剪贴板（A-G03-2/A-G11-3）：npm + Rust `tauri-plugin-clipboard-manager`，仅 `read-text`/`write-text` capability；侧边栏 ID 复制迁移到同一插件通道（弃用 `navigator.clipboard`）；权限错误显示可恢复错误。
- [x] **11a-3** 右键菜单（A-G11-1）：复制/粘贴/搜索/清屏；无 selection 时复制禁用、session 结束后粘贴禁用；菜单关闭焦点回终端。快捷键 Ctrl/Cmd+Shift+C/V 与右键一致；粘贴走 `term.paste` -> `writeSession`（1 MiB 上限，A-G11-4）。
- [x] **11a-4** 滚动（A-G03-3）：scrollback 5000 默认；向上查看历史不强制跳底，回底恢复 follow；PageUp/PageDown/Home/End 原生可用。
- [x] **11a-5** 终端填满（手测修复，2026-08-10）：`.terminal-area` 加 `display: flex`（term-wrap flex:1 拉伸）；恢复 counter-zoom 防实时缩放闪烁（移除后 canvas re-fit 闪烁，已回滚恢复）。默认缩放终端填满。
- [x] **11a-6** 设置滑块（用户反馈，2026-08-10）：`ui.font_scale`/`terminal.font_size`/`line_height`/`letter_spacing`/`scrollback`/`smooth_scroll_duration` 改滑块（限定区间 min/max/step 取自 Rust schema），内联显示当前值；`v-model.number` 修复滑块数字不更新 + 保存失败（range v-model 产生字符串 -> `.toFixed` 崩溃 + serde 拒收）。
- [x] **11b-1** 手动测试（通过，2026-08-10）：用户确认"可以接受"，余留细节问题之后调整。
- **Step 11 结论（2026-08-10）**：vue-tsc + 44 vitest + cargo build 全绿；搜索/剪贴板/右键/滚动/填满/滑块全部手测通过。**Step 11 完成。**

## Step 12 验收清单（G-13 一键诊断，分支 step-12-doctor）

> 规范：06 §十三、02 §五（F-4）、05 §六（Doctor 契约）、01 R-10。

- [x] **12a-1** Rust doctor 模块（A-G13-2 前半）：`doctor_argv()` 纯函数（`doctor --format json`）；`DoctorCheck/DoctorSummary/DoctorReport` serde 类型；Tauri `run_doctor` command 复用 `run_control`（30s timeout / 8 MiB stdout cap / stderr redaction / exit-code 校验），并额外校验 `meta.command == doctor`。成功/CLI error/timeout/stdout overflow/无效 envelope 均有稳定映射（失败保留原错误事实，A-G13-1）。
- [x] **12a-2** 解析健壮性（A-G13-4）：`data.host.checks/summary` 类型合法；`data.container=null` 省略、未来结构存在不导致 host 解析失败；未知 check 字段忽略；每个 check 的 `detail/hint` 经 `redact()` 脱敏。
- [x] **12b-1** Frontend 通道：`DoctorCheck/DoctorSummary/DoctorReport` TS 类型 + `ipc.runDoctor`。
- [x] **12b-2** Doctor store：`idle/running/done/error`；在途时重复 `run()` 不启动第二个 doctor（A-G13-3）；不触碰 runtime/settings store（关闭/重开不改变 startup state）。
- [x] **12b-3** UI：`DoctorDialog.vue` 展示 `checks`/`summary`/`hint`（不渲染原始 stdout/stderr）；blocked/error/ready（sidebar 开发者详情）三个入口触发同一 command；在途按钮禁用；失败显示结构化 Workbench error + 重试。
- [x] **12c-1** i18n：zh-CN/en-US 文案齐全 + key-parity 测试。
- [x] **12c-2** 自动化：Rust 单测 101（含 10 doctor）+ cli_runner 7 + pty_supervisor 7 + vitest 49 全绿；vue-tsc + cargo build 通过。
- [x] **12b-4** 手动测试（通过，2026-08-10）：用户确认 1-6 全过——ready 详情入口弹诊断自动运行、check 状态/summary/hint 展示正常；连点运行按钮只跑一次（在途禁用）；退出 Docker Desktop 后 docker check 显示失败 + hint、页面不卡、可重试；关闭后 startup 状态不变。
- **Step 12 结论（2026-08-10）**：Rust 101 + cli_runner 7 + pty_supervisor 7 + vitest 49 + vue-tsc + cargo build 全绿；手测 1-6 通过。**Step 12 完成。**

## Step 13 验收清单（G-14 构建最终耗时与通知，分支 step-13-build-notify）

> 规范：06 §十四、02 §七（F-6）、01 R-11。

- [x] **13a-1** 依赖与插件（06 §十四）：npm `@tauri-apps/plugin-notification` + Rust `tauri-plugin-notification`，`.plugin(init())`；capability 仅 `notification:allow-is-permission-granted`/`allow-request-permission`/`allow-notify` + `core:window:allow-is-focused`/`allow-is-minimized`。
- [x] **13b-1** store 计时（A-G14-1/4）：`buildStartedAt/buildFinishedAt/buildDurationMs` 入 store；`startBuild` stamp started；首次 Promise settle 冻结 finished/duration 一次；cancelled 同样冻结；离开再返回显示冻结值不增长。
- [x] **13b-2** 单一终态（A-G14-2）：terminal 结果仅由 `buildImage()` Promise settle 写入（Channel 只流 build.output）；单调 op 计数 guard，被取代 build 的迟到 settle 忽略（duration/状态/通知不重复）。
- [x] **13b-3** 通知（A-G14-1/3）：仅窗口后台（失焦或最小化）且 complete/failed 通知一次；cancelled 不通知；前台 0 条。权限每 launch 至多请求一次；denied/unavailable/勿扰静默降级不改变 build 事实。
- [x] **13b-4** BuildProgress 显示：building 时活计时（tick 停止于 settle，A-G14-4），settle 后显示冻结耗时；终态耗时始终显示。
- [x] **13c-1** i18n：notification.title/buildComplete/buildFailed zh-CN/en-US + key-parity。
- [x] **13c-2** 自动化：vitest 59（+10 build/notify，含 A-G14-2 乱序/被取代、A-G14-1 前台 0 条/后台恰好 1 条、A-G14-3 权限降级不循环）；Rust 101 + cli_runner 7 + pty_supervisor 7 + vue-tsc + cargo build 全绿。
- [x] **13b-5** 手动测试（通过，2026-08-10）：后台 build 完成收到恰好 1 条系统通知；前台 build 0 条；终态耗时冻结不增长；权限拒绝降级、cancelled 不通知。
- [x] **13d-1** 手测中发现并修复的 bug：① 镜像缺失时若 action=reuse（工作区有匹配 runtime），构建按钮被 `imageMissing` 隐藏 → 死路；改为 `imageNotFound`（fail + `AISC_ERR_IMAGE_NOT_FOUND`，与 action 无关）驱动按钮与提示。② stale registry 记录（container 被手动删除）被 preflight 判为 reuse → session open 打不存在 container → RUNTIME_NOT_FOUND 死循环；CLI `_get_container_state` 区分 `not_found`，matching 分支对 stale 记录报 conflict（resolve_conflict → ConflictManager），ConflictManager 对 not_found 状态补「移除」按钮。均带 vitest/Python 测试锁定（vitest 65、Python 392）。
- **Step 13 结论（2026-08-10）**：vitest 65 + Python 392 + Rust 101/cli_runner 7/pty_supervisor 7 + vue-tsc + cargo build 全绿；G-14 手测 1-6 通过；手测暴露的镜像缺失按钮、stale runtime 两个 bug 已修复并验证。**Step 13 完成。**

## Step 14 验收清单（G-15 动态窗口标题，分支 step-14-dynamic-title）

> 规范：06 §十五、02 §六（F-5）、01 R-12。

- [x] **14a-1** 标题纯函数（A-G15-2）：`computeWindowTitle` 优先级——活动 tab 有 Session type → `<workspace> · <Session type> · AISC Workbench`；有 workspace 无 session → `<workspace> · AISC Workbench`；无 workspace → `AISC Workbench`；idle tab（空 tree）不残留旧 type。
- [x] **14a-2** basename（A-G15-1）：跨 `/` 与 `\`、去尾分隔符、drive root 保留。
- [x] **14a-3** 截断（A-G15-3）：workspace basename >40 grapheme 保留首尾各 18 + `…`；`Intl.Segmenter` grapheme 级，CJK/emoji/组合字符不截断 cluster。
- [x] **14a-4** 接线：App.vue watch 活动上下文（workspace + activeTab + session state）→ `getCurrentWindow().setTitle()`；无轮询；setTitle 失败仅 console.warn 不影响主流程。仅新增 `core:window:allow-set-title` capability。
- [x] **14a-5** 自动化：vitest 75（+10 title，含 basename/优先级/grapheme 截断）+ vue-tsc + cargo build + Rust 101/7/7 全绿。
- [x] **14b-1** 手动测试（通过，2026-08-10）：无 workspace → `AISC Workbench`；选 workspace → `test · AISC Workbench`；开 Bash → `test · Bash · AISC Workbench`；切 Claude/Codex tab 标题跟随；关全部 tab 回落 `test · AISC Workbench`。
- **Step 14 结论（2026-08-10）**：vitest 75 + Rust 101/cli_runner 7/pty_supervisor 7 + vue-tsc + cargo build 全绿；手测通过。**Step 14 完成。**

## Step 15 验收清单（G-16 可选最小化到托盘，分支 step-15-tray）

> 规范：06 §十六、03 §A-G16-1..5、01 R-13。

- [x] **15a-1** Rust tray（A-G16-1）：tauri 启用 `tray-icon` feature；`tray.rs` 用 `TrayIconBuilder` 创建「显示/退出」菜单并持有 owner（`TrayState`）；左键不弹菜单。
- [x] **15a-2** CloseRequested 拦截（A-G16-1/4）：`.on_window_event` 对主窗口 CloseRequested 一律 `prevent_close`；`effective_close_behavior`=minimize-to-tray 且 tray 可用 → hide；否则 quit（前端确认 + shutdown）。tray 初始化失败/平台不支持 → `tray_available=false` → 运行态回退 quit，最后窗口不会被隐藏。
- [x] **15a-3** tray 菜单（A-G16-3）：显示 → `show+set_focus`；退出 → emit `exit-requested` → 前端复用同一 confirm + `shutdown_workbench`（同一 ShutdownReport）；取消确认保持隐藏前状态。
- [x] **15b-1** Frontend：`ipc.trayAvailable()` 一次查询；onCloseRequested 分支——tray 模式且 tray 可用 → return（Rust 已 hide，Session 连续运行）；否则 runExitFlow。`listen("exit-requested")` 触发同一 runExitFlow。
- [x] **15b-2** 设置：`window.close_behavior` 已有（Step 7）持久化；即时生效（Rust 关闭时重读 settings）；Reset 恢复 quit（settings 默认）。
- [x] **15b-3** 自动化：vue-tsc + vitest 75 + Rust 101/cli_runner 7/pty_supervisor 7 + cargo build（tray-icon）全绿。
- [x] **15b-4** 手动测试（通过，2026-08-10，安装版）：默认 quit 正常退出；minimize-to-tray 关窗仅隐藏无确认框、session 连续；托盘「显示」恢复窗口+焦点；托盘「退出」同确认 + shutdown；托盘图标退出后立即消失；重启后 tray 值保持。
- [x] **15c-1** 手测发现并修复的 bug：① Tauri command 命名不匹配（fn `tray_available_command` → invoke 名 `tray_available_command`，前端调 `tray_available` → reject → trayAvailable=false → 关窗仍走 quit 流程弹确认）；helper 改名 `tray_live`、command 改名 `tray_available`。② 托盘退出后图标残留整个清理期（~12s）；新增 `tray_remove`（`set_visible(false)`），确认通过后立即隐藏图标，清理后台透明运行。③ 设置对话框小窗口下 head/foot 滚出视野，「已保存」不可见；head/foot 粘性固定。
- **Step 15 结论（2026-08-10）**：vue-tsc + vitest 75 + Rust 101/7/7 + cargo build（tray-icon）全绿；安装版手测通过；3 个手测暴露问题已修复。**Step 15 完成。**

## Step 16 验收清单（G-17 Tab 内分屏，分支 step-16-panes）

> 规范：06 §十七、03 §六（G-17 分屏模型）、01 R-14。P3，最大步骤，拆 6 子阶段。

- [x] **16a-1** PaneTree 纯模块（schema 冻结，03 §6.1/6.3）：`SplitNode/PaneLeaf/PaneNode` tagged union；`singleLeaf/splitLeaf/removeLeaf/setRatioBySplitKey/leafCount/depth/firstLeaf/listPaneIds/validateTree`；MAX_DEPTH=4、MAX_LEAVES=8、ratio clamp 0.10..0.90；关闭压缩、split 拒绝（深/满）时 tree 不变。
- [x] **16a-2** 纯模块 vitest：嵌套 split、关闭压缩、ratio clamp、深度/叶数上限拒绝、非法 tree 校验、round-trip。
- [x] **16b-1** history schema v2（A-G17-3）：Rust `schema_version=2`，TabRecord 增 `split_layout`（version/active_pane_id/root tagged union）；v1→v2 锁内原子迁移（旧 tab 转单叶、保留 tab ID/顺序/active），迁移失败保留 v1 原文件；旧版本拒写 v2；v2 round-trip + 损坏/过深/重复 ID 降级。
- [x] **16c-1** store 迁移（A-G17-2/5/6）：tab 持有 PaneTree + `active_pane_id`；open/close/reopen/Exit reducer 按 pane；资源原子计数（opening/running/closing ≤8）；provider polling/sidebar/title/generation 经 active pane；last-pane 关闭 → dormant 单叶保留 tab。
- [x] **16d-1** 分屏渲染与交互（A-G17-1/4/5）：PaneTree.vue 递归 CSS grid + divider；split 动作（水平/垂直）校验容量；divider 指针拖拽 + 键盘 0.05 步长；每叶独立 Terminal/Session/ResizeObserver；点击 pane 激活。
- [x] **16d-2** 自动化：paneTree 17 + paneRuntime 12 + 全量 vitest 104 + vue-tsc 全绿；Rust 105（16b history）+ cli_runner 7 + pty_supervisor 7。
- [x] **16e-1** 手动测试：嵌套 split、关闭压缩、拖拽 resize、tab+pane、第 9 个拒绝、重启恢复、runtime stop/退出全回收（2026-08-10 用户确认"暂时算通过，之后再改"）。
- **Step 16 结论（2026-08-10）**：自动化全绿 + 手测通过。**Step 16 完成。** 遗留：分屏键盘导航（Ctrl+Shift+hjkl/方向键）在 WebView2 无效、其他小问题，见 `docs/todo.md`。

## Step 17 验收清单（G-04 明暗主题切换，分支 step-17-theme）

> 规范：06 §十八、02 §三.5；门禁 A-G04-1..4。

- [x] **17a-1** 主题基础设施（A-G04-1/2）：`theme.ts` 纯模块——`ThemeMode`（system/dark/light）→ `resolveTheme` → `effectiveTheme` reactive；`applyTheme` 写 DOM `data-theme` + `color-scheme` + localStorage 渲染缓存；`systemDark()`/`createSystemListener`（单实例 + unsubscribe）；`index.html` 首帧前内联脚本读缓存设 `data-theme`（无暗/亮闪屏）。
- [x] **17a-2** 语义 token：`styles.css` `:root`（dark 默认）+ `:root[data-theme="light"]` 覆盖；`--bg/--surface/--text/--muted/--border/--accent/--success/--warn/--error/--selection/--focus` 全套 token；`color-scheme` 跟随。
- [x] **17b-1** 全量 token 收敛：13 个组件 CSS 全部 `var(--*)`（LaunchSummary/PreflightGate/StartProgress/BuildProgress/ConflictManager/SettingsDialog/DoctorDialog/RuntimeSidebar/TabBar/Terminal/PaneTree/GuidePane）；App chrome token 化。
- [x] **17c-1** xterm 明暗（A-G04-3）：`TERMINAL_THEME`/`LIGHT_TERMINAL_THEME` + `terminalTheme(effectiveTheme)`；Terminal.vue watch `effectiveTheme` 原地更新 `term.options.theme` + `term.refresh(0, rows-1)`，不重建 Session/PTY。
- [x] **17c-2** 设置接线：SettingsDialog theme 字段 `effect: "immediate"`；`ui.theme` 持久化、重启保持。
- [x] **17d-1** 自动化：`theme.test.ts`（resolveTheme/applyTheme/cache/system 解析/createSystemListener 单例+清理/token 对比度 WCAG AA fixture）；settings.rs theme 校验；全量 vitest 122 + Rust + vue-tsc + cargo build 全绿。
- [x] **17d-2** 手动测试（通过，2026-08-10）：深/浅色切换即时生效、xterm 跟随、重启保持、对比度达标；用户确认"一切正常"。
- **Step 17 结论（2026-08-10）**：vitest 122 + Rust 全绿 + 手测通过。**Step 17 完成。G-01..G-18 全部 18 个目标完成。**

# v2.3.0-dev (2026-08-06 ~ 2026-08-09) - Workbench Phase 1 + Phase 2（S2.1/S2.2.a/S2.2.b/S2.3.a/S2.3.b/S2.4.a/S2.4.b）+ Phase 3（S3.1/S3.2/S3.3）+ Phase 4（S4.1.a/S4.1.b）+ S4.2 发布门（CI+文档）

### S4.2 发布门（2026-08-09，06-implementation-plan.md §七 S4.2）

- **三平台契约 smoke**：`tests.yml` matrix 加 `macos-latest`（原 ubuntu+windows），3.11/3.12/3.13 × 3 OS。验证待 GitHub Actions dispatch。
- **Linux/macOS bundle CI**：新增 `.github/workflows/bundle-linux-macos.yml`——ubuntu 产 deb、macos 产 DMG，各自从源码构建 sidecar + stage aisc-bundle + `tauri build --bundles`，产物上传 artifact。验证待 CI。
- **Windows 覆盖升级/卸载安全冒烟**：`nsis-installer.yml` 冒烟扩展——静默装后放置 `%APPDATA%\cn.aisc.workbench\` 与 workspace `.aisc/` 数据标记 → 同版本覆盖重装（silent 走 uninstall+reinstall 维护流程）→ 断言标记存活 + bundle 在 → 静默卸载 → 断言 app 文件与卸载注册表键清除、**数据标记保留**。验证待 CI。
- **回滚文档**：新增 `docs/releases/rollback.md`——数据保留边界（app_config_dir/工作区不受卸载影响）、降级路径（allow_downgrades=false 需先卸载）、CLI 协商顺序（`--aisc-cli` > pin > sidecar > PATH > 平台已知位置，对应 `cli.rs` `enumerate_candidates`）、pin 清理方法、回滚验证清单。
- 范围外 blocked：Windows 代码签名（无证书）、macOS 公证（无账号/机），正式 Preview 发布在签名/公证前不进行。计划见 `docs/plans/PLAN-workbench-s4.2-release-gates.md`。
- **CI 验证（2026-08-09）全绿**：Tests 9/9（3 OS × 3 Python，macOS runner 新接入）；Bundle Linux/macOS 产出 deb + DMG；NSIS 冒烟 SMOKE/UPGRADE/UNINSTALL 三阶段 PASSED（升级重装与卸载均保留 `%APPDATA%\cn.aisc.workbench\` 与 workspace 数据标记）。macOS runner 暴露 2 个平台假设并修复：(1) `test_session_wrapper.py` /proc start-ticks 测试 macOS 无 /proc → 拆 `linux_only` guard（POSIX 部分保留 `posix_only`）；(2) `test_runtime_preflight_no_side_effects.py` 无 docker CLI 时 docker 存在性断言 FileNotFoundError → try/except 容错跳过。

### 变更

#### Windows 实机测试修复（S4.1.b 实测反馈，docs/问题.txt）

- **问题 1（装完 Docker 不引导启动）**：NSIS Finish 页 RUN 改 `RunFinishApp`——`$DepsDockerWasMissing`（Deps 页检测到 Docker 缺失时置 1）时先 `ExecShell` 启动 Docker Desktop（首次运行用户确认 license），再启动 Workbench。
- **问题 2（Docker 未启动时 preflight 识别不到）**：`start_docker` Tauri 命令（Windows 启动 `%LOCALAPPDATA%\Docker\Docker Desktop\Docker Desktop.exe`，macOS Docker.app；Linux 返回可操作错误）+ 前端「启动 Docker」按钮——summary docker gate fail 时显示，点击后启动 Docker Desktop 并每 2s 轮询 preflight 直到 docker check pass（90s 超时提示手动打开）。`AISC_ERR_DOCKER_UNAVAILABLE` action 从 Retry 改 `StartDocker`。
- **问题 3（所有操作弹 Windows Terminal 闪现）**：`cli.rs` `run_control`/`run_build_stream` spawn 加 `creation_flags(0x08000000)`（CREATE_NO_WINDOW，`#[cfg(windows)]` 门控——tokio `creation_flags` 仅 Windows 存在）。PTY session 不动（交互终端）。
- **问题 4（构建镜像直接失败）**：build 失败错误码 `AISC_ERR_DOCKER_UNAVAILABLE` 时 BuildProgress 显示「启动 Docker」按钮 + 明确文案（引擎未运行无法构建），启动后回摘要重试。
- **问题 5（winget 装 Docker → Finish 页勾选打开 Workbench → 摘要页检测不到 Docker、「启动 Docker」也无效，重开才正常；TODO 20260806 line 76）**：A+C 方案落地——**A** 摘要页 docker gate 红时**自动**触发 `startDockerAndRepreflight`（`runtime.ts` `runPreflight` summary 分支；每 3s 重跑 preflight，上限 120s，`dockerStarting` 防重入；按钮保留为手动兜底），期间文案「Docker 引擎启动中，正在自动重试检测…」；**C** CLI docker 解析兜底（`docker_.py` `_resolve_path`：`shutil.which` 失败时回退 `C:\Program Files\Docker\Docker\resources\bin\docker.exe` + `%LOCALAPPDATA%\...`，消除安装器拉起 Workbench 继承旧 PATH 的坑）。验证：python unittest 35 绿（新增 4 个 `_resolve_path` fallback 用例）+ `vue-tsc`/`vite build` 零错误。**2026-08-09 实机复测通过**（用户确认：其余问题基本通过，无明显异常）。另确认：已安装时选择「卸载」→ 卸载完成后继续进入新安装向导 = tauri-bundler 2.9.4 默认模板 maintenance-mode 行为（卸载后继续安装流程），非 bug，经用户确认保持现状（A 方案）。
- **问题 6（复测新发现）**：(1) **空目录误报「工作区已有不兼容 Runtime」**——`runtime.py` `recommended_action` 原先任何 check 失败都置 `resolve_conflict`（含镜像缺失），全新安装没镜像就误报冲突；改为仅 `runtime_conflict` check 失败才置 `resolve_conflict`，其他 gate 失败保持 `start`（UI 按 gate 显示对应按钮/文案）。验证：unittest 29 绿（新增 image-missing→start、真冲突→resolve_conflict 两个回归用例）+ 实机 exe 空目录 preflight 实测 `action: start`。(2) **构建镜像失败 `docker-credential-desktop: executable file not found in %PATH%`**——CLI 靠兜底绝对路径找到 docker.exe，但子进程 PATH 仍是安装器继承的旧环境，credential helper 解析不到；`docker_.py` 新增 `_subprocess_env()`：所有 docker 子进程（preflight/inspect/run_*/streaming_captured 共 6 处）PATH 头部插入 resolved docker 目录。验证：unittest 29 绿 + 全量 435 绿（61 跳过）。
- 验证：cargo 70 绿；npm build 零错误；NSIS 模板改动（`RunFinishApp`）由 CI Windows runner 重新编译验证通过；复测清单见 `docs/platform-windows.md`「实机修复复测」（待用户 Windows 复测确认）。

#### S4.1.b Windows NSIS 定制安装器（06-implementation-plan.md §六 S4.1）

- **定制 NSIS 模板**：`workbench/src-tauri/nsis/installer.nsi`（tauri-bundler 2.9.4 默认模板复制 + S4.1.b 扩展；Handlebars 模板由 bundler 渲染）。`tauri.conf.json` 加 `bundle.windows.nsis.template`（installMode currentUser、languages English）+ `webviewInstallMode {type: downloadBootstrapper}`（WebView2 由 Tauri 原生 section 自动处理）。
- **Environment Check 页**（`PageDepsCheck`，StartMenu 页后 INSTFILES 前）：nsDialogs 检测 Docker Desktop（`%LOCALAPPDATA%\Docker\Docker Desktop\Docker Desktop.exe` + HKLM 注册表兜底）、Python 3（`HKLM/HKCU \SOFTWARE\[WOW6432Node\]Python\PythonCore`）、winget（`where winget`）、WebView2（仅提示，由安装器处理）。按钮：**Install missing dependencies** / **Skip** / **Start Docker Desktop**（Docker 已装时）/ **Open Microsoft Store**（winget 缺失时，App Installer 9NBLGGH4NNS1）。
- **`Section Dependencies`**（EarlyChecks 后、WebView2 前）：用户选择安装时经 winget 安装 Docker Desktop（`Docker.DockerDesktop`）+ Python 3.12（`Python.Python.3.12`），`--accept-source-agreements --accept-package-agreements`，UAC 提权 = 用户授权环节（非静默）。安装失败不阻断（DetailPrint 提示手动装），Workbench 首启 preflight 兜底报缺。winget 缺失时跳过 + 提示 Store 引导。
- **`nsis/README.md`**：模板来源（tauri-bundler 2.9.4）+ 升级维护说明（diff 默认模板重放 3 处 S4.1.b 扩展，防模板漂移）。
- **CI**：`.github/workflows/nsis-installer.yml`（新）--windows-2022 runner：setup-python + PyInstaller 构建 CLI sidecar -> 移入 `workbench/src-tauri/binaries/aisc-x86_64-pc-windows-msvc.exe`（externalBin 命名）-> setup-node + npm ci -> `npm run tauri build -- --bundles nsis`（tauri 自动下载 NSIS 3.11 + nsis_tauri_utils 插件，零手动 NSIS 配置）-> 产物 `*-setup.exe` upload-artifact。触发：workflow_dispatch + push develop/main paths（tauri.conf/nsis/workflow/src.aisc/packaging）。
- **`docs/platform-windows.md`**（新）：Windows 平台依赖表 + 安装器行为说明 + 实机验证清单（06 §七 S4.1「Windows 检查 WebView2/Docker Desktop」文档要求）。
- 验证：cargo 70 绿（tauri.conf schema 校验通过，`webviewInstallMode` 是 internally-tagged enum 需 `{type: ...}` 形状）；npm build 零错误；**CI Windows runner 全链路验证通过**（`.github/workflows/nsis-installer.yml` dispatch：PyInstaller sidecar → `tauri build --bundles nsis` → makensis 编译定制模板零错误 → `AISC Workbench_2.1.5-dev_x64-setup.exe` 10.9MB artifact 下载验证）；本机 Linux 无 makensis，NSIS 编译只能 CI 验证。**顺带修 2 个 CI 暴露 bug**：(1) `cli-sidecar.yml` step 层 `${{ matrix.shell }}` 无效表达式（GitHub Actions 2.0 拒绝）→ 改 `if: matrix.os` 条件 + 硬编码 shell；(2) `scripts/build-cli.sh` 缺可执行位（git mode 100644 → 100755，Linux/macOS runner exit 126）；(3) `sigint_or_kill(&Child)` Windows release 编译错误（`start_kill()` 需 `&mut`，Unix 分支掩盖）→ 改 `&mut Child`。实机手测清单见 `docs/platform-windows.md`（用户 Windows 实机，待测）。
- gap（明确 deferral）：macOS pkg / Linux preinst 安装体验 -> S4.1.c；签名/公证 -> S4.2 发布门；安装器多语言（zh-CN 等，模板已留结构）-> 后续；winget 安装进度显示（当前 DetailPrint 文本）-> 后续。

#### S4.1.b 修复 — 安装版 Workbench「打开目录 → 构建镜像」失败（2026-08-08）

- **根因（两个叠加）**：① 安装器只装 sidecar exe 无 `aisc-bundle\`，CLI root 发现（`src/aisc/application/resources.py` 冻结 bundle 分支）无来源 → CliError "AISC root not found"（`AISC_ERR_GENERAL`）→ Workbench 显示通用「AISC CLI 返回错误」；Linux dev 正常纯属 CWD 恰好是仓库。② 修好 ① 后必现：`build --events` 路径 `run_streaming_captured`（`src/aisc/adapters/docker_.py`）POSIX-only——`select.select` 在 Windows 管道 fd 抛 WinError 10038、`os.killpg`/`SIGKILL` 不存在，CLI 带 traceback 崩溃、不发 `build.failed` 终端事件 → Workbench 报 `WB_ERR_CLI_PROTOCOL`。
- **Fix B（流式捕获跨平台）**：drain 拆为 `_drain_select`（POSIX 原样保留，零回归）+ `_drain_threads`（Windows：daemon reader 线程 + queue，`on_chunk` 仅主线程调用，超时抛 `subprocess.TimeoutExpired` 与 POSIX 契约一致）；杀子进程统一 `_kill_child`（POSIX `os.killpg` + Windows `taskkill /T /F` 兜底 + `proc.kill()`）。preflight `text=True` 补 `encoding="utf-8", errors="replace"`（Windows 非 UTF-8 区域按 ANSI 解码可崩）。新增 `tests/features/test_streaming_captured_cross_platform.py`（6 用例，任意 OS 可跑，Windows CI 覆盖线程分支）。
- **Fix A（安装器随附 CLI bundle）**：`.github/workflows/nsis-installer.yml` 加 staging 步骤（`packaging/artifact.py stage` → `workbench/src-tauri/nsis/bundle`，复用 stage_bundle + verify_staged_bundle）+ 安装后冒烟（静默 `/S` 安装 → 定位 `$LOCALAPPDATA\AISC Workbench` 下 sidecar → `version --format json` + `build --dry-run --tag smoke:latest --events`，零 docker 调用验证冻结 bundle root 发现）；`tauri.conf.json` `bundle.resources` 映射 `nsis/bundle/aisc-bundle` → `$INSTDIR\aisc-bundle`（目录递归展开，命中 `resources.py` 冻结分支）；staging 产物为 CI 生成构建物，`.gitignore` 排除 `workbench/src-tauri/nsis/bundle/`。
- **Fix C（sidecar 发现名字失配，冒烟测试暴露）**：tauri-bundler 2.9.x externalBin 安装为**基名** `aisc.exe`（去 triple 后缀，7z 检查安装包确认），而 `cli.rs` `sidecar_candidate_in` 只找 `aisc-<triple>.exe` → 安装版永远发现不了 sidecar，回退 PATH（用户机器命中 dev 装的 `aisc`，无随装 bundle → 同一个 "AISC root not found"）。修复：`sidecar_candidate_in` 增加基名候选（triple 名保留兼容既有部署/测试）+ 新单测；冒烟步骤改查 `aisc.exe`（triple 名兜底）。此修复对 macOS/Linux bundle（S4.1.c，安装名同为基名）同样生效。
- **vendor/checksums.txt 刷新（前置修复）**：Dockerfile/entrypoint.sh 在 S0.4（f0877a5）修改后未重算哈希、`aisc-provider-inspect`/`aisc-session-wrapper` 从未录入，`artifact.py stage` 校验（release artifact 流程与本 CI staging 均依赖）全平台失败；`bash tools/vendor-refresh.sh` 重生成（DEVELOP_WIKI 维护要求）。
- 验证：Fix B 单测 6/6 + features 55 绿，`tests.yml` Windows runner（3.11/3.12/3.13）全绿（线程分支）；本机 staging VERIFICATION PASSED（CI 同命令）；`nsis-installer.yml` 全链路绿——staging → `tauri build` → 静默 `/S` 安装 → 冒烟：`aisc.exe` 被发现（基名）→ `version` 返回 `bundle_version: 2.1.5-dev`（随装 bundle root 发现）→ `build --dry-run --events` 发出 build.start/build.plan（bundle 目录为构建上下文）→ SMOKE: PASSED。最终实机全流程（打开目录 → preflight → 构建镜像 → runtime start）待用户 Windows 实机验收（用该 run 的 `aisc-workbench-windows-nsis` artifact）。
- gap（观察项，不在本次范围）：`runtime start` 卷挂载 `-v C:\...:/root/app` 依赖 Docker Desktop file-sharing（Windows 路径盘符/大小写语义）。
- **修复（实机验收暴露，2026-08-08）**：安装新版后「选择工作区 → 下一步」报「未找到兼容的 AISC CLI」。根因：`negotiate_capabilities` 自动选中唯一合法候选但**从不写 pin**——`runtime_preflight` 等所有 runtime 命令只经 `session::resolve_pin` 取 CLI，全新安装协商通过后仍无 pin → preflight 直接 `cli_not_found`。叠加 Fix C：sidecar 基名可发现后安装版合法出现 2+ 候选（sidecar + PATH dev CLI），旧「恰好一个」门在 ≥2 时同样报 `cli_not_found`。修复（cli.rs `negotiate_capabilities`）：按优先级（S4.1.a sidecar > PATH > platform）取**第一个**合法候选并协商成功后**持久化为 pin**（镜像 `cli_pin` 语义），0 合法才报 `cli_not_found`。验证：NSIS CI run 31260617514（编译 + 冒烟）→ 实机复测。
- **安装向导中文化（2026-08-08，用户请求）**：`tauri.conf.json` `bundle.windows.nsis.languages` 加 `SimpChinese` + `displayLanguageSelector: true` → 首次安装显示语言选择框（MUI LangDLL，记忆于 HKCU 注册表，静默 /S 自动跳过）；MUI 页面字符串来自 tauri-bundler 内嵌语言文件，S4.1.b 自定义字符串（依赖检查页标题/组件/按钮/状态、完成页「启动 AISC Workbench」、Section Dependencies 日志）以 `LangString DEP_*` 双语定义（installer.nsi 语言 include 之后）。编码要点：模板源文件保持 UTF-8 无 BOM，tauri-bundler 渲染时加 BOM + `-INPUTCHARSET UTF8` 编译，CJK 在任何区域均正确渲染（en-US CI runner 上中文不mojibake）。验证：NSIS CI 编译 + 静默安装冒烟 → 实机看语言框与中文 UI。
- **修复（实机验收暴露 #2，2026-08-08，GBK stdout 崩溃）**：重装后 preflight 通过、构建真实启动（docker 输出流式正常），中途报「AISC CLI 输出不符合协议」。实机复现（后台跑安装版 sidecar `build --events`）抓到 traceback：`JsonlEmitter.emit` → `UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f4e6'`。根因：zh-CN Windows 上冻结 CLI 的 `sys.stdout` 是 GBK 编码，buildkit 输出含 emoji（`#N [1/50] FROM` 行的 📦），`print(json.dumps(..., ensure_ascii=False))` 崩溃 → CLI 带 traceback 退出、无终端事件 → Workbench 报协议错误。CI 冒烟不触发（`--dry-run` 不流式转发 docker 输出；runner 区域设置亦非 GBK）。修复：`emit_json`/`JsonlEmitter.emit` 改 `ensure_ascii=True`（协议线纯 ASCII，Rust serde_json 解析 `\uXXXX` 转义结果一致）+ `main()` 入口 `sys.stdout.reconfigure(errors="replace")`（其余不可编码输出降级为 `?` 而非崩溃）+ 回归测试（GBK TextIOWrapper + emoji chunk + CJK envelope，9/9 与流式 6/6 本地绿）。验证：NSIS CI run 31261676013 + tests.yml 31261677484 → 实机复测。
- **修复（实机验收暴露 #3，2026-08-09，依赖检测误报 + winget 弹终端）**：Deps 页对已装的 Docker/Python 报「未找到」，点安装后弹黑框秒退（winget 发现其实已装）。根因：`CheckDocker` 查 `HKLM\SOFTWARE\Docker Inc.\Docker Desktop\DefaultPath`——该键不存在，Docker Desktop 实际注册在卸载键 `InstallLocation`（机器级装在 `Program Files\Docker\Docker`）；`CheckPython` 读 `PythonCore` 键**默认值**——恒为空，真实路径在 `PythonCore\<版本>\InstallPath`（本机 3.14 在 HKLM 64 位视图、3.12 在 HKCU，均读不到）。修复：Docker 查真实双路径（`$PROGRAMFILES64` + `%LOCALAPPDATA%`）+ 卸载键 `InstallLocation` 兜底（64 位视图 → HKCU → WOW6432Node），并记住 exe 路径供「启动 Docker」按钮复用；Python 枚举 `PythonCore` 版本子键（SetRegView 64/32 + HKCU）验证 `InstallPath\python.exe` 真实存在，结束恢复 32 位视图（32 位安装器进程其余模板依赖默认重定向视图）；winget 从 `ExecWait`（弹控制台窗）改 `nsExec::ExecToLog`（隐藏控制台、输出实时流入安装日志），退出码非 0 时**重新检测**——winget 对「已安装」返回非 0，以实际状态而非退出码判定成功。验证：本机装 makensis 3.12，`check-deps-test.nsi`（生产函数逐字复制 + 真编译真运行 `/S`）→ `docker_installed=1` / `python_installed=1`；`nsExec::ExecToLog` 退出码压栈实测确认。CI 重建安装包 → 实机复测。
- **修复（实机验收暴露 #4，2026-08-09，winget 日志乱码）**：`ExecToLog` 流式显示的 winget 输出是乱码。字节实测（管道重定向捕获 winget stdout）：`E5 90 8D...` = **UTF-8**（.NET 在 stdout 重定向时写死 UTF-8），而 nsExec 按系统 ANSI 代码页（GBK）转换 → 中文变「鍚嶇О」式乱码，无解（无法让 winget 改吐 GBK）。修复：改 `nsExec::ExecToStack` 静默捕获丢弃输出（压栈序退出码→输出，makensis 实测确认），日志只显示本地化状态行（「正在安装……（可能需要几分钟）」→ 装完重检测 → 成功/失败+退出码）。无窗口、无乱码。

#### S4.1.a CLI sidecar 打包与分发基础（06-implementation-plan.md §六 S4.1；02 §四.3）

- **PyInstaller CLI 独立二进制**：`packaging/aisc.spec`（onefile、console=True--CLI 是控制台工具，`session open` 经 PTY/ConPTY 需 console subsystem；piped spawn 用 CREATE_NO_WINDOW 防窗口闪现）+ `scripts/build-cli.sh`（linux/macos，TARGET_TRIPLE 命名）+ `scripts/build-cli.ps1`（windows）。产物 `aisc-<target-triple>`（Tauri externalBin 约定）。本地产物 10MB 单文件，`version --format json` envelope 正确。
- **CI 矩阵**：`.github/workflows/cli-sidecar.yml`（workflow_dispatch + push develop/main 触发，paths 过滤 src/aisc/packaging/scripts/VERSION）--ubuntu/windows/macos 三平台 PyInstaller 构建 -> `actions/upload-artifact`（release 时供 Tauri bundle 使用）。
- **Tauri sidecar 集成**：`tauri.conf.json` `bundle.externalBin: ["binaries/aisc"]`（Tauri 自动追加 target triple，Windows 自动 .exe）；`version` 0.1.0 -> **2.1.5-dev**（对齐 CLI VERSION，capability 协商兜底版本失配）。**手动路径解析**（不引 shell plugin，S3.2 原则）：`sidecar_candidate_in(exe_dir)` 查 exe 同目录 `aisc-<triple>`（含 .exe），`target_triple()` cfg 匹配。
- **cli.rs discovery 候选序**：`explicit > saved pin > sidecar > PATH > platform`（02 §四.3 + S4.1.a；内置 CLI 优先于 pip/PATH 装的，用户显式 pin 仍可覆盖）；`CandidateSource::Sidecar`（TS CandidateSource 同步加 `"sidecar"`）。3 个新单测（sidecar 优先级于 PATH、查找、缺失）。
- **`--aisc-cli` 启动 arg 接线**（S2.1 deferred）：main.rs 解析 `--aisc-cli <path>` -> lib.rs `run(cli_arg)` -> `.manage(CliArg)` managed state -> cli.rs `explicit_cli_path()` 在 negotiate/discover 优先（进程 arg > saved pin > sidecar）。
- `.gitignore`：`workbench/src-tauri/binaries/`（sidecar 二进制 CI 生成，不提交）+ `.dockerignore` 同目录。
- 验证：cargo 70 绿（59 lib +3 sidecar + 7 cli + 4 pty，零回归）；npm build 零错误；本机 PyInstaller 产物验证；dev 无 pin 启动（唯一候选 sidecar，capability 协商直接验证通过）；`npx tauri dev -- -- --aisc-cli <path>` 透传验证（`Running workbench --aisc-cli ...`，tauri CLI 双层 `--` 才透传 app args）。
- gap（明确 deferral）：Windows NSIS 定制安装器（winget 引导装 Python/Docker/WebView2）-> S4.1.b；macOS pkg / Linux preinst -> S4.1.c；Docker 安装检测 UI -> S4.1.b；平台依赖文档完整版 -> S4.1.b/c。

#### S3.3 可访问性（06-implementation-plan.md §六 S3.3；02 §十二；04 §九）- Phase 3 收尾

- `TabBar.vue`：ARIA tabs 键盘导航--`@keydown` on tablist：ArrowLeft/Up 前一、ArrowRight/Down 后一（wrap-around）、Home/End 首尾，激活 + `tabRefs[i].focus()` 焦点跟随（04 §九）；`aria-controls` 指向终端。
- `App.vue`：aria-live 区域（`role="status" aria-live="polite"` + `role="alert" aria-live="assertive"`，`.sr-only` 视觉隐藏）；`announce(text, alert)` helper **节流 ~1s**（burst 合并为最近一次，普通 poll 不播报，04 §九）；`watch(store.runtimeState)` 状态变化播报「Runtime Running/Stopped/…」、`watch(store.error)` 失败播报（alert）。平台快捷键（capture-phase window handler）：`Ctrl/Cmd+1..4` 切 tab + **自动聚焦目标终端**（`defineExpose({focus})` + `terminalRefs` Map + `nextTick` 延迟 focus--同步 focus 时 v-show 切换未完成、xterm 不可见导致焦点无效，实测需按两次才聚焦，nextTick 修复）、`Ctrl/Cmd+Enter` 摘要启动；终端聚焦未修饰键归 xterm（路由优先级，06 §六.3.3）；onBeforeUnmount remove listener + clear announceTimer（cleanup 延续 S3.1）。
- `styles.css`：`:focus-visible` 全局轮廓（键盘导航可见、鼠标点击不显）。
- 非仅靠色审计：PreflightGate dot+状态文本 ✓、Sidebar state+freshness 文本 ✓、TabBar 状态文本 ✓（文档确认无仅色项）。
- 验证：npm build 零错误；cargo 零改零错；dev 无 panic；实机手测通过--键盘 Tab 全流程（picker 输入+下一步、summary Ctrl+Enter 启动、ready 后 Ctrl+1..4 切 tab 直接输入（nextTick focus 修复后一次到位）、TabBar 方向键/Home/End 切换焦点跟随、focus-visible 轮廓、终端未修饰键输入正常、常规回归不破）。
- gap（明确 deferral）：屏幕阅读器完整 smoke test（NVDA/VoiceOver 真机）-> release 实机；OS 级全局快捷键 -> MVP 不做（06 §六.3.3）；焦点陷阱/复杂 roving tabindex -> 简单方向键导航已够。

#### S3.2 安全硬化（06-implementation-plan.md §六 S3.2）

- **显式 CSP**：`tauri.conf.json` `app.security.csp` 从 `null`（宽松）改为显式：`default-src 'self'; connect-src ipc: http://ipc.localhost ws://localhost:1420 http://localhost:1420; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; script-src 'self'`。`ipc:` + dev 端口给 Tauri IPC/vite HMR，`'unsafe-inline'` style 给 Vue scoped style 运行时注入。dev 实测 HMR/终端/样式不破。
- **移除未用 opener**：前端零调用 `openUrl`/`openPath`（grep 确认）-> `Cargo.toml`+`Cargo.lock` 移除 `tauri-plugin-opener`、`lib.rs` 移除 plugin init、`capabilities` 移除 `opener:default`、`package.json` 移除 `@tauri-apps/plugin-opener`。最小攻击面（Workbench 不打开外部 URL）。
- **破坏性操作确认**（`confirm` 原生对话框，取消不执行）：`stopRuntime`（侧栏，有活动 session 时文案含数量「有 N 个活动会话，停止将结束它们并停止 Runtime」）、`stopConflictRuntime`（「停止 Runtime <id 前 8 位>？容器将停止但保留」）、`removeConflictRuntime`（「移除/强制移除运行中 Runtime <id 前 8 位>？容器与元数据将永久删除」，force 文案区分）。
- **`docs/security-checklist.md`**（新）：安全验证清单--Tauri 配置（CSP/最小权限/opener 移除）、破坏性操作边界（confirm/退出确认/workspace 只读预检）、secret 与敏感数据（history/settings 无 secret、PTY scrollback 不持久化、粘贴 1MB cap S1.3、redact 脱敏）、进程与资源（无孤儿进程、无持久化日志通道）。已知 defer：签名/公证（S4）、Provider 密钥（MVP 从不读）、完整日志通道（无持久化日志）。
- 验证：cargo 67 绿（opener 移除 + CSP 编译零回归）；npm build 零错误；dev 无 panic/CSP 错误；实机手测通过--CSP 不破 HMR/终端/样式、确认弹窗（取消不执行/确认执行）、常规回归正常、`~/.config/cn.aisc.workbench/` 仅 history.json/history.lock/settings.json（无 scrollback/日志/secret 文件）。
- gap（明确 deferral）：macOS 签名/公证 + Windows 代码签名 -> S4 发布门；8h/10 session/高输出长测 -> release 实机。

#### S3.1 并发与异常硬化（03-lifecycle-contract.md §九；04-observability.md §六.2）

- 后端 `runtime.rs`：`OpMutexes` managed state（`HashMap<runtime_id, Arc<tokio::sync::Mutex<()>>>`，std Mutex 护 map、tokio Mutex 跨 await 持锁）+ `acquire_op_lock`（`lock_owned`，guard 命令结束时 drop 释放）。`stop_runtime`/`runtime_restart`/`remove_runtime` 在 run_control 前 acquire 该 runtime_id 的锁：**同 runtime 串行、不同 runtime 并发**（03 §九.1/§九.6；Tauri op mutex 只处理本进程排序，跨进程由 CLI registry/workspace lock 保证）。`start_runtime` 仍用 StartOp 全局单 start token。`lib.rs` `.manage(OpMutexes::default())`。2 个 tokio 单测（同 id 二次 acquire 阻塞、不同 id 并发立即获锁）。
- store `stores/runtime.ts`：**request_seq/revision reducer**（04 §六.2）替换 S2.2.b 的 observed_at 排序守卫--`requestSeq`/`lastAppliedSeq`/`revision` 计数器；`refreshRuntime`（轮询）每次 `++requestSeq` 赋 seq，`applyRuntimeSnapshot(snap, seq)` 仅当 `seq >= lastAppliedSeq` 才 apply（stale 低 seq 响应丢弃，慢 poll/被控制操作取代的响应不覆盖新状态）+ revision 递增；控制操作（ensureRuntime start/reuse/restart）赋 `++requestSeq`（restart apply snapshot；start/reuse 设代际边界 `lastAppliedSeq = ++requestSeq`，supersede 在途旧 poll）。observed_at 仍用于 freshness 显示（不再用于排序）。`resetWorkspace`/`stopRuntime` 重置 seq/revision。
- **cleanup 审计**（无缺口需修）：useRuntimePolling/useProviderPolling `stop()` 清 timer + remove 3 listeners（visibility/focus/blur）✓；Terminal `onBeforeUnmount` closePty + clear resize timer + disconnect ResizeObserver + remove window resize listener ✓；store `startTimer`（stopTimer 清）/`saveTimer`（debounce，app 生命周期 OK）✓。useProviderPolling 的 `watch(activeTabId, runtimeState)` 不 unlisten（App 根组件生命周期，可接受，文档注明）。
- 验证：cargo 67 绿（56 lib+2 op lock+7 cli+4 pty，2 新测试零回归）；npm build 零错误；dev 无 panic；实机手测回归通过--常规流程（picker->summary->Start/恢复布局->多 tab->停止->重进）正常，侧栏 Runtime 项（state+freshness+observed）轮询正常更新，控制台无报错。
- gap（明确 deferral）：operation_id for control ops（cancel 流程已处理 start 取消；UI 单 op 按钮禁用无并发竞态）-> 后续多 op 并发再加；两窗口 runtime state 细粒度 merge（CLI 跨进程锁 + 轮询已覆盖）-> 后续；Docker daemon 重启/runtime OOM 特殊处理（轮询检测 unknown/stopped，session 经 PTY 自终）-> 无额外代码；8h/10 session/高输出长测 -> S3.2（scrollback 不持久化）+ release 实机。

#### S2.4.b 恢复布局（resume layout）（02-startup-flow.md §2.3；03-lifecycle-contract.md §六）- Phase 2 收尾

- 纯前端切片（无后端）。关 Phase 2「恢复布局」gate。「崩溃后发现 runtime」gate 已被 S2.4.a recents + S2.2.b discovery 覆盖（preflight 显 reuse/restart，不自动 stop/remove）。
- store `stores/runtime.ts`：`buildPatch` 只记 **open（非 idle）tab**（之前记全部 4 个），使 history layout 反映实际开着的 tab；`restorableLayout` computed（preflight reuse/restart + history 该 workspace 有 open tabs 时返回 `{agents, activeAgent}`）；抽 `ensureRuntime()`（start/reuse/restart 共用逻辑）；`initTabs(agentsToOpen[], activeAgent?)` 重构--为指定 agents 各开新 session（新 session_id，**不续接 PTY**，03 §六）；`launchRuntime(agentsToOpen, activeAgent)` 共用「ensureRuntime + initTabs + cancel/error 处理」；`startFromSummary` 改调 `launchRuntime([launch.agent], launch.agent)`；`resumeLayout()` 调 `launchRuntime(historyAgents, historyActive)`。
- `LaunchSummary.vue`：preflight reuse/restart + history 有 open tabs 时显**「恢复布局」按钮** + 蓝色文案「检测到上次的标签布局。「恢复布局」会为各标签启动新的 Agent 会话，不会续接上次终端内容」（02 §2.3）。`Start`=空白打开（单 tab），`Cancel`=选择其他工作区（等效 contract 的 resume prompt [恢复布局]/[空白打开]/[选择其他工作区]）。
- 验证：npm build 零错误；cargo 零改零错；dev 无 panic；实机手测通过--开 claude+bash 两 tab 关 app 重启 -> picker 点该工作区 -> summary 显「恢复布局」+ 文案 -> 点恢复布局 -> runtime reuse/restart + 自动开 claude+bash 两新 session（独立可交互）+ active 为上次的；Start 空白打开只开 1 tab；关 app 重启恢复布局仍可用。
- gap（明确 deferral）：孤儿 session 检测/处理（`session list` 找无 PTY session -> 结束/忽略，03 §8.1）-> S3.1/后续；窗口几何 save/restore（02 §九.2）-> 后续；独立 resume prompt 视图（本切片用 summary 按钮等效）；history 损坏可恢复错误 UI -> 后续。
- **Phase 2 验收门**：✅ 首次启动/快速启动（S2.1.a）/恢复布局（S2.4.b）三条主路径通过；✅ Docker 未运行/CLI 过旧/镜像缺失/workspace 无权限稳定可操作错误（S2.1.a）；✅ GUI 外 stop/remove 轮询周期内显真实状态（S2.3.a）；✅ 崩溃后重启发现 runtime 不自动 stop/remove（S2.4.a recents + S2.2.b discovery）；✅ 两窗口并发更新 history 不丢 workspace/tab（S2.4.a fs4 锁 + expected_revision 有界重试）。Phase 2 完成。

#### S2.4.a history 持久化 + 最近工作区（02-startup-flow.md §九；06 §五 S2.4）

- 后端 `history.rs`（新模块）：schema-versioned `history.json`（02 §九.2 subset：schema_version/revision/workspaces，含 runtime ref + layout tabs）。`load(dir)` 缺失->空、corrupt JSON->隔离 rename `.corrupt`、unsupported schema->error 不覆盖。`save(dir, expected_revision, patch)`：**fs4 跨进程锁**（`history.lock` exclusive，~5s 超时 fail-closed）-> 锁内 reload -> `revision != expected_revision` 返回 `Conflict{current_revision}` -> merge patch（upsert by path，保留其他 workspace，02 §九「多窗口只 patch 自己拥有的」）-> revision+1 -> 原子写（temp+fsync+rename，复用 settings.rs 模式）。命令 `load_history`/`save_history`。`error.rs` 加 `history_conflict()`（WB_ERR_HISTORY_CONFLICT，store 据此重试）/`history_error()` 构造器。`session.rs` `config_dir` 改 pub。`Cargo.toml` 加 `fs4`。7 个单测（round-trip / corrupt 隔离 / revision conflict / merge 保留其他 / unsupported schema 不覆盖 / upsert / load-missing）。
- 前端 `types/index.ts`：`WorkbenchHistory`/`WorkspaceRecord`/`RuntimeRef`/`Layout`/`TabRecord`/`HistoryPatch`。`lib/ipc.ts`：`loadHistory`/`saveHistory(expectedRevision, patch)`。
- store `stores/runtime.ts`：`history`/`historyRevision`/`lastRuntimeRef`/`recentWorkspaces`（按 last_used desc）；`loadHistory`（startup negotiate 并行）；`scheduleSave`（debounce 300ms）在 runtime ready / tab open/activate / workspace 选中 时持久化；`doSave(retries)` Conflict -> reload+adopt revision+有界重试 3 次；`selectRecentWorkspace(path)` 从 history 恢复 launch config（image/network/scope/agent）+ lastRuntimeRef（02 §六 优先级），避免 preflight 用默认配置与已有 runtime 冲突 + 防止 null 覆盖 disk runtime ref。
- `App.vue`：picker 加最近工作区列表（basename + 全路径 + last_agent），点击 `selectRecent` -> `store.selectRecentWorkspace`。
- **测试中修 2 个遗留 bug**：(1) `runPreflight` 之前把所有 `recommended_action=resolve_conflict`（任意 check 失败都返回）路由到冲突视图，导致 workspace/image 失败时进冲突视图且 `loadConflicts` 空->死锁；改：仅 `runtime_conflict` check 自身 fail 才进冲突视图，其他失败进 summary 显真实 gate。(2) `backToSummaryFromBuild` 之前有 stale preflight 时不 re-preflight，build 完返回摘要仍显旧「缺镜像」-> Start 禁用；改：清 stale preflight + 总是 re-preflight。
- **`.dockerignore` 修复**（build-context-perf memory，阻塞测试时顺手修）：原 `node_modules/` 只匹配顶层，漏了 `workbench/src-tauri/target`（15G）/`workbench/node_modules`/`.venv`；加 `**/target/`/`**/node_modules/`/`.venv/`/`**/dist/`，build context 15.57GB -> 72MB。（buildx 切换仍 defer，`docker buildx` 未装。）
- 验证：cargo 65 绿（54 lib+7 history+7 cli+4 pty，7 新 history 测试零回归）；npm build 零错误；dev 无 panic；实机手测通过--选工作区 start+开 tab 关 app 重启 -> picker 最近列表显该工作区 -> 点击恢复配置进 preflight -> start；`history.json` schema/revision/workspaces(runtime ref+4 tabs layout) 正确。
- gap（明确 deferral）：启动对账（runtime list 合并 history vs 实际）+ 恢复布局提示（恢复布局/空白打开）+ 为 tabs 创建新 session（文案「不续接」）+ 孤儿 session 检测/处理 -> S2.4.b（关「崩溃后发现 runtime」+「恢复布局」gate）；窗口几何 save/restore -> S2.4.b；两窗口同 workspace 细粒度合并（MVP last-write-wins on same path）；history 损坏可恢复错误 UI -> S2.4.b（a 静默隔离）；buildx 切换（CLI adapter）-> 后续。

#### S2.3.b Provider 状态 + P1 可观察性（04-observability.md §二.P1/§四.2/§五；05-cli-gui-contract.md §七）

- 后端 `runtime.rs`：`ProviderStatus{runtime_id, agent, provider_id, provider_name, route_mode, auth_status, observed_at}`（secret-free，仅路由/auth 元数据，永不含密钥）+ `provider_current_argv` 纯函数 + `get_provider_status(app, workspace, runtime_id, agent)` 命令（包 `aisc provider current --runtime-id --agent <claude|codex> --workspace --format json`，run_control + envelope_error + parse；agent 校验 claude|codex，bash/cc-switch 客户端拒；错误码 `AISC_ERR_PROVIDER_STATUS_FAILED` 经 map_aisc 映射）+ 3 单测（argv 形状 + 完整解析 + 空字段解析）。`lib.rs` 注册。PROVIDER_TIMEOUT=30s。
- 前端 `types/index.ts`：`ProviderStatus`。`lib/ipc.ts`：`getProviderStatus(workspace, runtimeId, agent)`。
- store `stores/runtime.ts`：`providerStatuses: Record<"claude"|"codex", ProviderStatus|null>` per-agent 缓存（04 §四.2「不存在全局 Provider」，claude/codex 各一份不互相覆盖）+ `providerError` + `providerInFlight`（去重）+ `loadProviderStatus(agent)`（仅 runtime running 时查）+ `clearProviderStatuses`（runtime 切换/停止时清）。
- `composables/useProviderPolling.ts`（新）：活动 agent 感知的 provider 轮询--活动 tab 为 claude/codex 且 runtime running 时，切换 tab 立即查 + 15s（聚焦）/60s（失焦）/隐藏暂停（04 §五）；bash/cc-switch 或非 running 不查；`watch(activeTabId, runtimeState)` 触发重查/暂停。
- `RuntimeSidebar.vue`：P1 区--活动 agent 的 provider_name / route_mode / auth_status；bash/cc-switch 显「不适用」；capability 缺失（`!provider_status`）显「Unknown · 需升级 CLI」（04 §八）；加载态「加载中…」；auth_status 着色（configured 绿/login_required·not_configured 黄/unknown 灰，不只靠色）。
- `App.vue`：mount `useProviderPolling`（与 runtime 轮询同 ready 生命周期）。
- 验证：cargo 58 绿（47 lib+7 cli+4 pty，3 新 provider 测试零回归）；npm build 零错误（59 模块）；dev 无 panic；实机手测通过--claude tab 显 provider/route/auth；codex tab 独立缓存；bash/cc-switch 显「不适用」；外部 stop 后不再查 provider。
- gap（明确 deferral）：cc-switch 退出后失效 Claude/Codex provider 缓存并立即刷新活动 Agent（04 §五 末句边缘规则）-> S2.4（tab 生命周期细化时一起）；provider 查询 revision/request_seq 抗乱序硬化 -> S3.1；P2 runtime 详情面板 / aria-live 节流播报 -> S3.3；provider GUI 编辑器 -> 永不（06 §十.6）。

#### S2.3.a 轮询对账 + P0 可观察性侧栏（04-observability.md §二/§四.1/§五/§六；06 §五）

- 纯前端切片（复用 S2.2.b `runtime_inspect(workspace)`，后端零改）。关 Phase 2 gate「GUI 外 stop/remove 在轮询周期内显示真实状态」。
- `composables/useRuntimePolling.ts`（新）：可见性感知 inspect 循环--聚焦 5s / 失焦 15s / 最小化隐藏暂停（04 §五）；±10% jitter；`store.inspectInFlight` 去重；resume（hidden->visible 或 focus）先 `markStale` 再立即 tick。`start/stop` 由 App.vue `watch(store.status)` 驱动（ready->start，离开->stop）。
- store `stores/runtime.ts`：`freshness`（fresh/stale/unknown，04 §六.1）+ `inspectInFlight`；`applyRuntimeSnapshot` 成功 apply 时置 fresh；`markStale()`（失败/resume，保留 last snapshot 标 stale）；`refreshRuntime()`（inspect+apply，dedupe，驱动轮询 + 手动刷新按钮）；`resetWorkspace`/`stopRuntime` 重置 freshness。
- `features/workspace/RuntimeSidebar.vue`（新）：ready 视图常驻 P0 侧栏--Workspace / Runtime state 徽章 + freshness + observed Xs ago（本地 1s timer）+ runtime_id（短显，**点击复制完整 UUID**）+ container_name（点击复制）/ Config(image/network/scope，来自 snapshot.config) / Active agent / Sessions 列表 / 刷新 + 停止 Runtime。状态用文本+色（不只靠色，04 §九）。
- `App.vue`：ready 视图改 `[sidebar | (TabBar+terminal)]`，原 toolbar 内容并入侧栏（删孤儿 `.toolbar`/`.meta` 样式）；mount 轮询 composable。
- `types/index.ts`：`Freshness` 类型。
- 验证：npm build 零错误（58 模块）；cargo 零改零错；dev 无 panic；实机手测通过--外部 `runtime stop` -> ~5s 内侧栏 Stopped·stale；外部 `runtime remove` -> Not found；手动「刷新」即时 inspect（observed 重置）；点击 id/ctr 行复制完整值。
- gap（明确 deferral）：provider status（claude/codex 的 provider/route/auth）+ 刷新 -> S2.3.b（P1）；freshness fresh/stale/unknown 全 revision/request_seq 抗乱序硬化 -> S3.1（本切片 observed_at 简单守卫）；runtime_stop session reason 精修 / stopped 状态保留 tabs 供 restart -> S2.4（外部 stop 时 session 经 PTY 自终 disconnected，侧栏显 stopped，不自动 restart）；history / 启动 list 对账 / 孤儿检测 -> S2.4；P2 runtime 详情面板（last_operation_error/启动诊断折叠）/ aria-live 节流播报 -> 后续/S3.3。

#### S2.2.b Runtime 状态机 + 管理 UI + 退出确认（03-lifecycle-contract.md §四/§七.2-3/§十；04 §四.1/§六；02 §七.3）

- 后端 `runtime.rs`：`RuntimeSnapshot` 对齐 CLI `to_dict()`--修 S2.1.a 遗留 bug（struct 有 `ready` 字段但 CLI inspect/list 不发 `ready`，deserialize 必败，被 cancel 路径 try/catch 吞了致 inspect 实际从未成功）；现 drop `ready`，加 `config{workspace,image,network,scope}`/`owner`/`config_fingerprint`/`container_id`/`registry_state`/`observed_at`/`stale`，optional 字段 `#[serde(default)]`；新增 `RuntimeConfig`/`RuntimeListResult`。新增命令 `list_runtimes(workspace, owner)`（`aisc runtime list --workspace --owner --format json`）+ `remove_runtime(workspace, runtime_id, force)`（`--force`）。`runtime_inspect`/`stop_runtime`/`runtime_restart` 全部加 `workspace` 参数透传 `--workspace`（修 registry 定位 + config 回填；之前不带 workspace 致 registry_state=missing + config 空），且 stop/restart/remove 返回 `RuntimeSnapshot`（op 结果即 observation）。argv 抽纯函数 + 8 个单测（inspect/stop/restart/remove/list argv + snapshot 反序列化无 ready + docker-only 最小 + list_result）。`lib.rs` 注册 2 新命令；`capabilities/default.json` 加 `core:window:allow-destroy`。
- 前端 `types/index.ts`：`RuntimeSnapshot` 扩全字段（drop `ready`）；`RuntimeState` 补 stopping/stopped/removing；`RuntimeListResult`。`lib/ipc.ts`：inspect/stop/restart 加 workspace 参数；`listRuntimes`/`removeRuntime`。
- store `stores/runtime.ts`：`runtimeState`/`runtimeSnapshot` + `applyRuntimeSnapshot`（observed_at 守卫，旧观察不覆盖新，04 §六.2 简化版；全 revision/request_seq 硬化留 S3.1）；`conflicts`/`conflictError` + `loadConflicts`/`stopConflictRuntime`/`removeConflictRuntime`/`retryFromConflict`；`confirmExit`（02 §七.3：有活动 session 弹 confirm + 结束 owned session + 保留 runtime）。`runPreflight` 加 **discovery**--preflight 前先 `list_runtimes(workspace, workbench)` 找已有 project runtime 复用其 id（修根因：Workbench 每次生成新 runtime_id 不命中 CLI 的 reuse/restart，重进有 project runtime 的工作区必误报 resolve_conflict；现同配置->reuse/restart，异配置->resolve_conflict）。`startFromSummary` restart 路径 apply 返回 snapshot；resolve_conflict 进 `conflict` 状态。`WorkbenchStatus` 加 `conflict`。
- **测试中修 3 个流程 bug**：(1) preflight `resolve_conflict` 原先进 summary 但 `can_start=false` 致 Start 禁用卡死 -> `runPreflight` 见 resolve_conflict 直接进冲突视图；(2) stop 后重进显冲突而非 restart -> discovery 复用已有 runtime id 修复；(3) 退出确认点确认后窗口不关（async `preventDefault` 时序）-> 始终同步 `preventDefault` + allow 则显式 `destroy()` + 加 `core:window:allow-destroy` 权限。
- 组件 `features/startup/ConflictManager.vue`（新）：列出工作区 workbench runtime（id 缩写/state/image·scope）+ 停止（running/starting）/强制移除（running，force）/移除（stopped）+ 重新预检/返回。`App.vue`：`conflict` 视图 + onMounted 注册 `onCloseRequested`（始终 preventDefault + confirm + destroy）。
- 验证：cargo 55 绿（44 lib+7 cli+4 pty，8 新测试零回归）；npm build 零错误；dev 无 panic；实机手测通过--制造 project runtime 冲突 -> 冲突视图列出 -> 强制移除 -> re-preflight -> start -> ready；stop 后重进 -> discovery 复用 -> restart -> ready；有活动 session 关窗弹确认 -> 确认关窗 + runtime 保留运行。
- gap（明确 deferral）：轮询对账/外部 stop-remove 周期检测 -> S2.3；freshness fresh/stale/unknown + revision/request_seq 抗乱序硬化 -> S3.1；stopped 状态保留 tabs 供 restart 的 richer UX + runtime_stop session reason 精修 -> S2.4；history 持久化/启动 list 对账完整版（孤儿/多窗口）/崩溃恢复 -> S2.4（本切片 discovery 是其轻量子集）；Provider/auth + P0/P1 可观察性侧栏 -> S2.3。

#### S2.2.a 多标签 + Session 状态机（03-lifecycle-contract.md §五/§六/§七.1；06 §五）

- 纯前端切片（后端 S1.3 session registry 已是多 session 能力，零改动）。4 固定 agent 标签（Claude/Codex/Bash/cc-switch）共享同一 runtime（03 §二.3/§六），Tab 只是 Session 视图。
- `types/index.ts` 加 `TabSessionState`（`idle` + SessionState）、`TabExit`、`Tab`（tabId/agent/title/sessionId/sessionState/exit）。
- `stores/runtime.ts`：替换单一 `sessionId` 为 `tabs: Tab[]` + `activeTabId`；session 状态机 reducer--`initTabs`（runtime ready 后建 4 标签 + 开初始 agent 标签）、`openTab`/`reopenTab`（新 session_id -> `starting`）、`activateTab`（idle 标签首次激活即开）、`closeTab`（-> `closing` + `close_session`，PTY Exit 事件 finalize）、`onTabOpenOk/Fail`、`onTabSessionExit`（idempotent first-writer-wins，03 §五.2 重复终止事件合并为单一 TabExit）；`stopRuntime` 迭代关所有 live session 后 stop + 回 picker。`resetWorkspace` 统一清 tabs/runtimeId/preflight。
- `Terminal.vue` 重构 tab-scoped：props `tabId`，从 store 读 `tab.sessionId/agent`；每非-idle 标签各一实例，`v-show` 仅活动标签可见（隐藏 PTY 继续跑，切换不丢 scrollback，03 §六.8）；`visible` watch + ResizeObserver 双重 fit（补 display 切换时 ResizeObserver 不触发缺口）；PTY `Exit` 事件为单一终态信号 -> `onTabSessionExit`，`closeTab` 仅触发 closeSession 不自行判定终态。
- `features/workspace/TabBar.vue`（新）：4 标签 + 状态指示（未打开/启动中/关闭中/退出 code N/失败/已断开）+ × 关闭（running/starting/closing）+ ↻ 重新打开（exited/failed/disconnected，新 session_id）。
- `App.vue` ready 视图：TabBar + `v-for` 渲染非-idle 标签 Terminal（key=tabId，v-show active）。
- 验证：`npm run build`（vue-tsc+vite）零错误；`cargo build` 零改动零错误；dev 启动无 panic；实机手测通过--4 标签开/关/重开、切换不丢历史、隐藏标签继续运行、停止 Runtime 关全部回 picker、resize 正常。
- gap（明确 deferral）：runtime 状态机/observed_at/revision/freshness/轮询对账 -> S2.2.b；list/remove/force-remove 管理 UI + 冲突复用/停止替换 -> S2.2.b；退出 Workbench 确认 + Tauri 关闭拦截 -> S2.2.b；runtime stop 时 session reason 精修为 `runtime_stop`（现为 transport_error/disconnected）-> S2.2.b 状态机关联；history 持久化/恢复布局/崩溃对账 -> S2.4；Provider/auth Warning + P0/P1 可观察性侧栏 -> S2.3。

#### S2.1.b 镜像构建流式进度（05-cli-gui-contract.md §4.1）

- `cli.rs` 增 `BuildEvent`（JSONL `{protocol,command,run_id,seq,type,ts,data}`）+ `run_build_stream(executable, argv, timeout, cancel, mpsc)`：`tokio::process` spawn + `BufReader::read_line` 逐行解析 `build.*` 事件 -> bounded mpsc(256) 背压；terminal 事件（complete/failed/cancelled）决定返回（complete->Ok，failed->Err(map_aisc(error_code))，cancelled->Err(cli_cancelled)）；取消/超时 `sigint_or_kill`（Unix `libc::kill(SIGINT)` 让 CLI 发 `build.cancelled` + 清 docker 子进程组；Windows fallback SIGKILL = transport failure，§4.1.4）。build.output 仅内存转发、不解析百分比（§4.1.3/§4.1.5）。
- `runtime.rs` 增 `build_image(app, tag, on_event: Channel<BuildEvent>)`（mpsc->Channel 桥接，同 open_session 模式）+ `cancel_build`；`BuildOp` managed state（newtype 包 `Arc<Mutex<Option<CancellationToken>>>`，与 `StartOp` 同型但 Tauri 按具体类型管理 state，必须 distinct 类型--type alias 会 panic "already being managed"）。
- **CLI 修复（S0.5 遗留）**：`output.py` `emit_json` + `JsonlEmitter.emit` 加 `flush=True`--Python stdout 管道下块缓冲，build 事件积压到进程结束才出，违反 §4.1.1「不能等进程结束后一次性返回」；实测 `python -u` 验证，修复后事件即时流出（契约测试 8 个仍过）。
- 前端：`BuildEvent`/`BuildStatus` 类型；`ipc.buildImage/cancelBuild`；store `startBuild`（Channel 只收 build.output 追加 log；终态由命令返回值判定，避开回调 race + TS narrowing）、`cancelBuild`、`backToSummaryFromBuild`（回摘要并 re-preflight）；`BuildProgress.vue`（滚动 log + 经过时间 + Cancel + complete/failed/cancelled + 返回摘要；complete 后停留可看完整 log，不再自动跳走）；App.vue `building` 视图；LaunchSummary 「构建镜像」按钮在 image 缺失时启用。
- 验证：cargo build/test 47 绿、npm build 零错误；CLI 时间戳实测事件流式到达（非突发）；实机手测通过（镜像缺失 -> 构建 -> 实时日志 -> complete -> 返回摘要 re-preflight -> image pass -> Start）。
- 已知观感问题（已记 memory，后续解决）：`aisc build` context = 整个 repo（含 node_modules/target/.venv）-> Docker legacy builder 初始化 ~22s 空档，缓存命中后输出突发；Workbench 侧已加经过时间+占位提示缓解；根治 = `.dockerignore` + 换 buildx。
- gap（明确 deferral）：runtime 状态机/对账/管理 UI（冲突复用/stop-remove）-> S2.2；workspace 最近列表 -> S2.4；多标签 -> S2.2；Provider/auth Warning -> S2.3。

#### S2.1.a 启动与预检主路径（02-startup-flow.md §三/§四/§七/§八）

- 后端 `runtime.rs` 增极薄命令：`runtime_preflight`（`aisc runtime preflight --format json`，解析 `PreflightReport{checks,can_start,recommended_action,matching_runtime_id,conflicts,observed_at}`）、`runtime_inspect`（取消后对账）、`runtime_restart`（reuse/restart 路径）；`start_runtime` 改为可取消--managed `StartOp(Arc<Mutex<Option<CancellationToken>>>)` 状态 + `cancel_runtime_start` 命令（02 §三 每异步操作带 cancel token）。`lib.rs` 注册 4 新命令 + `.manage(StartOp::default())`。无状态机/对账/list/remove（S2.2）。
- 前端启动状态机（`stores/runtime.ts`）：idle/negotiating/blocked/picker/preflight/summary/starting/cancelled/ready/error；持 preflight 报告 + `LaunchConfig{agent,image,network,scope}` + runtime_id/matching_runtime_id + start 计时。actions：`runPreflight`、`startFromSummary`（按 recommended_action 走 start/reuse/restart -> 开 session；resolve_conflict 阻塞）、`cancelStart`（cancel_runtime_start -> inspect -> 保留/停止，02 §八）、`stopRuntime`、`backToPicker`。
- 组件 `src/features/startup/`：`PreflightGate.vue`（逐项 check pass/warn/fail + hard/config 分类，02 §四.2）、`LaunchSummary.vue`（摘要屏 Workspace/Agent dropdown/Runtime reuse|start|restart/Image/Network/Scope + Start/Change settings/Cancel；image 缺失 config gate 禁用 Start，「构建镜像」禁用占位 S2.1.b）、`StartProgress.vue`（经过时间 + Cancel；取消后 inspect -> 保留|停止）。`App.vue` 状态路由壳；`Terminal.vue` agent 改从 `store.launch.agent` 取，sessionId watcher 加 `immediate:true`（修复 Terminal 在 status=ready 后才挂载导致 watcher 漏触发、bash 不出的问题）。
- 类型 `types/index.ts` 加 PreflightReport/Check/RuntimeSnapshot/CheckStatus/RecommendedAction/LaunchConfig；`lib/ipc.ts` 加 runtimePreflight/runtimeInspect/runtimeRestart/cancelRuntimeStart。
- 验证：`cargo build`/`cargo test`（47 绿）零 warning；`npm run build`（vue-tsc+vite）零错误；实机手测全链路通过--picker(原生 dialog) -> 预检 -> 摘要(agent=bash) -> Start -> bash 可交互 -> 停止 Runtime。（测试中遇主机内核升级未重启致 Docker veth 缺失，非代码问题，重启后恢复。）
- gap（明确 deferral）：`build --events` 流式 + 构建进度 UI -> S2.1.b；workspace 最近列表 -> S2.4（history）；runtime 状态机/observed_at/revision/对账/list/remove -> S2.2；多标签 + Claude/Codex/cc-switch 标签 -> S2.2（S2.1.a 单 session + agent 选择）；`--workspace` 启动 arg 接线、resume_prompt -> S2.1.b/S2.4；Provider/auth Warning -> S2.3。

#### S1.1 工程脚手架（06-implementation-plan.md §四）

- 新建 `workbench/` Tauri 2 + Vue 3 + TypeScript 工程；引入 xterm.js + FitAddon；Tauri capabilities 仅允许 Workbench 命名 command；后端仅 `greet` 占位（lib.rs/main.rs）。

#### S1.2 结构化 CLI runner（05-cli-gui-contract.md §九.1 / 02 §四.3 / 03 §十）

- `workbench/src-tauri/src/cli.rs` argv-only runner（禁 shell，05 §九.1）：`tokio::process::Command` + `tokio::select!` 三路（`child.wait` / `tokio::time::sleep` / `CancellationToken`），超时与取消均 `kill`+`wait` 回收子进程；stdout 8MB 上限，超限后 drain-to-EOF 再返回 `WB_ERR_CLI_PROTOCOL`（不阻塞子进程退出）；`aisc.cli/v1` envelope 校验（`meta.protocol` 一致 + `meta.exit_code`==进程退出码，05 §八）。
- discovery/pinning（02 §四.3）：按优先级枚举去重（explicit arg > `settings.json` pin > 进程 PATH `aisc`/`aisc.exe` > 平台已知位置 Linux `${XDG_BIN_HOME:-$HOME/.local/bin}`、macOS `/usr/local/bin`+`~/.local/bin`、Windows `%LOCALAPPDATA%\Programs\AISC`+`%LOCALAPPDATA%\AISC`）；`is_executable` 跨平台（Unix `mode&0o111` / Windows `.exe` 存在）；多安装冲突 `needs_confirm=true`，pinned 失效走 hard gate 不静默换；只保存 canonical 绝对路径，原子写（temp+fsync+rename）。
- capability 协商：`negotiate` 跑 `version --format json` 取 `data.capabilities`，required={runtime,session} 缺失 -> `CapabilityReport(required_ok=false)` 携带 `WB_ERR_CAPABILITY_UNSUPPORTED`（不 panic，前端可显阻塞页而非崩溃）；optional={providerStatus,buildEvents}。值需精确匹配 `aisc.* /v1`（不按版本号猜）。
- `error.rs`：`WorkbenchError{code,message,technical_detail,retryable,action}` + `map_aisc`（§八 全量 `AISC_ERR_*` -> action 路由，不靠 message 字符串匹配，02 §十）+ `redact`（env-var `KEY=VALUE` 与 `sk-` token 脱敏，4KB 上限，UTF-8 安全）；WB_ERR_* 传输/协议码（CLI_NOT_FOUND/TIMEOUT/CANCELLED/PROTOCOL/CAPABILITY_UNSUPPORTED/SETTINGS），action 枚举在 03 §十 基线上加 `choose_cli`。
- `settings.rs`：`settings.json` 读写，保留未知字段（后续切片可扩展），`schema_version` 不支持时保留原文件返回可恢复错误（02 §九）；跨进程锁 deferral 到 S2.4（`history.rs` 切片负责跨平台锁），S1.2 仅原子写。
- Tauri commands：`cli_discover` / `cli_pin` / `cli_clear_pin` / `negotiate_capabilities`；移除 `greet` 占位。
- 测试：25 单测（envelope 校验 / capability classify / error map / discovery 优先级去重 / PATH 查找 / redact / settings 往返与 schema 守卫）+ 7 集成（`python3 -c` 发射 envelope 验 parse/timeout/cancel/stdout-cap/exit-code-mismatch；real `aisc` gated on `AISC_TEST_CLI` -> `required_ok=true`）。`cargo build` 零 warning，`cargo test` 32 全绿。
- gap（明确 deferral）：settings 跨进程锁 -> S2.4；`--aisc-cli` 启动 arg 接线到 `cli_discover.explicit_path` -> S2.1；capability 不支持的阻塞页 UI -> S2.1。

#### S1.3 PTY supervisor（05-cli-gui-contract.md §6.1/§9.2 / 03 §五/§七.1）

- `workbench/src-tauri/src/pty.rs` portable-pty 监督核心（不依赖 Tauri，可本地子进程测）：`native_pty_system().openpty` + `slave.spawn_command` 起 `aisc session open`（text-only TTY，PTY 数据不混 JSON）；三个独立 `spawn_blocking` 任务——write 任务（拥 PTY writer，bounded mpsc 16 = 大段粘贴背压）、reader 任务（阻塞读循环，每 chunk base64 + 单调 seq 经 mpsc 发 `Output`）、wait 任务（拥 child，`child.wait()` 阻塞 -> 定 reason + 发单一 `Exit` + 置 `ExitSignal`）。`child.clone_killer()` 让 close/reader 在 `wait` 阻塞时强杀 child（满足「close 后无孤儿进程」验收门）。
- Linux PTY 语义：slave 关闭时 master `read` 返回 `EIO`（非 EOF），reader 将 `EIO` 视为正常 EOF（不误判 transport_error），其它 `Err` 才是 transport loss（kill child + 标 `transport_error`）。
- `ExitSignal`（`Arc<Mutex<Option<SessionExit>>>` + `Notify`）：idempotent `set`（first writer wins），`wait`/`wait_timeout`；wait 任务 set，close 与 observer 都 await 它，多终止信号合并为单一 `SessionExit`（03 §五）。
- `session.rs`：`SessionRegistry`（`Arc<Mutex<HashMap>>` 作 `tauri::State`）+ 4 个 Tauri command。`open_session` 校验 runtime_id/session_id UUID v4 + agent enum（快失败，映射 `AISC_ERR_INVALID_*`），resolve pin（复用 S1.2 settings，无 pin -> `WB_ERR_CLI_NOT_FOUND`），建 mpsc(256) -> `spawn_pty_session` -> 桥接任务（mpsc -> `tauri::ipc::Channel`，先建 Channel 再起子进程不丢首屏）+ observer 任务（child 自然退出时更新 registry state=Exited/Disconnected + 缓存 exit）。`write_session`（1MB 粘贴上限 -> `WB_ERR_INPUT_TOO_LARGE`，clone writer_sender 跨 await 不持锁）。`resize_session`。`close_session`：移除 entry -> 若已 exited 直接返回缓存 exit -> 否则 `cancel`（user_close reason）+ `run_control` 跑 `session terminate --format json`（幂等，best-effort）+ `signal.wait_timeout(10s)` -> 超时则 `force_kill` + `wait_timeout(2s)` -> 返回 `SessionExit`，scope 结束 drop session 关 PTY（03 §七.1 terminate -> close PTY -> wait/reap）。
- `PtyEvent`（`{type: output|exit|error}`，camelCase 字段，bytes base64）/ `SessionExit`（exit_code/reason/finishedAtMs）/ `SessionState`（starting/running/closing/exited/failed/disconnected）。
- error.rs 增补：`input_too_large()` (`WB_ERR_INPUT_TOO_LARGE`) + `map_aisc` 加 `AISC_ERR_INVALID_RUNTIME_ID` arm。
- deps：`portable-pty 0.9`、`base64 0.22`、`libc 0.2`（EIO 常量）。
- 测试：36 单测（PtyEvent/SessionState 序列化、ExitSignal idempotent/wait/wait_timeout、UUID v4 校验、agent/argv 校验、snapshot camelCase）+ 4 PTY 集成（本地 `sh` 子进程验 Output 流 + exit_code 传递 + write 回显 + cancel user_close + resize；real `aisc session open --agent bash` gated on `AISC_TEST_CLI`+`AISC_TEST_RUNTIME_ID` -> 写 `echo hi_aisc` 收输出 + `exit` -> process_exit，已实机验证通过）。`cargo build` 零 warning，`cargo test` 47 全绿。
- gap（明确 deferral）：`ResizeObserver` 节流 / 标签可见 fit / 终端 UI -> S1.4；runtime_stop 触发 session exited 联动 -> S2.2；disconnected->exited 的 terminate 确认重试 UI -> S2.x；session_list Tauri command -> S2.x。

#### S1.4 最小端到端 UI（06-implementation-plan.md §四 S1.4）

- 极薄 `workbench/src-tauri/src/runtime.rs`：`start_runtime`（`aisc runtime start --runtime-id --workspace --image super-claude:latest --network direct --scope project --owner workbench --format json`，120s 超时，解析 envelope data -> `RuntimeStartResult`）/ `stop_runtime`（`aisc runtime stop`，30s）——直接复用 S1.2 `run_control` + `session::resolve_pin`（后者改 pub），无状态机/对账（S2.2）。`session.rs` `resolve_pin` 改 `pub` 供 runtime.rs 复用。
- 前端 PTY 接线（`Terminal.vue`）：`Channel<PtyEvent>` 先建再 invoke `open_session`（不丢首屏）；`onmessage` Output -> `atob` -> `Uint8Array` -> `term.write`，Exit/Error -> 终端内显式退出/错误行 + 通知 store；`term.onData` -> `TextEncoder` UTF-8 -> `write_session`（后端 1MB 粘贴上限 + bounded mpsc 背压）；`ResizeObserver`（150ms 节流）+ 窗口 resize 监听 -> `fit.fit()` + `resize_session`；watcher 新旧 sessionId 切换时先关旧 PTY 再开新。
- `store`：`negotiate()`（mount 时 `negotiate_capabilities`，`required_ok=false` -> `blocked` 态显阻塞文案 +「选择 AISC CLI」文件 dialog -> `cli_pin` 重协商，不做 S2.1 完整启动流程）；`startBash()`（`crypto.randomUUID()` 生成 runtime_id/session_id -> `start_runtime` -> 置 sessionId 触发 Terminal 开 bash）；`stopRuntime()`（先 `close_session` 后 `stop_runtime`，best-effort）；`pickWorkspace()` 原生目录 dialog。
- `App.vue`：工作区输入（回车也可触发）+「选择」+「启动 Bash」+「停止 Runtime」+ 状态行（status 着色）+ 工具栏错误行（含重试）。
- deps：`tauri-plugin-dialog`（Cargo + `dialog:default` capability）+ `@tauri-apps/plugin-dialog`（npm）。
- 类型：`types/index.ts` 加 `CapabilityReport`/`WorkbenchError`/`PtyEvent`/`SessionSnapshot`/`SessionExit`/`RuntimeStartResult` 等；`lib/ipc.ts` 类型化 invoke 封装。
- 验证：`npm run build`（vue-tsc + vite）零错误；`cargo build` 零 warning；实机手测通过——未 pin 时阻塞页 + 选 CLI、工作区选择、启动 Bash 后终端可交互（`ls`/`echo`/中文/emoji）、resize 跟随、停止 Runtime 确定性关闭，测试后无残留 runtime/容器。
- gap（明确 deferral）：多标签 + agent 选择（Claude/Codex/cc-switch）-> S2.2；启动摘要 + preflight gate + 镜像构建进度 -> S2.1；runtime 状态机/对账/list/inspect -> S2.2；history 持久化/崩溃对账 -> S2.4；Phase 1 验收门余项（10MB 输出、1MB 粘贴、100 次 resize、50 次开关、Claude/Codex smoke、Windows/macOS 实机）= 实机手测清单。

#### S0.3 Session 数据面（05-cli-gui-contract.md §6）

- 新增容器内 `aisc-session-wrapper`（Python）：`open` 从 `/run/aisc/runtime-context.json` 重建 scope 环境（CLAUDE/CODEX/CC_SWITCH config dir，CODEX_HOME 派生），`os.fork`+`os.execvpe`+sync pipe 在父进程 `tcsetpgrp` 后才 exec（消除 SIGTTOU 前台竞态），独立进程组启动受控 agent，原子 0600 `/run/aisc/sessions/<uuid>.json` 记录，wait/reap，传递退出码；`list` 输出 JSON 数组；`terminate` PID/PGID/start-ticks 身份校验 + 向整个 session 的进程组发信号（spare session leader 让 open wrapper reap agent，避免 zombie 堆积在 PID 1 sleep infinity 下）。
- CLI：`aisc session open/list/terminate`，受控 argv（无 shell），runtime_id/session_id UUID v4 + agent enum 校验，稳定错误码；`session open` text-only（拒绝 `--format json`，PTY 数据不混 JSON）；`terminate` 超时跟随 `--grace`（grace+10s）。
- secret-free：record/stdout 不含 env/argv/key；wrapper 断言 context runtime_id 与请求一致。
- 集成测试：bash open project+temporary scope、live-session terminate 无残留、PID 复用/unknown 幂等不误杀。

#### S0.4 Provider 状态 + Workbench capabilities（§4/§7）

- `aisc version --format json` 广告 `capabilities` {runtime, session, providerStatus}（buildEvents 留 S0.5）。
- `aisc provider current --runtime-id --agent claude|codex --format json`：容器内 `aisc-provider-inspect` 读 cc-switch.db(sqlite) + claude settings.json / codex config.toml + OAuth 文件，输出 secret-free `{provider_id, provider_name, route_mode, auth_status}`。`model_provider` 选 active codex entry；`PROXY_MANAGED` 占位符不算 configured；isinstance 守卫防畸形 config。
- `resolve_running_container` 提到 `application/runtime.py` public（#5 cleanup，session+provider 共用，session 保留 alias，零测试改动）。
- 错误码 `AISC_ERR_PROVIDER_STATUS_FAILED`（exit 21）登记到契约 §八 + RFC §4.1（同时回填 S0.3 的 18-20）。

#### S0.5 build --events 契约（§4.1）

- `DockerExecutor.run_streaming_captured(argv, on_chunk)`：`Popen` stdout/stderr=PIPE + 独立进程组（`start_new_session`），select 增量读，每 chunk -> `build.output` 事件；中断时 `killpg` docker 子进程组。
- `run_build --events`：实时 `build.output`（非末尾回放）；KeyboardInterrupt -> `build.cancelled`(130, {image_tag, docker_exit_code, reason}) + exit 130；terminal `build.complete`/`build.failed`(带 error_code) 走 main.py。移除 `build.step.complete`/`build.warning`，image_exists 折进 `build.plan`。
- `buildEvents: "aisc.build-events/v1"` capability 广告；逐 chunk 流式 = 天然背压，无无界缓冲。
- 契约测试 8（成功/失败/取消三流、纯 JSONL、seq 单调）+ 取消集成 1（killpg 无 docker-client 残留）。

#### Phase 0 验收门（§十二）

- 全量 422 passed，capability 与 §4 逐项匹配，Linux Docker E2E 通过；代码级 §十二 全过。
- 修复 `runtime remove` 非幂等：已移除 runtime 的二次 remove 现返回 not_found(rc0)，不再 RUNTIME_NOT_FOUND(rc1)。
- 登记校验类错误码（SCOPE/NETWORK/WORKSPACE/INVALID_AGENT/INVALID_SESSION_ID）到契约 §八 + RFC §4.1 注明退出码与 code 多对一（JSON `errors[].code` 权威）；修正 INVALID_SESSION_ID 退出码 15->2（不再与 INVALID_RUNTIME_ID 冲突）。
- 实机 deferral：claude/codex/cc-switch 交互、PTY 信号链路 -> Phase 1 S1.3；Windows/macOS 实机 -> 手测。

# v2.2.0-dev (2026-08-03 ~ 2026-08-06) — Workbench Phase 0 S0.2: Runtime 控制面

### 变更

- 实现 `aisc runtime preflight` 命令：只读，零副作用，执行 Docker/workspace/image/network/runtime_conflict 五项检查后返回 JSON payload（`docs/gui-planning/05-cli-gui-contract.md §5.1`）。
- Runtime ID 由 Workbench 提供（UUID v4），CLI 严格校验格式；不允许 CLI 自生成 ID。
- 配置指纹 `sha256:<hex>` 对 image/network/scope/canonical workspace 规范化计算，用于幂等重试和复用检测。
- Registry 路径修正：`containers.json`（非 `registry.json`），根目录已含 `.aisc` 时不再嵌套。
- 新增 `list_containers_readonly()`：无锁、无副作用 registry 快照读；文件缺失返回空、损坏则抛异常（fail-closed）。
- GC 修复：lock→snapshot→unlock→inspect→relock→compare→prune 模式，消除锁内 Docker 调用和 NameError 回归。
- `_check_image()` 区分 "image not found" 与 "cannot observe"（Docker 不可用时返回 `DOCKER_UNAVAILABLE` 而非 `IMAGE_NOT_FOUND`）。
- 基于 Docker label `io.aisc.runtime-id` 的容器发现与 reconciliation；Docker 中存在但 registry 中缺失的容器报告为 conflict。
- 旧 registry 记录检测：缺失 runtime_id/scope/owner 的旧条目自动标记为 conflict（按 contract §5.1 行 140）。
- CLI 命令层移除内联 PreflightExecutor，改用 `RealDockerExecutor()` 结构化 API（`preflight()`/`inspect_image()`/`inspect_container()`）。
- 注册 exit codes 14-16（RUNTIME_CONFLICT/INVALID_RUNTIME_ID/RUNTIME_OPERATION_FAILED）到 `docs/rfc/aisc-cli-v1.md`。
- 全部 runtime 测试从 pytest 迁移到 `unittest.TestCase`，同时兼容 unittest discover 和 pytest 运行器。
- 新增 25 个 preflight 单元测试、13 个 subprocess 契约测试、8 个零副作用测试。

#### Runtime CRUD 命令（§5.2-5.5）

- 实现 `aisc runtime start/list/inspect/stop/restart/remove`，覆盖生命周期状态机（`03-lifecycle-contract.md §四`）。
- `start`：workspace lock 内复用 preflight 的冲突判定做幂等/冲突重验（不信任客户端 preflight）；`docker run -d` 以 detached idle 模式创建容器，带 5 个 Docker labels（`io.aisc.managed`/`kind`/`runtime-id`/`owner`/`workspace-key`，不写原始宿主路径）；轮询 `docker exec cat /run/aisc/runtime-context.json` 做 ready check（校验 schema/runtime_id）；成功后才在 registry lock 内提交 registry 记录；registry commit 失败时 `docker rm -f` 清理新容器并返回 partial identity。
- 容器名确定性：`aisc-wb-<runtime_id 前 8 hex>`，支撑幂等重试与定向 `docker rm`。
- 新增 `workspace_lock()`（`.aisc/workspace-locks/<sha256>.lock`，POSIX `fcntl.flock` / Windows `msvcrt.locking`，fail-closed），锁顺序固定 workspace lock -> registry lock，仅 `start` 获取。
- `list`：registry 快照 + Docker inspect 对账；Docker-only 容器标记 `registry_state: "missing"` 不自动删除；Docker 不可用返回稳定错误(3)，不伪装缓存为实时。
- `inspect`：按 runtime_id 在 registry + Docker label 查找，区分 `not_found`/`stopped`/`unknown`。
- `stop` 幂等；`restart` 原配置重启 + ready check；`remove` 运行中无 `--force` 拒绝(16)，`--force` 或已停止才删除容器并注销 registry。
- `container/entrypoint.sh` 新增 idle 分支：`AISC_RUNTIME_MODE=idle` 时完成 scope/cc-switch/目录初始化后，原子写不含密钥的 `/run/aisc/runtime-context.json`（schema/runtime_id/scope/config dirs/ready_time），再 `exec sleep infinity` 保活 PID 1 供 `session open` 接入。
- 修复 registry 一致性：`_state_dir()` 统一接受 workspace root 或 `.aisc` 路径，`_registry_lock`/`_write_registry_unlocked`/`workspace_lock` 共用；修复 `_query_docker_labels`/`_get_container_state` 误用 `returncode`（应为 `exit_code`）的潜在 bug（Mock 执行器下不显现，RealDockerExecutor 下崩溃）。
- 旧 `aisc run/shell/switch/stop` 兼容路径不受影响；新语义全在 `runtime` 子命令族内。

#### Code review 修复（645170b review）

- **锁超时映射**：`workspace_lock`/`_registry_lock` 超时改为抛 `CliError(STATE_LOCK_TIMEOUT, exit 17)`，不再裸 `TimeoutError` 堆栈；注册 exit 17 到 RFC §4.1；`start_runtime` 的 workspace lock 超时改为 `ready_timeout + 30s`，避免并发 start 在 winner 持锁期间误超时。
- **Docker-only registry_state**：`_snapshot_from_registry` 接受 `registry_state` 参数；`_resolve_container_for_lifecycle` 返回 4-tuple 含 registry_state；stop/restart 对 Docker-only 容器正确返回 `missing`（原先误标 `registered`）。
- **`_wait_ready` 瞬态异常**：单次 `docker exec` 异常不再立即返回 None 触发清理，改为继续轮询到 deadline（仅超时或校验失败才返回 None）。
- **重用已停止 runtime**：`start` 重用匹配但已停止的 runtime 时自动 `docker start` + ready check，返回 `reused=True, running, ready`（原先返回 stopped limbo）。
- **proxy_config 接线**：`runtime start` 增加 `--proxy-config` 选项并透传到 `start_runtime`，proxy 模式可挂载 mihomo 配置。
- **entrypoint 安全 JSON**：idle 分支改用 python3 写 `runtime-context.json`（quoted heredoc + env），避免路径含 `"`/`\` 时 shell 插值破坏 JSON。
- 小清理：`_iso_now` 去重（CLI 层改 import）、`_require_image` 用 `RuntimeExitCode.IMAGE_NOT_FOUND` 常量、移除未用的 `conflict_check`、`stop_runtime` docstring 明确幂等边界、`container_name_for` 标注 32-bit 熵、`_list_docker_runtime_containers` 标注瞬态假阴性。
- 新增 7 个回归测试（锁超时映射 ×2、Docker-only stop/restart、_wait_ready 瞬态/超时、重用已停止 runtime）。
- **ac65adb review 回归修复**：锁超时改 `CliError` 后，`start_runtime` 的 register cleanup `except (ValueError, OSError)` 不再捕获它（`TimeoutError` 是 `OSError` 子类，`CliError` 不是），导致 ready 容器成孤儿。新增 `except CliError:` 分支清理容器并 re-raise 保留 `STATE_LOCK_TIMEOUT`。`_iso_now` 改公开名 `iso_now`；workspace_lock 标注 SIGALRM 主线程限制。新增 1 个回归测试。

### 关键提交

- `000a878` 登记 exit codes 14-16
- `69821aa` preflight 垂直切片（domain/application/CLI/tests）
- `d2bd4f3` 消除 registry 读竞态条件
- `59e43c8` 修正 registry 路径和 fail-closed 语义
- `5a983b3` PreflightExecutor → RealDockerExecutor
- `86716e7` 区分不可观测与缺失语义
- `9d1fef9` Docker label reconciliation
- `ab0493a` 旧记录冲突检测
- `96260e8` pytest → unittest.TestCase
- (本批) runtime start/list/inspect/stop/restart/remove + entrypoint idle 模式 + workspace lock

### 状态

- 分支: `feature/workbench-phase0-s0.2`
- 315 tests passed, 8 skipped（含 25 个 lifecycle 单元测试、runtime CRUD 契约测试、真 Docker start->remove 集成测试与并发 start 竞态测试）
- Runtime 控制面（preflight + start/list/inspect/stop/restart/remove）已实现并通过 S0.2 DoD：空 Docker 状态 start->remove 全链路通过，JSON envelope 与退出码一致；同 workspace 并发 project start 只有一个成功，另一个 conflict(14)。
- 下一步：S0.3 Session 数据面（`aisc session open/list/terminate` + 容器内 `aisc-session-wrapper`）。

---

# v2.1.4 (2026-07-24) — Codex 官方登录直连与安全的 Skills 同步

### 变更

- Codex 启动时不再自动执行 `cc-switch proxy -a codex enable`。官方网页登录、本地 `auth.json` 和 Codex 自身配置保持直连，不会因 cc-switch 的托管 Provider 状态出现“未真正登录但可进入界面”的混淆；需要托管账号时仍可显式运行 `cc-switch proxy -a codex enable`。
- 容器交互启动菜单新增第 4 个入口，可直接打开 cc-switch 的 Provider、代理路由与 Skills 管理 TUI。
- 内置 skills 同步改为默认 `auto`：镜像构建时生成 bundle 哈希，普通重启在内容、登记和已启用目标均完整时直接跳过，避免重复复制、写库和全量 `skills sync`。
- cc-switch 中已有 skill 仅刷新元数据，不再在容器启动时强制写回 `enabled_claude=1` / `enabled_codex=1`，用户手动停用状态可跨重启保留；另提供 `AISC_SKILLS_SYNC=always|off`。
- Windows/Docker Desktop 挂载无法取得文件锁时不再静默复制：仅当 `.cc-switch/skills`、`.claude/skills`、`.codex/skills` 全部不存在才直接安装；任一已存在则以 `[y/N]` 请求确认，非交互默认保留宿主内容。
- 增加 Codex 代理默认关闭、skills 增量判定、启停状态保留、同步失败重试标记和无锁降级行为的回归测试。

### 从上一版 Release 到本版

- 上一版 GitHub Release `v2.1.3` 的已发布提交为 `a455bd1`。
- 本版包含后续提交 `a7a0824`、`5b00a73`、`85355dd`，以及本次 Codex 默认直连修复和版本发布提交。
- 完整比较：[`a455bd1...v2.1.4`](https://github.com/wangyuncepu/AISC/compare/a455bd1...v2.1.4)

### 发布

- Git 标签：`v2.1.4`
- 发布类型：稳定 Release（无 `-dev` 后缀）
- 标签推送后由 `.github/workflows/artifact.yml` 自动构建 Linux x86_64、Windows x86_64、macOS arm64 产物，聚合 `SHA256SUMS` 并上传 GitHub Release。

---

# v2.1.3 (2026-07-24) — 稳定发布与跨平台制品校验

### 变更

- 将项目版本从 `2.1.2-dev` 提升到稳定版 `2.1.3`；根目录 `VERSION` 继续作为 CLI、wheel、PyInstaller、bundle、安装包和标签的唯一版本源。
- 重写 README 与开发者手册中的当前版本、cc-switch 配置边界、故障排查和自动发布说明。
- 将本开发日志按版本发布时间重新排序，并依据真实 commit 历史重写 `v2.0.0-dev`。
- 将已经在 `v2.1.2-dev` 验证的 root/cc-switch/单一版本源运行时提升为首个 `v2.1.x` 稳定发布；本版本除版本与发布文档外不引入新的运行时代码。

### 发布

- Git 标签：`v2.1.3`
- 发布类型：稳定 Release（无 `-dev` 后缀）
- 标签推送后由 `.github/workflows/artifact.yml` 自动构建 Linux x86_64、Windows x86_64、macOS arm64 产物，聚合 `SHA256SUMS` 并上传 GitHub Release。

---

# v2.1.2-dev (2026-07-24) — 单一版本源、宿主入口与 cc-switch 收敛

### 变更

- commit `0d1059e`：删除 AISC 自有 Provider catalog、旧密钥存储/迁移、`cs` 命令和宿主 Provider CLI；Provider、认证、代理路由与 skills 统一由 cc-switch 管理。
- 镜像离线内置 caveman、document-skills、grill-me、superpowers，entrypoint 将其幂等登记到 cc-switch SQLite，并以 copy 模式同步给 Claude 与 Codex。
- commit `0a328ef`：删除 `CHANGELOG.md`、`start.sh`、`start.command`、`start.bat`、Shell/PowerShell 启动流水线和旧 Shell doctor；宿主机只保留 `aisc` Python CLI。
- commit `3782b93`：将根目录 `VERSION` 设为唯一版本源；setuptools、wheel data-file、PyInstaller `_MEIPASS`、artifact、CI 和安装包命名全部从该文件派生。
- 从 `config/versions.env` 删除重复的 `AISC_VERSION`；该文件只维护外部依赖 pin。
- commit `1b58668`：通过 `.gitattributes` 固定 vendored 文件行尾，并增加 artifact 回归测试，避免 Windows runner 对 `container/_bundle/` 计算出与 `vendor/checksums.txt` 不同的 SHA256。

### 发布

- Git 标签：`v2.1.2-dev`
- 发布类型：Pre-release

---

# v2.1.1-dev (2026-07-23 ~ 2026-07-24) — root 运行时与 `/root/app` 工作区

### 变更

- commit `72d7a8a`：容器运行身份从 AISC 用户切换为 `root`，路径从 `/home/AISC` 收敛到 `/root`，设置 `IS_SANDBOX=1`，并移除 sudo/递归权限修复链路。
- commit `0511280`、`585c8fc`：cc-switch daemon 使用 detach 模式启动并轮询 readiness；先导入或选择 Codex 当前 Provider，再尝试启用路由；失败日志提供明确路径。
- commit `bb520fd`：发布 root-home 运行时，项目/临时作用域分别使用工作区和 `/tmp/aisc-home`。
- commit `9d88133`：删除已经过时的 `docs/v2.1.0-dev-testing.md`。
- commit `2458f94`：`ensure_writable` 能识别 bind mount 上“路径已存在但不是目录”的情况，并输出真实 mkdir 错误。
- commit `317e648`：工作区挂载恢复为 `/root/app`，避免宿主目录覆盖 root 家目录运行时文件；修复 cc-switch wrapper 的 CRLF shebang，解决 `cannot execute: required file not found`。
- Codex wrapper 默认启用 `--dangerously-bypass-approvals-and-sandbox` 与 hook trust bypass，对齐 Claude 的容器 bypass 模式。

### 发布

- Git 标签：`v2.1.1-dev`
- 发布类型：Pre-release

---

# v2.1.0-dev (2026-07-23) — Claude 与 Codex 双 CLI

### 变更

- commit `6b4372c`：镜像同时安装 Claude Code 与 OpenAI Codex CLI；新增 `codex-wrapper`、`.codex` 配置作用域和启动菜单入口。
- commit `121376d`：容器交互菜单默认进入 bash，便于先检查 Provider 与环境。
- commit `c4b06dc`、`f8c41ef`：引入 cc-switch daemon/TUI/SQLite 运行时，建立项目作用域配置目录，并固化 Codex 出厂目录。
- commit `93beecb`：daemon 就绪后尝试启用 Claude/Codex proxy 路由，清理启动输出。
- commit `585c8fc`：补充 readiness、Codex Provider 初始化和路由启用顺序，避免全新数据库直接启用 Codex 路由被拒绝。

### 发布

- Git 标签：`v2.1.0-dev`
- 发布类型：Pre-release

---

# v2.0.5 (2026-07-22) — 配置管理与 Windows bind mount 修复

### 变更

- commit `4975431`：移除容器启动时对整个工作区的自动权限改写，降低 Windows/WSL2 bind mount 上递归 chown 的副作用。
- commit `502c9fc`：在当时的非 root 运行时中增加 `--user 1000:1000`，缓解 Windows 文件权限问题；该方案随后在 v2.1 的 root 运行时中被替代。
- commits `7d47b9e`、`77cacf6`、`aa83917`：移除 AI 简讯功能及 Dockerfile/PyInstaller 残留引用。
- commits `e9bf280`、`c50f232`：后端状态改为显示 Provider 名，并修复 `--keep-alive`。
- commit `386c1c4`：Docker 构建支持国内镜像源。
- commit `84800d0`：`VERSION` 去掉前导 `v`，兼容 macOS pkg 及 Python 打包。
- commits `0185fbb`、`be0ca72`：收敛配置目录，删除旧 skill 模块与 `.cc-config` fallback。
- commits `d50f2e5`、`a5539ae`：补齐 bundle 配置文件，并把 `aisc-bundle` 移到 `/opt/aisc/bundle/`，避免被工作区挂载覆盖。
- commits `c4de0ba`、`b1616cc`、`9b2e8d0`：修复 `.claude` 初始化、插件路径和 `settings.json` 检测，避免覆盖已有插件配置。

### 发布

- Git 标签：`v2.0.5`
- 发布类型：稳定 Release

---

# v2.0.4-dev (2026-07-21 ~ 2026-07-22) — Provider 预览与启动初始化修复

### 变更

- commit `8487c5d`：增加共享自定义 Provider 的预览实现。
- commits `178be30`、`ee764a6`：README 升级为用户手册，开发资料归档到开发者文档，并增加推荐服务说明。
- commit `4ee3ecc`：启动时增加工作区权限处理并移除 `cs add`。
- commit `d8dfa3c`：改进 `settings.json` 初始化与错误输出，保护用户已有配置。
- commit `a869029`：删除已移除 `cs add` 的相关测试。

### 发布

- Git 标签：`v2.0.4-dev`
- 发布类型：Pre-release

---

# v2.0.3-dev (2026-07-21) — `.aisc` 配置迁移

### 变更

- commits `d9dd35b`、`66192c1`、`6dac625`、`b09b5d5`、`0fcaf13`：修复 CI、Windows stat mock、VERSION smoke 和 workflow 触发条件。
- commits `247a67c`、`7e89cd7`：缺少镜像时自动构建，新增 `--keep-alive`、容器/镜像管理命令。
- commit `d37e8b1`：内部版本推进到 `2.0.2-dev`，同步用户文档。
- commits `410b98b`、`a871b90`、`b6cdc7b`：修复 Windows `os.getuid/getgid` 兼容性，完善镜像/容器管理和 build wizard。
- commit `6e8e01b`：Provider 配置迁移到 `.aisc/providers.json`，移除 `.cc-config` 主路径。
- commits `ba74b24`、`a5e2b34`、`6b3f92c`：修复 Provider fallback、版本 fixture 和剩余 CI 测试。

### 发布

- Git 标签：`v2.0.3-dev`
- 发布类型：Pre-release

---

# v2.0.1-dev (2026-07-20 ~ 2026-07-21) — 多容器管理与自动 Release

### 变更

- commit `0746127`：以容器注册表替代单一 `CONTAINER_NAME` 指针，支持多容器发现。
- commits `3216c35`、`3e522ef`：调整旧 `cs` Provider 集合，并精简容器工具链。
- commit `4a3fd65`：按已实现的安装包和 CLI 行为重写用户安装与命令文档。
- commits `4740521`、`af02f98`、`7f0c3c1`：推进 `2.0.1-dev`，同步包版本和集成测试。
- commits `0f5c523`、`a46c3f1`、`ef57532`：为 PyInstaller 构建接入图标并修复跨平台路径。
- commits `8b6282f`、`cf9edcb`、`d650b69`、`aef3d53`：标签推送后自动创建 GitHub Release，按 `-dev` 后缀区分 Pre-release，并修复权限、资产路径和 draft 状态。

### 发布

- Git 标签：`v2.0.1-dev`
- 发布类型：Pre-release

---

# v2.0.0-dev (2026-07-16 ~ 2026-07-20) — Python CLI、可验证制品与跨平台安装器

本节按 `v1.2.0..v2.0.0-dev` 的真实 commit 顺序重新整理。旧日志曾把计划、未提交实验和后续版本混入同一节，现只保留已经进入 `v2.0.0-dev` 标签的结果。

### 容器与启动体验

- commit `63ee54e`：增加 Windows SSH 服务配置辅助脚本。
- commits `26d8015`、`803897c`、`65f29a7`：建立非 root AISC 用户、双作用域配置、容器权限与插件路径修复。
- commits `271dbcc`、`dd3f655`、`ccd538a`、`8de4326`：加入 Mihomo TUN、多格式订阅转换、模块化宿主启动器、职责目录重组和容器 Python 运行时。
- commits `a3bd55d`、`dbed7b0`、`ec4a45b`、`e9945e4`：加入 OpenAI 协议转换/cc-switch 预研、修复启动代理与权限问题，并实现并发 AI 简讯。

### v2 可用性与仓库结构

- commits `370fb65`、`c651ea3`：将 Docker build context 收敛到仓库根，移除 LiteLLM demo 的默认接线，新增宿主诊断与语法 smoke。
- commits `5c3a52c`、`66b8a50`：目录迁移为 `container/` 与 `apps/ai-brief/`，Provider 元数据改为 JSON 数据驱动。
- commits `e1bddb0`、`33901a2`、`ffb970c`：增加 `--workspace`，状态迁移到 `.aisc/`，密钥采取保守复制迁移，并抽取 entrypoint 公共库。
- commits `ff240ae`、`a8ce21d`：引入 `VERSION`、外部依赖版本表、vendor manifest/checksums/licenses、CI、`vendor-refresh/verify` 和文档一致性检查。
- commits `2b37133`、`4dff7ae`：针对 Linux bind mount 增加真实 I/O probe，禁止递归 chown/chmod，并把镜像内 AISC 用户 UID/GID 对齐到基础镜像的 1000。

### Python CLI 与协议

- commits `c706a68`、`c95bd45`：确定 stdlib Python CLI、`aisc.cli/v1` JSON envelope/JSONL 协议，并建立 legacy characterization tests。
- commit `a8cee46`：实现 `version`、`doctor`、资源定位、结构化输出和 wheel console script。
- commit `4508248`：实现 `aisc build` / `aisc run` 的 Docker planner、executor、dry-run、事件流和错误码映射。
- commits `4894ef0`、`1014acb`、`8fdf9e7`：建立安全配置发现模型，增加 `config validate/effective/show`、profile 和容器管理能力。
- commit `322d5be`：完成技能导入系统与容器生命周期管理 CLI。

### 制品、安装器与验证

- commit `238eed8`：实现 `packaging/artifact.py` 的 stage/archive/verify/build-onefile/aggregate，建立确定性压缩包、版本 guard 和三平台 PyInstaller workflow。
- commit `a227b12`：增加 Windows Inno Setup、macOS pkg 和 Linux/macOS 安装/卸载脚本。
- commits `735fc03`、`36804dd`、`e135bbc`、`5ec3e9d`、`a136c38`：修复 Windows packaging tests、Inno Setup define、PATH 移除、安装器进程等待和 UTF-8 输出。

### 发布边界

- Git 标签：`v2.0.0-dev`
- 发布类型：Pre-release
- 该标签已经包含 Python CLI、跨平台 artifact workflow 和独立安装器；后续的自动 GitHub Release 发布、`.aisc` Provider 迁移、root 容器运行时和 cc-switch 统一管理分别属于 `v2.0.1-dev` 之后的版本。

---

# v1.5.2 (2026-07-16) — AI 简讯性能与可靠性

- commit `e9945e4`：5 个资讯源并发抓取、全局截止时间、瞬时错误重试、gzip/deflate 解压、raw/rendered 双层缓存和 `--debug` 计时。
- `--ai` 模式处理 reasoning-only 输出、token 耗尽和独立 LLM timeout；失败时降素材重试。
- 默认启动路径不再强制同步等待简讯；后续 v2 重构将其进一步解耦。

---

# v1.5.1 (2026-07-14) - 权限修复 + 简讯 URL 增强

### 变更
- **`entrypoint.sh`**：项目模式下对 `.claude` 目录追加 `sudo chown -R AISC:AISC`，解决挂载卷文件属主非 uid 1000 导致 `cs` 写 `settings.json` 时报 `EACCES: permission denied`。
- **`scripts/03_build_image.sh`**：临时构建上下文目录（`image/api_route_demo/`、`image/ai_brief/`）`mkdir -p` 前先 `rm -rf`，避免上次 `sudo` 构建残留 root 文件导致普通用户 `cp` 权限拒绝，`start.sh` 不再强制要求 sudo。
- **`ai_brief/brief.py`**：`--ai` 模式的素材和 prompt 增加原始链接 URL（`🔗`），LLM 输出每条简讯下方附带来源 URL，方便查看详情。

### 取舍
- **`.claude` chown 放在 entrypoint 而非构建期**：构建期 `USER AISC` 后 `chown` 对挂载卷无效（卷在运行时挂载）。entrypoint 启动时 `sudo chown` 自愈，利用 AISC 已在 sudoers NOPASSWD。

---

# v1.5.0 (2026-07-12) - AI 每日简讯注入启动头（TLDR + The Rundown）

### 动机
启动头那段「🚀 [Super Claude] 工作站初始化中... + 后端状态 + 分隔线」纯装饰、无信息量。把每日 AI 资讯（TLDR AI + The Rundown AI）抓取 + LLM 中文精选后注入启动头，每次进容器先看今日要闻；同时支持单独 CLI 输出。

### 变更
- **`ai_brief/` 新建**（项目根，与 `api_route_demo/` 平级）：
  - `brief.py`：**stdlib-only**（urllib + xml.etree + re），Py3.11（容器）/3.14（宿主）双端零安装。flags：`--date`/`--days`/`--top`/`--source`/`--ai`/`--save`/`--no-cache`/`--strict`。
  - `run.sh`：薄包装（`exec python3 brief.py`），绕 DrvFs 无 exec 位。
  - `README.md` + `.gitignore`（忽略 `cache/`）。
- **数据源**（curl 侦察确认）：
  - TLDR：RSS `tldr.tech/api/rss/ai` 拿期次 -> issue 页 `article.mt-3` 块解析（`a.font-bold` 链接 + `h3` 标题 + `div.newsletter-html` 摘要）。
  - Rundown：**无 RSS** -> `sitemap.xml` 过滤 `/p/` 按 `<lastmod>` 取最新 -> post 页（服务端渲染，964KB）解析 H1 头条 + 正文外链次要要闻。
- **规则筛选**：去赞助（blocklist：doubleclick/strandsagents/awscloud/videoask/typeform 等）+ 跨源去重（URL + 标题词集）+ 每源 Top N。Rundown 额外过滤裸域名/导航页/碎片锚文本。
- **`--ai` LLM 中文摘要**：读 cs 后端 env，urllib POST `/v1/messages` 精选 5 条 + 一句话中文。模型优先 `ANTHROPIC_DEFAULT_HAIKU_MODEL`（haiku/flash 档，快+省），回退 `ANTHROPIC_MODEL`。**兼容 GLM thinking 块**（遍历 content 取首个 `type:text`）；`max_tokens=4096`；失败回退规则英文输出。
- **终端渲染**：输出纯文本（编号 + 缩进 + emoji 段头 + 日期），无 `##`/`**` markdown 标记，终端直读；`--ai` 头带日期 `🤖 AI 精选简讯 · YYYY-MM-DD（N 条）`。
- **Dockerfile**：LiteLLM 层后新增 `COPY ai_brief/ -> /home/AISC/ai_brief/`（stdlib-only，无需 pip）。
- **entrypoint.sh**：mihomo 段（§3.5）后、启动菜单（§4）前新增 §3.6 - **有后端配置**（§3 算好的 `BASE_URL`+`AUTH`）才跑 `timeout 45 python3 /home/AISC/ai_brief/brief.py --ai --top 5`（中文精选）；**无后端**（临时作用域/cc/全新）-> 一行「简讯跳过」提示，不显示英文 fallback。BRIEF 空（timeout 杀/全失败）打印诊断行；绝不阻断启动。
- **构建脚本（`03_build_image.{sh,ps1}`）**：api_route_demo staging 旁加 `ai_brief`（brief.py + run.sh）临时进 `image/ai_brief/`，构建后清理。

### 取舍
- **stdlib-only 而非 bs4/requests**：换 Py3.11/3.14 双端零安装（契合 DrvFs/PEP 668/uvloop 约束）。正则解析规整 HTML，站点改版失效则优雅降级（空输出 + exit 0）。
- **启动头走 `--ai` 中文（haiku/flash 档）**：用户要中文；flash 模型控延迟/成本（~10s LLM + 6s 抓取 ≈ 15s）。后端未配/超时 -> 回退规则英文 + 提示；`timeout 45` 兜底（LLM 内部 30s 超时则回退）。实测 GLM-5.2[1m] 大模型 thinking 读超时，改 flash 后稳定。
- **无后端跳过简讯**：临时作用域读镜像出厂 settings.json（无 cs env），--ai 无 LLM 可用；§3.6 检测 `BASE_URL`+`AUTH`，无则一行跳过提示，不回退英文废话。
- **终端纯文本非 markdown**：启动头是终端输出，markdown 源码（`##`/`**`）不渲染显累赘；改纯文本编号+缩进直读。
- **每源独立 try + http_get 单次重试**：单源间歇失败不影响另一源，部分成功仍渲染；`--strict` 供调试非零退出。
- **`--rm` 容器缓存随容器销毁**：每次 `docker run` 重抓+LLM ≈ 15s；宿主单跑或同会话内重跑命中缓存。
- **日期取源站「最新已发刊」一期**：美 newsletter，北京早晨时当日刊未发（美早间=北京晚），故周二早显示周一 7.13 是正确的最新期，非 bug。

### 测试
- 宿主 `brief.py` 全 flag：双源/`--source`/`--top`/`--no-cache`/`--save`/缓存命中/`--ai`（haiku/flash 出中文 5 条 + 日期头）/断网静默 exit 0/`--strict` exit 1。
- 容器内（Python 3.11 + 容器网络）：双源抓取渲染 exit 0。
- **端到端重建**（`super-claude:latest`，项目挂载读 cs 后端）：启动头显示 `📰 今日 AI 简讯：🤖 AI 精选简讯 · 2026-07-13（5 条）` + 5 条中文一句话，纯文本无 markdown 标记；容器正常继续 exec（exit 0）。
- 全脚本 `bash -n` + `ast.parse` 通过。

### 其他
- entrypoint §3.6 注入点在 mihomo 之后（网络就绪）。
- 缓存默认开（`--no-cache` 关），非 `--cache` flag -- entrypoint 用 `--ai --top 5`。
- README 头版本号 v1.4.0 -> v1.5.0。

### v1.5.0 增量 — 多源扩展（5 源）+ 分类面板 TUI

在初版 TLDR+Rundown 双源基础上，curl 侦察见现存源偏向行业新闻（融资/诉讼/模型发布），用户要的是**工具+工作流+方法**。补 3 个 RSS/Atom 源并重做输出格式。

**新增数据源**（curl 验证存活+内容风味）：
- **Simon Willison**（`simonwillison.net/atom/everything/`，Atom）：LLM 实战工具 + 工作流，最贴合。
- **Changelog**（`changelog.com/news/feed`，RSS）：开发工具/开源/agent 工作流讨论。
- **HN Show HN**（`hnrss.org/show`，RSS）：新项目/工具火龙，加 AI/dev 关键词过滤（`ai/llm/agent/tool/cli/dev/claude/cursor/...`）。

**源码重组**（`ai_brief/brief.py` 大幅重写）：
- **源注册表**：`SOURCE_FETCHERS` dict + `SOURCE_GROUPS`（`all`/`tools`/`industry`/`workflow`），`--source` 支持组合（如 `tldr,simon`）。
- **通用 RSS 抓取**：`rss_fetch()` 兼容 RSS `<item>` + Atom `<entry>` + 命名空间（`{http://www.w3.org/2005/Atom}`，Simon feed 实测）。Atom `<link href="...">`（self-closing 有属性无文本）vs RSS `<link>url</link>`（文本值）两格式通吃。**Python 3.14 ElementTree 适配**：`el.find("link")` 对命名空间元素的行为变化，改为 namespace-aware 查找 + 独立 `if None` 检查（避 `or` 触 DeprecationWarning）。
- **HN 过滤**：`hn_filter()` 检查标题+URL 含白名单关键词，拉 3 倍条目再过滤，保证过滤后够 top 数。

**分类面板 TUI**：
- 3 分类：🛠️ 新工具 / 🔧 工作流/方法 / 📰 行业动态。
- 规则模式：按源分到预定义分类（`SOURCE_CATEGORIES`），每分类下子源分块，编号+缩进。
- `--ai` 模式：改 prompt 让 LLM **跨源按内容动态分类**（不按源），每类最多 4 条中文一句话，输出即用。实测深度求索 flash 中文分类质量好。
- 新 `--source` 快捷值：`all`（5 源）/ `tools` / `industry` / `workflow` / 逗号组合。

**取舍（增量）**：
- **Atom 命名空间兼容**：Simon 用 Atom（非 RSS），字段在 `{ns}title/link/summary` 下，通用 `rss_fetch` 同时兼容两格式（按 `els[0].tag` 检测 ns）。
- **分类不由源绑定**：规则模式按预定义表分，`--ai` 由 LLM 按内容分（更准）。
- **仅加 RSS 源不换掉 TLDR/Rundown**：用户选择保留（原说要中文 TLDR，后放宽；Rundown 虽无标准 feed 但因用户要求保留）。

### 测试（增量）
- 宿主：5 源各自单独拉（含 Atom 命名空间修复）、`--source all` 分类规则输出、`--ai` 分类中文（🛠️4 条/🔧4 条/📰4 条）、`--source tools/industry/tldr,simon` 组合。
- 容器端到端：因 Docker bridge 网络故障未重跑（宿主全量验证 + 先前端到端已证 entrypoint §3.6 调用链有效）。待 Docker 恢复后重建 + 验证启动头分类面板。

---

# v1.4.0 (2026-07-10) - LiteLLM 协议转换 + cc-switch-cli 集成

### 动机
TODO「claude code CLI外配置 cc-switch-cli」+ 汇报演示「Claude Code 接入 OpenAI 格式渠道的技术可行性」。内置 `cs` 只切 Anthropic 兼容后端（不改协议）；需 LiteLLM 做 Anthropic↔OpenAI 协议转换，并集成 cc-switch-cli（4.1k stars，多 AI CLI 管理）与 cs 共存。

### 变更
- **LiteLLM Demo（`api_route_demo/` 新建）**：
  - `config.yaml`：模型映射 `claude-3-7-sonnet-20250219`（Claude Code 强校验）-> `openai/gpt-4o`，占位 key。
  - `start_proxy.sh`：交互式输入 base_url + api_key，生成 `.config.runtime.yaml`（含 key 不入 git）；宿主/容器双环境（有 `run_proxy.py` 走 venv python，否则直接 `litellm`）。
  - `run_claude_demo.sh`：注入 `ANTHROPIC_BASE_URL=http://localhost:4000` + 起 claude。
  - `run_proxy.py`：宿主机 Python 3.14 绕 uvloop 不兼容（monkeypatch `ProxyInitializationHelpers._get_loop_type`）。
- **Dockerfile**：
  - LiteLLM 层（venv 后）：COPY demo + `pip install litellm[proxy]`（清华源，`USE_CN_MIRROR` 控制）+ `EXPOSE 4000`；demo 放 `/home/AISC/api_route_demo`（避开 app 挂载点）。
  - cc-switch-cli 层（litellm 后）：`ARG CC_SWITCH_VERSION=v5.9.0` + 下载 musl 二进制（复用 GH_PROXY 多镜像）-> `/usr/local/bin/cc-switch`；`USER root` 临时切 root 写再切回 AISC，**不破坏 litellm 缓存**。
- **构建脚本（`scripts/03_build_image.{sh,ps1}`）**：
  - 国内镜像源从单一 daocloud 改**多源 fallback**（daocloud -> nju -> 163）：优先本地缓存（`docker image inspect`），否则测 manifest 端点（仅 200/401 算通，403 排除），全不通回退官方源。
  - build 前把 demo 3 文件 cp 进 `image/api_route_demo/`（context=image/ 取不到项目根），build 后清理。
- **README**：版本 v1.2.2 -> v1.4.0；加「OpenAI 协议转换」+「cc-switch-cli」亮点与使用章节。

### 取舍
- **cc-switch 与 cs 共存**（非替代）：命令名 `cc-switch` vs `cs` 不冲突；cc-switch 功能全（多 AI CLI 管理），cs 轻量内置，按需选。
- **cc-switch 放 litellm 层后**：litellm pip 重型层缓存保留，重建仅 cc-switch 下载（~10s）；代价是 `USER root`/`USER AISC` 切换（比 sudo 干净）。
- **start_proxy.sh 生成运行时配置**（不覆盖原 config.yaml）：`.config.runtime.yaml` 含 key 加 `.gitignore`；非交互可预设 `OPENAI_API_BASE`/`OPENAI_API_KEY`。
- **构建脚本多源 fallback**：daocloud `/v2/` 通但 manifest TLS 超时、nju 403、Docker Hub 直连超时——多源 + 本地缓存优先是当前网络最稳方案；极端全不通才需配 daemon mirror。
- **宿主机 Python 3.14 兼容**：orjson 强制 3.11.9（litellm 钉 3.10.15 无 cp314 wheel）、uvloop monkeypatch（3.14 移除 `BaseDefaultEventLoopPolicy`）；容器 Python 3.11 无此问题。

### 测试
- 构建成功（`super-claude:latest`，2.55GB）：cc-switch `--version` -> `cc-switch 5.9.0`，ghfast.top 下载通。
- 容器内：`cs` + `cc-switch` 共存（`/usr/local/bin/`）；`/v1/models` 返回 `claude-3-7-sonnet-20250219`（owned_by: openai）；`/v1/messages` 带 placeholder_key 上游 401（config 无语法错误）。
- 宿主机回归：start_proxy.sh 改后仍走 run_proxy.py 分支，proxy 6s 就绪；交互式输入生成正确 YAML，`/health/readiness` 200。

### 其他
- TODO「cc-switch-cli」标完成。
- 发现 `docker rmi -f`（选 [2]）会清构建缓存，增量改动应选 [3] 新镜像名或保留镜像。

---

# v1.3.2 (2026-07-04) — 容器内 Python 运行时

### 动机
TODO「配置 docker 容器系统的 python」——容器内无 Python，Claude Code 无法跑 Python 脚本 / pip 装包。

### 变更
- **Dockerfile**：新增 Python apt 层（放 sed CRLF 之后，避免使 npm/claude 重型层缓存失效）——`python3 python3-pip python3-venv python-is-python3`（Debian 12 → Python 3.11）。
- **默认 venv**：`python3 -m venv /home/AISC/.venv`（USER AISC 后创建，AISC 可写）+ `ENV PATH="/home/AISC/.venv/bin:$PATH"`（venv 挂 PATH 头）。
- 绕过 Debian 12 PEP 668：系统 `pip install` 受限（externally-managed-environment），venv 内 `pip install` 直达，无需 `--break-system-packages`。

### 取舍
- **venv 在镜像内（`--rm` 每次重置）**：pip 装的包每次容器重启回到出厂（仅 pip 升级）。如需持久化包，加 requirements.txt + 启动安装脚本（未做，按需）。
- **Python 版本**：用系统 3.11（Debian 12 自带），不引入 pyenv/deadsnakes（够用）。
- **层位置**：python apt 放 sed CRLF 之后，npm/claude 重型层缓存命中，重建仅 ~30s。

### 测试
- 构建：python apt + venv 层新建，重型层 CACHED。
- 容器内：`which python` → `/home/AISC/.venv/bin/python`；`python --version` → 3.11.2；`pip install requests` → 成功（PEP 668 绕过）。

### 其他
- PLAN 文件从 `docs/TODO/` 移到 `docs/plans/`（与 TODO 分开）。
- TODO #3（启动器规范化）、#5（python）标完成。

---

# v1.3.1 (2026-07-04) — 项目目录重构（按职责分组）

### 动机

根目录 ~18 项混杂（Dockerfile/entrypoint/claude-switch/wrapper/_bundle/downloads/commands/启动器/文档/生成器…），违反高聚合。按职责分组到 `image/` / `scripts/` / `tools/` / `docs/`，根目录收敛到 7 项（入口 + README + 配置 + 锁文件）。

### 变更

- **`image/`**（新建，= 镜像构建上下文）：Dockerfile + entrypoint.sh + claude-switch + claude-wrapper + claude-settings.json + global-claude.md + mihomo-build-config.js + commands/ + _bundle/ + downloads/ 全部搬入。构建上下文从根改为 `image/`，**Dockerfile COPY 路径零改动**（全相对上下文）。
- **`tools/`**（新建）：stage-skills.sh + stage-mihomo.sh 搬入；`DST` 改为 `image/_bundle`、`image/downloads`（`$(dirname "$0")/..` 推导项目根）。
- **`docs/`**（新建）：devlog.md + TODO/ 搬入。
- **`scripts/03_build_image.{sh,ps1}`**：构建命令加 `-f $PROJECT_ROOT/image/Dockerfile` + 上下文改 `$PROJECT_ROOT/image`。
- **根目录**：仅留 README.md + .gitignore + .gitattributes + 3 个入口(.bat/.sh/.command) + skills-lock.json。
- **README**：项目结构章节重写；构建命令全部更新（`docker build -f image/Dockerfile ... image/`）；引用更新（stage-*.sh → tools/，downloads/ → image/downloads/，devlog.md → docs/devlog.md）。

### 取舍

- **构建上下文 = `image/`**：Dockerfile COPY 全相对上下文，搬入后零改动；额外收益——上下文从根（含 `.git/`/62MB 二进制/scripts/docs）缩到 `image/`，**传输更小、构建更快**。
- **`.gitattributes`/`.gitignore` 不动**：模式全局（`*.sh`/`*.ps1`/`claude-switch` 按文件名匹配子目录；`.claude/`/`.deploy/` 全局忽略），移动后仍生效。
- **宿主 `.claude/mihomo/` 留根**：02 写、04 挂载的代理配置是宿主运行时产物，非镜像输入。
- **`skills-lock.json` 留根**：未被构建/启动器引用，锁文件约定根。
- **版本号**：v1.3.0（模块化）已推送，本次续 v1.3.1（目录重构），不 force-push 重写历史。

### 测试

- `bash -n` 全 .sh；PS 语法全 .ps1。
- `docker build -f image/Dockerfile image/` 构建成功（验证上下文 + COPY）。
- e2e：启动器流水线（镜像存在→run）两平台通过。

---

# v1.3.0 (2026-07-04) — 启动器模块化重构（流水线 + 状态解耦）

### 动机

`launcher.ps1`（131 行）/ `启动_AI工作站.sh`（134 行）随 Mihomo TUN、API 配置等功能膨胀，构建/代理/运行逻辑耦合在单体脚本里，违反低耦合高聚合。拆为 4 个生命周期模块 + 薄流水线入口，模块间用状态文件解耦。

### 设计决策

- **D1 · 按平台 .sh + .ps1 平行**（已与用户确认）：bash/PowerShell 各平台自带，零宿主依赖（不选 Node.js 调度——宿主 Node 不可控，违反"开箱即用"）。代价：两套平行逻辑同步维护。
- **D2 · 状态文件解耦**：`.deploy/state.env`（KEY=value，gitignored）。只存简单值 `IMAGE`/`PROXY_ENABLED`/`CONTAINER_NAME`/`DO_RUN`；**路径不入状态**——各模块从 `$0`/`$PSScriptRoot` 推导 `PROJECT_ROOT`，避免空格/特殊字符破坏 `source`/解析。bash `source`/grep 读、PS 正则读；写用追加+去重。
- **D3 · 入口极薄**：根 `.sh`/`.bat` 只按序调 4 模块（pipeline）。
- **D4 · 行为保持**：根文件名 + 双击入口不变；代理 TUI/构建菜单/docker run 参数等价迁移。**API Key 仍在容器内 `cs`**、**作用域仍在 entrypoint**（不挪到宿主 02）。
- **D5 · 容器侧不动**：Dockerfile/entrypoint/mihomo-build-config.js/stage-mihomo.sh 全不变。

### 变更

- **scripts/ 流水线**（新增 12 文件，6 .sh + 6 .ps1）：
  - `run.*` 编排器：`state_init` + 写 `CONTAINER_NAME`/`IMAGE`/`DO_RUN`/`PROXY_ENABLED` 默认值 → 按序调 01-04，任一非零退出即中止。
  - `01_check_env.*`：`docker` 命令存在 + `docker info` daemon 运行；失败友好退出。
  - `02_config_wizard.*`：代理 TUI（y/N → 本地/URL → 下载/拷贝 → 非空校验）→ 写 `.claude/mihomo/config.yaml` + `state(PROXY_ENABLED)`。代理非阻断：失败/跳过 → `PROXY_ENABLED=0` 回退直连（匹配旧行为）。
  - `03_build_image.*`：镜像存在菜单（[1]运行/[2]重建/[3]新名）+ 构建（cache/镜像源提示）+ "立即运行?" → `state(IMAGE, DO_RUN)`。`DO_RUN=0`（选不运行）→ 04 跳过 docker run。
  - `04_launcher.*`：读 state → 清退出的旧容器 → 拼 `docker run`（`PROXY_ENABLED=1` 追加 `--cap-add=NET_ADMIN --device=/dev/net/tun` + 配置只读挂载）。
  - `_state.*`：`state_init`/`state_set`/`state_get`（bash）/ `Init-State`/`Set-State`/`Get-State`（PS）。PS 用 .NET `WriteAllText`（UTF-8 无 BOM + LF）避免 bash `source` 被 BOM/CR 破坏；bash `state_get` 末尾 `tr -d '\r'` 防御。
- **根入口改薄**：`启动_AI工作站.sh` → `exec bash scripts/run.sh`；`一键启动_AI工作站.bat`（ASCII）→ `powershell -File scripts/run.ps1`；`.command` 不变。
- **PS1 BOM**：所有 `scripts/*.ps1` UTF-8 BOM（PS5.1 按 BOM 识别中文）；`.gitattributes` `*.ps1 text eol=lf` 保证提交后 LF+BOM。
- **`.gitignore`**：加 `.deploy/`（运行时状态）。

### 取舍

- **PS 编排用子进程**：`run.ps1` 用 `& powershell -NoProfile -File` 调各模块（独立进程 + `$LASTEXITCODE`），而非 dot-source——dot-source 下模块 `exit 0` 会退出整个 run.ps1，破坏流水线。子进程有 ~1-2s 启动开销，可接受。bash 同理用 `bash scripts/0X.sh` 子进程。
- **DO_RUN 状态位**：03"构建后不运行"需干净中止 04。用 `DO_RUN` 状态位（0/1）而非特殊退出码，符合状态解耦原则。
- **两套平行逻辑**：改提示文案需同步 .sh + .ps1 两份（用户已接受）。

### 测试

- `bash -n` 全 .sh 通过；PS `[Parser]::ParseFile` 全 .ps1 通过。
- e2e 两平台 × 两路径（配/不配代理）全通过：4 模块按序、state.env 正确流转（`PROXY_ENABLED`/`DO_RUN`/`IMAGE`/`CONTAINER_NAME`）、docker run 拿到正确参数（代理路径含 `--cap-add=NET_ADMIN --device=/dev/net/tun` + 配置挂载）。

---

# v1.2.3 (2026-07-04) — 容器内建 Mihomo TUN 透明代理

### 动机

宿主机零代理场景下，让容器内 Claude Code 直连 Anthropic API。在容器内以 Mihomo (Clash Meta) TUN 模式接管全部出站，宿主无需开任何代理；TUI 引导用户完成配置，开箱即用。对应 TODO「clash翻墙配置（docker内部翻墙）」。

### 设计决策（与用户确认）

- **D1 · TUN 补丁容器内权威注入**：宿主启动器只下载/拷贝用户**原始**配置到 `.claude/mihomo/config.yaml`（不打补丁）；`entrypoint.sh` 用 Node 在可写副本上 strip+append。落盘文件保留原始配置，运行时强制含 TUN。理由：容器内 Node+工具必有、每次启动重打、手动丢配置也兜底；宿主环境不可控（Windows BAT 无 Node/awk）。
- **D2 · docker run 特权按需追加**：仅 TUI 选“需要代理”时追加 `--cap-add=NET_ADMIN --device /dev/net/tun` 与配置只读挂载；不配代理则零特权、零 tun 设备依赖，避免宿主缺 `/dev/net/tun` 时启动失败。

### 变更

- **Dockerfile**：apt 增加 `iptables iproute2 ca-certificates`（TUN auto-route 操纵 iptables/路由表、https 下载）；新增 mihomo 下载层（pin `MIHOMO_VERSION=v1.19.27`，arch 自适应）+ geodata 预置层（geoip.metadb/geosite.dat/country.mmdb → `/home/AISC/.mihomo`，单文件失败仅 warn 不阻断）。**下载加固**：优先用 `downloads/` 本地预置（离线/弱网）；否则多镜像轮询（ghfast.top 实测稳，依次 gh-proxy/github.moeyy/ghproxy.net/mirror.ghproxy）+ 强制 `--http1.1`（绕开 curl/GitHub CDN HTTP/2 流异常）+ 短 connect-timeout 快失败 + 直连兜底。
- **stage-mihomo.sh**（新增）：预下载 mihomo.gz + geodata 到 `downloads/`。镜像 `stage-skills.sh`+`_bundle` 自包含哲学；`downloads/` **已纳入 git** → `docker build` 完全不访问 GitHub（详见增量）。
- **entrypoint.sh**：新增 §3.5 — 若 `/etc/mihomo/config.yaml` 存在：Node 读 ro 源 → 通用顶层块剥离（`tun:`/`dns:`）→ 追加规范 `tun:` 块（+ 缺失时补最小 `dns:` 防 53 端口解析死循环）→ 写可写副本 → `sudo -b mihomo -d ~/.mihomo -f 副本` → sleep 2 → pgrep 健康检查 + `curl api.anthropic.com` 探测 → 极客日志。失败仅告警不阻断（便于进 bash 排障）。
- **启动_AI工作站.sh**：新增 `configure_proxy()`（本地文件/URL 二选一，curl 下载，base64 异常检测）+ `docker run` 数组化条件追加 `--cap-add=NET_ADMIN --device /dev/net/tun -v .../config.yaml:/etc/mihomo/config.yaml:ro`。
- **一键启动_AI工作站.bat**：降级为纯 ASCII 三行包装（`chcp 65001` + `powershell -File launcher.ps1`）；中文 UI 与全部逻辑移至 `launcher.ps1`（PowerShell 原生 Unicode）。cmd .bat 对中文有 DBCS 解析缺陷，无法在 .bat 内承载中文（详见增量「Windows 启动器中文化」）。
- **.gitignore**：显式忽略 `.claude/mihomo/`（订阅凭据敏感；`.claude/` 已覆盖，此处防御性显式）。
- **README / devlog**：新增“代理网络（容器内建 Mihomo TUN）”章节（原理图/使用/手动构建/已知限制）+ 数据模型补 `.claude/mihomo/`。

### 取舍

- **DNS 块**：用户 spec 仅列 `tun:`；实测 TUN `dns-hijack: any:53` 无解析器易形成解析死循环 → 仅在用户配置**无** `dns:` 顶层块时补一个最小 `dns:`（fake-ip + 国内外 nameserver/fallback），不覆盖用户已有 `dns:`。
- **mihomo 版本 pin**：v1.19.27（build-arg 可覆盖），换可复现构建；asset `mihomo-linux-<arch>-<ver>.gz` 已核验。
- **mihomo 以 root 启动**：`USER AISC` 无 `CAP_NET_ADMIN`，建 TUN + iptables 必须 root → `sudo`（NOPASSWD sudoers 已就绪）。后台 `sudo -b`，容器退出随 PID1 终止，`--rm` 自动清理。
- **geodata 失败降级**：不阻断构建（GEO 规则不可用，多数订阅仍可用 IP-CIDR/域名规则）。
- **ghproxy flaky**：`GH_PROXY` build-arg 可覆盖；下载逻辑代理→直连回退。

### v1.2.3 增量（多格式订阅自动转换 + 启动器中文化 + 构建下载加固）

- **下载加固（Dockerfile）**：mihomo/geodata 下载层重写——优先用 `downloads/` 本地预置（离线/弱网）；否则多镜像轮询（`ghfast.top` 实测稳，依次 gh-proxy / github.moeyy / ghproxy.net / mirror.ghproxy）+ 强制 `--http1.1`（绕开 curl/GitHub CDN HTTP/2 流异常）+ 短 connect-timeout 快失败 + 直连兜底。修复用户构建时 `mirror.ghproxy.com` SSL 失败 + GitHub HTTP/2 流异常导致下载失败。
- **stage-mihomo.sh（新增）**：预下载 mihomo.gz + geodata 到 `downloads/`。**已纳入 git**（同 `_bundle` 哲学）→ `docker build` 完全不访问 GitHub，国内网络无忧（消除用户提出的「构建期 GitHub 下载慢/失败」风险）。升级 mihomo：改 Dockerfile `MIHOMO_VERSION` 后重跑本脚本更新 `downloads/` 再提交。`downloads/` 为空时构建自动回退多镜像下载。
- **mihomo-build-config.js（新增）**：把原 entrypoint 内联 heredoc 抽成独立脚本（可测、清晰）。职责 = 原始订阅 → mihomo 配置：①格式识别（clash-yaml / base64订阅 / URI直链 / JSON(SIP008)），非 yaml 自动转最小 Clash 配置（proxies + url-test自动选最快 + select + MATCH,PROXY），节点协议支持 ss/vmess/trojan/vless/hysteria2(hy2)；②剥离已有 tun:/dns: 顶层块 → 追加规范 tun:（+ 缺失时补 dns:）。退出码：0 产出配置 / 1 硬失败（空 / 识别为订阅但 0 节点 / 读取失败）。
- **entrypoint.sh**：§3.5 改调 `node /usr/local/bin/mihomo-build-config.js`，去掉大段内联 heredoc。健康检查改用 **curl 探测作主信号**——初版用 `pgrep -x mihomo` 在 3s 时点曾误报「启动失败」（进程名/时序问题），但 mihomo 实际存活并处理了请求；改为 `curl -sS https://api.anthropic.com`（去 `-f`：无 auth 返 401/404，`-f` 会误判失败，任何 HTTP 响应都算可达）。sleep→4 给 url-test 初选时间。curl 失败时用 `pgrep -f 'mihomo -d'` 区分「进程退出 vs 仍在初选」。实测：用户 base64 订阅 → 31 节点 → TUN 接口 `Meta` UP → api.anthropic.com 经 hysteria2 节点可达（HTTP 404）。
- **启动器校验放宽**：`.sh`/`.bat` 去掉「必须含冒号」的 yaml 限制，改为非空即可——格式由容器内识别/转换。
- **Windows 启动器中文化（.bat → .ps1 拆分）**：cmd.exe 的 .bat 对中文有 DBCS 解析缺陷，三方案全败——① UTF-8 文件按 OEM(936/GBK)解析致 3 字节错切，中文片段被当命令执行（`'时多开...' is not recognized`）；② GBK 编码又撞 cmd 第二个 bug（GBK 尾字节落 ASCII 特殊字符区如 `|`/`{`，`if/goto` 上下文不当双字节处理 → `syntax incorrect`）；③ UTF-8 BOM 不被 cmd 识别（破坏 `@echo off`）。`chcp`/BOM 均改不了 .bat 解析码页（固定 OEM）。故 `.bat` 降级为纯 ASCII 三行包装（`chcp 65001` + `powershell -File launcher.ps1`），所有中文 UI 移到 `launcher.ps1`（PowerShell 原生 Unicode，UTF-8 BOM 解析无缺陷）。`launcher.ps1` 设 `[Console]::OutputEncoding=UTF8` + `.bat` 已 `chcp 65001` → 中文在任何 Windows 正常显示。docker 调用用数组 splatting（`& docker @args`）规避 PS 原生参数引号问题；`--device=/dev/net/tun` 用 `=` 形式避免 PS 对 `/` 前缀的处理。实测中文 UI 完美显示、无解析错误、两条路径（配/不配代理）均正确拼出 docker run。
- **多格式验证**：用户订阅 `https://103.14.76.98/sub/fsc/...`（base64，31 节点：trojan/vless/hysteria2）→ 转换后 `mihomo -t` 校验通过。

### 已知限制

- 自动转换生成最小配置（自动选最快节点 + 全流量走代理），不含原订阅分流规则/分组；需精细分流仍可提供 Clash YAML 直链（原样使用，仅注入 TUN）。节点协议暂支持 ss/vmess/trojan/vless/hysteria2，其余协议解析到 0 节点会明确报错。
- `/dev/net/tun` 依赖：Docker Desktop LinuxKit VM 内置；原生 Linux 需 tun 模块。仅启用代理时挂载。
- mihomo 日志在容器内 `/home/AISC/.mihomo/mihomo.log`。

---

# v1.2.2 (2026-07-01) — 非 root 运行（AISC 用户）

### 动机

Claude Code 在 root 下拒绝 `--dangerously-skip-permissions` 模式。容器全程改用非 root 用户 `AISC`（uid 1000），
让该模式可用；挂载点从 `/app` 移到 AISC 家目录 `/home/AISC/app`，所有运行态目录均在 AISC 可写范围内。

### 变更

- **Dockerfile**：`useradd -m -u 1000 AISC`；出厂 `.claude` 由 `/root/.claude` 改建 `/home/AISC/.claude`；
  `WORKDIR /home/AISC/app`；构建末尾 `chown -R AISC:AISC /home/AISC` 后 `USER AISC`。
- **entrypoint.sh**：`GLOBAL=/home/AISC/.claude`、`PROJECT=/home/AISC/app/.claude`、`CC_CONFIG=/home/AISC/app/.cc-config`；
  删除 root 专属的 `chown` 权限交还逻辑（AISC 直接读写挂载卷）；作用域导出改写 `~/.bashrc`，不再写 `/etc/profile.d`。
- **claude-wrapper / claude-switch**：fallback 与 `do_upgrade` 出厂源路径改 `/home/AISC/.claude`；
  `cs` KEY_DIR 解析路径改 `/home/AISC/app/.cc-config`；`do_upgrade` 删除 `chown` 交还块。
- **stage-skills.sh**：`IMG_HOME=/home/AISC/.claude`。
- **启动器（.sh / .bat）**：挂载目标 `:/app` → `:/home/AISC/app`（.bat 的 named volume 同步改 `/home/AISC/app/.claude`）。
- **README / devlog**：路径表与示例命令同步更新。

### 取舍

- 不做 UID 匹配（无 build-arg UID/GID）。Docker Desktop 下容器 uid 对宿主透明，AISC(1000) 写入即归宿主用户。
  原生 Linux Docker 若宿主 uid ≠ 1000，挂载卷可能写不动 —— 留待实际遇到再加 build-arg。
- 不保留旧 root 所有权文件的迁移修复：全新非 root 环境，旧 `/app/.claude` 若 root 所有权残留需手动删除重建。

### v1.2.2 增量（容器配置加固）

在非 root 运行基础上，补齐权限/安全/构建稳健性与 git 工作流。

- **AISC 用户密码 + sudoers**：`echo 'AISC:AISC' | chpasswd`；`/etc/sudoers.d/aisc` 写 `AISC ALL=(ALL) NOPASSWD:ALL`（440）。容器内 AISC 免密 sudo，便于权限修复与系统操作。
- **entrypoint.sh 自愈 `.cc-config` 所有权**：旧镜像曾以 root 运行，绑定挂载把 root 所有权持久化到宿主，导致 AISC 读不了 `root:600` 的 `api-keys` → `cs` 切换静默失败。改为 `sudo chown -R AISC:AISC "$CC_CONFIG_DIR"` 自愈（依赖前述 sudoers）。
- **claude-wrapper 默认 `--dangerously-skip-permissions`**：注入默认 flag 跳过权限确认（容器内自动流），用户手动传入则不重复追加，避免重复 flag 报错。前提是 `USER AISC`（root 下 Claude 拒绝此 flag）。
- **git 全局 `core.autocrlf=input`**：Dockerfile 内 `USER AISC` 后 `git config --global core.autocrlf input`。commit 时 CRLF→LF（仓库永远干净 LF），checkout 不转；跨平台(Win 宿主 + Linux 容器)避免 CRLF 噪音进历史，`.gitattributes` 优先于此。
- **`.gitattributes` 行尾规范化**：`git add --renormalize .` 一次性把 665 个 `_bundle` CRLF 噪音归零（纯行尾，无内容差异），分两个 commit（行尾规范化 + 源文件改动）入库。
- **启动器 `.bat` 加固**：
  - `:build` 开头检查 `%~dp0Dockerfile` 是否存在，缺失则报错退出（提示「请在有 Dockerfile 及其它资源的文件夹下进行 build 操作」）。
  - build 失败检测修正：`if` 块内 echo 去括号（修 "was unexpected at this time" 解析错误）；每个 `call :build` 后加 `if errorlevel 1 exit /b 1`（修 `exit /b` 从 call 返回不退出脚本、假报成功的问题）。
- **本项目 git 配置**：`user.name=Thomas Wang`、`user.email`、`credential.helper=store`（token 存 `.git-credentials`，600 权限，`.gitignore` 忽略），remote 走 HTTPS + PAT。

### 取舍（增量）

- `--dangerously-skip-permissions` 默认开：容器 `--rm` 隔离 + 绑定挂载仅 `app/`，风险可控；纯本地自动流场景值得。
- token 存仓库内 `.git-credentials`：随项目走但明文（600），比放 `~/.git-credentials` 风险略高，用户取舍。
- sudoers `NOPASSWD`：容器内便利 > 安全约束；容器即用即弃，影响域有限。

### v1.2.2 增量二（后端模型配置对齐 + xf 后端 + cs show 增强）

实测各代理可用模型后，对齐 `claude-switch` 配置。

- **新增 xf 后端**（讯飞 maas-coding）：`XF_BASE=https://maas-coding-api.cn-huabei-1.xf-yun.com/anthropic`，独立 `XF_KEY`。三档：OPUS=`xopglm52`（glm5.2，512k 无 1M）、SONNET=`xopdeepseekv4pro[1m]`、HAIKU/SUBAGENT=`xopdeepseekv4flash[1m]`；EFFORT=max、COMPACT=512000。
- **ark 低端两档换 deepseek**：SONNET 由 `glm-5.2[1m]` → `deepseek-v4-pro[1m]`，HAIKU/SUBAGENT 由 `glm-4.7` → `deepseek-v4-flash[1m]`；OPUS 保持 `glm-5.2[1m]`；EFFORT 开 max。
- **1y 配置实测对齐**：1y 仅 `glm-5.2` 可用（Claude 模型名全 503），全档改 `glm-5.2[1m]`。
- **duo-cc 配置实测对齐**：duo-cc Claude 模型名 `claude-sonnet-5`/`claude-opus-4.8`/`claude-haiku-4.5` 实测可用，MODEL 全设 `claude-sonnet-5[1m]`。
- **COMPACT 统一**：除 cc（清空设计）与 xf（512000）外，deepseek/ark/1y/duo-cc 全设 `1000000`，充分利用 1M 窗口、减少压缩损失。
- **`cs show` 增强**：不再只显示后端名，打印全部 11 个 settings.json env 变量（BASE/TOKEN/API_KEY/MODEL/OPUS/SONNET/HAIKU/SUBAGENT/EFFORT/COMPACT），敏感 token 截断显示（前 12 + 后 4）。

### 取舍（增量二）

- duo-cc/1y 设 COMPACT=1M 但模型未必真支持 1M：若实际窗口 <1M，到模型上限才报错而非提前压缩。duo-cc 充值后实测确认。
- xf OPUS `xopglm52` 不加 `[1m]`：glm5.2 在讯飞只有 512k，加后缀会错。

# v1.2.1 (2026-06-30) — README 手动构建/运行 文档完善

- **README 手动构建/运行部分重写**：拆分为构建/运行/常用变体三个小节，覆盖三平台命令。
  - 构建：明确 `USE_CN_MIRROR` 默认=1，新增 `--no-cache` 示例。
  - 运行：新增 Windows PowerShell/CMD 的 `-v` 语法，强调 `TERM=xterm-256color` 必要性。
  - 常用变体：`CLAUDE_SCOPE` 跳过菜单、`bash` 直接进 shell、`cs <后端>` 一键切换、`--name` 容器命名。

# v1.2.0 (2026-06-30) — 插件化重构 + 双作用域 + 跨平台修复

### 架构重构

- **临时 / 项目双作用域**：用 Claude CLI 原生 `CLAUDE_CONFIG_DIR` 驱动。
  临时 = 镜像内置 `/root/.claude`（即用即弃）；项目 = `/app/.claude`（从镜像完整复制，持久到宿主机卷）。
  entrypoint 交互菜单 / `CLAUDE_SCOPE` 环境变量选择，导出并写入 `.bashrc`/`profile.d`。
- **`.claude` 与 `.cc-config` 分离**：`.claude` 为 CLI 原生完整目录（skills/plugins/projects…）；
  `.cc-config` 仅存 cs 的 `api-keys`（密钥隔离，gitignore）。
- **插件机制集成 6 套技能**（离线可用，预置 cache + marketplaces + 注册表 + `enabledPlugins`）：
  caveman（SessionStart hook 默认激活）/ claude-hud（statusLine HUD）/ document-skills /
  superpowers / skill-creator + gstack（扁平文档，6 子技能 + 斜杠命令）。
  `skill-creator` 构建期从本地 marketplace 离线 install。
- **自包含构建**：插件包 `_bundle` 纳入 git（约 24M），`docker build` 不再依赖宿主机 `~/.claude`。
  `stage-skills.sh` 作为一次性生成器（裁剪 marketplace、cache 版本剪枝、gstack 仅 6 子技能）。
- **cs 实时切换**：env 块改写入 `.claude/settings.json`（Claude Code 原生读取），`!cs ds` 当场生效；
  `write_settings` 合并保留 `enabledPlugins/statusLine`。`cs cc` 允许留空清空所有配置。
- **cs upgrade + 出厂版本检测**：`.factory-version`（出厂内容哈希）；项目版本旧则提示升级；
  `cs upgrade` 叠加更新出厂部分、合并 settings（留 env）、保留运行态、孤项编号表格多选删除。

### 启动器增强（.sh / .bat / .command）

- 镜像不存在自动构建；已存在三选一（直接运行 / 删旧重建防悬空 / 新镜像名）。
- 构建前两问：是否用缓存（`--no-cache`）、是否用国内镜像源（`USE_CN_MIRROR` + daocloud 基础镜像）。
- 容器名唯一后缀（`$$` / `%RANDOM%`），仅清理已退出容器 → 项目+临时多开互不挤掉。

### 跨平台修复（Windows 重点）

- **`.bat` 改纯英文 ASCII**：UTF-8 中文被 cmd 按代码页解析断行报错（wt 同样），英文根治；`chcp 65001` 仅保障 claude 输出。
- **基础镜像 docker.io 超时**：国内镜像选项同时把 `NODE_IMAGE` 指向 daocloud，绕开 `auth.docker.io`。
- **HUD 不显示（多根因）**：① 强制 `TERM=xterm-256color`（Windows 容器 TERM 缺失致 statusLine 隐藏）；
  ② 符号链接（superpowers AGENTS.md）`cp -r` 在 grpcfuse 创建失败 + `set -e` 中断致 `.claude` 复制残缺 →
  镜像内解引用所有 symlink + entrypoint 完整性校验补拷 + `cp -rL`；
  ③ **插件自带 `.gitignore`（含 `dist/`）导致 claude-hud `dist/index.js` 漏提交** → 用户 clone 缺文件、
  statusLine `MODULE_NOT_FOUND`；stage-skills 删除嵌套 `.gitignore` + 补提交；
  ④ `installed_plugins.json` 路径写死 `/root` → CLI 误判项目副本 orphan 可能删 dist → 复制后重写路径为项目目录。
- **`.claude.json` 缺失**：新版 CLI 核心状态在 `.claude.json`，构建期写入 onboarding + 跑一次 CLI 补全运行字段。

### 网络 / 工具（前置工作）

- WSL → Windows Clash 代理（7890）走 SSH-over-443（`ssh.github.com`），9 仓库切 SSH remote。
- 主机 `claude-switch` 增加 `duo-cc` 后端。

## 修复：.bat WT 启动逻辑重做 (2026-06-29, bug4 后续)

### 🐛 no.4 修复后暴露的两个新问题

- **4a 重复开窗** — 已在 Windows Terminal 内运行 `.bat` 仍无条件再开一个 wt。
  根因：脚本只 `where wt` 判断系统是否装 wt，未判断**当前是否已在 wt 内**。
  修复：读环境变量 `WT_SESSION`，已在 wt 则 `goto run` 直接当前标签运行。
- **4b docker 丢参** — 新 wt 内报 `'docker run' requires at least 1 argument`（`%IMAGE%` 丢失）。
  根因：`wt ... cmd /k "...""%cd%:/app""...%IMAGE%"` 的嵌套双引号经 **wt tokenizer**（非 cmd）解析时被拆断，
  命令在 `-v` 后截断，`%IMAGE%` 落入 wt 的其它参数而丢失。
  修复：改为**自重启模式** — wt 仅以本脚本 `cmd /k ""%~f0""` 开新标签，
  `docker run` 在重启实例内**直接执行**，不再把命令串塞进 wt 解析器；`wt -d "%cd%"` 保留工作目录。
  结构用 `if defined WT_SESSION goto run` + `where wt` / `if errorlevel 1 goto run` + `:run` 标签，
  规避 `&&( ... )` 括号块的批处理解析坑。

### ⚠️ 验证

本机 Linux 无法执行 `.bat`，仅做静态校验（含 `WT_SESSION`/`wt -d`、docker run 参数完整、无嵌套 docker 串）。
**需 Windows + Windows Terminal 实测三场景**：① 已在 wt 标签内双击/运行 ② CMD/PowerShell 双击 ③ 未装 wt。

## 修复：容器运行时与 Windows 启动问题 (2026-06-29, no.3-5)

### 🐛 三项缺陷修复

- **no.5 中文乱码** — 容器内未配置 UTF-8 locale，`ls` 等输出八进制转义乱码。
  Dockerfile 注入 `ENV LANG=C.UTF-8 LC_ALL=C.UTF-8`（debian-slim/glibc 内置，无需 locale-gen），
  `entrypoint.sh` 追加 `export LANG/LC_ALL` 作运行期兜底。已在容器内验证 `locale`=`C.UTF-8`、中文文件名与渲染正常。
- **no.4 .bat 报错** — `一键启动_AI工作站.bat` 经 Windows Terminal 启动报 `参数格式不正确 - >nul`，
  根因为 `wt ... cmd /k "chcp 65001 ^>nul && ..."` 中 caret 转义的 `>nul` 被 wt 参数切分误判。
  去除该重定向（保留一行 `Active code page` 输出，无害）。
- **no.3 残留容器** — `docker run --rm` 无 `--name`，窗口被强制关闭时容器残留需手动删。
  启动脚本（`.bat` + `启动_AI工作站.sh`）改用固定 `--name super-claude-station`，
  并在每次启动前 `docker rm -f` 清理同名 stale 容器，保证不堆积。正常退出仍建议 `exit`。

### ✅ 验证

`docker build` 通过；容器内 `locale` 确认 `C.UTF-8`，`ls` 中文无乱码。
Windows `.bat` 的 no.4 需在 Windows + Windows Terminal 环境实测确认。

# v1.1.3 (2026-06-28)

### 🚀 启动体验与全局行为优化

**重大变更**：后端配置与 Key 统一持久化到项目挂载目录 `/app/.claude/`，并在 `entrypoint.sh` 与 `claude-wrapper` 中自动注入环境变量，解决配置后仍进入登录引导、首次进入 bash 后手动 `claude` 不生效等问题。

### ✨ 变更

| 项 | 说明 |
|----|------|
| 配置持久化 | `cs` 在 Docker 内优先写入 `/app/.claude/settings.json`，随项目挂载卷保留 |
| Key 持久化 | `cs` 在 Docker 内优先写入 `/app/.claude/api-keys`，容器重建不丢失 |
| `claude-wrapper` | 新增包装器：每次运行 `claude` 前读取 settings env，注入 `ANTHROPIC_*` / `CLAUDE_CODE_*` 后再执行 `claude-real` |
| 全局 `CLAUDE.md` | 新增 `global-claude.md`，构建时复制到 `/root/.claude/CLAUDE.md` |
| karpathy-flow 默认启用 | 将 Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution 写入全局 `CLAUDE.md` |
| Caveman 默认启用 | 全局默认 Caveman `full` 沟通风格，用户可用 `normal mode` / `stop caveman` 关闭 |
| 跨平台启动脚本 | 新增 Linux `启动_AI工作站.sh` 与 macOS `启动_AI工作站.command`，Windows `.bat` 更新为 v1.1.2 横幅并优先使用 Windows Terminal |
| README 启动说明 | 按 Windows / Linux / macOS 拆分，补充启动模式、单次运行、容器残留清理、终端乱码说明 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| 登录引导误触发 | `entrypoint.sh` 读取 settings 后真正 `export` env，避免只有配置文件但 Claude 进程无 token |
| 首次 bash 后手动 `claude` 不生效 | `claude-wrapper` 每次启动都重新注入 env，解决 `cs` 写入配置后当前 bash 环境未更新的问题 |
| 项目级 settings 覆盖全局 settings | `cs` 优先写 `/app/.claude/settings.json`，避免 `.claude/settings.json` 与 `~/.claude/settings.json` 不一致 |
| `/model` pin 冲突 | `cs` 写 settings 时删除 `model` 字段，让 `env.ANTHROPIC_MODEL` 接管当前后端 |
| 空 API Key 覆盖 Auth Token | env 注入时对空值执行 `unset`，避免 `ANTHROPIC_API_KEY=""` 干扰 `ANTHROPIC_AUTH_TOKEN` |
| 单次运行模式 | 验证 `docker run ... claude -p "..."` 可用，并写入 README |
| CMD 中文乱码 | `.bat` 优先使用 Windows Terminal；README 明确传统 CMD 可能乱码 |

### 📝 已知问题

- [ ] Termius SSH 配置文档未编写
- [ ] gstack 仅有技能描述，完整运行时安装方案待确认

---

# v1.1.2 (2026-06-27)

### 🔐 安全重构：API Key 与脚本分离

**重大变更**：`cs` 脚本不再硬编码 Key，改为从 `~/.claude/api-keys` 读取，无 Key 时交互式提示输入。

### ✨ 变更

| 项 | 说明 |
|----|------|
| Key Store | `~/.claude/api-keys`（chmod 600），`KEY_NAME=value` 格式，5 组 Key 独立存储 |
| `get_key()` | 新函数：先查 Key Store → 没有则提示用户输入 → 输入后自动保存 |
| `cs show` 增强 | 显示当前后端 + 各后端 Key 保存状态（✓/✗） |
| URL 保留 | 端点 URL 仍留在脚本中（非机密），仅 Key 走外部存储 |
| Dockerfile | 构建时不执行 `cs`，改为创建空 `api-keys` + 空 `settings.json` |
| entrypoint 引导 | 未配置时自动显示 `cs deepseek` / `cs ark` 等可用命令 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| 硬编码 Key | `claude-switch` 第 21-27 行移除全部默认 Key |
| 构建时依赖 Key | Dockerfile 不再 `RUN cs deepseek`，避免 build 阶段要求交互输入 |
| Key 注入 JS 字符串 | 改为 env var 传递（`export CS_AUTH_TOKEN`），消除 `'` `\` 等特殊字符引发的 SyntaxError |
| `get_key()` stdout 污染 | `echo` 提示文案全部改 `>&2`，`$()` 只捕获纯 Key 值 |
| CRLF 混入 Key | `grep` → `tr -d '\r'` 清洗 Windows 行尾 |
| 密钥路径 | Docker 容器内自动使用 `/app/.claude/api-keys`（随 `-v` 挂载） |
| entrypoint 重复提示 | Section 3 改为单行状态；Section 5 仅在拦截时显示一次性引导 |
| entrypoint 未配置拦截 | `claude` 命令在无后端时 `exec bash` 而非直接进 Claude Code |
| `.gitignore` | 新增 `api-keys` + `super-claude-v1.1.2.tar` 排除规则 |

### 📝 已知问题

- [ ] Termius SSH 配置文档未编写
- [x] ~~`cs` 脚本内 API Key 硬编码~~ → v1.1.2 修复

---

# v1.1.1 (2026-06-27)

### 🔄 切换脚本重构：`cs` 统一入口

**重大变更**：废弃交互式菜单方案，改用 `cs` 一键切换 + `~/.claude/settings.json` 持久化。

### ✨ 变更

| 项 | 说明 |
|----|------|
| `cs` 统一入口 | `cs` / `claude-switch` 指向同一脚本，写入 `~/.claude/settings.json` |
| 放弃菜单交互 | 旧版 `claude-switch` 菜单 + `.claude_keys` 方案全部移除 |
| 5 后端内嵌 Key | cc / deepseek / ark / 1y / duo-cc 的 API Key 内置脚本，切换即用 |
| `cs show` | 快速查看当前后端 |
| `SC_RESTART=1` | 切换后自动重启 Claude Code（Docker 直连模式） |
| 默认后端初始化 | Dockerfile 构建时 `RUN cs deepseek`，不再用 `ENV` 硬编码 |
| `ARG NODE_IMAGE` | 基础镜像可通过 `--build-arg` 替换，解决国内拉取问题 |
| `.gitignore` | 排除 `super-claude-v1.tar`、`.claude_keys` |
| 构建导出流程 | `docker build` + `docker save` → `super-claude-v1.tar` |

### 🔧 修复

| 项 | 说明 |
|----|------|
| CRLF 行尾 | `claude-switch` 从 CRLF 转为 LF，修复容器内 `bash\r` 错误 |
| DeepSeek 无 Key | 移除 Dockerfile 中 `ENV ANTHROPIC_BASE_URL`（有 URL 无 Token 导致 `ERR_BAD_REQUEST`） |
| entrypoint 横幅 | 改为从 `~/.claude/settings.json` 读取后端信息，不再依赖 Docker ENV |
| `claude` 包装器 | 简化为直接移交 `claude-real`，不再做 Key 检测（切换交给 `cs`） |
| cygpath 兼容 | `cs` 脚本自动识别 Windows/Linux 环境，Linux 容器内直接使用 POSIX 路径 |

### 📝 文档

- README.md 重写：`cs` 用法、平台详情表、构建导出流程
- 新增 `cs` 直连模式说明：`docker run ... cs ark`

### 🗑️ 移除

- 旧版交互式 `claude-switch` 菜单（Anthropic/DeepSeek/硅基流动/OpenRouter/智谱 5 选 1）
- `.claude_keys` Key 持久化文件（改为 `~/.claude/settings.json` 管理）
- `entrypoint.sh` 中无 Key 自动引导逻辑（不再需要）
- Dockerfile 中 7 行 `ENV` 硬编码 DeepSeek 变量

### 📂 当前项目结构

```
.
├── Dockerfile
├── entrypoint.sh
├── claude-switch                       # 同时是 cs 和 claude-switch 的源
├── 一键启动_AI工作站.bat
├── devlog.md
├── README.md
├── skills/
│   ├── claude.json
│   ├── karpathy-flow/
│   └── ... (20+ 技能)
├── .claude/
│   └── settings.local.json
├── .claude_keys                        (已废弃，不再使用)
└── todo/
    ├── todo.md
    └── 20260625/
        ├── claude-switch               (开发过程中的中间版本)
        └── setup-ssh-portproxy.ps1
```

### 已知问题

- [ ] Termius SSH 配置文档未编写
- [ ] `cs` 脚本内 API Key 硬编码，后续可改为环境变量覆盖 + 运行时输入

---

# v1.1.0 (2026-06-27)

### 🔄 架构重构：纯终端闭环

**重大决策**：彻底切断对第三方 GUI 黑盒工具的依赖，转向 100% 内部闭环的纯终端 CLI 工作流。

### ✨ 新增

| 项 | 说明 |
|----|------|
| `claude-switch` | 内置模型后端切换器 CLI，支持 5 大平台、15+ 模型 |
| 平台接入 | Anthropic 官方 / DeepSeek 官方 / 硅基流动 / OpenRouter / 智谱 Z.AI |
| 硅基流动子菜单 | 5 款国产模型可选（DeepSeek-V4-Pro、GLM-5.2、Nex-N2-Pro、MiniMax M3、Qwen3.6-35B） |
| OpenRouter 子菜单 | 6 款全球模型可选（Claude Opus 4.8、Sonnet 4.6、DeepSeek V3.2、GLM-5.2、Qwen3 Coder、Kimi K2.7） |
| 智谱 Z.AI 子菜单 | 3 款 GLM 模型可选（GLM-4.6、GLM-4.5、GLM-4.5-Air） |
| `一键启动_AI工作站.bat` | Windows 一键启动脚本，`chcp 65001` 防乱码，零参数开箱即用 |
| API Key 持久化 | `/app/.claude_keys`（chmod 600），5 组 Key 独立存储，容器重启不丢失 |
| `karpathy-flow` 技能 | Andrej Karpathy 编码规范 skill，自动化入容器 |
| `devlog.md` | 开发日志，提升至项目根目录 |
| entrypoint 自动引导 | 无 Key 时启动 `claude` 自动重定向到 `claude-switch` |
| `claude` 包装器 | 重命名原版为 `claude-real`，包装脚本统一拦截：有 Key → 原版，无 Key → `claude-switch` |
| `AUTH_METHOD` 双通道 | Anthropic 官方用 `ANTHROPIC_API_KEY`，第三方平台用 `ANTHROPIC_AUTH_TOKEN` + 清空 `API_KEY` |
| Claude Code 启动绕过 | 预置 `config.json`（`hasCompletedOnboarding: true`）跳过首次联网验证 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| Dockerfile — VPN 依赖 | 注入清华 apt 镜像源 + 淘宝 NPM 镜像源，国内网络无需 VPN 即可构建 |
| Dockerfile — `.claude/` 报错 | 不再 `COPY .claude/`（宿主机缺失时构建失败），改为镜像内生成默认 `settings.local.json` |
| entrypoint.sh — 覆盖风险 | 原逻辑缺文件就强覆盖，现改为仅首次运行注入，保护用户自定义配置 |
| entrypoint.sh — root 锁死 | 新增 `chown` 权限修复，自动检测宿主机 UID/GID 归还文件所有权 |
| entrypoint.sh — Shell | `#!/bin/sh` → `#!/bin/bash`，支持 `echo -e` 等特性 |
| Dockerfile — 工具链 | 补上 `sudo`、`tmux` |
| `claude-switch` — Anthropic 模型 | `claude-3-5-sonnet-20241022`（已退役）→ `claude-opus-4-8` |
| `claude-switch` — 硅基流动模型 | `Pro/deepseek-ai/DeepSeek-V3` → `Pro/deepseek-ai/DeepSeek-V4-Pro` |
| Claude Code — 国内无 VPN 无法启动 | 预置 `config.json` 跳过 onboarding + 第三方平台改用 `ANTHROPIC_AUTH_TOKEN` |
| `claude` 包装器 — 死循环 | 兼容 `ANTHROPIC_AUTH_TOKEN`，两个变量任非空即放行 |
| `claude-switch` — Anthropic 模型 | `claude-3-5-sonnet-20241022`（已退役）→ `claude-opus-4-8` |
| `claude-switch` — 硅基流动模型 | `Pro/deepseek-ai/DeepSeek-V3` → `Pro/deepseek-ai/DeepSeek-V4-Pro` |

### 📝 文档

- README.md 全面重写：5 大平台菜单、子菜单表格、claude-switch 详解

### 🗑️ 移除

- `docker_version/` 子目录清理，文件全部提升至项目根目录

### 📂 当前项目结构

```
.
├── Dockerfile
├── entrypoint.sh
├── claude-switch
├── 一键启动_AI工作站.bat
├── devlog.md
├── README.md
├── skills/
│   ├── claude.json
│   ├── karpathy-flow/SKILL.md     ← v1.1.0 新增
│   └── ... (20+ 技能)
├── .claude/
│   └── settings.local.json
├── .claude_keys                   (运行时生成)
└── todo/
    └── todo.md
```

---

# v1.0.0 (2026-06-25)

### 初始版本

- `node:20-slim` 基础镜像
- 全局安装 `@anthropic-ai/claude-code`
- 预配置 DeepSeek Anthropic 兼容 API（`ANTHROPIC_BASE_URL`、模型映射、effort）
- `claude.json` 全局配置（claude-hud + document-skills 插件）
- 20+ 预装技能库 → `/root/.claude/skills/`
- `entrypoint.sh` 入口脚本：自动注入项目级 `.claude/` 模板
- Windows SSH 端口代理配置（`setup-ssh-portproxy.ps1`）

### 已知问题

- [x] ~~无 VPN 时 `node:20-slim` apt/npm 安装失败~~ → v1.1.0 修复
- [x] ~~`.claude/` 缺失导致 Docker 构建报错~~ → v1.1.0 修复
- [x] ~~Skill 引入（andrej-karpathy-skills）~~ → v1.1.0 完成
- [x] ~~全局 claude-switch 命令~~ → v1.1.0 完成
- [ ] Termius SSH 配置文档未编写
