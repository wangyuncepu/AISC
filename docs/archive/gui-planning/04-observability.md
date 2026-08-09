# AISC Workbench MVP 可观察性规范

> 状态：**UI 状态规范（Proposed）**  
> 依赖：[03-lifecycle-contract.md](./03-lifecycle-contract.md)、[05-cli-gui-contract.md](./05-cli-gui-contract.md)  
> 原则：只展示有明确来源、观察时间和新鲜度的事实

## 一、目标与边界

可观察性的任务是随时回答四个问题：

1. 我正在操作哪个 workspace？
2. 它的 Runtime 现在是否可用，这个结论有多新？
3. 当前 Tab 运行哪个 Agent，属于哪个 Runtime？
4. 这个 Agent 使用哪个 Provider/route，Runtime 的 network/scope 是什么？

MVP 不提供 CPU、内存、磁盘或网络图表，不做 Docker Dashboard，不把终端输出变成日志系统，也不读取或展示 Provider 密钥及密钥片段。

## 二、信息层级

### P0：始终可见

| 状态 | 最小显示 | 交互 |
|---|---|---|
| Workspace | 目录名；重名时增加父目录；完整 canonical path 在详情中 | 复制路径、返回 workspace 列表 |
| Runtime | `Starting / Running / Stopped / Not found / Unknown`，并同时表达 fresh/stale | 打开 Runtime 详情；合法时提供 start/stop/restart |
| Active Agent | `Claude / Codex / Bash / cc-switch`；没有活动 Session 时显示 `No session` | 只随活动 Tab 改变，不做全局 Agent 假状态 |

P0 应在终端区域可见时保持可读。状态不能只依赖颜色；图标、文本和可访问名称必须表达同一含义。

### P1：紧邻上下文

| 状态 | 显示规则 |
|---|---|
| Provider | 仅对活动的 Claude/Codex 显示 provider name、route mode、auth status；Bash/cc-switch 显示 `Not applicable` |
| Network | 显示 Runtime 的 `direct` 或 `proxy`，它是不可变配置而不是实时流量状态 |
| Scope | 显示 Runtime 的 `project` 或 `temporary`，并用人类文案解释持久化边界 |

Provider 不是 Workbench 全局状态。Claude 与 Codex 的快照必须分别缓存和展示。Network/scope 不能在状态条中点击切换；修改它们意味着创建替代 Runtime，并进入带影响说明的显式流程。

### P2：按需详情

Runtime 详情面板可以显示：

- image、runtime UUID、container name/ID 和 owner。
- canonical workspace、network、scope、config fingerprint。
- 最后成功观察时间、最近刷新结果和 stale 原因。
- 当前 Workbench Session 与 wrapper 诊断结果；两者不用于声称可恢复原 PTY。
- 最近一次启动/停止/重启的阶段、run ID、稳定错误码、退出码、耗时和脱敏技术详情。

详情面板不包含资源图表、Provider 密钥、终端 scrollback 或“一键修改”不可变 Runtime 配置。

## 三、状态来源与所有权

| 状态 | Source of truth | Workbench 获取方式 | 缓存键 |
|---|---|---|---|
| Workspace 选择与布局 | Workbench history | schema-versioned 本地 JSON | canonical workspace path |
| Runtime 配置与实际状态 | Docker/registry，由 AISC CLI 统一对账 | `runtime list/inspect --format json` 与控制操作结果 | `runtime_id` |
| 当前 Workbench Session | Tauri PTY supervisor | 本地状态机和有序 Session event | `session_id` |
| 容器内 Session 进程 | AISC session wrapper | `session list/terminate --format json`，仅用于诊断/清理 | `(runtime_id, session_id)` |
| Provider/route/auth | cc-switch/Agent 配置，由 AISC CLI 脱敏读取 | `provider current --runtime-id --agent --format json` | `(runtime_id, agent)` |

Workbench 不读取 `<aisc-root>/.aisc/containers.json`，不直接调用 Docker 来补全状态，也不从终端文本或 Docker 日志猜测 Agent/Provider 状态。

## 四、标准快照

### 4.1 Runtime observation

Workbench 内部的 Runtime observation 至少包含：

```text
runtime_id
state
config { workspace, image, network, scope }
container_name/container_id
registry_state
observed_at            # CLI 对 Docker/registry 完成观察的时间
received_at            # Workbench 收到结果的本地时间
freshness              # fresh | stale | unknown
stale_reason?          # timeout | control_plane_unavailable | expired | app_resumed
last_operation_error?  # 与 state 分离
revision               # Workbench 本地单调 revision
```

`error` 不是 Runtime 事实状态。控制操作失败后，Workbench 保存结构化 operation error，并立即 inspect；标题继续显示 inspect 得到的 `running/stopped/...`，不能用一个笼统的红色 `Error` 覆盖真实状态。

### 4.2 Provider snapshot

Provider snapshot 固定为 Agent 维度：

```text
runtime_id
agent                  # claude | codex
provider_id
provider_name
route_mode             # official-direct | cc-switch-proxy | unknown
auth_status            # configured | login_required | not_configured | unknown
observed_at
received_at
freshness
```

约束：

- 不存在“当前 Runtime 的全局 Provider”。
- capability 缺失或查询失败显示 `Unknown`，不能推断为 `Not configured`。
- 不返回、缓存、日志化或渲染 API key、token、cookie、OAuth 凭据和任何密钥片段。
- cc-switch Session 退出后，使该 Runtime 的 Claude/Codex Provider 缓存失效；立即刷新活动 Agent，另一个 Agent 在切换到对应 Tab 时刷新。

## 五、刷新策略

MVP 使用 CLI 操作结果加轮询，不接入 Docker Events/Bollard。

| 场景 | Runtime 刷新 | Provider 刷新 |
|---|---|---|
| 应用启动/恢复 workspace | `runtime list` 对账一次，选中 Runtime 后立即 inspect | 活动 Tab 为 Claude/Codex 时立即查询 |
| 窗口聚焦且 Runtime 稳定 | 每 5 秒 inspect | 活动 Agent 每 15 秒查询 |
| `starting/stopping/removing` | 操作事件驱动；最多每 2 秒 inspect，直到终态或 timeout | 暂停，Runtime 回到 running 后刷新 |
| 窗口失焦但未最小化 | 每 15 秒 inspect | 活动 Agent 每 60 秒查询 |
| 最小化、系统 suspend | 暂停常规轮询 | 暂停常规轮询 |
| 回到前台、网络/Docker 恢复 | 先把旧快照标为 stale，再立即 inspect | 活动 Agent 立即查询 |
| start/stop/restart/remove 完成或失败 | 立即 inspect，不仅信任操作返回值 | Runtime running 且 Agent 活动时刷新 |
| 外部操作或用户手动刷新 | 立即 inspect；同一资源请求去重 | 活动 Agent 立即查询 |

调度约束：

1. 同一 Runtime/Provider 键最多一个常规轮询在途；手动刷新可取消或取代旧请求。
2. 轮询在基础周期上增加不超过 10% jitter，避免多个窗口同步冲击 CLI/Docker。
3. timeout 不清空最后一次成功事实，而是将其标为 stale；错误详情保留稳定 code。
4. Session 的实时状态由 PTY supervisor 事件驱动，不使用 5 秒轮询模拟。`session list` 只在启动对账、关闭失败、崩溃清理和详情页手动诊断时调用。
5. Provider 查询只在 Runtime 为 running 时调度；首次创建时等待 ready，不从 workspace 文件或历史推断。

这些频率是 MVP 默认值，应以 CLI 耗时与前后台负载指标调整，但不能通过降低频率掩盖状态错误。

## 六、新鲜度与乱序处理

### 6.1 `fresh / stale / unknown`

- `fresh`：最近一次请求成功，且 `received_at` 距当前时间不超过该场景刷新周期的 2 倍。
- `stale`：存在最后成功快照，但最新请求失败、应用刚恢复，或快照超过 fresh 预算且未超过 5 分钟。UI 显示“Last known”与观察时间。
- `unknown`：本进程尚无成功快照、runtime identity 不一致，或最后成功快照超过 5 分钟。详情可保留最后已知值，但 P0 状态必须显示 `Unknown`。

`stale` 是状态质量，不是 Runtime state。例如 `Running · status stale · observed 32s ago`；它不能被显示成仍然确定的绿色 Running。

### 6.2 Reducer 排序规则

每个 Runtime state 持有本地单调 `revision` 和最新 `request_seq`：

1. 每次用户控制操作先递增 revision，并记录操作开始时的 generation。
2. 每个 inspect/list/provider 请求分配递增 request sequence，并捕获发起时 revision。
3. 响应只有在 runtime identity 相同、捕获 revision 未落后且 request sequence 不小于已应用序号时才能提交。
4. 同一有效序列内，`observed_at` 早于已应用快照的响应被丢弃。
5. 应用成功 observation、operation error 或本地 Session event 后递增 revision。
6. 系统时钟异常时，进程内 request sequence/revision 优先；`observed_at` 仍用于用户可见的新鲜度，不作为唯一并发锁。

控制操作无论成功或失败都以一次新的 inspect 收尾。该规则防止慢 poll 将 `stopping` 覆盖回 `running`，也允许外部 CLI 操作在下一次有效观察中被发现。

## 七、诊断通道必须分离

| 通道 | 包含内容 | 展示/保留 | 明确不包含 |
|---|---|---|---|
| Runtime 初始化诊断 | build/start 的结构化阶段、耗时、ready/cancel 结果和不透明 build output | 启动界面与本进程详情 | Agent 对话、伪造百分比、持久化 build log |
| AISC 控制面诊断 | command name、run ID、稳定错误码、CLI version、exit code、脱敏 stderr 摘要 | 可操作错误 + 折叠技术详情 | 任意 shell、完整环境、密钥 |
| Session terminal | `aisc session open` 的 PTY byte stream | 仅对应 xterm.js；按终端 scrollback 上限驻留内存 | Workbench history、应用诊断日志、crash report |
| Docker PID 1 logs | entrypoint/idle runtime 的 stdout/stderr | MVP 不在 Workbench 自动采集；需要时由用户在外部诊断 | `docker exec` 内 Claude/Codex/Bash 的输出 |

`docker logs` 只观察容器 PID 1 的日志流，通常不包含 `docker exec` 启动的 Agent Session 输出。Workbench 不得把两者合并成“完整 Runtime 日志”。若未来增加日志查看，必须先在 AISC CLI 定义脱敏、大小与权限契约。

## 八、错误与降级展示

错误展示顺序固定为：

1. 人类可理解的事实，例如“无法确认 Runtime 状态”。
2. 基于稳定错误码的一至两个安全操作，例如“重试”“检查 Docker”。
3. 默认折叠的技术详情：run ID、错误码、版本、退出码、耗时和脱敏摘要。

典型降级：

| 情况 | P0/P1 表达 | 可用操作 |
|---|---|---|
| Docker/CLI 暂时不可用 | Runtime `Unknown` 或 `Last known … · stale` | 重试、打开诊断；不猜测、不自动删除 |
| Provider capability 缺失 | Provider `Unknown · CLI upgrade required` | 继续终端、打开 cc-switch、查看升级说明 |
| Runtime 在 GUI 外停止/删除 | 下一有效 poll 显示 `Stopped/Not found`；对应 Session 进入 disconnected/exited | restart/start replacement、关闭失效 Tab |
| Provider 查询失败 | 保留 Agent 专属 last-known snapshot 并标 stale | 重试；不能套用另一个 Agent 的 Provider |
| 控制操作失败 | 真实 Runtime state + 独立错误提示 | inspect 后按新状态给出动作 |

## 九、可访问性与状态文案

- 所有图标同时提供可见文本或 `aria-label`，例如 `Runtime running, status stale, observed 32 seconds ago`。
- `aria-live` 只播报语义变化：Runtime 状态变化、操作完成/失败、Provider/auth 变化；普通 poll 更新时间不播报。
- Warning/Error 不只依赖黄/红色；使用图标、标题和行动文案。
- 状态详情可通过键盘打开和关闭，焦点返回触发元素；终端按键路由遵循独立快捷键规范。
- 相对时间用于快速浏览，详情中必须同时提供本地化绝对观察时间。

## 十、验收清单

- [ ] P0 在所有主界面始终显示 workspace、真实 Runtime state/freshness 和活动 Agent。
- [ ] Claude/Codex Provider 分别缓存；切换 Tab、退出 cc-switch 和外部修改后按刷新策略更新。
- [ ] Provider payload、UI、history、backend log 和 crash report 均不含密钥或密钥片段。
- [ ] stop/restart 与慢 poll 乱序时，旧 observation 不覆盖新状态；操作错误不替代事实状态。
- [ ] GUI 外 stop/remove 在前台一个稳定轮询周期内可见；Docker 不可用时不显示伪 Running。
- [ ] 最小化暂停轮询，恢复时先标 stale 并立即刷新；没有并行无界 CLI 子进程。
- [ ] Session terminal 输出不进入应用日志/history；`docker logs` 不被描述为 Agent Session 输出。
- [ ] Network/scope 不可原地切换，修改入口明确表示需要替代 Runtime。
- [ ] 状态使用文本、图标和可访问名称，屏幕阅读器不会被周期性 poll 淹没。
- [ ] MVP 界面和后台均未实现 CPU/内存/网络资源采集与图表。
