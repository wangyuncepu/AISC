# Fine-Tune 启动与窗口流程

> 基线快照：commit `1f15f8bbb6beeee0e9a6af8a4daa3310ee02747a` 的 `docs/archive/gui-planning/02-startup-flow.md`。  
> 继承清单：§三启动状态机、§四 CLI discovery/capability、§五至§八 preflight/summary/start/cancel/recovery、§十错误 UI、§十一性能反馈、§十二可访问性。  
> 覆盖清单：本文件的动态 tab/恢复、typed settings、语言、geometry、doctor、build 通知和标题条款优先；归档 §九 settings/window 示例不再作为本阶段写入 schema。

## 一、当前流程与增量范围

现有启动流：

```text
negotiate → picker → preflight → summary → starting/building/conflict → ready
                                                    └──────────────→ error
```

本阶段覆盖：

- G-08 默认 tab 与动态 Session type 选择器。
- G-09 用户语言与默认语言解析。
- G-10 窗口 geometry 恢复。
- G-12 未配置 Claude/Codex 引导态。
- G-13 错误页一键诊断。
- G-14 构建最终耗时与后台通知。
- G-15 动态标题。

## 二、F-1 默认 tab 与 Session type 选择器（G-08/G-12）

### 2.1 默认行为

- 首个 Runtime ready 后仅创建并打开 **1 个 Bash tab**。
- 不再预建 4 个 idle tab。
- `+` 选择器始终列出 `Claude / Codex / Bash / cc-switch` 四种 Session type；`AGENT_ORDER` 仅用于显示顺序，不表示“每种只能一个”。
- 同一种 Session type 可以重复创建，每个 tab 有独立 `tab_id` 和 `session_id`。

### 2.2 未配置 Provider

- 用户选择 Claude/Codex 时先创建 `checking` tab/pane，并立即对该 type 执行一次受去重保护的 Provider query；查询返回后再转 `dormant`、`guide` 或 failed，不依赖“已有活动 Claude/Codex tab 才轮询”的旧逻辑。
- `not_configured` 或 `login_required` 不从选择器隐藏 Claude/Codex。
- 用户选择未配置的 Claude/Codex 时，先创建 **引导态 tab**，不调用 `open_session`。
- tab 顶部 banner 显示原因和「打开 cc-switch 配置」动作：
  1. 有可用 cc-switch tab：激活它；
  2. 没有：创建并激活新的 cc-switch tab。
- Provider 变为 `configured` 后，用户在原 tab 点击「启动会话」，才生成新 `session_id` 并调用 `open_session`。
- Provider capability 缺失时显示 `Unknown · 需升级 CLI`，不得误判为未配置。

### 2.3 布局恢复

- 恢复输入是完整 `layout.tabs[]`，不是 agent 列表。
- 按 `position` 排序，逐记录重建 tab/pane；重复 Session type 不去重。
- 先为所有记录创建新的 `tab_id/pane_id`，建立 saved ID → new ID 映射；Bash/cc-switch 初始 binding=`dormant`，Claude/Codex 初始 binding=`checking`，均尚无 `session_id`。
- tree 建立后立即对恢复出的 Claude/Codex 按 `(runtime_id, session_type)` 各发一次去重 Provider query；同 type 的多个 pane 共享结果，不依赖旧活动 tab 轮询。
- Provider query 完成后再按保存顺序自动启动可启动项：Bash/cc-switch 及 auth=`configured` 的 Claude/Codex。每个实际启动项才生成新 `session_id`。
- `not_configured/login_required/unknown` 的 Claude/Codex 恢复为 `guide`，不生成 `session_id`；Provider 变为 configured 后由用户点击启动。
- 每个 Runtime 最多恢复 8 个 pane 叶节点；超出的保存记录不创建 UI 叶，显示“布局已截断”warning。前 8 个中可启动项最多占用 8 个 Session 资源名额；释放资源名额后 dormant/guide 叶可手动启动。
- active 恢复流程：`saved active_tab_id/pane_id → 新 ID`；映射失败时激活第一 tab 的第一 pane。
- 不恢复 PTY 内容、旧 `session_id` 或旧 running 状态；新 Session 只通过新的 opening→running 流程建立。

## 三、F-2 设置与语言初始化（G-01/G-09）

### 3.1 启动读取顺序

Tauri 启动后并行读取 typed settings 和 capability；语言解析不得阻塞 CLI 协商。

`settings.ui.language` 取值：

- `auto`：按环境探测；
- `zh-CN`：固定中文；
- `en-US`：固定英文。

当值为 `auto` 或字段不存在时，按以下顺序选默认语言：

1. Windows 安装器语言；
2. 系统语言；
3. `zh-CN`。

用户显式选择必须优先于安装器/系统语言，不得在下次启动被覆盖。

### 3.2 安装器语言来源

- Windows 由 Rust backend 读取 NSIS 固定 key：`HKCU\Software\aisc\AISC Workbench\Installer Language`。
- 打包元数据固定 `manufacturer=aisc`、`productName=AISC Workbench`；CI 对生成后的 NSIS define 和 Rust 常量做一致性断言。
- 支持值：`1033 → en-US`，`2052 → zh-CN`；未知/读取失败返回 `None`。
- 非 Windows 返回 `None`，继续系统语言探测。

### 3.3 字典边界

必须字典化：negotiate、picker、preflight、summary、build、conflict、ready、error、侧边栏、tab、设置、对话框、Workbench 自己写入终端的欢迎/错误文本、托盘菜单和通知。

不翻译：Agent/TUI/CLI 的原始终端字节流、原始命令名、稳定错误码、文件路径和用户输入。

### 3.4 Settings 字段与边界

持久化 JSON 使用 snake_case；Frontend domain 可映射 camelCase，但组件不得直接写原始 JSON。`schema_version` 本阶段保持 1，新增 `revision`（缺失按 0）和其他字段均为向后兼容可选字段。

Settings 保存协议：settings/history 使用各自独立 lock；save 在锁内 reload 并比较 expected revision，字段级 patch 深合并 typed 值和 raw unknown map，冲突最多 reload/replay 3 次；temp+fsync+平台原子 replace。schema 高于支持版本时只读并拒绝覆盖；corrupt 文件先隔离备份，只有用户确认“重置设置”才写默认文件。

| 字段 | 默认 | 合法范围/枚举 | 生效 |
|---|---|---|---|
| `ui.language` | `auto` | `auto \| zh-CN \| en-US` | 即时 |
| `ui.font_scale` | `1.0` | `0.80..1.50`，步长 0.05 | 即时 |
| `ui.theme` | `system` | `system \| dark \| light` | 即时 |
| `terminal.font_family` | `Cascadia Mono, Cascadia Code, Consolas, monospace` | 非空 UTF-8，≤256 字符 | 重建 Terminal view，不重开 Session |
| `terminal.font_size` | `14` | `10..24` integer | 即时 |
| `terminal.line_height` | `1.2` | `1.0..1.6`，步长 0.05 | 即时 |
| `terminal.letter_spacing` | `0` | `-1..3` integer | 即时 |
| `terminal.scrollback` | `5000` | `1000..50000` integer | 即时 |
| `terminal.renderer` | `auto` | `auto \| default \| webgl`；Workbench addon 策略，不是 xterm option | 重建 Terminal view，不重开 Session |
| `terminal.smooth_scroll_duration` | `100` | `0..500` ms integer | 即时 |
| `window.remember_geometry` | `true` | boolean | 下次启动/保存 |
| `window.close_behavior` | `quit` | `quit \| minimize-to-tray` | 即时；tray 不可用时回退 quit |

非法字段按字段回退默认并报告 validation issue；unknown schema 整文件只读并拒绝覆盖。Reset GUI settings 不清除 `aisc_cli_path`、history、workspace 或 Runtime。

### 3.5 G-04 主题契约

- 范围仅 `system | dark | light`；不做大量预设、自定义 palette、主题导入/导出。
- `system` 跟随 `prefers-color-scheme`；系统变化即时应用。用户选择 dark/light 后不再随系统变化。
- Workbench 颜色使用 semantic tokens：background/surface/text/muted/border/accent/success/warn/error/selection/focus。组件不得新增主题相关裸色值。
- Terminal dark/light palette 与 semantic tokens 同步；主题切换更新 xterm options，不重建 Terminal、Session 或 PTY。
- 启动时在首帧渲染前解析主题，避免先暗后亮闪屏；持久化失败不谎称已保存。

## 四、F-3 窗口 geometry（G-10）

### 4.1 设置结构

```json
{
  "window": {
    "remember_geometry": true,
    "close_behavior": "quit",
    "geometry": {
      "x": 100,
      "y": 80,
      "width": 1200,
      "height": 800,
      "maximized": false
    }
  }
}
```

坐标和尺寸使用 Tauri logical units。`geometry` 可为 `null`。窗口枚举、monitor clamp、应用和读取 rect 统一由命名 Rust commands `restore_window_geometry` / `capture_window_geometry` 完成；前端只监听防抖事件并请求保存，不授予通用 position/size capability。

### 4.2 恢复规则

- `remember_geometry=false` 或无有效记录：沿用当前 Tauri/操作系统默认位置与 `tauri.conf.json` 默认尺寸，不宣称必然居中。
- 恢复前将 client size clamp 到最小 800×600 logical px；至少 64×64 logical px 必须落在当前任一显示器工作区。
- 完全离屏时将窗口夹取到主显示器可见区域；显示器/DPI 变化不导致窗口不可达。
- `maximized=true` 时先恢复经校验的普通 rect，再最大化。
- fullscreen 不作为持久化 geometry。

### 4.3 保存规则

- move/resize 事件防抖 300 ms；最大化/最小化的瞬时 rect 不覆盖普通 rect。
- 正常退出和 tray 退出前强制 flush；崩溃不作必然保存承诺。
- settings 写失败不阻止主流程，保留可恢复错误供设置页显示。

## 五、F-4 错误页诊断（G-13）

- error/blocked 视图保留 Retry/Back 和稳定错误码详情。
- 增加「运行诊断」按钮，调用完整命令：

```text
aisc doctor --format json
```

- Rust backend 新增独立 argv builder、响应类型和 Tauri command；复用结构化 runner 的 timeout、stdout cap、exit-code 校验和脱敏。
- UI 展示 `data.host.checks`、`data.host.summary` 及各 check 的 `hint`；`data.container` 当前为 null 时省略，不解析人类文本，不直接渲染原始 stdout/stderr。
- doctor 非零退出、超时或无效 JSON 时：原错误页保持不变，诊断区域显示结构化 Workbench error，并允许重试。

## 六、F-5 动态标题（G-15）

标题由纯函数计算，优先级固定：

1. 有有效活动 pane：`<workspace> · <Session type> · AISC Workbench`；
2. active pane 无效但活动 tab 的 tree 有叶：使用深度优先第一个叶的 Session type；
3. 已选择 workspace 但活动 tab 无有效叶：`<workspace> · AISC Workbench`；
4. 其他状态：`AISC Workbench`。

规则：

- workspace basename 同时处理 `/` 和 `\`，去除尾分隔符。
- 使用 Session type 文案，不使用 provider/model 名。
- 标题由活动上下文变化驱动，不由轮询 ticker 驱动。
- 标题通过前端 `getCurrentWindow().setTitle()` 更新，并仅新增 `core:window:allow-set-title` capability；不新增通用 Rust 窗口命令。

## 七、F-6 构建完成反馈（G-14）

现有 BuildProgress 已显示“构建中”经过时间；本阶段补齐：

- store 持久当前进程内的 `buildStartedAt`、`buildFinishedAt`、`buildDurationMs`。
- Rust build runner 仍以唯一 CLI terminal event 判定 command 结果；Frontend store **仅以 `buildImage()` Promise settle** 提交一次 `complete/failed/cancelled` 终态，Channel terminal event 不直接二次写状态。
- store 的首次终态提交冻结 `buildFinishedAt/buildDurationMs` 并停止 timer；同一 `operation_id` 的迟到/重复结果忽略。
- 构建结束后页面继续显示最终耗时。
- 仅当窗口失焦或最小化且终态为 `complete` 或 `failed` 时发送一次系统通知；前台不发送，`cancelled` 默认不通知。
- 首次满足“后台 complete/failed”条件时调用 `isPermissionGranted()`；若未授权且本次会话尚未请求，则调用一次 `requestPermission()`。结果 `granted` 才 `sendNotification()`；`denied/default/error` 本次构建只降级页面内状态，不循环弹权限。应用重启后可再次尝试一次。
- 最小 capability 固定为 `notification:allow-is-permission-granted`、`notification:allow-request-permission`、`notification:allow-notify`。
- 通知权限拒绝或插件不可用时静默降级为页面内状态，不把构建标为失败。
- 桌面通知仅作提示，不承诺跨平台点击回调；用户从任务栏/托盘重新打开后，页面必须保留该 build 的终态和最终耗时。若未来增加点击聚焦，需单独设计平台激活/deep-link/single-instance 契约。

## 八、启动与窗口验收

### A-G01-1 设置基础读写

- Given settings 不存在/合法/含未知字段，When load→修改一个 GUI 字段→save→reload，Then 默认值正确、目标字段生效、未知字段和 `aisc_cli_path` 保留。
- 自动化：Rust settings round-trip + 前端设置 store；Windows/Linux/macOS。

### A-G01-2 字段校验与恢复

- 对表中每个数值测试 min/max/越界/错误类型；非法字段仅字段级回退并产生 validation issue，其他合法字段不丢失。
- unknown schema 保留原文件并禁用保存；corrupt file 不静默覆盖。

### A-G01-3 生效边界

- 语言、UI scale、font size/line height/letter spacing/scrollback/smooth scroll 按表即时生效。
- font family/renderer 仅重建 Terminal view；原 `session_id`、PTY child 和 scrollback（在 xterm 可迁移范围外）不重开/不伪造恢复。

### A-G01-4 Reset 隔离

- Reset 后 GUI 字段恢复默认；`aisc_cli_path`、history、workspace `.aisc`、Runtime/container 均逐项保持。

### A-G01-5 可访问性与保存失败

- 设置页全键盘可达、字段有 label/error/生效说明；模拟 lock timeout/写失败时显示可重试错误，内存值与磁盘值不混称为已保存。

### A-G04-1 模式解析与持久化

- `system/dark/light` 三值解析正确；用户固定值优先于系统；重启保持。非法值字段级回退 `system` 并产生 validation issue。

### A-G04-2 首帧与运行时切换

- cold start 在首个可见 frame 前应用目标主题，无先暗后亮/先亮后暗 mutation；运行时切换不重建 Runtime、Session、PTY 或改变 `session_id`。

### A-G04-3 覆盖与对比度

- blocked/picker/summary/build/conflict/ready/error/settings/tray/context menu 和 Terminal 在 dark/light 各有截图基线；正文及关键控件达到 WCAG AA 4.5:1，focus/status 不只依赖颜色。

### A-G04-4 System 监听与清理

- `system` 模式下模拟系统 dark↔light 各 20 次，UI/xterm 同步且 listener 单实例；切换为固定模式后系统事件不再改主题，卸载时 listener 清理。

### A-G08-1 默认与动态 tab

- Given 全新 history、Runtime ready，When 进入 workspace，Then 仅存在 1 个 binding 为 `opening` 或 `running` 的 Bash tab。
- 连续创建两个 Claude tab 时，两个 tab/session ID 不同且互不影响。

### A-G08-2 未配置引导

- Given Claude auth=`not_configured`，When 从 `+` 选择 Claude，Then 创建引导态 tab且不调用 `open_session`；点击动作激活或创建 cc-switch。

### A-G08-3 恢复重复类型

- Given history 包含两个 Bash `TabRecord`，When 恢复布局，Then 还原两个 tab、顺序和 active 映射，并为实际启动项创建不同的新 Session。
- 未配置/unknown Claude/Codex 恢复为 guide、无 `session_id`；超过每 Runtime 8 个 pane 叶节点的保存记录被截断并产生 warning。

### A-G08-6 快捷键与焦点

- `Ctrl/Cmd+1..9` 映射当前已提交 tab 顺序；第 10 项以后使用 Left/Right/Home/End。
- 删除 active tab 后 DOM focus 与 active ID 同步落到右邻、左邻或空态“新建”按钮；pending removal 不重新参与序号映射。

### A-G08-7 停止与退出联动

- Given 1/8 个动态 tab，When stop Runtime 或 quit，Then 新建被拒绝、所有资源占用 Session 进入统一 shutdown/stop 流程，guide/dormant 不调用 terminate，最终无 child 残留。

### A-G08-8 上限与并发创建

- 同一 Runtime 并发请求第 8/9 个叶节点时，最多 8 个 PaneTree commit；第 9 个 tree 不变。已有 8 叶中的 Session start 仍以 opening/running/closing reservation 原子化，失败不留下半状态。

### A-G09-1 语言优先级

- 用户固定 `en-US` 时，即使安装器/系统是中文，重启仍为英文。
- `auto` 时 1033/2052/未知值分别解析为英文/中文/系统或中文 fallback。

### A-G09-2 字典完整性

- 自动扫描 `workbench/src/**/*.{vue,ts}`；除 allowlist 的 raw code/path/terminal bytes 外，用户可见硬编码使测试失败。
- zh-CN/en-US key 集完全相同，不存在 key、错误复数参数或空翻译均失败。

### A-G09-3 运行时切换

- 在 picker/summary/ready/error/settings 任一主状态切换语言，静态和动态文案、ARIA、tray/notification 后续文案立即使用新 locale；Runtime/Session/PTY 不重建。

### A-G09-4 原始内容边界

- CLI code、路径、用户输入、Agent/TUI 原始字节逐字不变；Workbench 自写欢迎/Exit/Error 辅助文本随 locale 变化，且不污染 PTY 输入。

### A-G10-1 geometry

- Windows：正常 rect 重启后 client size/position 在 ±2 logical px 内恢复。
- macOS/Linux：client size 在 ±4 logical px 内，位置允许窗口管理器调整，但必须位于同一显示器工作区且至少 64×64 可见。
- 保存显示器移除后重启，窗口至少有 64×64 logical px 可见。
- `window.remember_geometry=false` 时忽略已保存 rect。

### A-G10-2 单位与状态

- logical/physical conversion、DPI 100%/150%/200%、maximized→normal→restart 均使用普通 logical rect；fullscreen/minimized 瞬时值不覆盖。

### A-G10-3 异常数据

- width/height 小于 800×600 时 clamp 到最小值；非有限/缺字段/超大坐标按无效记录处理，不阻止启动并产生 warning。

### A-G10-4 多显示器

- 主/副屏交换、拔除保存屏、负坐标排列和不同 DPI 下，恢复窗口可见且不跨屏形成小于最小尺寸的 client area。

### A-G10-5 保存与退出

- move/resize 高频事件在 300ms 防抖内合并；正常 quit/tray exit 强制 flush。写失败显示可恢复错误，旧磁盘 geometry 保持可读。

### A-G13-1 诊断

- doctor 成功时 `data.host.checks/summary` 可读；非零、超时、协议错误均不替换原错误事实，也不展示未脱敏原始输出。

### A-G13-3 入口与重入

- blocked/error/ready details 均可触发同一命名 command；在途时按钮禁用，重复点击不启动第二个 doctor；返回/关闭诊断不改变 startup state。

### A-G13-4 安全与兼容

- check `hint/detail` 经过 redaction；未知 check/字段可忽略并继续显示已知项；`data.container=null` 省略，未来结构存在时不导致 host 解析失败。

### A-G14-1 耗时与通知

- complete/failed/cancelled 均冻结最终耗时；窗口前台 0 条系统通知；窗口后台时 complete/failed 恰好 1 条，cancelled 为 0 条。

### A-G14-2 单一终态

- 对同一 `operation_id` 注入 terminal Channel event 与 Promise settle 的两种乱序，store 只接受首次 Promise settle 一次；duration、状态和通知不重复。

### A-G14-3 权限与降级

- 通知 permission granted/denied/unavailable、OS 勿扰均不改变 build 事实状态；拒绝/不可用时页面内终态和最终耗时仍完整。

### A-G14-4 生命周期

- complete/failed/cancelled 后 elapsed timer、Channel listener 和 notification request 均有 cleanup；离开再返回页面仍显示冻结值，不继续增长。

### A-G15-1 标题

- Windows/POSIX 路径均只显示 basename；多 pane 时标题跟随活动 pane；无 Session 时不残留旧 Session type。

### A-G15-2 状态矩阵

- active pane → active tree 第一叶 fallback → workspace → product 四种输入产生唯一标题；guide/dormant/failed pane 使用其 Session type，空 tree 不显示旧 type。

### A-G15-3 Unicode 与权限

- workspace 超过 40 grapheme 时保留首尾各 18 grapheme，中间 `…`；中文、emoji、组合字符不截断 code point。
- 仅 `core:window:allow-set-title` 权限存在；setTitle 失败不影响主流程并记录可恢复 warning。

### CLI 回归门

以下命令在 GUI 改动前后 envelope、退出码和默认语义一致：

```text
aisc version --format json
aisc doctor --format json
aisc runtime preflight ... --format json
aisc runtime stop ... --format json        # 默认 grace 仍为 10
aisc session terminate ... --format json   # 默认 grace 仍为 5
```
