# 产品行为规范

## 1. 用户可见的主流程

### 1.1 首次打开 workspace

```text
选择 workspace
  -> 只读 preflight
  -> 自动处理可回收的旧 Workbench Runtime
  -> 创建新的 Runtime
  -> 创建一个当前 Tab 的新 Session
  -> 进入工作区
```

用户只需要处理 Docker、镜像、权限、网络等真正影响启动的错误。旧 Runtime 不再作为普通启动选项出现。

### 1.2 再次打开已经关闭过的 workspace

工作区文件和 Agent 配置仍在，因此用户可以继续工作；但 Runtime/container 是新的。系统不得显示：

- “工作区已有 Runtime”；
- “是否复用旧 Runtime”；
- “是否恢复旧终端内容”。

系统可以在状态抽屉或诊断日志中显示：`已清理上次未正常退出的运行环境`，但这不是阻断消息。

### 1.3 同一 Workbench 进程内切换 workspace

已打开的 workspace 仍保持自己的 Runtime 和 Session。切换 workspace：

- 不 stop；
- 不 remove；
- 不创建新 Runtime；
- 不修改另一个 workspace 的 layout；
- 后台 Runtime 继续由现有 polling 机制观察。

这条规则是“每次新打开创建新的 Runtime”和当前多工作区并存能力之间的边界。

## 2. Runtime 的默认生命周期

### 2.1 打开

- 为每个新 materialized workspace 生成新的 UUID v4 `runtime_id`。
- Runtime metadata 写入 `lifecycle=ephemeral`、`owner=workbench`、`retention=remove_on_close`。
- 创建成功后登记当前 Workbench `instance_id` 和 workspace lease。
- 只有 Runtime readiness 成功后，workspace 才 materialize 到 workspace bar。

### 2.2 关闭单个 workspace

用户点击 workspace chip 的关闭按钮或 Runtime sidebar 的关闭动作时：

1. 弹出一次确认；文案必须说明“将结束 N 个活动会话并删除此工作区的临时运行环境”。
2. 确认后立即从 UI 移除 workspace chip，保持现有的快速关闭体验。
3. 后台并发结束所有 Session，最多等待现有 session close budget。
4. 调用 `runtime stop`，随后 inspect；确认 stopped/not_found 后调用 `runtime remove`。
5. remove 必须注销 registry；即使 Docker 容器已经不存在，registry 清理也要幂等完成。
6. cleanup 成功后释放 lease、dispose workspace store。
7. history 保留 workspace 最近使用时间、Agent 偏好和 layout；`runtime` 字段改为 `null` 或标记为上一代兼容引用，不得再用于复用 Runtime。

关闭失败时：

- UI 不重新添加已关闭的 workspace chip；
- 记录结构化 cleanup error，包含 workspace hash、runtime id、阶段和 retryable；
- 下一次启动时由 stale-runtime reconcile 再尝试；
- 如果 lease 仍活跃，不允许后台 cleanup 误删另一个实例的资源。

### 2.3 真正退出 Workbench

“最小化到托盘”不是退出，Runtime 继续运行。只有以下情况算真正退出：

- 用户选择退出 Workbench；
- 托盘菜单选择退出；
- 主进程关闭流程进入 shutdown coordinator。

真正退出时：

1. 先拒绝新 Session；
2. 结束所有 workspace 的 Session；
3. 对所有当前 Workbench lease 调用 stop -> inspect -> remove；
4. flush history/settings；
5. 关闭进程。

如果用户没有活动 Session，可以不弹 Session 确认，但 cleanup 仍然必须执行。若 cleanup 超时，不能无限阻塞退出；应记录未回收 Runtime，并由下次启动 reconcile。

## 3. 冲突处理边界

正常启动不展示冲突页。preflight/reconcile 按以下顺序处理：

| 检测结果 | 系统行为 | 用户界面 |
|---|---|---|
| 同一 Workbench instance 已持有该 workspace lease | 复用当前前端 workspace 实例 | 不进入启动页；重复选择直接聚焦已有 workspace |
| Workbench-owned、`ephemeral`、lease 已过期 | stop/inspect/remove，随后创建新 Runtime | 不阻断；显示短暂进度或状态通知 |
| Workbench-owned、旧版本无 lease，但无其他活跃 lease 可证明 | 按兼容迁移策略视为 stale，回收后创建新 Runtime | 不阻断；可在诊断中查看回收记录 |
| Workbench-owned、lease 仍活跃且属于其他 Workbench instance | 不自动 stop/remove | 轻量阻断页：提示“此 workspace 正被另一个 Workbench 使用”，提供“重新检测”和“返回选择” |
| owner 缺失、owner 非 workbench、scope 不明 | 不自动删除 | 诊断页，不伪装成普通 Runtime 冲突；提供复制诊断信息和返回 |
| registry 有记录但 Docker container 不存在 | 清理 registry，随后创建新 Runtime | 不阻断，记录 stale registry cleanup |
| Docker 只发现带 AISC label 但无 registry 的 Workbench container | 只有在 lease 已确认过期时自动 stop/remove；否则阻断 | 显示“无法确认归属”，不提供一键强制删除 |
| Docker daemon 不可用 | 不判定 Runtime 不存在，不做删除 | 显示 Docker 错误和重试 |

### 3.1 冲突页的最小内容

保留页面只用于“另一个活跃实例/未知归属/无法安全回收”。页面只允许：

- `重新检测`；
- `返回工作区选择`；
- `打开诊断`。

不在普通冲突页显示 stop、remove、force remove 三组破坏性按钮。强制删除继续存在于 Runtime sidebar/Doctor 的高级诊断入口，并且必须显示 owner、lease、workspace、container 和影响范围。

## 4. 布局恢复策略

### 4.1 不删除 layout 数据

layout 是用户工作习惯数据，不是 Runtime 数据。关闭和退出时继续保存：

- Tab 顺序；
- active Tab；
- pane split tree；
- Agent 类型和标题。

保存内容不得包含可伪造为仍然运行的 Session ID。每次实际打开 Session 都生成新的 Session ID。

### 4.2 删除显式“恢复布局”按钮

当前 `Start` 与 `恢复布局` 让用户在“开一个新 Bash”与“重新启动多个 Agent”之间做选择，增加了启动认知负担。目标行为：

1. 打开 workspace 后读取 layout；
2. 创建 dormant placeholder tabs，不立即为所有 Tab 启动 Agent；
3. active Tab 进入可见的 starting/ready 状态并创建一个新 Session；
4. 非 active Tab 只有在用户切换到它时才创建新 Session；
5. 用户关闭 placeholder，只改 history，不发送 terminate；
6. 当前 workspace 没有历史 layout 时，创建默认 Bash Tab。

如果实现阶段暂时不能支持 placeholder，过渡版本可以保留一个次要的“打开上次标签”命令，但不得把它作为与 Start 并列的启动主按钮；最终目标仍是移除二选一。

### 4.3 不恢复终端内容

Runtime 是临时的，旧 PTY/终端滚动内容不恢复。UI 文案和技术契约必须明确：恢复的是 Tab 结构，不是 Agent 进程、PTY 或上下文。

## 5. 用户数据保留规则

默认清理 Runtime 时：

保留：

- workspace 文件和 Git 状态；
- `%LOCALAPPDATA%\\AISC\\data\\workspaces\\<hash>\\claude`；
- `codex`、`cc-switch`、`runtime` 等已有 data-root 挂载目录；
- Workbench history、settings、diagnostic logs。

删除：

- `aisc-wb-<runtime-prefix>` Docker container；
- 对应 registry entry；
- 仅存在于 container writable layer、且未挂载到宿主的临时文件。

任何会删除宿主持久目录的行为都不属于默认 Runtime cleanup，必须单独命名为“清除工作区运行数据”并二次确认。

## 6. 可观察性与文案

每次自动 cleanup 记录一条结构化事件：

```json
{
  "event": "runtime_reconcile",
  "workspace_hash": "…",
  "runtime_id": "…",
  "classification": "stale_ephemeral|stale_registry|active_other_instance|unknown_owner",
  "action": "remove|skip|block",
  "result": "ok|error|timeout",
  "observed_at": "…"
}
```

用户文案避免使用“垃圾 Runtime”“冲突 Runtime”作为默认称呼。优先使用结果导向的表达：

- `正在清理上次未正常关闭的运行环境…`
- `运行环境已回收，正在创建新的 Runtime…`
- `此工作区正在另一个 Workbench 实例中使用`
- `无法确认运行环境归属，已停止自动处理`

## 7. 依赖和工具的持久化

Runtime 删除只删除容器和 registry，不等于容器内所有安装都能跨 Runtime 保留。是否保留取决于文件实际写入的位置。

### 7.1 默认保留：workspace 和 data-root

以下内容默认保留：

| 安装/生成位置 | 示例 | 删除 Runtime 后 |
|---|---|---|
| `/root/app` workspace bind mount | `npm install` 生成的 `node_modules`、`.venv`、`vendor`、项目 `target` | 保留 |
| 项目清单和锁文件 | `package.json`、`package-lock.json`、`requirements.txt`、`uv.lock`、`Cargo.lock` | 保留 |
| data-root 的 Agent 配置 | Claude/Codex 配置、skills、plugins、sessions metadata | 保留 |
| data-root 的 Provider/cc-switch 状态 | Provider 配置、cc-switch DB、runtime state | 保留 |

前提是安装命令确实使用 workspace 或现有 data-root 挂载路径。项目依赖最好使用项目本地安装，而不是全局安装。

### 7.2 默认不保证：容器系统层

以下内容在 `remove_on_close` 下默认不保留：

| 安装方式 | 常见位置 | 原因 |
|---|---|---|
| `apt-get install` / `apk add` | `/usr/bin`、`/usr/lib`、`/etc` | 写入容器 writable layer 或系统目录 |
| `npm install -g` | `/usr/local/lib/node_modules`、全局 bin | 不在 workspace/data-root 挂载中 |
| 系统级 `pip install` | `/usr/local/lib/python*` | 不在持久挂载目录中 |
| `cargo install` 默认路径 | `/root/.cargo`、`/root/.rustup` 或 `/usr/local` | 当前没有完整 toolchain 挂载 |
| 手工下载到 `/opt`、`/usr/local/bin` | 系统级二进制 | 容器删除后随 writable layer 消失 |
| 启动中的 daemon、临时 socket、进程状态 | `/run`、`/tmp`、进程内存 | 本来就不属于持久数据 |

因此，用户看到“运行环境已回收”时，不能理解为“所有 Agent 安装过的软件都会自动恢复”。下一次 Runtime 会重新拥有镜像内置工具；额外的系统级工具需要重新安装，或者使用下面的持久化方案。

### 7.3 由启动模式派生的依赖策略

普通启动流程不提供单独的“依赖是否持久化”选项，避免用户同时理解 `scope`、Runtime retention 和 toolchain 三套设置。策略固定由启动模式派生：

| 启动模式 | 配置目录 | 用户级 toolchain | Runtime 删除后 |
|---|---|---|---|
| `project` | data-root 持久挂载 | persistent toolchain（host bind 或 Docker named volume） | toolchain 和配置保留 |
| `temporary` | `/tmp/aisc-home` 等容器临时目录 | `/tmp/aisc-toolchain` 等容器临时目录 | toolchain 和配置不保留 |

具体规则：

1. `project` 模式自动使用 `dependency_policy=persistent_toolchain`。
2. `temporary` 模式自动使用 `dependency_policy=ephemeral_toolchain`。
3. 两种模式都把 `/root/app` 作为用户 workspace 挂载，因此 workspace 内的文件修改、`node_modules`、`.venv`、`./bin` 等都保留。
4. `project` 模式只对专用 toolchain 中的用户级工具作持久化保证；`apt-get`、写入 `/usr`/`/etc`/`/usr/local` 的系统级修改仍属于 container-only。
5. 需要保留任意系统级修改时使用 `retention=keep_stopped`，而不是把整个系统目录挂载到宿主。
6. `temporary` 模式下用户级和系统级工具都只在当前 Runtime 存活；Runtime 删除后不恢复，但 workspace 中的文件变化仍然存在。

这意味着“临时模式不保留运行时产生的依赖”指的是 Runtime-owned toolchain/config，不包括用户 workspace 中已经写入的项目文件。Workbench 不得通过扫描或回滚 workspace 来实现临时模式清理。

### 7.4 Project toolchain 的存储后端

`project` 模式承诺“跨 Runtime 保留 toolchain”，不承诺该目录一定能在 Windows 文件管理器中直接看到。底层允许两种实现：

| 后端 | 存储位置 | 优点 | 风险/代价 |
|---|---|---|---|
| `host_bind` | data-root 的 workspace toolchain 目录 | 宿主可直接查看和备份 | Windows NTFS bind mount 上的 npm symlink、exec 和大量小文件性能可能不可靠 |
| `docker_volume` | Docker Desktop Linux VM 管理的 named volume | Linux 文件系统语义，适合 symlink、exec 和包管理器缓存 | 不直接出现在 data-root；备份、迁移和清理需通过 Docker/CLI |

Windows 实现必须先执行真实 npm spike，再选择默认后端。若 `host_bind` 在 symlink 创建、bin 执行、跨 Runtime 复用或性能任一项不达标，则 Windows project toolchain 使用 `docker_volume`。同一个 workspace 的 npm/pip/cargo toolchain 使用同一存储后端，不做按包管理器拆分。

使用 named volume 时：

- 删除 Runtime container 不删除 toolchain volume；
- 新 Runtime 通过 workspace key 找回并挂载同一 volume；
- volume 只在用户明确执行“清除工作区运行数据”、卸载清理或诊断修复时删除；
- Workbench 必须能展示 volume 名称、占用空间、最近使用时间和清理入口；
- 文案使用“项目 Toolchain 已持久化到 Docker 卷”，不得继续宣称它位于 data-root。

### 7.5 不建议的做法

- 不直接把整个 `/root` 或 `/usr/local` 作为宿主挂载点，避免覆盖镜像内置 CLI、权限和升级文件。
- 不通过猜测 shell history 来推断 Agent 安装了哪些依赖；命令可能由子进程、脚本或非交互 shell 执行，结果不可靠。
- 不把“自动重新执行所有安装命令”作为第一版承诺；安装命令可能有副作用、需要 secret、依赖网络或已不再可用。

## 8. 高级保留能力

本计划不把“保留 Runtime”放到普通启动流程。若后续确有需要，增加显式的高级策略：

- `remove_on_close`：默认，适合 Workbench；
- `keep_stopped`：高级诊断/开发模式，关闭时只 stop；
- `keep_running`：仅在托盘或服务开发场景启用。

策略必须存于 Runtime metadata，而不是只存于 UI 内存。普通用户看不到这些选项也不影响默认流程。
