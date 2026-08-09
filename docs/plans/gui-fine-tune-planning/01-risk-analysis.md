# GUI Fine-Tune 风险分析

> 适用范围：`00-overview.md` 中 G-01 至 G-18 全部目标。  
> 风险关闭条件：缓解措施已实现，并有 `06-implementation-plan.md` 指定的自动化或实机证据。

## 一、风险登记

### R-01 G-18：用户 PATH 被破坏或指向错误 CLI

- **触发条件**：覆盖整个 PATH、大小写/引号/尾斜杠比较错误、升级时旧卸载器删除新条目、卸载误删用户已有条目、PATH 中已有其他 `aisc`。
- **影响**：新终端无法运行 CLI，或解析到非 Workbench sidecar；严重时损坏用户 PATH。
- **缓解**：
  - 只修改 `HKCU\Environment\Path` 的单个目录项，不覆盖其他项；保留 `REG_EXPAND_SZ`。
  - 比较时规范化大小写、引号和尾斜杠；安装目录只出现一次。
  - 记录 `PathEntryOwned` marker；正常卸载仅在 marker 存在且目录精确匹配时删除。
  - `/UPDATE` 升级流程不得留下缺失或重复项；写入后广播 `WM_SETTINGCHANGE`。
  - 已有其他 `aisc` 时不覆盖；交互安装显示提示，静默安装写日志，Workbench 首启可提示实际解析路径。
- **残余风险**：已打开终端继承旧环境，必须新开进程；企业策略可能禁止用户环境变量写入。
- **证据**：`A-G18-1` 至 `A-G18-4`。

### R-02 G-07：停止快路径造成兼容性或清理回归

- **触发条件**：CLI 默认 grace 被改短；Runtime stop 先于 session terminate 使 `docker exec` 失败；最后窗口销毁导致异步 cleanup 被中止。
- **影响**：CLI 直用行为劣化、关闭变慢、宿主 PTY/CLI 子进程残留、未刷盘状态丢失。
- **缓解**：
  - `aisc runtime stop` 默认 grace 保持 10 秒；Workbench 显式传 3 秒。
  - session terminate 默认 5 秒保持不变；Workbench 显式传 `--grace 3`，并将 Rust command/wait budget 收紧为生命周期契约规定值。
  - Runtime stop 采用分阶段并发：先标记/发起 session close，再在短启动窗口后发 stop；不能假定二者完全无竞争。
  - 关窗由 Rust `shutdown_workbench` 统一并发关闭、强制回收、flush 后返回；返回后才 destroy/exit。
  - 区分正常性能目标与硬超时，不作“所有路径 <3 秒”的不可能承诺。
- **残余风险**：强制终止不会主动删除 container、image、volume 或 registry metadata，但可能丢失未刷盘的进程内状态。
- **证据**：`A-G07-1` 至 `A-G07-7`。

### R-03 G-01/G-09：设置 schema、并发写和 i18n 回归

- **触发条件**：用户显式语言被安装器语言覆盖；动态文案漏翻；损坏/未知 schema 被默认值覆盖；多窗口同时写设置。
- **影响**：设置不持久、启动失败、语言反复跳变或旧字段丢失。
- **缓解**：
  - typed settings 读写 API，字段校验、默认值、原子替换和跨进程锁/expected revision。
  - `ui.language=zh-CN/en-US` 时直接生效；值为 `auto` 或字段缺失时，依次使用安装器语言、系统语言、`zh-CN`。
  - `ui.language` 使用 `auto | zh-CN | en-US`；仅 `auto` 执行环境探测。
  - 用户可见字符串扫描；复数、参数和错误码使用 i18n API，不拼接句子。
  - 未知 schema 保留原文件并显示可恢复错误。
- **残余风险**：第三方 TUI 内容不受 Workbench i18n 控制。
- **证据**：`A-G01-*`、`A-G09-*`。

### R-04 G-08：动态 tab 与 Session 生命周期竞态

- **触发条件**：重复 Session type 恢复时按 agent 去重；删除 tab 后旧 Exit 事件回写；自然退出 entry 未回收；active tab 指向已删除对象。
- **影响**：布局丢失、错误 tab 状态、Rust SessionRegistry 增长或孤儿子进程。
- **缓解**：
  - 逐 `TabRecord` 恢复，不按 agent 查找；建立 saved tab ID 到新 tab ID 映射。
  - 每个 tab/session 使用 generation 或当前 `session_id` 校验事件归属。
  - 区分 `removeTab` 与 `closeSession`；Windows Terminal 式 `×` 采用 remove 语义。
  - 定义自然退出 entry 的 ack/删除机制和 registry size 测试。
  - 每个 Runtime 在单个 Workbench 进程内，资源占用态 `opening/running/closing` 原子计数合计上限 8；closing 完成前不释放名额；第 9 个请求在 spawn 前拒绝。
- **残余风险**：8 个并发 `docker exec` 会增加宿主与容器负载。
- **证据**：`A-G08-1` 至 `A-G08-8`。

### R-05 G-10：窗口恢复到离屏或不可用尺寸

- **触发条件**：显示器拔插、DPI 变化、保存最大化坐标、损坏 rect、physical/logical unit 混用。
- **影响**：窗口不可见、尺寸异常、无法进入设置页修复。
- **缓解**：
  - 保存 logical position/size、maximized 标志和显示器信息；普通 rect 不取最大化/fullscreen 瞬时值。
  - 恢复前校验最小尺寸，并将至少 64×64 logical px 的可见区域夹取到当前任一显示器工作区。
  - 无有效记录时沿用 Tauri/操作系统默认位置，不宣称必然居中。
  - 设置 `window.remember_geometry=false` 时停止写入并忽略旧 rect，但不必删除历史值。
- **残余风险**：跨平台窗口管理器可能调整最终位置。
- **证据**：`A-G10-1` 至 `A-G10-5`。

### R-06 G-06：WebGL、字体和终端参数兼容性

- **触发条件**：GPU/驱动不支持、WebGL context loss、addon dispose 不完整、错误的 xterm option、ligature 性能退化。
- **影响**：黑屏、渲染异常、内存/GPU 资源泄漏或类型构建失败。
- **缓解**：
  - 新增 `@xterm/addon-webgl`，应用代码显式捕获初始化失败；context loss 时 dispose 并回落到 xterm 默认 renderer。
  - 第一阶段不承诺 ligatures；如后续引入，必须作为独立 addon/开关和性能门。
  - 参数使用当前 xterm 版本的精确 option（如 `smoothScrollDuration`），以 `vue-tsc` 为门禁。
  - 每个 Terminal 实例在卸载时 dispose addon、observer、timer 和 listener。
- **残余风险**：不同字体安装状态会改变字形和 fallback。
- **证据**：`A-G06-1` 至 `A-G06-5`。

### R-07 G-05/G-12：信息分层后丢失事实或引导不可达

- **触发条件**：把 provider 当模型；隐藏开发者字段；未配置的 Claude/Codex 从选择器移除，导致 banner 不可达；1 秒 timer 导致整栏刷新。
- **影响**：用户无法理解状态或无法进入配置，开发者诊断信息丢失。
- **缓解**：
  - 用户层显示 Provider 名、route/auth 人话状态，不显示契约中不存在的模型名。
  - 开发者详情保留 runtime/container ID、freshness、observed time、image/network/scope、原始 route/auth。
  - 四种 Session type 始终可选；未配置 Claude/Codex 创建引导态 tab，不启动 agent session，banner 指向已有或新建 cc-switch tab。
  - 删除 1 秒 ticker；相对时间只在 observation 或展开详情时计算。
- **残余风险**：Provider capability 缺失时只能显示 Unknown/升级提示。
- **证据**：`A-G05-*`、`A-G12-*`。

### R-08 G-02：错误定位导致修复落错层

- **触发条件**：预先认定问题在前端、portable-pty、ConPTY 或 CLI/docker exec 中的某一层。
- **影响**：引入无效修改，甚至破坏 CLI 直用 resize。
- **缓解**：
  - 先记录完整链路：ResizeObserver → FitAddon → Tauri IPC → portable-pty → ConPTY → `aisc session open` → `docker exec` → 容器进程。
  - 每层记录 cols/rows 和时间戳；证据确认第一处偏差后再选修改层。
  - 若修改 CLI，终端直用和 GUI 必须共享收益；若问题在宿主 PTY，不改 CLI 契约。
- **残余风险**：Windows Terminal/ConPTY、Docker Desktop 版本差异需实机矩阵。
- **证据**：`A-G02-1` 至 `A-G02-4`。

### R-09 G-11：剪贴板、搜索和上下文菜单行为不一致

- **触发条件**：误称 SearchAddon 已存在；复制/粘贴权限不足；右键覆盖终端选择行为；菜单打开后键盘焦点丢失。
- **影响**：菜单无效、无法粘贴或破坏终端交互。
- **缓解**：
  - 显式新增 `@xterm/addon-search`，每个 Terminal 独立加载和 dispose。
  - 复制仅在有 selection 时启用；粘贴复用现有 PTY paste 大小上限和背压。
  - 右键菜单关闭后恢复终端焦点；键盘快捷键继续可用。
- **残余风险**：Linux 桌面/Wayland 剪贴板行为差异。
- **证据**：`A-G11-1` 至 `A-G11-4`。

### R-10 G-13：诊断超时、协议错误或敏感信息泄漏

- **触发条件**：doctor 非零退出、无效 JSON、stdout 过大、直接展示未脱敏 detail。
- **影响**：错误页卡死或泄密。
- **缓解**：
  - 独立 Rust argv builder/response struct/Tauri command/TS 类型；命令固定为 `aisc doctor --format json`。
  - 使用现有结构化 runner、stdout cap、timeout 和 redaction；协议错误保留原错误页及安全摘要。
  - UI 仅展示结构化 checks/summary/hint；原始输出不直接渲染。
- **残余风险**：CLI doctor 自身提供的 detail 仍需持续审查脱敏。
- **证据**：`A-G13-1` 至 `A-G13-4`。

### R-11 G-14：通知权限、重复通知和前台噪音

- **触发条件**：通知权限拒绝；前台也通知；同一 build 的 Promise/event 结果重复提交；最终耗时未冻结。
- **影响**：用户被打扰或看不到完成提示。
- **缓解**：
  - 采用 Tauri notification plugin；权限不可用时静默降级为窗口内完成状态。
  - Frontend 只在 `buildImage()` Promise 首次 settle 时按 operation ID 提交终态；仅当窗口不聚焦/最小化且终态为 complete/failed 时通知一次。
  - 在 store 保存 started/finished/duration；complete/failed/cancelled 均冻结最终耗时。
- **残余风险**：系统勿扰模式由 OS 控制。
- **证据**：`A-G14-1` 至 `A-G14-4`。

### R-12 G-15：动态标题在多 tab/pane 下歧义

- **触发条件**：活动 pane 与 tab 不一致、Windows 路径 basename 解析错误、标题过长。
- **影响**：标题展示错误上下文。
- **缓解**：
  - 标题使用活动 pane 的 Session type；无 pane 时使用活动 tab；无 Session 时仅 workspace；无 workspace 时仅产品名。
  - basename 同时处理 `/` 和 `\`；过长 workspace 名截断但 tooltip/详情保留全路径。
  - 通过 Rust command 或显式 `set-title` capability 更新。
- **残余风险**：OS 可能进一步截断标题。
- **证据**：`A-G15-1` 至 `A-G15-3`。

### R-13 G-16：托盘与退出语义冲突

- **触发条件**：把“关闭”默认改成隐藏；tray 无 owner；退出菜单绕过 session cleanup；无 tray 平台仍隐藏窗口。
- **影响**：应用看似退出但仍运行，或活动 Session 被意外终止。
- **缓解**：
  - 目标名称为“可选最小化到托盘”；默认 `quit` 保持现状。
  - `minimize-to-tray` 使用 hide，不 destroy；tray 显示/退出显式操作。
  - tray 退出复用 `shutdown_workbench`；tray 初始化失败时回退 `quit` 并提示。
- **残余风险**：Linux 桌面环境对 tray 支持不一致。
- **证据**：`A-G16-1` 至 `A-G16-5`。

### R-14 G-17：分屏模型、持久化和资源上限不清

- **触发条件**：pane 与 tab 同级/嵌套定义不一致；旧 history 无 split tree；按 UI 节点而非 Session 计数。
- **影响**：布局无法恢复、Session ownership 重复或无限创建。
- **缓解**：
  - 固定模型：一个 tab 拥有一个 pane tree；叶节点绑定一个 Session；未分屏 tab 是单叶树。
  - 每个 Runtime 在单个 Workbench 进程内 PaneTree 叶节点总数上限 8；`opening/running/closing` 另做资源原子计数。split 容器节点不计叶数；其他 binding 占叶数但不占资源名额。
  - G-08 的重复 tab 保持 history v1；G-17 将 history schema 升为 v2，并在锁内原子迁移 v1 平面 tab 为单叶 tree。
  - 活动上下文由 `active_tab_id + active_pane_id` 唯一确定。
- **残余风险**：复杂布局在小窗口中受最小 240×160 pane 和最大深度 4 限制；空间不足时明确拒绝 split。
- **证据**：`A-G17-1` 至 `A-G17-6`。

### R-15：测试与 CI 门禁不足

- **触发条件**：只有 Python 测试；bundle workflow 不因 `workbench/src/**` 或 package 变化触发；大量验收仅手测。
- **影响**：并发、布局、i18n、依赖和 capability 回归无法及时发现。
- **缓解**：
  - Step 0 增加 Workbench CI：`npm ci`、`npm run build`、前端测试、`cargo test`。
  - bundle/NSIS workflow paths 覆盖 `workbench/src/**`、`package*.json`、Vite/TS 配置。
  - Windows 安装器 smoke 验证 PATH；Tauri/ConPTY/tray/notification 保留 release 实机门。
- **残余风险**：GUI 像素和特定 GPU/桌面环境仍需实机。
- **证据**：`A-INFRA-1` 至 `A-INFRA-5`。

### R-16 G-04：明暗主题切换造成样式与终端割裂

- **触发条件**：组件继续硬编码深色值；Tauri/window、Workbench CSS、xterm theme 和系统控件未同步；切换时重建 Session。
- **影响**：浅色模式不可读、状态色失真、页面闪屏，或终端/宿主主题不一致。
- **缓解**：
  - 只交付 `system | dark | light` 三种模式，不引入主题市场或自定义配色编辑器。
  - 颜色收敛为 semantic CSS tokens；组件禁止新增裸色值。xterm dark/light theme 使用同一 semantic mapping。
  - `system` 监听 `prefers-color-scheme`；用户固定值优先。主题切换只更新 token/xterm options，不重建 Runtime、Session 或 PTY。
  - light/dark 均执行 WCAG AA、状态色、对话框、错误页和终端截图回归。
- **残余风险**：第三方 Agent/TUI 自身配色不受 Workbench 控制。
- **证据**：`A-G04-1` 至 `A-G04-4`。

## 二、风险优先级矩阵

| 风险 | 可能性 | 影响 | 实施 owner | 阻断门 |
|---|---|---|---|---|
| R-02 生命周期/清理回归 | 高 | 高 | Step 0/2 | G-07、G-16 前 |
| R-04 动态 tab 竞态/泄漏 | 高 | 高 | Step 0/5 | G-08、G-17 前 |
| R-15 CI 覆盖不足 | 高 | 高 | Step 0 | 所有功能前 |
| R-01 PATH 破坏 | 中 | 高 | Step 1 | G-18 发布前 |
| R-03 settings/i18n 回归 | 中 | 高 | Step 0/3/4 | G-01/G-09 前 |
| R-08 resize 根因误判 | 高 | 中 | Step 9 | G-02 修改前 |
| R-14 分屏模型错误 | 中 | 高 | Step 16 | G-17 前 |
| R-13 tray/退出冲突 | 中 | 高 | Step 15 | G-16 前 |
| R-05 离屏窗口 | 中 | 中 | Step 10 | G-10 前 |
| R-06 WebGL 兼容 | 中 | 中 | Step 6 | G-06 前 |
| R-07 状态/引导不可达 | 中 | 中 | Step 8 | G-05/G-12 前 |
| R-09 终端菜单回归 | 中 | 中 | Step 11 | G-11 前 |
| R-10 doctor 泄密/协议 | 低 | 高 | Step 12 | G-13 前 |
| R-11 通知噪音 | 中 | 低 | Step 13 | G-14 前 |
| R-12 标题歧义 | 中 | 低 | Step 14 | G-15 前 |
| R-16 主题割裂/对比度 | 中 | 中 | Step 17 | G-04 前 |
