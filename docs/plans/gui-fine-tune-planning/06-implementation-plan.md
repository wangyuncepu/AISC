# GUI Fine-Tune 实施计划

> 代码基线：`1f15f8bbb6beeee0e9a6af8a4daa3310ee02747a`。  
> 原则：每步独立提交、先自动化后实机；任何步骤不得以“后续再补测试”进入下一阶段。  
> G-01 至 G-18 定义完整；G-03/G-04 已依据 2026-08-09 原始规划对话恢复并纳入实施/验收。

## 一、Step 0：契约与测试基础设施（全部目标前置）

### 0.1 修复现有契约缺口

- `open_session/close_session` 全链路携带 canonical workspace；Rust 是唯一 canonicalize 生产者，成功结果回写 store/history，`SessionEntry` 保存 canonical 值。
- 修复自然退出 SessionRegistry entry 的回收/ack，避免 reopen 无界增长。
- SessionRegistry 增加 spawn 前 `Reserved`、原地 `Closing` 和共享 close completion；注册失败 kill+reap 回滚，shutdown 可枚举并接管 Reserved/Running/Closing。
- 为 tab/session event 增加 generation 或当前 session ID 校验。
- 新增 Rust `shutdown_workbench` 协调器；必要 cleanup 不依赖最后窗口销毁后的后台任务。
- settings 与 history 均扩展为 typed + raw-extra load/save：字段校验、各层 unknown-field 保留、原子替换、独立跨进程锁/expected revision、立即 flush。
- Windows replace 使用可替换既有文件的原子 API；若平台 API 不可用，采用 `target→backup`、`tmp→target`、失败恢复 backup 的协议，禁止先删旧文件后无保护 rename。

### 0.2 前端测试

在 `workbench/package.json` 增加：

- `vitest`
- `@vue/test-utils`
- DOM 环境（如 `jsdom`）
- `npm test` / `npm run test:watch`

优先覆盖 store reducer、dynamic tabs、i18n、sidebar、settings 和 title 的纯逻辑/组件测试。

### 0.3 CI

新增或扩展 Workbench CI，使 push/PR 至少运行：

```text
npm ci
npm run build             # vue-tsc + vite
npm test -- --run
cargo test --manifest-path workbench/src-tauri/Cargo.toml
python -m pytest          # 涉及 CLI 时
```

修正 `bundle-linux-macos.yml`、`nsis-installer.yml` path filters，至少覆盖：

```text
workbench/src/**
workbench/package.json
workbench/package-lock.json
workbench/vite.config.*
workbench/tsconfig*.json
workbench/src-tauri/**
src/aisc/**
```

- 增加 workflow 静态契约测试，解析 YAML 并断言上述 path filters，避免只靠人工判断触发条件。
- Linux/macOS bundle 构建后在非 checkout cwd 解包/挂载产物，验证 sidecar 路径、执行权限、架构、`aisc version --format json`、bundle resource discovery 和主程序最小启动；macOS 用 `file/lipo` 断言与声明架构一致。

### 0.4 门禁

Step 0 以本节后的 `A-INFRA-1` 至 `A-INFRA-5` 为唯一验收定义；五项全部通过后才允许合并后续功能步骤。

### A-INFRA-1 重复 Session type 恢复基线

- 先提交能复现旧 `.find(agent)` 去重缺陷的失败测试，再完成逐 TabRecord 修复；测试保留为回归门。

### A-INFRA-2 SessionRegistry 所有权

- 重复 ID 在 spawn 前拒绝；spawn/注册失败 kill+reap；并发 close 共享结果；自然退出/reopen 100 次后 registry metadata 有界且无旧 child。

### A-INFRA-3 Canonical workspace

- 从三个不同 cwd 调用同一 Workbench Session，open/terminate argv 均含 Rust canonicalize 后的选中 workspace；symlink/Windows case/UNC fixture 使用同一 identity key。

### A-INFRA-4 CI 触发与三平台 smoke

- YAML 静态测试断言 path filters；模拟前端/package/src-tauri/CLI 变更均命中预期 workflow。三平台 bundle 在非 checkout cwd 验证 sidecar 版本、权限/架构和资源发现。

### A-INFRA-5 持久化安全

- settings/history root、workspace、layout、tab unknown fields round-trip；unknown schema 不覆盖；并发 conflict 最多重试 3 次；模拟 Windows replace 第二阶段失败后旧文件恢复、无空文件窗口。

## 二、Step 1：G-18 Workbench sidecar 入用户 PATH（P0）

### 修改

- `workbench/src-tauri/nsis/installer.nsi`：安全 PATH helper、ownership marker、upgrade/uninstall 分支、环境广播、交互/静默冲突提示。
- 固定并测试 `manufacturer=aisc`、`productName=AISC Workbench` 及完整 registry key。
- NSIS 基于当前锁定的 Tauri CLI/Cargo Tauri 版本重新取得默认模板并做结构 diff；自定义依赖页、升级/卸载、语言和 WebView2 变更逐块 rebase，README 记录来源版本，禁止继续盲叠加 2.9.4 模板。
- 移除 Workbench NSIS 对宿主 Python 3 的检查/winget 安装和文案；frozen sidecar 不依赖宿主 Python，Runtime preflight 也无此 gate。
- `.github/workflows/nsis-installer.yml`：从 **新 PowerShell 进程** 通过 PATH 执行 `aisc version --format json`，而不是只按绝对路径调用 sidecar。
- smoke 覆盖 existing standalone AISC、重复安装、升级、卸载、sentinel PATH 和 `REG_EXPAND_SZ`。

### 门禁

`A-G18-1` 至 `A-G18-4` 全部通过；卸载后用户已有 PATH 内容逐项相等。

## 三、Step 2：G-07 停止、关闭与退出性能（P0）

### Python CLI

- `src/aisc/cli/main.py`：`runtime stop --grace`，默认 10，校验整数 `1..600`；`0`、负数和越界值拒绝。
- `src/aisc/cli/commands/runtime.py`、`src/aisc/application/runtime.py`：透传 grace。
- `src/aisc/adapters/docker_.py`：复用已有 `stop_container(timeout=...)`，不重复造接口。
- 测试 CLI 默认 10、显式 3、adapter exact argv。
- `runtime stop` 的 `--format json` 参数位置矩阵覆盖顶层、runtime group、stop leaf；`x/-1/0/601/1.5` 均返回 JSON usage envelope、exit 2、零 Docker 调用。
- `session terminate` 覆盖负数、NaN、Infinity、>600 的 JSON usage/零 Docker 调用，0 合法。

### Workbench Rust/Frontend

- `runtime_stop_argv` 加 `--grace 3`。
- `session_open_argv/session_terminate_argv` 加 `--workspace`；Workbench terminate 加 `--grace 3`。
- Python `session terminate` 校验有限数值 `0..600`，外层 Docker command timeout 从 `grace+10s` 收敛为 `grace+1s`，CLI 默认 grace 5 不变。
- `TERMINATE_TIMEOUT 15→5s`、`CLOSE_WAIT 10→4s`、`CLOSE_FORCE_WAIT=2s`；duration 可注入单测。
- `stopRuntime()` 按 `03` 的分阶段并发实现，覆盖 stop/terminate 竞态。
- 关窗/退出改走 `shutdown_workbench`；前端仅在 ShutdownReport 返回后 destroy/exit。

### 测试与证据

- Rust：argv、timeout、terminate-first、stop-first、already-stopped、多 Session 并发、force-reap。
- Vue/store：确认、状态、重复点击门禁、错误汇总。
- Windows 实机：预启动 Runtime，20 次单 Session close 和 20 次多 Session stop，记录 p50/p95/max、Docker/CLI/Workbench 版本。
- 门禁：`A-G07-1` 至 `A-G07-7`。

## 四、Step 3：typed settings 基础设施（P0 前置；支撑 P1 G-01）

### 设置范围

字段、默认值、边界、非法值和生效方式的唯一规范见 `02-startup-flow.md` §三.4；本步骤只实现该 schema/API，不复制第二份 JSON 默认值。

- 范围固定为语言、UI 字号/缩放、终端、窗口记忆和关闭行为。
- 本阶段不增加全局亮色/暗色主题切换；G-06 只统一现有暗色终端与对比度。
- 设置页骨架先提供路由/对话框、load/save/reset、字段错误和即时/重开生效标记。

### 门禁

- 字段边界、默认值、round-trip、unknown field、corrupt file、多窗口冲突测试通过。
- `A-G01-1`：设置页可键盘访问，保存失败可恢复，不丢 `aisc_cli_path`。

## 五、Step 4：G-09 i18n（P0）

### 修改

- 增加 `vue-i18n`，语言包 `zh-CN`/`en-US`。
- Rust 新增 installer language/system preference 读取；Windows registry key 与生成 NSIS 一致。
- 语言解析严格按 `02`：`ui.language=zh-CN/en-US` 直接生效；值为 `auto` 或字段缺失时才按安装器语言 → 系统语言 → 中文。
- 扫描 `workbench/src/**/*.{vue,ts}` 用户可见硬编码；允许 raw code/path/terminal bytes。
- Workbench 写入终端的欢迎、Exit/Error 辅助文本进入字典。

### 测试

- locale resolver 纯函数矩阵；设置重启保持；动态参数/数量；不存在 key 在测试中失败。
- 双语组件快照/关键流程走查：blocked、picker、summary、build、conflict、ready、error、settings、tray、notification。
- 门禁：`A-G09-1` 至 `A-G09-4`。

## 六、Step 5：G-08 动态多 tab（P0）

### Store/History

- 固定四 tab 模型改为 `createTab(sessionType)` 动态数组；默认 Start 仅创建 Bash。
- LaunchSummary 移除“初始 Agent”选择；Runtime summary 只负责 Runtime 配置。恢复布局保留独立入口。
- `×` 改为 `removeTab`；保留明确的“重开会话”语义。
- 恢复完整 `TabRecord`，支持重复 type、position、active ID 映射。
- 快捷键按当前 tab 序动态映射；`Ctrl/Cmd+1..9` 支持前 9 项，超出用 tablist 键盘导航。

### UI

- TabBar `+` 菜单四项、关闭按钮、空态、新建引导、ARIA tablist。
- 未配置 Provider 的最小 `checking → guide/dormant` 流程在本步具备：从 `+` 选择 Claude/Codex 后立即发一次按 type 去重的 Provider query，不依赖旧的“已有活动 tab 才轮询”路径；完整 G-12 文案/展示在 Step 8。

### 测试

- duplicate type、多开/关闭/自然退出/reopen、迟到 event、active fallback、空态、恢复、停止 Runtime、退出 Workbench。
- 门禁：`A-G08-1` 至 `A-G08-8`。

## 七、Step 6：G-06 终端渲染升级（P1）

### 依赖与实现

- 新增 `@xterm/addon-webgl`。
- 字体栈、`fontSize=14`、`lineHeight=1.2`、`letterSpacing=0`、`scrollback=5000`、`smoothScrollDuration=100`；最终值来自 settings。
- `terminal.renderer` 是 Workbench 自有枚举 `auto | default | webgl`，用于决定 WebglAddon 的 load/dispose；它不是 xterm `TerminalOptions` 字段，不得直接写入 `term.options`。
- WebGL 初始化显式 try/catch；context loss 时 dispose 后回落默认 renderer。
- 第一阶段不交付 ligatures；如恢复该范围，需独立 addon、设置开关和性能 ADR。
- 终端颜色集中到一个 theme 对象，与 Workbench CSS token 对齐；正文/背景/selection/error 对比度走查。

### 测试/证据

- WebGL 成功、构造失败、context loss、dispose；canvas/default fallback 仍可输入输出。
- 高频输出基准使用固定 10 MiB fixture，记录 renderer、耗时、UI 无冻结；不承诺无依据 FPS。
- 门禁：`A-G06-1` 至 `A-G06-5`。

## 八、Step 7：G-01 设置页交付（P1）

- UI font scale、terminal font/size/lineHeight/scrollback/renderer/smooth scroll 接入。
- 明确即时生效：语言、UI scale、可安全修改的 xterm options。
- 明确需重建：renderer/addon 切换；保存后提示，仅重建受影响 Terminal，Session/PTY 不重开。
- Reset 只恢复 GUI 设置，不清除 CLI pin、history、workspace 或 Runtime。
- 门禁：`A-G01-2` 至 `A-G01-5`。

## 九、Step 8：G-05 侧边栏 + G-12 Provider 引导（P1/P2）

- 按 `04-observability.md` 拆为 User layer 与 Developer details。
- 删除 1 秒 ticker，建立 semantic view model。
- Provider 显示 provider 名，不显示不存在的 model。
- guide banner 位于 tab/pane 顶部；动作激活/创建 cc-switch；配置后重试并启动新 Session。
- 测试 12 秒无语义变化 DOM mutation=0、stale、能力缺失、详情字段、ARIA。
- 门禁：`A-G05-*`、`A-G12-*`。

## 十、Step 9：G-02 Resize 根因定位与修复（P1）

### 先诊断，后修改

- 临时诊断模式记录每层 rows/cols/timestamp，不记录终端内容。
- Windows 实机使用 Bash `stty size`/等价探针和 cc-switch TUI，依次调整 80×24、120×40、60×20 等可重复尺寸。
- 找到第一处偏差后提交根因记录，再决定 Frontend/Rust/CLI/cc-switch 修改点。

### 验收

- ResizeObserver 稳定后 500ms 内，容器内报告 rows/cols 与 xterm 一致。
- cc-switch TUI 连续 20 次 resize 无残留旧区域，输入光标仍在可见区域。
- 若改 CLI，终端直用 `aisc session open` 同样通过。
- 门禁：`A-G02-1` 至 `A-G02-4`。

## 十一、Step 10：G-10 窗口尺寸/位置记忆（P2）

- settings geometry schema、logical units、debounce、maximized、display clamp。
- 实现 Rust `restore_window_geometry/capture_window_geometry` 命名 commands，负责 logical units、monitor clamp 和 window API；前端不增加通用 position/size capability。
- 单/多显示器、DPI 变化、离屏、损坏 rect、`window.remember_geometry=false`、退出 flush。
- 门禁：`A-G10-1` 至 `A-G10-5`。

## 十二、Step 11：G-03 终端基础体验 + G-11 右键菜单（P1/P2）

- 新增 `@xterm/addon-search`；每 Terminal 独立加载/dispose；提供 `Ctrl/Cmd+F` 搜索条、前后结果、大小写和 Esc 关闭。
- 精确新增 npm `@tauri-apps/plugin-clipboard-manager`、Rust `tauri-plugin-clipboard-manager`，初始化 plugin，并仅授予 `clipboard-manager:allow-read-text` / `allow-write-text`；侧边栏复制也迁移到同一受控通道。
- 明确滚动行为：默认 scrollback 5000、查看历史时不强制跳底、回到底部后恢复 follow output；PageUp/PageDown/Home/End 可用。
- 右键菜单：复制、粘贴、搜索、清屏；selection/focus/disabled 状态明确。
- 粘贴复用 1 MiB（1,048,576 bytes）上限/背压，不记录内容。
- 门禁：`A-G03-1` 至 `A-G03-4`、`A-G11-1` 至 `A-G11-4`。

## 十三、Step 12：G-13 一键诊断（P2）

- 增加 Doctor Rust/IPC/TS/UI 五层实现。
- 30 秒 timeout、结构化 envelope、checks/summary/hint、错误/超时/协议测试。
- 诊断入口同时用于 startup error 与 ready 详情，但不自动执行修复。
- 门禁：`A-G13-1` 至 `A-G13-4`。

## 十四、Step 13：G-14 构建最终耗时与通知（P2）

- 增加 npm `@tauri-apps/plugin-notification`、Rust `tauri-plugin-notification`，初始化 `.plugin(tauri_plugin_notification::init())`；仅授予 `notification:allow-is-permission-granted`、`notification:allow-request-permission`、`notification:allow-notify`。
- elapsed 从组件局部迁入 store；Rust 用 CLI terminal event 决定 command result，Frontend 只在 `buildImage()` Promise 首次 settle 时按 `operation_id` 冻结 final duration/终态，Channel 不二次写终态。
- 仅当主窗口失焦或已最小化，且终态为 complete/failed 时，对同一 `operation_id` 通知一次；cancelled 不通知。
- 权限拒绝/勿扰不改变 build 结果；桌面通知不设点击回调验收，重新打开 Workbench 后仍可看到终态与最终耗时。
- 门禁：`A-G14-1` 至 `A-G14-4`。

## 十五、Step 14：G-15 动态标题（P2）

- 实现标题纯函数和跨分隔符 basename。
- 使用前端 `getCurrentWindow().setTitle()`，仅增加 `core:window:allow-set-title` capability。
- active pane > active tab > workspace > product 的优先级；无轮询驱动。
- 门禁：`A-G15-1` 至 `A-G15-3`。

## 十六、Step 15：G-16 可选最小化到托盘（P2）

- `tauri` 启用 `tray-icon` feature；Rust 使用 `TrayIconBuilder` 创建「显示/退出」菜单并持有 tray owner。
- Rust `.on_window_event` 拦截主窗口 `CloseRequested`：`minimize-to-tray` 时 `api.prevent_close()` + `window.hide()`；`quit` 时也先 prevent_close，由前端确认后调用 shutdown。`.run`/`RunEvent::ExitRequested` 只处理 OS/app exit 兜底，不绕过 cleanup。
- `quit` 默认；`minimize-to-tray` 仅 hide，不 destroy。
- tray Exit 通过主窗口事件/命名 command 触发同一确认与 Step 2 shutdown coordinator；ShutdownReport 允许后调用 app exit。初始化失败回退 quit。
- 覆盖活动 Session、无 Session、隐藏/显示、多次点击、OS logout/exit requested。
- 门禁：`A-G16-1` 至 `A-G16-5`。

## 十七、Step 16：G-17 Tab 内分屏（P3）

- 先冻结 PaneTree/ownership/history schema；不使用 tmux。
- 将前端 domain 从“一 tab 一 session”迁移为 pane-aware API：Terminal prop/ref 使用 `paneId`，focus/visible/快捷键、open/close/reopen/Exit reducer、Provider polling、sidebar、title 和 generation 都通过 active pane 解析。
- CSS grid + pointer events 实现 split/ratio；每叶独立 Terminal/Session/ResizeObserver。
- G-08 重复 tab 继续使用 history v1；G-17 将 history schema 升为 v2，锁内原子迁移旧 tab 为单叶 tree，迁移失败保留 v1 原文件并拒绝无保护写入。
- 每个 Runtime 在单个 Workbench 进程内 PaneTree 叶节点总数上限 8；`opening/running/closing` 另做资源原子计数。第 9 个叶请求在 PaneTree commit 前拒绝，第 9 个资源请求在 spawn reservation 前拒绝。
- 测试嵌套、关闭压缩、tab+pane、resize、runtime stop、shutdown、恢复。
- 门禁：`A-G17-1` 至 `A-G17-6`。

## 十八、Step 17：G-04 明暗主题切换（P2）

- `02` settings schema 接入 `ui.theme=system|dark|light`；首帧前解析，监听系统 theme。
- 将 Workbench CSS 和 xterm palette 收敛为 semantic tokens；清除组件主题相关硬编码色。
- 主题切换只更新 DOM token/xterm options，不重建 Session/PTY。
- dark/light 跑关键状态截图、WCAG AA、系统切换 listener 清理和持久化测试。
- 门禁：`A-G04-1` 至 `A-G04-4`。

## 十九、依赖图

箭头表示“前置步骤 → 后置步骤”。

```text
Step 0 ─┬→ Step 1  (PATH)
        ├→ Step 2  (shutdown/stop)
        ├→ Step 3  (settings shell) ─┬→ Step 4  (i18n)
        │                            ├→ Step 7  (settings complete)
        │                            ├→ Step 10 (geometry)
        │                            ├→ Step 15 (tray setting)
        │                            └→ Step 17 (theme)
        ├→ Step 5  (dynamic tabs) ───┬→ Step 8  (sidebar/banner)
        │                            └→ Step 16 (split)
        ├→ Step 6  (terminal) ───────┬→ Step 7
        │                            ├→ Step 11 (search/menu)
        │                            └→ Step 16 (pane-aware Terminal)
        ├→ Step 8  (guide/active pane semantics) → Step 16
        ├→ Step 9  (resize) ─────────→ Step 16
        ├→ Step 12 (doctor)
        ├→ Step 13 (notification)
        └→ Step 14 (title)

Step 2 ─→ Step 15  (tray exit 必须复用 shutdown)
```

## 二十、每步通用 Definition of Done

仅要求适用于该步骤的路径；不再强制每个纯展示功能都具备“取消/重试”。

- 实现符合 00/02/03/04/05 的规范与验收 ID。
- 正常、失败、边界和并发路径有适用的自动化测试；平台 API 保留实机证据。
- 新字段/依赖/capability/命令有向后兼容、最小权限和清理策略。
- 不泄漏密钥、终端内容或完整环境。
- 新增 child、PTY、timer、observer、listener、channel、tray、notification addon 均有 dispose/reap 证据。
- `npm run build`、前端测试、`cargo test` 通过；涉及 CLI 时 Python/契约测试通过；涉及打包时 bundle/NSIS 通过。
- 更新 devlog、手工验证清单和目标追踪矩阵。

## 二十一、实机证据格式

每次实机签收记录：

```text
目标/验收 ID：
Commit：
OS/arch：
Workbench/CLI/Docker 版本：
GPU/显示器/通知或 tray 环境（适用时）：
前置条件：
步骤：
期望：
结果：
耗时样本与 p50/p95/max（性能项）：
截图/日志路径：
结论：PASS | FAIL
```

禁止只写“Windows 实测正常”。
