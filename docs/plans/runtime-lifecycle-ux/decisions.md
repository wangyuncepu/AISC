# 决策记录

## D-RUNTIME-01：默认采用临时 Runtime

**决定**：Workbench-created project Runtime 默认 `remove_on_close`。

**原因**：当前 Workbench 主要把 Runtime 当作终端/Agent 的执行载体，而不是用户直接管理的 Docker 项目。保留 stopped container 和 registry 只增加冲突、残留和诊断成本；容器删除不会删除已挂载的 workspace/data-root 数据。

**不采用**：每次启动都复用旧 Runtime。复用会让镜像更新、旧配置、崩溃后残留和跨进程归属更难解释；也与用户希望“每次打开是新的运行时”不一致。

## D-RUNTIME-02：不删除 Workspace 数据

**决定**：Runtime cleanup 只删 container 和 registry entry；工作区文件、Agent/Provider 配置和 data-root 状态保留。

**原因**：Runtime 生命周期和用户项目数据是两个不同层级。必须避免用户将“关闭工作区”理解成“清空项目环境”。

## D-RUNTIME-03：冲突页只处理安全阻断

**决定**：普通用户不再在冲突页选择 stop/remove/force remove。只有 active other instance、unknown owner 或 Docker/registry 无法安全对账时阻断。

**原因**：stop/remove 是实现层动作，不是普通用户的工作目标。将所有旧 Runtime 都列出来会让用户在没有足够上下文的情况下做破坏性选择。

## D-RUNTIME-04：保留布局数据，移除布局选择题

**决定**：不删除 layout history；删除与 Start 并列的“恢复布局”主按钮，采用 lazy placeholder restore。

**原因**：Tab 顺序和分屏结构是用户工作习惯，值得保留；但一次性启动多个 Agent 会产生启动时间、额度和副作用。placeholder 可以同时保留结构和控制资源消耗。

## D-RUNTIME-05：同一进程内不重复创建 Runtime

**决定**：每个“新 materialized workspace”创建新 Runtime；同一 Workbench 进程内切换已打开 workspace 继续使用原 Runtime。

**原因**：现有产品支持最多多个并行 workspace。把切换误做成重启会破坏 Session 连续性，也会无意义地增加容器创建成本。

## D-RUNTIME-06：托盘隐藏不是退出

**决定**：minimize-to-tray 保持 Runtime 和 lease；显式退出才执行 Runtime cleanup。

**原因**：托盘模式的用户意图是暂时隐藏窗口，而不是结束工作。若隐藏即删除 Runtime，恢复托盘窗口会丢失会话。

## D-RUNTIME-07：未知归属必须保守处理

**决定**：owner 缺失、非 Workbench owner、lease 无法确认的 Runtime 不自动删除。

**原因**：自动化可以减少普通流程选项，但不能用“少一个按钮”换取误删外部容器的风险。此类情况进入诊断路径，并保留 CLI/高级入口。

## D-RUNTIME-08：过渡期兼容旧 Runtime

**决定**：旧 registry/history 可读；旧 Workbench Runtime 先经过 reconcile 分类，不能直接按新数据格式假设，也不能无条件复用。

**原因**：现有用户可能有 stopped Runtime、stale registry 或镜像更新后的旧 container。迁移必须可审计、可重试、可回滚。

## D-RUNTIME-09：依赖策略由 project/temporary 派生

**决定**：`scope=project` 自动使用 persistent toolchain，`scope=temporary` 自动使用 ephemeral toolchain。两种模式都保留 workspace 文件修改；不承诺自动保留任意系统级安装。需要精确保留整个容器环境时使用高级 `keep_stopped`。

**原因**：当前 Runtime 始终把 workspace 挂载到 `/root/app`，因此 workspace 内的 `node_modules`、`.venv` 等属于项目文件，不能在 temporary 模式退出时无差别删除。另一方面，`apt-get`、全局 npm、系统级 pip/cargo 等写入容器系统层，删除 container 后无法自然恢复。把整个 `/root` 或 `/usr/local` 挂载出去会覆盖镜像内置工具并增加升级/权限风险。

**产品含义**：普通用户不需要在启动时选择依赖策略；项目模式保留 project toolchain，临时模式不保留 Runtime-owned toolchain，但两者都保留 workspace 文件。系统级工具的保留属于高级开发环境能力。文案必须明确这条边界，不能笼统承诺“运行环境全部恢复”。

## D-RUNTIME-10：Windows project toolchain 先 spike，再决定 bind 或 volume

**决定**：Stage 3a 第一天先在真实 Windows + Docker Desktop 上比较 NTFS bind mount 与 Docker named volume。npm global 的 symlink、exec、跨 Runtime 复用或性能任一不达标，Windows project toolchain 默认使用 named volume。

**原因**：现有 data-root 挂载主要承载配置和数据库等纯数据，而 npm global toolchain 包含大量小文件、bin symlink 和可执行文件，风险模型不同。不能因为已有配置 bind mount 可用，就推断 toolchain bind mount 同样可靠。

**代价**：使用 named volume 时，toolchain 不直接位于 `%LOCALAPPDATA%\\AISC\\data`。产品承诺改为“项目 Toolchain 持久化”，v1 必须提供 inspect、export/import 和显式清理能力，不承诺宿主文件管理器直接可见。

## D-RUNTIME-11：v1 不实现工具 manifest 和强 ABI 门禁

**决定**：v1 砍掉安装 manifest、任意安装命令拦截和阻断式 ABI 检查。仅在 toolchain 初始化时写入轻量 `environment.json`，启动时比较 OS/arch/glibc/Node/Python/镜像 ID；不匹配时发出非阻断 `toolchain_incompatible` warning。

**原因**：系统无法完整拦截 Agent 发起的 npm/pip/cargo/apt 和任意脚本安装。不完整 manifest 会制造虚假的兼容性保证。轻量环境标记只能提示风险，不能证明所有工具可用。

**后续条件**：只有在引入受控 installer/wrapper、明确支持的包管理器集合和完整事件记录后，才重新评估工具 manifest 与精细兼容性检查。

## D-RUNTIME-12：Heartbeat 由 Tauri/Rust backend 负责

**决定**：lease heartbeat 由 Tauri/Rust backend 的 tokio interval 任务写入，前端 WebView 不承担保活职责。

**原因**：窗口隐藏、最小化到托盘和 WebView2 后台节流都可能暂停或延迟 JavaScript 定时器。将 heartbeat 放在 Rust 侧可以使 lease 生命周期绑定到实际 Workbench 进程和 workspace/runtime 实例。

**恢复规则**：系统睡眠/休眠或进程长时间暂停后，恢复时先执行立即 heartbeat 和 workspace/container 对账；不能仅凭过期时间戳删除疑似 stale Runtime。
