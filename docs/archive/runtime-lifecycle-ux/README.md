# Runtime 生命周期与工作区启动体验

> 状态：Accepted planning / 待实施
> 规划日期：2026-08-25
> 适用范围：Workbench workspace picker、preflight、runtime start/stop/remove、workspace close、Workbench exit、history layout

## 1. 结论摘要

当前“工作区已有 Runtime”页把 Runtime 的内部资源管理决策暴露给了普通用户。对 Workbench 创建的 Runtime，用户通常没有“保留一个已停止容器”的明确需求；而当前 `stop` 又只停止容器、保留容器和 registry，导致下一次打开工作区时旧 Runtime 继续参与冲突判断。结果是：

```text
关闭工作区/退出 Workbench
  -> Session 被结束
  -> Runtime 只 stop，不 remove
  -> history 继续保存 runtime ref 和 layout
  -> 下一次打开同一 workspace
  -> preflight 发现旧 Runtime
  -> 用户被送入只能 stop/remove 的冲突页
```

本计划采用以下默认产品策略：

1. **Workbench Runtime 默认是“会话级临时资源”**：打开工作区时创建，关闭工作区或真正退出 Workbench 时结束 Session 并删除容器及 registry 记录。
2. **冲突不再是正常启动路径**：Workbench 自己创建、且确认已无其他活跃 Workbench lease 的旧 Runtime，由系统自动回收；用户不需要选择 stop/remove。
3. **只保留真正需要用户判断的阻断**：检测到另一个仍活跃的 Workbench 实例、未知 owner、损坏 registry 或无法确认资源归属时，才显示异常页；页面只提供最小恢复动作和诊断入口。
4. **保留工作区数据和历史布局，不保留 Runtime 容器**：容器删除不删除工作区文件，也不删除 data-root 下的 `.claude`、`.codex`、`.cc-switch`、runtime state 等持久数据。
5. **去掉“恢复布局”按钮造成的二选一**：历史布局继续保存，但恢复改为自动建立 dormant placeholder；只为当前激活的 Tab 创建新 Session，其他 Tab 在用户激活时懒启动。
6. **依赖和工具策略由启动模式派生**：`project` 自动使用持久化 toolchain，`temporary` 自动使用容器内临时 toolchain；workspace 文件修改在两种模式下都保留。Windows 上 project toolchain 的底层存储必须先经过 npm symlink/exec 性能 spike，在 NTFS bind mount 不可靠时使用 Docker named volume。完整容器层保留仍属于高级 `keep_stopped`。

“每次启动都是新的运行时”在本计划中的精确定义是：

- Workbench **新打开**一个 workspace 时，使用新的 `runtime_id` 和新的容器。
- 同一个 Workbench 进程内切换到已经打开的 workspace，不创建新 Runtime，因为它仍然拥有一个活跃的 workspace lease。
- 用户关闭 workspace 后再次打开，旧 Runtime 已被删除，因此会创建新的 Runtime。
- “新的 Runtime”不等于新的工作区数据；Agent 登录、Provider、cc-switch 配置和工作区文件继续持久化。

详细的产品行为、领域契约、实施顺序和验收场景分别见：

- [`01-product-behavior.md`](01-product-behavior.md)
- [`02-domain-contract.md`](02-domain-contract.md)
- [`03-implementation-plan.md`](03-implementation-plan.md)
- [`04-acceptance.md`](04-acceptance.md)
- [`decisions.md`](decisions.md)

## 2. 当前实现证据

以下现状是本计划的输入，不是目标行为：

- `ConflictManager.vue` 只展示 Workbench-owned Runtime，并把 stop/remove/retry 暴露给用户。
- `src/aisc/application/runtime.py` 的 `stop_runtime` 明确定义为“停止但保留 container + registry metadata”；`remove_runtime` 才删除容器并注销 registry。
- `workbench/src/stores/workspaces.ts` 关闭工作区时后台 stop Runtime，失败由下一次启动的 `runtime_conflict` gate 再暴露。
- `workbench/src-tauri/src/session.rs` 的 `shutdown_workbench` 当前只清理 Session，`stop_runtime` 参数尚未实际使用，退出后 Runtime 按设计继续运行。
- `workspaceRuntime.ts` 会持久化 `runtime` ref，并在匹配 Runtime 时生成 `restorableLayout`，由 `LaunchSummary.vue` 显示“恢复布局”。
- 容器的 Agent/Provider 状态通过 data-root bind mount 保存，删除容器本身不会删除这些宿主侧持久目录。

## 3. 非目标

- 不把 AISC CLI 的通用 Runtime 管理命令改成只能临时运行。CLI 仍需支持显式 stop、restart、remove，供诊断和高级用户使用。
- 不自动删除非 Workbench owner 的容器。
- 不自动删除 workspace 文件、`.claude`、`.codex`、`.cc-switch`、Provider 密钥或其他 data-root 持久状态。
- 不在本计划中实现跨机器、跨用户的 Runtime 共享或 PTY attach。
- 不为了简化页面而取消 crash recovery、registry 对账和可审计日志。

## 4. 实施门槛

实施必须同时更新：

- Workbench 前端状态机和页面；
- Tauri shutdown/close 协调器；
- AISC Runtime registry 元数据与 lease/reconcile 能力；
- history schema 的语义说明，必要时增加兼容字段；
- 自动化测试、真实 Docker 手测和回滚说明。

不能只删除 `ConflictManager.vue` 或把按钮改成“自动删除”，否则会在多窗口、崩溃恢复和未知容器场景下产生误删风险。

依赖持久化的具体边界见 [`01-product-behavior.md`](01-product-behavior.md) 第 6 节和 [`02-domain-contract.md`](02-domain-contract.md) 第 8 节。

## 5. Docker 资源阶段依赖

本计划的 reconcile、toolchain volume labels 和 image ID 冲突检测依赖
[`docker-resource-lifecycle` Stage A0](../docker-resource-lifecycle/03-implementation-plan.md)
提供的共享 ownership foundation。

两边必须共用：

- `io.aisc.*` label 常量；
- 结构化 image ID；
- Docker maintenance lock；
- 普通卸载保留 toolchain volume 的规则。

交汇点和实施顺序见
[`05-cross-plan-coordination.md`](../docker-resource-lifecycle/05-cross-plan-coordination.md)。
