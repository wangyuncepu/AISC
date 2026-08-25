# 领域与 IPC 契约

## 1. Runtime metadata

在不破坏旧 registry 读取的前提下，为 Workbench-managed Runtime 增加以下字段：

```json
{
  "runtime_id": "UUID v4",
  "owner": "workbench",
  "scope": "project",
  "workspace": "canonical path",
  "workspace_key": "sha256",
  "lifecycle": "ephemeral",
  "retention": "remove_on_close",
  "dependency_policy": "persistent_toolchain",
  "toolchain_storage": "host_bind|docker_volume",
  "workbench_instance_id": "UUID v4",
  "lease_id": "UUID v4",
  "lease_last_seen_at": "RFC3339 timestamp",
  "created_at": "RFC3339 timestamp",
  "last_state_change_at": "RFC3339 timestamp"
}
```

兼容规则：

- 缺少 `lifecycle` 的旧 Workbench record 不得直接当作可复用 Runtime。
- 缺少 lease 时先进行一次 owner/容器/registry 对账；只有确认没有活跃 owner 后才可按 stale 处理。
- owner 不是 `workbench` 或字段无法确认时，默认 fail-closed，不自动删除。
- `retention` 只控制 Workbench 的编排行为，不改变 `scope=project|temporary` 的挂载语义。

## 2. Lease

### 2.1 目的

仅凭 Docker `running/stopped` 无法区分“用户仍在使用”与“上次崩溃遗留”。因此需要一个跨进程、可过期的 workspace lease。Lease 是防误删机制，不是 Session attach 机制。

### 2.2 最小契约

- Workbench 启动或 materialize workspace 时 claim lease。
- 活跃 workspace 每 10-15 秒 heartbeat 一次；允许 2-3 个 heartbeat 周期的宽限时间。
- heartbeat 必须由 Tauri/Rust backend 的 tokio interval 任务写入；前端 JavaScript 不负责 lease heartbeat。
- heartbeat 任务的生命周期绑定到 Tauri workspace/runtime 实例，而不是 WebView 可见性；窗口隐藏、最小化到托盘、WebView2 后台节流都不得暂停 heartbeat。
- heartbeat 任务必须在 workspace close、显式退出和 runtime cleanup 完成后停止；重复启动同一 workspace 不得产生多个 heartbeat writer。
- 正常 close/exit 先释放 lease，再 remove Runtime；remove 失败时保留一个可识别的 stale cleanup record。
- 另一进程 claim 同一 canonical workspace 时，如果 lease 未过期，返回 `ACTIVE_WORKSPACE_LEASE`。
- lease 过期后必须再次 inspect/container label 对账，不能只凭时间戳删除。
- 系统睡眠/休眠或 Tauri 进程长时间暂停后，恢复时必须先执行一次立即 heartbeat + workspace/container 对账，再决定 lease 是否仍有效；任何实例不得仅凭过期时间戳删除 Runtime。

### 2.3 Lease 文件/存储

优先复用现有 data-root workspace state dir 和锁机制，不新增一个全局数据库。建议：

```text
data/workspaces/<hash>/runtime-lease.json
data/workspaces/<hash>/locks/<workspace-key>.lock
```

写入采用临时文件 + atomic replace；claim、heartbeat、release 使用现有跨进程 lock。Lease 文件不包含 secret。

## 3. Reconcile API

新增一个面向 Workbench 的编排 API，避免前端自己组合多次 list/inspect/remove：

```text
runtime reconcile
  --workspace <path>
  --workspace-key <hash>
  --instance-id <uuid>
  --desired-lifecycle ephemeral
  --format json
```

返回：

```json
{
  "workspace_key": "…",
  "classification": "clean|active_same_instance|stale_ephemeral|active_other_instance|unknown_owner|stale_registry|docker_unavailable",
  "runtime_id": "…",
  "can_proceed": true,
  "cleanup": {
    "attempted": true,
    "stopped": true,
    "removed": true,
    "registry_pruned": true
  },
  "observed_at": "…",
  "error_code": null,
  "technical_detail": null
}
```

语义：

- `clean`：没有需要处理的旧 Runtime，可以 start。
- `active_same_instance`：当前进程已有实例，前端聚焦已有 workspace，不再创建第二个。
- `stale_ephemeral`：系统已完成 stop/remove 或确认幂等 not_found，可以 start。
- `active_other_instance`：不能自动处理，显示最小阻断页。
- `unknown_owner`：不能自动删除，进入诊断路径。
- `stale_registry`：只清理 registry，再允许 start。
- `docker_unavailable`：不做任何破坏性动作。

如果短期不新增 CLI 子命令，也必须在 Tauri backend 实现等价的单次协调操作；前端不得先 list、过一段时间再无锁 remove。

## 4. Shutdown API

当前 `shutdown_workbench(stop_runtime: bool)` 的布尔参数不足以表达多 workspace 目标和清理结果。改为结构化请求：

```ts
interface ShutdownRequest {
  workspaces: Array<{
    workspace: string;
    runtime_id: string;
    lease_id: string | null;
    retention: "remove_on_close" | "keep_stopped" | "keep_running";
  }>;
  reason: "window_close" | "tray_exit" | "app_exit";
}
```

返回报告增加：

```ts
interface ShutdownReport {
  graceful_closed: number;
  force_reaped: number;
  runtime_cleanup: Array<{
    workspace_key: string;
    runtime_id: string;
    action: "removed" | "kept" | "skipped" | "failed";
    state: "stopped" | "not_found" | "unknown";
    error_code: string | null;
  }>;
  unreaped_session_ids: string[];
  flush_errors: string[];
}
```

Rust shutdown coordinator必须保证：

1. `reject_new` 后不再接收新 Session；
2. Session cleanup 完成或达到 budget 后，按 Runtime 逐个执行 stop/inspect/remove；
3. 单个 Runtime 失败不阻塞其他 Runtime cleanup；
4. 最终报告写入 lifecycle log；
5. 进程退出后下次启动仍能通过 lease/reconcile 处理残留。

## 5. Preflight 语义变化

`runtime_conflict` 不再是“存在任意旧 Runtime 即 fail”。建议将 preflight 输出拆为：

```text
runtime_reconcile: pass | progress | block | unknown
recommended_action: start | focus_existing | reconcile_then_start | block
```

兼容期可继续输出旧字段：

- `recommended_action=resolve_conflict` 只用于 `active_other_instance` 和 `unknown_owner`；
- `stale_ephemeral`、`stale_registry` 返回 `start` 或 `reconcile_then_start`，不能让 UI 进入 ConflictManager；
- `matching_runtime_id` 只用于同一 instance 的已有 workspace，不再作为跨启动复用依据。

## 6. History 语义变化

`WorkspaceRecord.runtime` 进入兼容过渡：

- 保留字段读取能力，避免旧 history 解析失败；
- 新写入可以设置 `runtime: null`，或增加 `last_runtime` 只作为诊断信息；
- 新启动不得把 history 中的 runtime id 当作创建新 Runtime 的输入；
- layout 继续保存，但 Tab record 不得保存仍有效的 Session ID；
- `last_agent` 仍可用于默认 active placeholder 的 Agent 类型。

建议新增：

```json
{
  "layout_restore": "lazy",
  "last_runtime": {
    "runtime_id": "…",
    "closed_at": "…",
    "cleanup_result": "removed|not_found|failed"
  }
}
```

若不希望立即扩展 history schema，`layout_restore=lazy` 可先作为固定产品行为，不暴露设置项。

## 7. 安全不变量

以下规则必须写入代码注释和测试：

1. 只能自动删除 `owner=workbench` 且 `lifecycle=ephemeral` 的 Runtime。
2. 自动删除前必须同时满足 lease 过期、workspace key 相同、Docker label 与 registry 至少一侧可对账。
3. Docker 不可用时不得把状态写成 `not_found`，也不得 remove registry 作为“修复”。
4. `remove` 只删除 container 和 registry entry，不删除 workspace/data-root bind mounts。
5. 多窗口/多进程的 claim、cleanup、registry commit 必须在 workspace lock 下重新验证。
6. 异步旧结果不能把已完成 cleanup 的 workspace 回写成 running/conflict。
7. cleanup 超时后的状态必须是 `unknown/stale`，不能乐观显示 `removed`。

## 8. 依赖与 Toolchain 契约

### 8.1 持久化分类

Runtime metadata 增加由 `scope` 派生的依赖策略字段：

```json
{
  "scope": "project",
  "dependency_policy": "persistent_toolchain"
}
```

`dependency_policy` 不是普通用户可独立选择的设置，而是由 `scope` 派生：

```text
scope=project    -> dependency_policy=persistent_toolchain
scope=temporary  -> dependency_policy=ephemeral_toolchain
```

`retention` 是另一条独立维度：

```text
retention=remove_on_close -> 删除 Runtime container
retention=keep_stopped    -> 只 stop，保留 container writable layer
retention=keep_running    -> 保持运行，适用于托盘/服务场景
```

语义：

| 策略 | 来源 | 保证范围 | Runtime 删除后 |
|---|---|---|---|
| `persistent_toolchain` | `scope=project` 派生 | workspace + 持久 toolchain backend 中的用户级工具/缓存 | toolchain 保留，需重新注入 PATH |
| `ephemeral_toolchain` | `scope=temporary` 派生 | 当前 Runtime 内的临时用户级工具/缓存 | Runtime 删除后丢失 |

`scope=project|temporary` 仍表示 CLI 配置/挂载作用域；`dependency_policy` 是由它产生的规范化结果，便于 Runtime inspect、日志和 UI 展示。

### 8.2 Toolchain 目录

项目模式提供两种持久存储后端。

`host_bind` 使用 data-root 下的独立目录：

```text
data/workspaces/<hash>/toolchain/
  bin/
  npm-global/
  python/
  cargo/
  cache/
  environment.json
```

`docker_volume` 使用 Docker-managed named volume：

```text
volume name: aisc-wb-toolchain-<workspace-key>
mount target: /opt/aisc/toolchain
labels:
  io.aisc.owner=workbench
  io.aisc.kind=toolchain
  io.aisc.workspace-key=<full workspace key>
  io.aisc.schema-version=1
```

若完整 workspace key 使 volume 名过长，可使用稳定截断名，但 label 必须保存完整 key，并在 workspace lock 下核验名称和 label，避免哈希前缀碰撞。

无论使用哪种后端，Runtime 都只挂载专用目录 `/opt/aisc/toolchain`，并由 entrypoint 设置 PATH 和各包管理器的用户级路径。不要覆盖整个 `/root`、`/usr/local` 或镜像内置 CLI 目录。

临时模式不挂载这个宿主目录，而是在容器内创建等价的 `/tmp/aisc-toolchain`，使用同一套 PATH/包管理器配置；Runtime 退出后由容器层一并清理。

### 8.3 安装行为的保证边界

- 写入 `/root/app` 的内容属于 workspace 文件，在两种 scope 下都保留。
- `scope=project` 下写入已选择 toolchain backend 的内容属于可持久化范围。
- `scope=temporary` 下 toolchain 只存在于当前 Runtime。
- 写入 `/usr`、`/etc`、`/opt`（toolchain 外）、`/usr/local` 的内容只在 `retention=keep_stopped|keep_running` 下保证保留。
- v1 不维护已安装工具 manifest，也不拦截任意 npm/pip/cargo/apt 安装命令。
- v1 只在 toolchain 初始化时写入轻量 `environment.json`，记录 schema、OS、arch、glibc、Node、Python、镜像 ID 和写入时间；不记录包清单或安装命令。
- 启动时只比较轻量环境标记。关键版本不匹配时设置 `toolchain_incompatible` 警告，但不阻断 Runtime、不自动删除或迁移工具。
- 标记缺失或无法读取时状态为 `unknown`，继续挂载并显示诊断提示；不得假装已验证兼容。
- named volume 的生命周期独立于 Runtime container；`runtime remove` 不得附带 `docker volume rm`。

### 8.4 依赖状态 API

Runtime inspect 或新增 `runtime dependencies` 应能返回摘要，不返回 secret：

```json
{
  "scope": "project",
  "dependency_policy": "persistent_toolchain",
  "workspace_managed": true,
  "toolchain": {
    "mounted": true,
    "path": "/opt/aisc/toolchain",
    "storage": "docker_volume",
    "volume_name": "aisc-wb-toolchain-…",
    "environment_marker_version": 1,
    "compatibility": "compatible|warning|unknown",
    "warning_code": null,
    "last_checked_at": "…"
  },
  "container_only_changes": "unknown"
}
```

`container_only_changes=unknown` 是允许且预期的；系统不能声称已经发现、验证或保存了所有 Agent 安装过的工具和系统包。

### 8.5 Named volume 管理 API

如果平台选择 `docker_volume`，v1 必须提供最低限度的可管理性，不能只创建一个用户无法发现和备份的卷：

```text
aisc runtime toolchain inspect --workspace <path>
aisc runtime toolchain export  --workspace <path> --output <archive>
aisc runtime toolchain import  --workspace <path> --input <archive>
aisc runtime toolchain remove  --workspace <path> --confirm-workspace-key <hash>
```

约束：

- `inspect` 返回 backend、volume name、labels、粗略占用空间、创建/最后使用时间和 environment marker 摘要。
- `export` 使用只读 helper container 将 volume 内容归档；归档写入前先验证目标路径，不包含 Runtime container writable layer。
- `import` 默认只允许导入空的新 volume；覆盖已有 volume 必须使用单独的显式 force 流程。
- `remove` 必须核验 owner/kind/full workspace-key labels，并在 workspace lock 下确认没有活跃 lease 或挂载该 volume 的 Runtime。
- 普通 `runtime remove`、workspace close 和 stale reconcile 不调用 toolchain volume remove。
- 卸载器只有在用户选择“同时删除 AISC 工作区运行数据”时才删除这些 volume，并列出数量/占用空间。
