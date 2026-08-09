# Fine-Tune 生命周期契约

> 基线快照：commit `1f15f8bbb6beeee0e9a6af8a4daa3310ee02747a` 的 `docs/archive/gui-planning/03-lifecycle-contract.md`。  
> 继承清单：§一 Workspace/Runtime/Session 身份、§二不变量、§三 RuntimeSpec、§四 Runtime 状态机、§五 Session 状态机、§八崩溃/外部操作恢复、§九并发排序、§十 Domain API/error shape（由本文件增量扩展）。  
> 覆盖清单：归档 §六 Tab 契约、§七关闭/退出和 history layout 相关条款以本文件动态 Tab/Pane/shutdown 设计为准。CLI 命令与默认值以 `05-cli-gui-contract.md` 为最终权威。

## 一、沿用不变量

- Runtime 与 Session 状态枚举沿用基线。
- PTY/child 的单一终止结果由 Rust backend reducer 产生；前端不自行合并多个终止信号。
- Runtime observation 使用 `request_seq / revision` 防回退。
- 停止 Runtime 保留 container、registry metadata、image 和 volume；remove 的删除语义不变。
- Session 只属于一个 Runtime，不能迁移；恢复 layout 只创建新 Session。

## 二、身份与数据模型

```text
Workspace
└── Runtime(runtime_id)
    └── Tab[]
        └── PaneTree
            ├── Split(axis, ratio, first, second)
            └── Pane(pane_id, session_binding)
```

### 2.1 Tab

```text
Tab
  tab_id: UUID
  title: string
  position: integer
  root_pane: PaneNode
  active_pane_id: UUID
```

- G-08 未分屏 tab 的 pane tree 只有一个叶节点。
- 同一种 Session type 可出现多次；agent/type 不是唯一键。
- `tab_id` 是 UI/layout 身份，不是 `session_id`。

### 2.2 Pane

```text
Pane
  pane_id: UUID
  session_type: claude | codex | bash | cc-switch
  binding: checking | dormant | guide | opening(session_id) | running(session_id) |
           closing(session_id) | exited(summary) | failed(summary)
```

- `checking` 是 Claude/Codex 等待首次 Provider query 的瞬态，不持有 Session，查询完成后只转 `dormant`、`guide` 或 `failed`。
- `dormant` 是已恢复/新建但尚未启动的普通 pane，不持有 Session。
- `guide` 用于 Provider 未配置或状态无法确认的 Claude/Codex，不持有 Session。
- 一个 Pane 在任一时刻至多绑定一个 Session。
- 每个 Runtime 在单个 Workbench 进程内，PaneTree 叶节点总数不超过 8；其中资源占用态 `opening/running/closing` 另做原子计数，closing 完成前不释放资源名额。`checking/dormant/guide/exited/failed` 不占资源名额，但仍占叶节点名额。

### 2.3 Session registry

`SessionRegistry` 必须把“预留/启动/关闭”本身建模，不能只保存已运行 entry：

1. `open_session` 先在 mutex 内按 `session_id` 原子插入 `Reserved`；重复 ID 在 spawn 前失败。
2. spawn/open 成功后替换为 `Running`；任何 spawn、Channel bridge 或注册失败必须 kill+reap 已创建 child 并删除 reservation。
3. `close_session` 把 entry 原地转为 `Closing`，在 terminate/wait/force-reap 完成前不从 registry 移除。
4. 并发/重复 close 共享同一 closing completion/result，不重复 terminate 或丢失 child ownership。
5. `shutdown_workbench` 枚举并接管 `Reserved/Running/Closing`；其中 `Reserved` 回滚，`Running` 发 close，`Closing` 等待同一 completion。
6. 只有 terminal result 已缓存并满足 ack/TTL 协议后才删除 entry。

`SessionEntry` 至少保存：

```text
session_id
runtime_id
canonical_workspace
session_type/agent
PTY handles
state
exit?
generation
```

`aisc session open/terminate` 必须传相同 `--workspace`。任何新 Session event 必须同时匹配 `session_id` 和当前 generation，旧事件不得写入已重开/删除的 pane。

## 三、G-08 动态 tab 生命周期

### 3.1 创建

```text
createTab(type)
  → 新 tab_id + 单叶 pane
  → 若需要引导：binding=guide
  → 否则新 session_id，binding=opening
  → open_session
  → running | failed
```

### 3.2 关闭会话与删除 tab

必须区分：

- `closeSession(pane_id)`：终止 Session，保留 pane/tab 为 exited，可重新打开。
- `removeTab(tab_id)`：对该 tab 所有活 Session 执行 bounded close；随后从 layout 删除。

TabBar 的 `×` 采用 `removeTab`（Windows Terminal 语义）。如果正在关闭：

1. tab 标记 `pending_removal=true` 并停止接受输入；
2. 并发关闭其所有活 Session；
3. 终止结果或硬超时后删除 tab；
4. 迟到事件因 generation/tab 已不存在而被丢弃；
5. active tab 选右侧邻项，否则左侧，否则进入空态。

全部 tab 删除后 Runtime 继续运行，页面显示空态和「新建 tab」。

### 3.3 自然退出回收

采用固定的显式 ack 协议：

1. backend observer wait/reap child，写入 terminal `SessionExit`，并向前端发送唯一 Exit。
2. 前端先按 `session_id + generation` 提交 pane 状态，再调用幂等 `ack_session_exit(session_id)`。
3. `ack_session_exit` 仅删除已处于 terminal state 的 registry entry；活 Session 返回稳定错误，已删除 entry 返回成功 `already_acknowledged`。
4. `close_session` 命中 terminal entry 时返回缓存 Exit 并删除 entry；随后到达的 ack 仍幂等成功。
5. 前端/窗口崩溃导致未 ack 时，backend 只保留已 reap 的 metadata：terminal entry TTL 为 60 秒，且每个 Runtime 最多 32 条；超限按 finished time 删除最旧项。
6. reopen 必须先生成新 `session_id/generation`；旧 Exit/ack 不得影响新 Session。

验收：同一 pane 自然退出/reopen 100 次后，registry 中无旧活 child，terminal metadata 不超过上述上限。

### 3.4 History 兼容

当前 `layout.tabs[]` schema 可容纳重复 type，但现有恢复算法不兼容。必须：

- 逐 `TabRecord` 恢复；
- 按 position 排序；
- 建立 saved `tab_id` 到新 `tab_id` 的映射；
- 不按 agent `.find()`；
- 不恢复旧 `session_id`。

## 四、G-07 关闭与停止性能

### 4.1 单 Session close

Workbench Rust 预算：

- `TERMINATE_TIMEOUT = 5s`：运行 `aisc session terminate --grace 3` 的 Workbench command budget。为与该预算兼容，CLI 的 terminate application timeout 必须从当前 `grace + 10s` 收敛为 `grace + 1s`（Workbench 路径最多 4s），同时保留 standalone CLI 默认 grace 5 秒；Docker/CLI 超时后由 Rust 本地回收兜底。
- `CLOSE_WAIT = 4s`：terminate 返回后等待 PTY child/Exit。
- `CLOSE_FORCE_WAIT = 2s`：force kill 后最终 reap 等待。

这些是**硬上限路径**，不是“所有关闭都必须等满”。Duration 应可注入测试。

正常性能目标：

- P50 单 Session close ≤ 1.5s；
- P95 单 Session close ≤ 4s；
- 硬超时路径 ≤ 11.5s（含调度余量）；
- 多 Session 并发关闭的 P95 ≤ 最慢单 Session P95 + 1s，不按 Session 数线性累加。

计时起点：用户确认或调用 close action；终点：唯一 Exit 已提交且本地 child 已 reap。

### 4.2 Runtime stop

- CLI 直用省略 `--grace` 时解析为 10 秒：

```text
aisc runtime stop ... --format json
```

Workbench 路径：

```text
aisc runtime stop --grace 3
```

停止采用分阶段并发，避免 Runtime 先停导致全部 session terminate 的 `docker exec` 失败：

1. UI/registry 拒绝创建新 Session，所有活 Session 进入 closing，本地 PTY 停止接受输入。
2. 并发发起 session terminate。
3. 等待全部 terminate 请求完成 CLI spawn，或固定 400ms deadline，以先发生者为准；不等待 terminate 全部完成。
4. 发起 Runtime stop。
5. Runtime stop 确认后，容器内 Session 视为终止；继续有界回收所有本地 PTY/CLI child。
6. 最后 `runtime inspect`，只有观察到 stopped/not_found 才更新事实状态。

必须覆盖三种竞争：terminate 先完成、stop 先完成、容器开始时已停止。

Runtime stop 计时起点为用户确认，终点为 inspect 得到 `stopped/not_found` 且本地 child 全部 reap。标准环境目标：0/1/8 个 Session 的 P95 分别 ≤5s/6s/7s，hard deadline 35s；Docker stop grace 包含在总时长内。

### 4.3 Workbench 退出协调器

禁止“前端 fire-and-forget 后销毁最后窗口，并假定后台继续收尾”。新增 Rust `shutdown_workbench`：

```text
close-requested
  → confirming (frontend)
  → shutdown_workbench(mode)
      → reject-new-sessions
      → bounded concurrent session close
      → optional runtime stop (仅用户明确选择)
      → force-reap leftovers
      → flush settings/history
      → return ShutdownReport
  → window.destroy / app.exit
```

- 默认退出保留 Runtime，只结束本 Workbench 拥有的 Session。
- 总 hard deadline 固定为 12 秒；所有内部等待读取同一剩余 deadline，不把 5s/4s/2s 串行重复计满。
- graceful concurrent close 阶段最多 6 秒；到期后取消/终止仍在运行的 CLI terminate，并进入最多 2 秒的本地 force-kill 请求与 reap。
- settings/history flush 预留最多 1 秒；剩余时间用于汇总和返回 `ShutdownReport`。
- `ShutdownReport` 至少包含 `graceful_closed`、`force_reaped`、`terminate_timed_out`、`reap_timed_out`、`unreaped_session_ids`、`flush_errors`。
- 只有 `unreaped_session_ids` 为空时前端才可正常 destroy/exit。若 reap 超时，退出被阻止并显示「重试退出 / 保持窗口并查看详情」；不得仅因 deadline 到达而遗弃仍由本进程持有的 child。
- 若用户选择同时停止 Runtime，使用独立 hard deadline 35 秒（覆盖 Workbench `--grace 3`、runner/inspect 余量）；Session cleanup 仍复用上述阶段，不额外串行 12 秒。
- 最后一个窗口 destroy 之后不再承担任何必要 cleanup。

## 五、G-16 窗口与托盘生命周期

`window.close_behavior`：

- `quit`（默认）：显示现有活动 Session 确认，调用 `shutdown_workbench`，返回后退出。
- `minimize-to-tray`：close request 仅 hide 窗口，不关闭 Session，不 destroy。

Rust 持有 tray owner，并在主窗口 `CloseRequested` 统一 `prevent_close()`，避免默认 destroy 抢先发生。

Tray 菜单：

- `显示`：show + unminimize + focus 主窗口；
- `退出`：向主窗口触发与 `quit` 相同的确认；确认后调用 `shutdown_workbench`，仅在 report 允许时 app exit。
- OS/app `ExitRequested` 作为兜底也必须走 shutdown gate；不得从 tray/menu handler 直接 `std::process::exit` 或绕过 flush/reap。

Tray 初始化失败或平台不支持时：

- 不隐藏最后窗口；
- 行为回退 `quit`；
- 设置页显示平台/初始化不可用原因。

## 六、G-17 分屏模型

### 6.1 模型与事务语义

- 一个 Tab 拥有一个 PaneTree；叶 Pane 绑定或准备绑定 Session。
- PaneTree 最大深度 4；split `axis` 为 `horizontal | vertical`，ratio clamp 为 `0.10..0.90`，默认 `0.50`。
- 每个 pane 最小 240×160 logical px；当前可用尺寸不足时拒绝 split，tree 不变。divider 支持指针拖动及键盘 0.05 步长调整。
- 分屏前先原子验证目标叶和容量。需要启动资源占用 Session 时先在 SessionRegistry 预留名额，再提交 PaneTree；第 9 个请求失败时 tree 完全不变。
- Provider 为 `not_configured/login_required/unknown` 时允许提交新叶，但 binding=`guide`、无 `session_id`、不占容量。
- PaneTree 已提交后 `open_session` 失败时保留 `failed(summary)` 叶供重试/关闭，不静默回滚布局。
- 关闭非最后 Pane：close Session 后删除叶节点，父 Split 压缩为剩余兄弟。
- 关闭 Tab 的最后 Pane：保留该 Tab 和单叶 `dormant` pane（沿用原 Session type），显示「启动/更换 Session」；只有 TabBar `×` 删除 tab。
- 关闭 Tab：关闭该 tree 全部活 Session 并删除 tab。
- 活动上下文由 `active_tab_id + active_pane_id` 唯一决定。

### 6.2 Resize

每个可见 Pane 独立：

```text
ResizeObserver → FitAddon.fit → resize_session(session_id, cols, rows)
```

resize 需节流且按 session ID 去重；隐藏 pane/tab 不发送零尺寸。分割拖动结束后必须发送最终尺寸。

### 6.3 持久化

G-08 的平面重复 tab 继续使用 history schema v1。G-17 引入分屏时将 history `schema_version` 升为 **2**，避免旧版本读写后静默丢弃 split tree：

PaneTree 的持久化 tagged union 固定为：

```text
PaneNode =
  { kind: "split",
    axis: "horizontal" | "vertical",
    ratio: number,
    first: PaneNode,
    second: PaneNode }
| { kind: "pane",
    pane_id: UUID,
    session_type: "claude" | "codex" | "bash" | "cc-switch" }
```

- binding、`session_id`、exit summary 和 Provider 状态不持久化。
- 恢复时为所有 saved pane ID 建立 saved→new 映射，再恢复 `active_pane_id`；Session 依 `02` 的恢复状态机新建。
- 非法 kind/axis、非有限 ratio、重复 pane ID、深度>4、叶数>8 或空 tree：该 tab 降级为使用 legacy `agent` 的单叶 dormant tree，并记录可恢复 history warning，不覆盖原文件直到用户确认保存。
- legacy `agent` 固定为：有效 active pane 的 type；否则深度优先第一个叶的 type；无有效叶时为 `bash`。

示例：

```json
{
  "schema_version": 2,
  "workspaces": [
    {
      "layout": {
        "active_tab_id": "...",
        "tabs": [
          {
            "tab_id": "...",
            "agent": "bash",
            "title": "Bash",
            "position": 0,
            "split_layout": {
              "version": 1,
              "active_pane_id": "pane-a",
              "root": {
                "kind": "split",
                "axis": "horizontal",
                "ratio": 0.5,
                "first": {"kind": "pane", "pane_id": "pane-a", "session_type": "bash"},
                "second": {"kind": "pane", "pane_id": "pane-b", "session_type": "claude"}
              }
            }
          }
        ]
      }
    }
  ]
}
```

迁移规则：

- 新版本首次读取 v1 时，在锁内迁移为 v2；每个旧 tab 转成单叶 tree，保留 tab ID、顺序和 active tab。
- 迁移前保留可诊断备份，使用 atomic replace；迁移失败不覆盖 v1 原文件。
- 旧版本读取 v2 时沿用现有 unsupported-schema 保护：保留文件、不写默认值。因此这是向前迁移，不承诺旧版本编辑 v2。
- `agent` 作为 flat fallback 保留，代表活动或第一叶的 Session type；v2 writer 必须同步写入。
- settings/history 测试覆盖 v1→v2、v2 round-trip、损坏数据、并发 migration 和 downgrade refusal。

## 七、G-06/G-11 Terminal 资源生命周期

每个 Terminal/Pane 独立拥有并在卸载时清理：

- xterm Terminal；
- FitAddon；
- 可选 WebglAddon；
- SearchAddon；
- ResizeObserver；
- resize timer；
- input/output subscriptions；
- context-menu/search UI listener。

WebGL 初始化失败或 context loss 不改变 Session 状态；dispose addon 后继续使用 xterm 默认 renderer。

右键菜单粘贴复用 `write_session` 的 1 MiB（1,048,576 bytes）上限和背压，不新增任意 shell/命令通道。

### A-G06-1 WebGL 成功路径

- 支持环境加载 WebglAddon 后输入、输出、selection、resize 正常；renderer setting=`webgl` 且 addon active，卸载后 GPU/context 资源释放。

### A-G06-2 回退路径

- 构造异常和 context loss 分别注入，Session 状态不变，addon dispose，默认 renderer 在 500ms 内继续渲染和接受输入。

### A-G06-3 设置与重建

- `auto/default/webgl` 切换遵循 `02` 设置边界；仅重建 Terminal view，不创建新 `session_id`，listener/observer 数量不增长。

### A-G06-4 固定输出基准

- 使用仓库内固定 10 MiB UTF-8/ANSI 混合 fixture（记录 SHA-256），4 KiB chunks 连续写入；标准测试机无 >200ms main-thread long task，输入回显 P95≤100ms，并记录 default/WebGL 总耗时而不设虚假 FPS。

### A-G06-5 视觉与字体

- 终端正文/背景和 selection 文本达到 WCAG AA 4.5:1；字体缺失依次 fallback；中英文、宽字符、emoji、combining character 的光标/选择位置通过截图基线。

### A-G03-1 搜索体验

- SearchAddon 每 pane 独立；`Ctrl/Cmd+F`、右键入口、前后结果、大小写、无结果、Esc 关闭可用；tab/pane 切换不串查询。

### A-G03-2 复制与粘贴

- selection 复制、快捷键和右键行为一致；粘贴保持 UTF-8/换行，遵守 1 MiB backend 上限和背压；权限失败显示可恢复错误。

### A-G03-3 滚动与 scrollback

- 鼠标滚轮、触控板、PageUp/PageDown、Home/End 在 5000 行默认 scrollback 下工作；用户向上查看历史时新输出不强制跳底，回到底部后 follow output 恢复。

### A-G03-4 输入与清理

- 中文 IME、宽字符、emoji、combining character 的输入/选择/复制不破坏字节流；关闭 pane 后 SearchAddon、clipboard/context listener、scroll handler 全部 dispose。

### A-G11-1 菜单状态

- 有/无 selection、clipboard 成功/失败、running/closing pane 下复制/粘贴/搜索/清屏 enabled 状态符合规范；菜单关闭后焦点回终端。

### A-G11-2 搜索

- SearchAddon 每 pane 独立；大小写/上下方向/无结果、关闭搜索和 tab/pane 切换不串状态，dispose 后 listener 数归零。

### A-G11-3 剪贴板权限

- 仅声明 read-text/write-text capability；复制 ID 和终端 selection 走同一 plugin；权限拒绝显示可恢复错误，不吞掉为“已复制”。

### A-G11-4 粘贴边界

- 1 MiB 恰好成功，1 MiB+1 byte 在 backend 拒绝；多字节 UTF-8 按 bytes 计数；粘贴不进入日志/history/crash report。

## 八、生命周期验收

### A-G07-1 CLI 默认不变

- `aisc runtime stop` 未传参数时 FakeDockerExecutor 记录 timeout=10；Workbench argv 明确含 `--grace 3`。
- `aisc session terminate` 未传参数时 grace=5；Workbench close argv 明确含 `--grace 3`。

### A-G07-2 竞争与回收

- terminate-first、stop-first、already-stopped 三种顺序均产生一个终止结果；宿主 child/PTY 无残留。
- 多 Session stop 不串行累加全部 timeout。

### A-G07-3 退出

- `shutdown_workbench` 返回且 `unreaped_session_ids=[]` 后才 destroy；前端 destroy 后没有必要后台任务。
- terminate/reap/flush timeout 均进入对应 report 字段；有 unreaped child 时阻止退出并可重试。

### A-G07-5 时间目标

- 可注入 fake clock 验证单 Session P50/P95 采样口径与 11.5s hard path；0/1/8 Session Runtime stop 按 5s/6s/7s P95 和 35s hard deadline 判定。

### A-G07-6 重入与所有权

- close/stop/shutdown 并发触发时，同一 Session 仅一个 Closing completion；Reserved/Running/Closing 都可被 shutdown 枚举，重复操作返回同一结果而非 SESSION_NOT_FOUND。

### A-G07-7 数据保留

- Workbench stop/quit 后 container/image/volume/registry metadata 按动作语义保留；仅 remove 显式删除。测试不声称强杀后的未刷盘进程状态零损失。

### A-G08-4 Tab 删除

- 运行中 tab 删除后不会被迟到 Exit 复活；active fallback 与空态正确；Runtime 保持 running。

### A-G08-5 Registry 回收

- 同一 pane 自然退出/reopen 100 次后，registry 不随次数无界增长，且无旧 child。

### A-G16-1 Tray

- `quit` 默认关闭；tray 模式 close 仅 hide、Session 连续运行；tray 退出复用 shutdown；tray 不可用时不产生无窗口后台进程。

### A-G16-2 隐藏/恢复

- 活动 Session 下连续 hide/show 20 次，`session_id`、PTY child、scrollback 和 provider polling 状态连续；show 后窗口 focus 和 active pane focus 恢复。

### A-G16-3 退出门禁

- tray Exit 与窗口 quit 使用同一确认和 `ShutdownReport`；取消确认保持隐藏/显示前状态；有 unreaped child 时不退出。

### A-G16-4 初始化与平台降级

- tray feature/menu 初始化成功时显示/退出可用；模拟初始化失败或不支持平台时 `close_behavior` 运行态回退 quit，最后窗口不会被隐藏。

### A-G16-5 设置持久化

- `quit/minimize-to-tray` 切换即时生效并重启保持；Reset 恢复 quit；无 tray 平台保存的 tray 值不导致下次无窗口启动。

### A-G17-1 分屏

- 单叶、水平/垂直嵌套、关闭压缩、拖拽 resize、tab+pane 混合和重启恢复均通过；第 9 个资源占用 Session 被拒绝并给出可理解提示。

### A-G17-2 PaneTree 事务

- 容量不足/尺寸不足时 tree 不变；Provider 未配置提交 guide 叶且无 session ID；open 失败保留 failed 叶；无半提交 Split 或泄漏 reservation。

### A-G17-3 Schema 与迁移

- v1→v2 锁内原子迁移保留 tab/order/active；v2 tagged union round-trip；损坏/过深/重复 ID tree 降级但原文件未确认前不覆盖；旧版本拒写 v2。

### A-G17-4 Resize 与可访问性

- divider 指针和键盘均工作；ratio clamp 0.10..0.90、步长 0.05；可见 pane 500ms 内收到最终 rows/cols，隐藏 pane 不发送零尺寸。

### A-G17-5 关闭与活动上下文

- 非最后 pane 关闭后压缩；最后 pane 变 dormant 且 tab 保留；Tab `×` 才删除；active tab/pane、sidebar、title、Provider query 和 terminal focus 同步。

### A-G17-6 资源上限与全路径

- 每 Runtime/单 Workbench 的 PaneTree 叶节点数≤8；opening/running/closing 资源计数≤8，closing 完成前不释放；Runtime stop、quit/tray exit 对嵌套 tree 全部 Session 无遗漏回收。
