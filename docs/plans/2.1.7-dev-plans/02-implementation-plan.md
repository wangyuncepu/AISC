# 02 · 实现计划（S1-S7）

> 每阶段独立分支 `s<N>-<short>`，小步提交，本地门禁全绿 + 手测 PASS + 用户确认后 `--no-ff` 合 develop 并删分支（本地+远程）。验收 ID 见 [03-acceptance.md](03-acceptance.md)。

## S1 快修批（对应 ⑤ + #29 + 版本日志）

**范围**：三处小修，热身批。

1. **黑框闪现**（#29）：
   - `workbench/src-tauri/src/workspace.rs` `open_path`：`cmd /C start` spawn 前补 `CREATE_NO_WINDOW`（`std::os::windows::process::CommandExt`，仓库已有同款先例 cli.rs:628 / env.rs:189）。
   - `workbench/src-tauri/src/runtime.rs` `winget_available`：`where winget` 同样补 flag。
2. **app_start 版本日志**：定位 Rust 侧 `app_start` 事件写点，`app_version` 字段从 Tauri `AppHandle::package_info().version` 取真实值，替换硬编码 "0.1.0"。
3. **Provider 表头**（⑤）：Provider 管理页列表增加表头行（列：名称/端点类型/模型映射状态/使用中等，以实际列为准），i18n 双语。

**测试**：Rust 单测（版本来源）；vitest 若 Provider 列表结构有既有断言需同步；静态无新增契约。

## S2 工作区历史 UX（⑦⑧）

**范围**：首页/历史存储与交互。

1. **历史数据结构**：确认现有 history 存储位置（settings/workspaces 合并历史）；新增"彻底忘记"所需的删除路径：首页记录条目 + data 根 `workspaces/<hash>/` 整目录（含 claude/codex/cc-switch/runtime/toolchain 状态）。
2. **右键删除（彻底忘记）**：
   - 右键菜单 → 确认弹窗（**逐项列明将删除内容**：首页记录、该工作区的 AISC 侧状态目录；明示"不会触碰你磁盘上的原始工作区文件"）。
   - 前置校验：该工作区当前未在打开状态（活跃 workspace 拒删并提示先关闭）；lease 活跃同样拒删。
   - 实现：Rust IPC 命令 `workspace_forget(path)`（存在性/活跃校验 → 删 data 根目录 → 摘历史记录 → 原子回报），删除动作进 UI 打点日志。
3. **上限 8 + 内联展开**：首页历史默认渲染前 8 条；第 9 条起折叠，显示"查看全部 N 个"按钮，点击**同页内联展开**（无弹窗）；再点收起。
4. **路径失效校验**（⑧）：点击历史条目先 `exists()`；不存在 → 弹窗"该工作区已移动或删除"，两个动作：「清除记录」（仅摘历史条目，不动任何数据）与「浏览定位新路径」（可选做，若成本高则本期只做前者）。

**测试**：vitest（列表裁剪/展开/右键菜单/确认流）；Rust（forget 命令的校验分支与目录删除）；手测重点 = 确认弹窗文案与"不动用户文件"红线。

## S3 引导重定位（⑥）

**范围**：启动路由与向导入口。

1. **启动直入 picker**：移除首跑自动进向导的路由条件；picker 成为所有启动的默认页。
2. **向导入口保留**：设置页保留"重新运行设置向导"入口（现已有此能力则复用）；向导代码全部保留，仅去掉自动触发。
3. **环境检测后移**：用户在 picker 选定工作区后，进入该工作区的启动流程；环境检测（CLI/Docker/WebView2）嵌入启动卡片：全绿则无感直进；有失败项则卡片内呈现失败详情与修复动作（一键装 Docker / 重检），不弹整页向导。
4. **FirstRun 标记**：NSIS 写入的 `FirstRun` 注册表标记不再驱动自动向导；保留字段供诊断。
5. **手测轮顺带**：睡眠/恢复行（挂账）——开工作区 → 系统睡眠 30s → 唤醒 → 验证容器仍活、lease 恢复心跳、无冲突页。

**测试**：vitest 路由（首次启动到 picker）；Rust 环境检测嵌入逻辑若为 IPC 编排则补契约测试。

## S4 构建进度条 + Docker 安装心跳（① + #27）

**范围**：构建事件流 → 进度 UI；安装等待心跳。

1. **进度语义（真实优先）**：
   - 构建步数：Dockerfile 指令总数为分母（构建前解析 bundle Dockerfile 得 total），构建事件流按步序号推进 → 真实百分比。
   - 拉取层：以字节为单位（docker build 事件含 layer 进度时聚合为"下载基础层 xx%"阶段条）。
   - 降级：无步数信息时显示阶段文案（解析依赖 → 拉取基础层 → 执行指令 → 导出镜像）+ 不确定动画进度条，不伪造百分比。
2. **UI（设计感重点）**：进度视图替换构建期终端刷屏——大号百分比 + 阶段说明 + 已耗时 + 当前步骤摘要行；下方可折叠"详细日志"抽屉（保留完整原始输出，等宽字体滚动区，默认收起）。视觉沿用设计 token，动效遵守 reduced-motion。
3. **Docker 安装心跳（#27）**：`install_docker_desktop_*` 等待期间每 5s emit `docker-install-heartbeat` 事件（已耗时 + 阶段预期文案）；前端按钮区显示已计时；超时（10min）判定前 30s 给出"即将超时"预告。（不解析 winget 输出，D8。）
4. **事件契约**：新增/扩展 build 进度事件走既有 `buildEvents` 能力通道版本化（`aisc.build-events/v1` → 若字段新增则升 v2 并双端同步 fixture）。

**测试**：Rust（步数解析/事件发射/心跳）；Python（若 CLI 侧事件源改造）；vitest（进度视图状态机、降级路径、抽屉开合）。

## S5 产物转圈调查 + 渲染性能（② + #28）

**范围**：调查先行，修复凭证据。

1. **调查（先出报告再动刀）**：
   - 复现：构造 200+/1000+ 产物目录打开工作区，记录时间线（watcher 事件洪峰 → artifact 归因调用 → store 写入 → 渲染）。
   - 假设清单：H1 watcher 批量事件未聚合，逐事件触发全量 artifact 列表 IPC；H2 归因逐文件起 CLI 进程（spawn 风暴）；H3 列表全量赋值触发整树重渲（与 #28 同根）；H4 转圈=加载态被高频事件反复置位。
   - 产出：`spike-artifact-flood.md`（数据+根因+修复方案），经用户过目后实施。
2. **#28 轮询闪烁**：runtime snapshot 写入改为 diff 后按需 patch（仅变化字段触发订阅）；评估轮询退避（窗口隐藏/失焦时降频）。
3. **性能回归锚点**：为产物面板建立可重复的计时用例（vitest bench 或手动基准脚本），修复前后留档。

## S6 终端教学（③）

**范围**：内容 + 交互 + 视觉。

1. **bash 首屏速查卡**（替换"AISC已启动"类横幅）：≤12 行中文，覆盖——三个入口关系一句话、claude/codex 最常用 5-6 条命令、Workbench 三个关键 UI 元素、`help` 提示。视觉做成低饱和卡片（非终端喷刷文本，见"实现取舍"）。
2. **`help` 分页教学**：bash 内输入 `help` 输出分页教学（实现取舍：经 shell profile 注入的轻量函数/PROMPT_COMMAND，或 PTY 首屏注入后由真实 shell 响应——以 spike 结论定，约束：不改变 shell 行为、退出容器不留宿主副作用）：
   - 第 1 页 claude CLI 核心（会话/续聊/权限/模型切换/常用斜杠命令）
   - 第 2 页 codex CLI 核心
   - 第 3 页 Workbench 入门（每个按钮/面板一句话）
   - 末尾互动小练习：引导跑一条真实命令（如 `claude -p "..."` 单次问答），完成后提示已具备核心用法。
3. **claude/codex tab 头速查卡**：新建对应工具 tab 时头部显示该工具 6-8 行快速上手卡 + 底部"输入 help 查看完整教学"提示；卡片可关闭，同会话不再重复出现。
4. **内容 SSOT**：教学文案集中一处常量文件（i18n zh-CN 为主，en-US 简版），便于后续迭代。

**测试**：内容快照测试（防漂移）；交互注入的集成手测为主。

## S7 文件标注语义（④）

**范围**：Explorer/产物面板的变更徽章体系。

1. **语义分类重设计**：现状"修改/重命名"等词感知弱。方案（待审阅定稿）：
   - 维度拆分：**变更类型**（新增/修改/删除/重命名→移动）× **来源**（Agent 产物 / 未归因）。
   - 视觉：类型用图标+色相（绿+ / 蓝· / 红− / 紫⇄），来源用第二级角标（🤖 agent 归因 / ⋯ 未归因）；悬停 tooltip 一句话说明。
   - 文案：动词改为结果语义（"内容已变"→`已修改`；重命名/移动合并为 `已移动(原名)`）。
2. **一致性**：Explorer 与产物面板共用同一徽章组件；图例（legend）入口常驻可折叠。
3. **测试**：vitest 组件快照 + 分类映射单测。

## 审阅补充：跨阶段契约与实施修订

> 以下条款覆盖前文同主题的粗略描述。

### A. S2“彻底忘记”安全契约

1. IPC 不采用只返回 `Ok(())` 的 `workspace_forget(path)`，而返回结构化结果：workspace key、history removal、host data removal、toolchain action、warnings、error code；重复调用必须幂等。
2. 前端不得拼接或展示后再回传可删除绝对路径；Rust/Python 通过统一 data-root resolver 计算目标，并验证目标是 `<data-root>/workspaces/<workspace-key>/` 的直接受控子树。
3. 校验顺序：历史记录/identity → 当前进程打开状态 → 跨进程 lease/reconcile → 路径 containment/reparse 检查 → 删除预览 → 用户确认 → 后端执行。
4. 删除执行必须定义半失败语义。建议同卷原子 rename 到 data-root 内 quarantine/tombstone，成功摘除 history 后再清理 tombstone；任一步失败都返回可重试事实，绝不把部分成功写成全部成功。
5. 不把 secret 内容写入预览或日志，只显示类别和受控路径：历史记录、Claude/Codex/cc-switch 配置状态、runtime/lease/log、host-bind toolchain。Docker named volume 若存在，必须单独列项；没有 ownership 证明或 lease 活跃时保留并告警。
6. “打开中”包括本窗口已 materialize workspace、后台 launcher 正在启动、当前/其他实例 lease 活跃。未知 lease/损坏 metadata 一律拒删并给诊断入口。
7. 右键菜单之外增加键盘可达的 `…` 菜单；确认弹窗默认焦点在取消，Escape 取消，破坏性按钮使用明确文案“彻底忘记此工作区”。
8. 路径失效的“清除记录”是独立轻操作，只改 history，不删 data-root；本期删除“浏览定位新路径（可选做）”的摇摆表述，若未排期则明确非目标。

### B. S3 环境检测后移的精确边界

1. 保留应用启动级检查：Tauri/WebView2 能否运行是 UI 存在的前提；CLI discovery/capability negotiate 仍在主界面可用前完成或以全局 blocked gate 呈现。
2. 后移到选定 workspace 后的只有 workspace launch checks：workspace 可访问、Docker CLI/engine、image、network、runtime reconcile/lease。
3. “启动一律直入 picker”定义为：完成最小应用 boot/negotiate 后的第一个业务页面是 picker；不是绕过 CLI blocked gate。
4. 内嵌启动卡片复用 `PreflightGate`/`LaunchSummary`/environment store，状态至少包含 checking、action_required、repairing、retrying、ready、blocked；提供返回 picker、重新检测、诊断。不得检测失败即自动安装 Docker，安装必须由用户动作触发。
5. Docker 缺失、Docker 已装但 engine 未就绪、CLI 不可用、workspace 无权限必须使用不同文案和动作；WebView2 不作为卡片项目。

### C. S4 诚实进度与事件契约

1. Python CLI 是 build progress 的事实源。前端不得解析 `build.output.chunk`；Rust 只校验 schema/seq 并转发。
2. 新事件建议升为 `aisc.build-events/v2`，至少包含：`phase`、`step_current`、`step_total`、`percent: number|null`、`progress_kind=determinate|indeterminate`、`summary`；原始输出继续走 `build.output`。
3. Dockerfile 解析得到的指令总数只是一项 metadata。只有机器可读构建事件能稳定映射“已完成指令/总指令”时才显示百分比；不能映射时显示 `步骤 X/Y` 或不确定进度。缓存步骤可瞬时完成，但百分比必须单调，且 `build.complete` 前不得显示 100%。
4. 拉取层字节进度是独立的阶段内进度，不能与 Dockerfile 步数拼成一个伪整体百分比；无总字节时同样降级为不确定状态。
5. 结构化能力不可得、事件版本未知、事件乱序/缺失时，保留原始日志并降级，不得因进度 UI 令构建失败。
6. “完整详细日志”不可继续无界追加到一个 Vue string。后端/CLI 将原始输出写入有界 operation log 文件；UI 使用虚拟化/尾部窗口显示，并提供打开完整日志。取消、失败、成功都保留可诊断尾部和日志位置。
7. Docker 安装进度单独定义 `docker-install-progress/v1`（或等价 Tauri Channel），字段包括 `operation_id`、`backend=winget|bundled`、`state`、`elapsed_ms`、`deadline_ms`、`remaining_ms`、`terminal`。阶段文案只陈述已知事实，不把心跳伪装成下载百分比。
8. winget 与 bundled installer 都必须单飞；超时/取消时 kill 并 wait/reap 子进程。安装完成后进入独立的 engine-start poll，不能把 10 分钟安装 deadline 与 2 分钟 engine deadline 混成一个状态。

### D. S5 调查与性能证据

1. 复现基准固定 fixture 生成器、机器/VM 配置、冷/热启动条件，至少记录 200/500/1000 项的 p50/p95/max，而不是只写“CPU 无尖峰”。
2. 记录 watcher 收件数、artifact IPC 次数、CLI spawn 次数、store commit 次数、Vue render 次数和 loading 状态切换次数，先证明瓶颈层。
3. 修复方案必须有有界队列/批处理、取消与 generation guard，旧一代扫描结果不得覆盖新 workspace。
4. A-21752 的 `≤2s` 仅在注明的基准机与 fixture 上成立；其他环境用“相对基线不回退 + 无无限 loading”验收。

### E. S6 help spike 决策门

1. PTY 首屏注入只可生成速查卡，不能实现后续命令响应；不得通过 Workbench 拦截普通终端输入伪装成 shell 命令。
2. spike 候选应为：受控 Bash 启动文件注入，或镜像内独立 `aisc-help` 命令；`PROMPT_COMMAND` 不作为首选，因为它会污染每次 prompt 生命周期。
3. 若产品坚持裸 `help`：只在 AISC 管理的 Bash session 中对“无参数 help”展示教程；带参数调用必须委托 `builtin help "$@"`。不得修改用户 workspace、宿主 profile 或持久化的 Claude/Codex 配置目录。
4. Claude/Codex tab 运行的是各自 TUI，不能承诺输入裸 `help` 会进入 Bash 教程；速查卡应提供 UI“打开教程”入口或明确使用可执行的专用命令/退出到 Bash 后命令。
5. spike 验证 bash interactive/non-interactive、临时/项目 scope、容器重建、多个 tab、退出码、Ctrl+C/Ctrl+D、prompt 延迟和清理副作用；结论写入 `decisions.md` 后才进入实现。
6. 互动练习不得默认发起计费/联网真实请求；应先提供 dry/local 练习，用户主动确认后才运行 `claude -p` 等真实命令。

### F. S7 数据源门

1. 先建立分类映射表：每个新增/修改/删除/移动和 Agent/未归因状态分别由 artifact manifest、watcher、history 或其他哪一权威源提供。
2. Explorer 当前只渲染现存节点；删除、重命名前项若无可持久事件模型，不能仅靠颜色补出来。证据不足时 S7 先交付“现有状态视觉统一 + legend”，把缺失语义另立协议任务。
3. 颜色不是唯一信号；图标、文本、ARIA label/tooltip 必须同时表达，覆盖高对比度与色觉差异。

### G. 阶段/提交门修订

- S2 在 S3 前完成不是技术硬依赖，但二者都会修改 picker/history/store，禁止并行改同文件。
- S4 与 S5 不建议并行修改 `workspaceRuntime.ts`/事件 reducer；先冻结 S4 event reducer，再做 S5 渲染优化。
- 每阶段必须写回 acceptance evidence：commit、OS/arch、版本、fixture、步骤、期望、结果、耗时/截图/日志。
- 回滚：S2 可关闭 destructive action 并保留只清 history；S3 可恢复向导 gate；S4 可回退到原始日志视图；S6 可撤掉 profile hook 保留静态卡。
