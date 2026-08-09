# AISC Workbench Runtime / Session 生命周期契约

> 状态：**MVP 规范（Proposed）**  
> 技术前置：[05-cli-gui-contract.md](./05-cli-gui-contract.md)  
> 适用范围：Workspace、Runtime、Session、Tab 的身份、状态、所有权与转移

## 一、对象与身份

| 对象 | 身份 | 实体 | 所有者 |
|---|---|---|---|
| Workspace | canonical absolute path | 宿主项目目录 | 用户/文件系统 |
| Runtime | UUID v4 `runtime_id` | 一个 Docker 容器 + 不可变配置 | AISC CLI |
| Session | UUID v4 `session_id` | 宿主 PTY + `aisc session open` + 容器内 Agent 进程组 | Tauri + AISC session wrapper |
| Tab | UUID v4 `tab_id` | Session 的 UI 视图或待重建占位符 | Vue/Workbench history |

引用规则：

- Workbench 对 Runtime 的后续操作只使用 `runtime_id`，不依赖随机容器名或 registry default pointer。
- Workbench 内部使用 `session_id` 关联 PTY、Channel、容器 session wrapper 元数据和 Tab。
- `tab_id` 可跨 Workbench 重启持久化；`session_id` 不作为可恢复活 PTY 的承诺。

## 二、核心不变量

1. 每个 Session 只属于一个 Runtime，不允许迁移。
2. Runtime 配置为 workspace、image、network、scope 的不可变值对象。
3. Session 不持有独立 network/scope/image，它只继承 Runtime 配置。
4. 同一 canonical workspace 最多一个 `project` Runtime。
5. 额外 `temporary` Runtime 必须由用户显式创建，不由 Session 配置冲突隐式产生。
6. Runtime 不是否运行以 AISC CLI 对 Docker 的观察为准；Workbench 缓存不是事实源。
7. Runtime 停止或被删除时，所有关联 Session 必须进入终止态。
8. 关闭 Tab 默认结束对应 Session，但不停止 Runtime。
9. MVP 不允许“Tab 关闭但 Agent 无头运行”；此能力需要可重连会话层后再设计。
10. Workbench 崩溃不能被当作可靠 cleanup 触发器；下次启动必须对账。

## 三、RuntimeSpec

```text
RuntimeSpec
  runtime_id: UUID
  workspace: canonical absolute path
  image: normalized image reference
  network: direct | proxy
  scope: project | temporary
  owner: workbench
  config_fingerprint: sha256(canonical serialized config)
```

Runtime 运行后不允许就地修改 RuntimeSpec。用户要求变更时：

- 无活动 Session：提示“停止并删除旧 Runtime，再创建新 Runtime”。
- 有活动 Session：列出受影响 Session，用户明确确认前不操作。
- 新请求为 temporary：可显式创建额外 Runtime，并在 UI 中显示隔离边界。
- 新请求为第二个 project Runtime：MVP 拒绝，不提供“强制并行”选项。

## 四、Runtime 状态机

### 4.1 状态

```text
unknown     无法观察 Docker，不知道真实状态
not_found   Docker 和 registry 对账后确认不存在
starting    正在创建/启动并等待 ready
running     容器运行且 runtime ready
stopping    正在结束 Sessions 并停止容器
stopped     容器存在但未运行
removing    正在删除容器与 registry 元数据
```

`error` 不是 Runtime 事实状态。操作失败表示为：

```text
RuntimeSnapshot
  state: RuntimeState
  observed_at: timestamp
  stale: boolean
  last_operation_error: optional structured error
```

操作失败后必须重新 inspect，用观察到的真实 state 更新 UI，不把所有失败粗暴归为 `error`。

### 4.2 转移

```text
not_found --start--> starting --ready--> running
                               --fail--> inspect -> observed state + operation error

stopped   --restart--> starting --ready--> running
running   --stop-----> stopping ---------> stopped
stopped   --remove---> removing ---------> not_found
running   --force remove--> removing ----> not_found

any observed state --Docker unavailable--> unknown
unknown --successful inspect-------------> observed state
```

合法操作：

| 当前状态 | 允许操作 |
|---|---|
| unknown | refresh |
| not_found | start |
| starting | cancel, view diagnostics |
| running | open session, stop, force remove |
| stopping | view progress |
| stopped | restart, remove |
| removing | view progress |

同一 Runtime 一次只允许一个破坏性 operation。Tauri backend 以 runtime ID 为粒度串行化 start/stop/restart/remove，前端禁用重复操作按钮。

## 五、Session 状态机

### 5.1 状态

```text
starting      正在创建 PTY 并启动 aisc session open
running       PTY 与容器 Agent 交互中
closing       正在 terminate 容器进程组并回收宿主子进程
exited        进程已结束，有 exit result
failed        会话未进入 running 或关闭无法确认
disconnected  宿主 PTY 丢失，但容器 session metadata 仍表明进程可能存活
```

`SessionExit` 必须包含：

```text
exit_code: integer | null
reason: process_exit | user_close | runtime_stop | transport_error | workbench_crash_cleanup
finished_at: timestamp
```

### 5.2 转移

```text
starting --PTY+child ready--> running
starting --spawn/contract fail--> failed
running  --process exits-----> exited
running  --close-------------> closing --confirmed gone--> exited
running  --PTY transport lost-----------------------------> disconnected
closing  --cannot confirm termination---------------------> failed
disconnected --terminate confirmed------------------------> exited
```

Session 输出终止必须由单一 EOF/exit event 表示。重复 EOF、child exit 和 terminate response 由 backend reducer 合并，前端不自行猜测最终原因。

## 六、Tab 契约

Tab 是 UI 对象，不是容器进程。

```text
Tab
  tab_id: UUID
  runtime_id: UUID
  desired_agent: claude | codex | bash | cc-switch
  title: string
  position: integer
  active: boolean (derived from active_tab_id; not persisted per tab)
  binding: placeholder | opening | session(session_id) | exited(summary)
```

规则：

- history 恢复后 Tab 先是 `placeholder`，不伪造 running Session。
- 用户确认恢复布局后，Workbench 为 placeholder 创建新 Session。
- 已退出 Tab 可显示 exit summary，用户可“重新打开”以创建新 Session ID。
- 关闭 placeholder/exited Tab 只更新 UI history，不发送 session terminate。
- 关闭 running Tab 必须执行第七节的 Session 关闭流程。

## 七、关闭与退出语义

### 7.1 关闭 Session/Tab

```text
1. Tab 进入 closing，停止接收新输入。
2. Tauri 调用 aisc session terminate(runtime_id, session_id)。
3. 终止确认后关闭 PTY writer/master。
4. wait/reap 本地 aisc/docker 子进程。
5. 发出单一 SessionExit(reason=user_close)。
6. 从布局中删除 Tab，原子写入 history。
```

如 terminate 失败或 Docker 不可用：

- 不宣称 Session 已关闭。
- 状态进入 `failed` 或 `disconnected`，显示“重试结束”和“停止整个 Runtime”。
- 只有用户明确选择“仅从界面移除”时才删除 Tab，并记录 unresolved session ID 供下次对账。

### 7.2 停止 Runtime

1. 展示将被结束的 Session 数量和类型。
2. 用户确认后拒绝新 Session。
3. 并发调用 session terminate，有界等待并汇总结果。
4. 调用 `aisc runtime stop`。
5. 调用 inspect 确认 stopped，再更新 UI。
6. Tab 保留为 exited/placeholder，便于重启 Runtime 后重新打开。

### 7.3 退出 Workbench

MVP 默认策略：

- 有活动 Session 时显示退出确认，因为 MVP 不能保留其 PTY。
- 确认退出后结束本 Workbench 拥有的 Session，保留 Runtime 运行。
- 用户可选“结束 Sessions 并停止 Runtimes”；不提供无确认的全部停止。
- 没有活动 Session 时直接退出，不干预 Runtime。

## 八、崩溃与外部操作恢复

### 8.1 启动对账

```text
1. 读取 Workbench history（失败则隔离损坏文件，不覆盖）。
2. 调用 aisc runtime list --owner workbench --format json。
3. 按 runtime_id 合并 history 与实际 RuntimeSnapshot。
4. 对 running Runtime 调用 aisc session list 查找无 PTY 的孤儿 Session。
5. 显示不破坏的恢复摘要：恢复布局 / 结束孤儿 Sessions / 忽略。
```

禁止行为：

- 不因 history 缺失自动停止或删除 Workbench Docker label 的 Runtime。
- 不把存活容器称为“泄漏”或“垃圾”；默认保守保留。
- 不声称可 attach 到无持久会话层的旧 Agent PTY。

### 8.2 CLI 外部操作

MVP 通过定期 inspect/list 及操作后立即刷新发现外部变化：

- 外部 stop：Runtime -> stopped，关联 Session -> exited(reason=runtime_stop)。
- 外部 remove：Runtime -> not_found，Tab 保留为 placeholder。
- Docker daemon 不可用：Runtime -> unknown/stale，不返回 not_found。
- 外部 Provider 切换：下次 Provider 刷新更新活动 Session 状态。

## 九、并发与顺序

1. 每个 runtime ID 有独立 operation mutex；不同 Runtime 可并发。
2. 每个 Session 有独立顺序事件流，事件含单调 `seq`。
3. 操作请求含 `operation_id`；前端只接受当前 operation 的结果。
4. Runtime observation 含 `observed_at`；旧 observation 不得覆盖更新状态。
5. 幂等 CLI 操作可安全重试；非幂等操作在 timeout 后必须先 inspect 再决定重试。
6. Tauri 的 operation mutex 只处理本进程排序；GUI/CLI 和多窗口的互斥由 AISC CLI 的跨进程 registry/workspace lock 保证，锁超时后必须 refresh 而不是绕过。

## 十、Tauri Domain API

以下是 Workbench 内部命名 API，不直接暴露 shell/Docker 参数：

```text
negotiate_capabilities() -> CapabilityReport
run_preflight(workspace, runtime_spec) -> PreflightReport

create_runtime(runtime_spec) -> RuntimeSnapshot
list_runtimes(filter) -> RuntimeSnapshot[]
refresh_runtime(runtime_id) -> RuntimeSnapshot
stop_runtime(runtime_id) -> RuntimeSnapshot
restart_runtime(runtime_id) -> RuntimeSnapshot
remove_runtime(runtime_id, force) -> RuntimeSnapshot

open_session(runtime_id, session_id, agent, output_channel) -> SessionSnapshot
write_session(session_id, utf8_bytes) -> void
resize_session(session_id, cols, rows) -> void
close_session(session_id) -> SessionExit

get_provider_status(runtime_id, agent) -> ProviderSnapshot
load_history() -> WorkbenchHistory
save_history(expected_revision, owned_patch) -> new_revision | conflict
```

所有返回错误使用结构化 Workbench error：

```text
code: stable symbolic code
message: localized/user-facing summary
technical_detail: optional redacted detail
retryable: boolean
action: retry | refresh | upgrade_cli | start_docker | build_image | choose_workspace | none
```

## 十一、验收测试

### Runtime

- [ ] start 成功、失败、取消和同 runtime ID 重试符合状态机。
- [ ] stop/restart/remove 幂等，失败后 inspect 回到真实状态。
- [ ] Docker 不可用显示 unknown，不误报 not_found。
- [ ] 同 workspace 的第二个 project Runtime 被拒绝。

### Session

- [ ] 四种 Agent 均经过 starting -> running -> exited。
- [ ] Agent 自然退出、用户关闭、Runtime stop 和 PTY 断开有不同 reason。
- [ ] close 后宿主和容器内均无孤儿进程。
- [ ] 多个终止事件只生成一个 SessionExit。

### Recovery

- [ ] 正常退出后恢复布局，不伪造活 Session。
- [ ] Workbench 被 kill 后可发现 Runtime 与孤儿 Session，默认不删除。
- [ ] GUI 外 stop/remove 在刷新周期内更新状态。
- [ ] history 损坏时可启动并保留损坏文件供诊断。
