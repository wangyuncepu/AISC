# 实施计划

## 0. 先冻结行为和兼容策略

目标：在改代码前明确旧 Runtime、旧 history、旧 Workbench 进程的处理方式。

任务：

1. 为 Runtime metadata 增加 lifecycle/retention/lease 字段，并保证旧 registry 可读。
2. 统一定义 lease TTL、heartbeat 周期、stop/remove timeout 和 cleanup retry 次数。
3. 确认 data-root 挂载目录不会被 `runtime remove` 删除，补充测试保护。
4. 生成旧数据分类矩阵：matching、stopped、stale registry、unknown owner、active other instance。
5. 冻结 `history.json` 兼容读取和新写入规则。
6. 冻结依赖持久化边界：workspace、project persistent toolchain、temporary ephemeral toolchain、container-only system changes 四类分别处理。
7. 先消费 `docker-resource-lifecycle` Stage A0 的共享 labels、结构化 image ID
   和 Docker maintenance lock；本计划不另建 ownership 常量。

交付：更新 [`02-domain-contract.md`](02-domain-contract.md) 中的字段、错误码和 timeout 数值。

## 1. AISC CLI / registry：实现 reconcile 和 lease

前置：

- [`docker-resource-lifecycle` Stage A0](../docker-resource-lifecycle/03-implementation-plan.md)
  已完成；
- 固定锁顺序为 Docker maintenance lock -> workspace lock -> registry transaction。

涉及模块：

- `src/aisc/application/runtime.py`
- `src/aisc/adapters/container_registry.py`
- `src/aisc/domain/models.py`
- `src/aisc/cli/commands/runtime.py`
- `src/aisc/cli/main.py`

任务：

1. 增加 Runtime lifecycle/dependency metadata 的序列化、读取和旧数据默认值。
2. 增加 workspace lease 的 claim/heartbeat/release/inspect。
3. **冻结 heartbeat 写入方**：由 Tauri/Rust backend 为每个活跃 workspace 启动一个 tokio interval 任务；任务不依赖前端页面可见性，不由 JS `setInterval` 实现。
4. heartbeat interval、lease TTL、宽限期和恢复后的立即 reconcile 必须使用 Rust 单调时钟/实际时间戳共同判断；系统睡眠恢复后不得直接依据旧 heartbeat 时间戳执行删除。
5. 实现 workspace lock 内的 reconcile：重新读取 registry、查询 Docker label、判断 lease、必要时 stop/inspect/remove。
6. 让 stale registry 清理幂等，不因 Docker container 已不存在而失败。
7. 新增稳定错误码：

   - `AISC_ERR_ACTIVE_WORKSPACE_LEASE`
   - `AISC_ERR_RUNTIME_OWNER_UNKNOWN`
   - `AISC_ERR_RUNTIME_RECONCILE_FAILED`
   - `AISC_ERR_RUNTIME_LEASE_CONFLICT`

8. 保留现有 stop/remove CLI 语义，新增 reconcile 不改变 CLI 高级命令的破坏性确认策略。
9. 增加单元测试覆盖并发 claim、过期 lease、Docker unavailable、unknown owner、stale registry、remove 幂等、睡眠恢复和 heartbeat writer 的单实例约束。
10. 增加依赖分类测试，确认 workspace 两种模式都保留，project toolchain 保留，temporary toolchain 不保留，container-only 路径不被错误标记为持久化。

门禁：现有 `tests/test_runtime_lifecycle.py`、registry 测试和 CLI contract 测试全部通过；旧 registry fixture 可以读写而不丢字段。

## 2. Tauri backend：接入结构化 shutdown 和 reconcile

涉及模块：

- `workbench/src-tauri/src/session.rs`
- `workbench/src-tauri/src/runtime.rs`
- `workbench/src-tauri/src/lib.rs`
- `workbench/src/lib/ipc.ts`
- `workbench/src/types/index.ts`

任务：

1. 把 `shutdown_workbench(stop_runtime: bool)` 改成结构化 request；保留兼容 wrapper 直到前端迁移完成。
2. 在 shutdown coordinator 中执行 Session cleanup 后的 Runtime cleanup。
3. 为 `runtime_reconcile` 暴露 typed IPC。
4. 同一 runtime ID 的 stop/remove/reconcile 使用现有 operation mutex；workspace claim/reconcile 仍由 CLI 跨进程 lock 保证。
5. cleanup 结果必须可区分 `removed`、`not_found`、`skipped`、`failed`。
6. 保持 tray minimize 语义：隐藏不是退出，不释放 lease，不删除 Runtime。
7. 对 Tauri backend 增加操作顺序和超时测试。

门禁：窗口退出、托盘退出、Docker 不可用、单个 Runtime cleanup 超时都不能导致 Session registry 或其他 workspace 被误清理。

## 3. Workbench store：正常路径自动回收，去掉旧 ref 复用

涉及模块：

- `workbench/src/stores/workspaceRuntime.ts`
- `workbench/src/stores/workspaces.ts`
- `workbench/src/stores/runtime.ts`
- `workbench/src/composables/useRuntimePolling.ts`

任务：

1. materialize 新 workspace 时 claim lease 并生成新 runtime ID。
2. `runPreflight` 改为调用 reconcile，而不是先 list 再决定是否进入冲突页。
3. 同一进程中重复选择相同路径直接激活已有 workspace。
4. close workspace 改为 stop -> inspect -> remove，后台失败写入 cleanup error，不回退成用户必须处理的普通冲突。
5. `confirmExit` 汇总所有 workspace；退出 IPC 携带所有 runtime targets。
6. history 中的 `runtime` 不再驱动下一次复用；保留 `last_runtime` 只用于诊断/日志。
7. 旧 `keepCancelledRuntime` 只保留给启动取消后的恢复场景，不作为常规启动策略。
8. 在 runtime facade 中暴露 dependency policy 和 toolchain health，但不把它们加入普通启动选项。

门禁：现有多 workspace 行为不变；关闭 A 不影响 B；启动取消、关闭失败、外部 Docker remove 都能进入明确状态。

## 3a. Toolchain 持久化

涉及模块：

- `src/aisc/domain/models.py`
- `src/aisc/application/runtime.py`
- `container/Dockerfile`
- `container/entrypoint.sh`
- `workbench/src/types/index.ts`
- `workbench/src/features/workspace/RuntimeSidebar.vue`

任务：

1. **第一天先做 Windows 实机 spike，不开始正式挂载实现**：
   - 分别以 `%LOCALAPPDATA%\\AISC\\data` NTFS bind mount 和 Docker named volume 挂载 `/opt/aisc/toolchain`；
   - 使用固定的本地 npm package tarball（必须含 bin entry，例如冻结版本的 TypeScript 包），避免网络波动污染文件系统性能对比；
   - 设置 npm global prefix/cache 后执行 `npm install -g <local-package.tgz>`；
   - 验证 symlink 创建、`which`/直接执行、容器删除后新 Runtime 复用、冷/热安装耗时和大量小文件操作；
   - 记录 Docker Desktop 版本、文件共享后端、Windows 版本、命令、耗时和失败证据。
2. 决策门：以下任一成立即选 `docker_volume` 作为 Windows project toolchain 默认后端：
   - npm bin symlink 创建或解析失败；
   - 挂载目录中的二进制不能执行；
   - 删除旧 Runtime 后新 Runtime 不能完整复用；
   - 每个后端至少执行 3 次冷安装和 5 次热安装；排除首次镜像启动后，bind mount 中位数超过 named volume 2 倍，或绝对额外耗时超过 30 秒；
   - 行为依赖管理员权限、Developer Mode 或用户机器上的非默认设置。
3. 为 Runtime metadata 增加 `toolchain_storage=host_bind|docker_volume`；该字段由平台能力和 spike 结论决定，不进入普通启动选项。
4. 为 `scope=project` Runtime 增加 `dependency_policy=persistent_toolchain`：
   - `host_bind` 使用 data-root toolchain 目录；
   - `docker_volume` 使用带 AISC labels 的 workspace-keyed named volume。
5. 为 `scope=temporary` Runtime 创建容器内 `/tmp/aisc-toolchain`，设置 `dependency_policy=ephemeral_toolchain`，不挂载宿主 toolchain 或 named volume。
6. 两种模式都只挂载 `/root/app` workspace；不通过删除或回滚 workspace 文件实现临时清理。
7. 两种 project 后端都挂载到容器内 `/opt/aisc/toolchain`，不覆盖 `/root`、`/usr/local` 或镜像内置 CLI 路径。
8. 为两种模式定义一致的用户级 npm/pip/cargo 工具安装路径和 PATH 注入规则，路径根由 scope 决定；root 容器中显式设置 `PIP_USER=1`、`PYTHONUSERBASE=<toolchain>/python`、`NPM_CONFIG_PREFIX=<toolchain>/npm-global`，并将对应 bin 目录加入 PATH。
9. v1 只写入 `environment.json` 轻量环境标记，不实现安装 manifest、不拦截包管理器命令。
10. 启动时比较 OS/arch/glibc/Node/Python/镜像 ID；不匹配只产生 `toolchain_incompatible` warning，不阻断、不自动删除。
11. 在 Runtime sidebar/diagnostics 展示当前 scope、dependency policy、storage backend、volume/path 和 compatibility warning。
12. 实现 named volume 的 inspect/export/import/remove CLI；remove 必须验证 labels、workspace lock 和活跃 lease。
13. 与 `docker-resource-lifecycle` 的安装器接入共同更新卸载流程：普通
    container/image cleanup 默认保留 project toolchain volume；NSIS/Inno/PKG
    只有在独立、明确的 toolchain volume 选项被选择时才调用工作区运行数据清理。
14. 对 `apt-get`、系统级 pip/npm/cargo 和任意 `/usr/local` 手工修改明确标记为 container-only；不假装可以自动恢复。
15. 为需要完整容器层的用户保留高级 `keep_stopped` 策略，但不让它进入普通启动页。

门禁：Windows spike 和存储后端决策已留证；删除 project Runtime 后 workspace 依赖和 project toolchain 仍在；删除 temporary Runtime 后 temporary toolchain 不可见；两种模式都能重新注入正确 PATH；environment marker 不匹配只警告；named volume 可 inspect/export/import/显式 remove；系统级安装的丢失边界在 UI/文档中可见。

## 4. Startup UI：从冲突管理页改为异常阻断页

涉及模块：

- `workbench/src/features/startup/ConflictManager.vue`
- `workbench/src/features/startup/LaunchSummary.vue`
- `workbench/src/features/startup/PreflightGate.vue`
- `workbench/src/features/startup/StartProgress.vue`
- `workbench/src/i18n/zh-CN.ts`
- `workbench/src/i18n/en-US.ts`

任务：

1. 删除普通冲突页中的 stop/remove/force remove 列表操作。
2. `stale_ephemeral` 和 `stale_registry` 显示自动处理进度，不改变页面为 conflict。
3. `active_other_instance` 显示“另一个 Workbench 正在使用”并提供重新检测/返回/诊断。
4. `unknown_owner` 显示保守阻断和诊断，不提供一键删除。
5. 删除 LaunchSummary 的并列“Start/恢复布局”主按钮。
6. 增加 dormant placeholder 视觉状态；placeholder 关闭只改 history。
7. 所有 destructive action 统一移动到 Runtime sidebar/Doctor 高级入口。

门禁：中文/英文、Compact/Standard/Wide、键盘 focus、Escape、错误重试和无 Docker 场景通过。

## 5. Layout lazy restore

涉及模块：

- `workbench/src/stores/workspaceRuntime.ts`
- `workbench/src/types/index.ts`
- `workbench/src/features/workspace/TabBar.vue`
- `workbench/src/features/terminal/GuidePane.vue`
- 相关 store/component tests

任务：

1. 保存 layout 结构，但不保存可复用 Session ID。
2. 加载 layout 时先创建 placeholder tab records。
3. active tab 创建一个新 Session；其余 tab 在 activation 时创建新 Session。
4. placeholder 与 exited tab 的 UI 要区分，不能伪装为 running。
5. 删除 `restorableLayout` 作为 Start 分支的 gate；保留必要的 history migration。
6. 为“无 layout、空 layout、旧 layout、split layout、多个 Agent”补充测试。

门禁：启动后不恢复旧 PTY；重复点击 tab 不创建两个 Session；关闭 placeholder 不调用 terminate。

## 6. 手测、发布和迁移

1. 在真实 Docker 上建立：正常退出、崩溃后重启、Docker 被外部删除、registry 被删除、两个 Workbench 进程、旧版本 registry、镜像更新等场景。
2. 记录每个场景的 runtime/container/registry/lease/history 前后快照。
3. 对旧 Runtime 提供一次性诊断：自动回收前显示分类和预计影响，但默认流程不要求用户操作。
4. 若迁移失败，保留旧 registry 文件并进入诊断，不执行广泛删除。
5. 发布说明明确：Runtime container 是临时资源；Agent/Provider 配置和 workspace 数据继续保留。

## 7. 回滚策略

- CLI/registry、Tauri、Workbench store、UI 分阶段提交，每阶段可独立回滚。
- 若 lease/reconcile 发现误判风险，先回滚“自动删除”开关为“自动 stop + 阻断”，不回滚数据格式读取能力。
- 若 lazy restore 不稳定，可以暂时恢复单个显式“打开上次标签”命令，但不能恢复 stop/remove 冲突页作为普通入口。
- 任何涉及 workspace/data-root 删除的回归都必须立即停止发布并回滚对应 Runtime cleanup 提交。
