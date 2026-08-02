# AISC Workbench CLI / PTY 契约

> 状态：**MVP 规范（Proposed）**  
> 优先级：**P0，阻塞 Workbench 端到端实现**  
> 依赖：现有 `aisc.cli/v1` JSON envelope 和稳定错误码  
> 规范关键词：“必须”表示 MVP 强制要求，“应”表示可在有证据时偏离

## 一、契约目标

Workbench 需要在不复制 AISC 容器逻辑的前提下，完成两类完全不同的交互：

1. **控制面**：创建、查询、停止 runtime，检查环境和 Provider 状态。
2. **数据面**：将用户的终端输入输出、窗口尺寸和信号传递到容器内 Agent。

两者必须分离：

```text
Vue / xterm.js
  ├── control invoke ──> Tauri Command ──> aisc ... --format json
  └── terminal bytes ──> portable-pty ──> aisc session open ...
```

## 二、不可变约束

1. **AISC CLI 是唯一 Docker 控制面。** Workbench 不直接写 `containers.json`，不直接 `docker run/stop/rm`。
2. **Workbench 不解析人类文本来推断状态。** 普通控制命令必须返回 `aisc.cli/v1` JSON envelope；长任务只使用本规范定义的 JSONL event stream。
3. **PTY 数据不混入 JSON。** `aisc session open` 是 text-only 交互命令，stdout/stderr 均属于终端会话。
4. **前端不能传入任意 shell 命令。** Agent 类型由受控 enum 映射为容器内 argv，全程不使用 `shell=True`。
5. **密钥不进入 Workbench。** Provider 契约只返回标识、路由模式和 `configured`/`login_required` 等元数据。
6. **Runtime 配置创建后不可变。** workspace、image、network、scope 变更必须创建新 runtime。
7. **MVP 不承诺恢复活 PTY。** Workbench 可重新发现 runtime 并重建标签布局，但不 attach 到原 Agent 会话。

## 三、现有 CLI 差距

| 需求 | 当前行为 | MVP 所需变更 |
|---|---|---|
| 持久 runtime | `aisc run` 默认交互运行镜像 `CMD` | 新增无 TTY、初始化后 idle 的 runtime 启动命令 |
| 显式 scope | 交互菜单或 `--non-interactive` 强制 project | runtime start 必须显式接受 `project|temporary` |
| 直接 Agent Session | 仅 `shell` 和 `switch`；`docker exec` 不继承 entrypoint 动态环境 | 新增基于 runtime context 重建作用域环境的 `session open` |
| 稳定 runtime ID | `--name` 只是前缀，最终名含随机后缀 | 由调用者提供 UUID，幂等启动并返回精确容器身份 |
| Workbench 发现 | registry 只存 image/workspace/network/label | 以向后兼容方式新增 runtime/owner/scope 元数据和 Docker labels |
| Session 确定性关闭 | 杀掉宿主 Docker client 的容器内效果未定义 | 新增 session wrapper 和 terminate 命令，保证 Agent 进程组结束 |
| Provider 可观察 | CLI 只有 Claude quick switch 和交互编辑 | 新增按 Agent 读取 current/routing/auth metadata 的结构化命令 |

## 四、能力协商

Workbench 启动后首先调用 `aisc version --format json`。返回数据应向后兼容地增加：

```json
{
  "capabilities": {
    "runtime": "aisc.runtime/v1",
    "session": "aisc.session/v1",
    "providerStatus": "aisc.provider-status/v1",
    "buildEvents": "aisc.build-events/v1"
  }
}
```

协商规则：

- `runtime` 或 `session` 能力缺失：阻止启动 runtime，显示升级 AISC 的操作建议。
- `providerStatus` 缺失：允许进入终端，Provider 显示为 `Unknown`，仍可打开 cc-switch。
- `buildEvents` 缺失：已有镜像仍可启动；镜像缺失时禁用 Workbench 内构建，提示升级 CLI 或在外部完成构建。
- Workbench 不根据版本号猜测能力，只依赖 capability 字段。

### 4.1 长任务：`aisc build --events`

镜像构建是 MVP 唯一需要流式结构化进度的控制命令：

```text
aisc build --tag IMAGE --events
```

`--events` 的 stdout 必须是 `aisc.cli/v1` JSONL；每行至少包含 `protocol`、`command`、`run_id`、单调 `seq`、`type`、`ts` 和 `data`。事件集合固定为：

| Event | 语义 |
|---|---|
| `build.start` | 已接受请求，包含 image tag |
| `build.plan` | 预检完成，包含不含环境和密钥的计划摘要 |
| `build.output` | Docker/BuildKit 的不透明输出块，包含 `stream` 和 `chunk`；Workbench 只显示、不解析 |
| `build.complete` | 唯一成功终止事件，包含 `exit_code: 0` |
| `build.failed` | 唯一失败终止事件，包含非零 exit code 和稳定 error code |
| `build.cancelled` | 唯一取消终止事件，包含 `exit_code: 130` 和实际资源摘要 |

强制语义：

1. stdout 不得混入非 JSONL 文本；build output 必须封装在 `build.output`，不能等进程结束后一次性返回。
2. 每个流必须恰好有一个 terminal event；进程退出码与 terminal event 的 `data.exit_code` 一致。
3. Workbench 不根据 build output 计算百分比或判断成功，只消费 event type、稳定 error code 和 terminal event。
4. Tauri 取消时必须结束 CLI 及其 Docker 子进程组/Job；CLI 尽力发出 `build.cancelled`。若被强杀无法发出，Workbench 将其表示为 transport failure，再调用 image preflight 确认事实。
5. `build.output` 只在当前启动界面内存中显示，使用大小上限和背压，不写入 history、应用日志或 crash report。
6. 当前 CLI 已有 `--events` 基础协议，但 Phase 0 必须补齐增量 output、terminal/cancel 语义和契约测试后，Workbench 才能依赖该 capability。

## 五、Runtime 命令

### 5.1 `aisc runtime preflight`

```text
aisc runtime preflight
  --runtime-id UUID
  --workspace PATH
  [--image IMAGE]
  [--network direct|proxy]
  [--scope project|temporary]
  [--owner workbench]
  --format json
```

该命令只读且无副作用：不得创建 workspace/config 目录、容器、registry 记录或下载资源。成功执行命令表示“完成了检查”，不等于配置可启动；payload 示例：

```json
{
  "spec": {
    "runtime_id": "0e7b7e3b-5c97-4d20-9292-bca647cc940a",
    "workspace": "/home/user/project",
    "image": "super-claude:latest",
    "network": "direct",
    "scope": "project"
  },
  "checks": [
    {"id": "docker", "status": "pass", "error_code": null},
    {"id": "workspace", "status": "pass", "error_code": null},
    {"id": "image", "status": "pass", "error_code": null},
    {"id": "network", "status": "pass", "error_code": null},
    {"id": "runtime_conflict", "status": "pass", "error_code": null}
  ],
  "can_start": true,
  "recommended_action": "start",
  "matching_runtime_id": null,
  "conflicts": [],
  "observed_at": "2026-08-02T12:00:00Z"
}
```

规则：

- check ID 固定为 `docker/workspace/image/network/runtime_conflict`，status 为 `pass/warn/fail`；失败项携带稳定 error code 和可选脱敏 detail。
- `recommended_action` 固定为 `start|reuse|restart|resolve_conflict`。配置指纹相同的 Workbench Runtime 返回 `matching_runtime_id`，供 UI 复用/重启；此时不得用新 runtime ID 再创建第二个 project Runtime。不兼容 Runtime 放入 `conflicts`，不能由 preflight 自动 stop/remove。
- 同 workspace 的旧 AISC container 若 scope/owner 无法确认，作为 conflict 返回，不自动视为可复用，也不自动删除。
- `can_start` 表示“可用请求中的 runtime ID 新建”，matching project Runtime 使用其他 ID 时为 false 并推荐 reuse/restart。该值只汇总本次观察；`runtime start` 必须在 workspace lock 内重新执行关键验证，不能信任客户端传回的 preflight 结果。
- image 缺失只返回 config failure，不触发 build/pull。

### 5.2 `aisc runtime start`

```text
aisc runtime start
  --runtime-id UUID
  --workspace PATH
  [--image IMAGE]
  [--network direct|proxy]
  [--scope project|temporary]
  [--owner workbench]
  [--format json]
```

强制语义：

1. `runtime_id` 由 Workbench 在首次请求前生成，必须是 UUID v4。
2. CLI 对 workspace 做 canonicalize 和可读写校验，返回 canonical path。
3. 容器以 detached idle 模式运行；entrypoint 完成 scope、cc-switch 和目录初始化，原子写入 `/run/aisc/runtime-context.json` 后才返回 ready。
4. CLI 只在 Docker 创建成功后写 registry，失败不留活动记录。
5. 容器必须包含 `io.aisc.managed=true`、`io.aisc.kind=runtime`、`io.aisc.runtime-id=<uuid>`、`io.aisc.owner=workbench` 和 canonical workspace 哈希 `io.aisc.workspace-key=<sha256>` Docker labels；label 不写入原始宿主路径。
6. 相同 runtime ID 重试时：配置指纹相同则幂等返回已有 runtime；指纹不同则返回 conflict。
7. `project` scope 下，同一 canonical workspace 已有其他 project runtime 时必须拒绝；MVP 不允许共享 `.claude/.codex/.cc-switch` 的并行 project runtime。

`runtime-context.json` 是容器内 Session 的非秘密交接文件，至少包含 schema version、runtime ID、scope、workspace mount、Claude/Codex/cc-switch config dir 和 ready time。它不得包含环境变量值、Provider key/token/cookie；文件写入必须先临时文件再 rename。Runtime ready check 同时验证 schema、runtime ID 与目录可访问。

并发与 registry 规则：

1. registry 保持现有 `{ default, containers: { container_name: metadata } }` 外形，使用 `.containers.lock` 保护完整 read-modify-write，并以同目录临时文件、fsync、`os.replace` 提交。
2. 锁必须跨平台且 fail closed：POSIX 使用 `fcntl.flock`；Windows 使用 `msvcrt.locking` 的有界重试实现。平台锁不可用或超时必须返回稳定错误，不能像当前实现一样在 Windows 静默无锁继续。
3. 所有 registry snapshot read 也在锁内完成，避免 Windows reader 与 replace 冲突；Docker inspect 在复制出 snapshot 并释放锁后执行。
4. `project` Runtime start 另按 canonical workspace hash 获取 `.aisc/workspace-locks/<sha256>.lock`，锁顺序固定为 workspace lock -> registry lock，且不得反向获取。
5. workspace lock 覆盖“registry/labels 冲突检查 -> Docker 创建/ready -> registry commit”。若 registry commit 失败，CLI 尝试删除新容器；清理失败时返回 partial resource identity，供 inspect/retry 处理。
6. POSIX 与 Windows 均以两个独立 CLI 进程做竞态测试；同一 workspace 只能有一个 `project` start 成功，不能只测单进程 mutex。

成功时 `data` payload：

```json
{
  "runtime_id": "0e7b7e3b-5c97-4d20-9292-bca647cc940a",
  "container_name": "aisc-wb-0e7b7e3b",
  "container_id": "0123456789ab",
  "state": "running",
  "ready": true,
  "reused": false,
  "config": {
    "workspace": "/home/user/project",
    "image": "super-claude:latest",
    "network": "direct",
    "scope": "project"
  },
  "config_fingerprint": "sha256:...",
  "created_at": "2026-08-02T12:00:00Z"
}
```

### 5.3 `aisc runtime list`

```text
aisc runtime list [--owner workbench] [--workspace PATH] --format json
```

- 必须一次返回 registry 元数据与 Docker 实际状态的对账结果。
- 容器存在但 registry 缺失时标记 `registry_state: "missing"`，不自动删除。
- Docker 不可用时返回稳定错误，不把缓存状态伪装成实时值。

每个 runtime 至少包含：

```json
{
  "runtime_id": "...",
  "container_name": "...",
  "container_id": "...",
  "state": "running",
  "config": {
    "workspace": "...",
    "image": "...",
    "network": "direct",
    "scope": "project"
  },
  "owner": "workbench",
  "registry_state": "registered",
  "observed_at": "2026-08-02T12:00:00Z"
}
```

### 5.4 `aisc runtime inspect`

```text
aisc runtime inspect --runtime-id UUID --format json
```

返回与 list row 同构的单个 runtime。命令必须区分：

- `not_found`：Docker 与 registry 均不存在。
- `stopped`：容器存在但未运行。
- `unknown`：Docker daemon 或权限不可用，无法确认实际状态。

### 5.5 `aisc runtime stop|restart|remove`

```text
aisc runtime stop --runtime-id UUID --format json
aisc runtime restart --runtime-id UUID --format json
aisc runtime remove --runtime-id UUID [--force] --format json
```

- `stop` 停止但保留容器和 runtime 元数据，幂等成功。
- `restart` 使用原配置重启同一容器，完成 ready check 后返回。
- `remove` 删除容器并注销 registry；运行中且没有 `--force` 时拒绝。
- 这些新语义不得静默改变旧 `aisc stop` 的兼容行为。

## 六、Session 命令

### 6.1 `aisc session open`

```text
aisc session open
  --runtime-id UUID
  --session-id UUID
  --agent claude|codex|bash|cc-switch
```

强制语义：

1. 命令仅支持 text 模式，必须在 TTY 中运行。
2. CLI 检查 runtime 存在且 running，否则在 stderr 输出简洁错误并以稳定退出码结束。
3. CLI 使用受控 argv 执行 `docker exec -it aisc-session-wrapper ...`；wrapper 必须从 `/run/aisc/runtime-context.json` 重建 `CLAUDE_CONFIG_DIR`、`CODEX_CONFIG_DIR`、`CODEX_HOME`、`CC_SWITCH_CONFIG_DIR`，不能假设 `docker exec` 会继承 PID 1 环境。
4. 容器内 session wrapper 记录 session ID、Agent、PID/PGID 和启动时间，不记录输入输出或环境密钥。
5. Agent 退出码传递为 `aisc session open` 的进程退出码。
6. Ctrl+C、Ctrl+Z、EOF 和 resize 必须经过 GUI PTY、Docker exec PTY 传递到 Agent，并由 Phase 1 实机测试验收。

Provider/Agent 环境重建规则：

- wrapper 每次打开 Session 时重新读取 context 指向的当前配置，因此 Runtime 启动后的 cc-switch 变更对新 Session 生效。
- Claude `settings.json` 的 `env` 只注入 Agent 子进程；变量名必须校验，值必须通过无 shell/eval 的 exec environment 传递。
- 不把重建后的环境写入 session metadata、stdout/stderr、Workbench JSON 或诊断日志。
- Bash/cc-switch 继承同一 config dir 边界；不同 Agent 使用受控 argv，不接受前端自定义 executable/arguments。

Session metadata 与进程身份：

- metadata 固定在容器内 `/run/aisc/sessions/<session-id>.json`；session ID 必须先按 UUID 解析，禁止作为任意路径片段。
- record 至少包含 schema version、runtime/session ID、Agent、state、PID、PGID、Linux process start ticks、started/finished time 和 exit code；权限为 `0600`，临时文件 + rename 提交，不含 argv、环境或输出。
- wrapper 以独立进程组启动受控 Agent，负责 wait/reap，并将 record 原子更新为 terminal state；同 session ID 冲突必须拒绝。
- terminate 发信号前同时核对 PID、PGID 与 `/proc/<pid>/stat` start ticks。目标不存在或身份不匹配时幂等标记 exited，不得向可能复用该 PID 的进程发信号。
- 身份确认后向进程组发送 TERM，等待可配置但有界的宽限期，再发送 KILL 并 wait；重复 terminate 返回同一 terminal 事实。
- Runtime 启动和 `session list` 可清理超过保留期的 terminal record；绝不根据 metadata 声称 PTY 可恢复。

### 6.2 `aisc session list|terminate`

```text
aisc session list --runtime-id UUID --format json
aisc session terminate --runtime-id UUID --session-id UUID --format json
```

- `list` 读取容器内 session wrapper 元数据，仅用于诊断和崩溃后清理，不表示可恢复 PTY。
- `terminate` 先向会话进程组发 TERM，等待宽限期，再在必要时 KILL；目标已退出时幂等成功。
- Workbench 关闭标签时先调用 `terminate`，再关闭宿主 PTY 并 wait/reap 本地子进程。

## 七、Provider 状态命令

```text
aisc provider current
  --runtime-id UUID
  --agent claude|codex
  --format json
```

成功 payload：

```json
{
  "runtime_id": "...",
  "agent": "codex",
  "provider_id": "codex-official",
  "provider_name": "Codex Official",
  "route_mode": "official-direct",
  "auth_status": "configured",
  "observed_at": "2026-08-02T12:00:00Z"
}
```

约束：

- 命令要求 Runtime 为 running；不存在/未运行时返回对应 Runtime 稳定错误，不读取宿主 workspace 文件来猜测。
- `route_mode` 至少支持 `official-direct|cc-switch-proxy|unknown`。
- `auth_status` 至少支持 `configured|login_required|not_configured|unknown`。
- 不返回 API key、token、cookie、OAuth 凭据或任何可恢复的密钥片段。
- MVP 只要求可观察；Provider 快速切换仍可通过 cc-switch Session 完成。

## 八、错误、退出码与取消

新增稳定错误码：

| 错误码 | 场景 |
|---|---|
| `AISC_ERR_CAPABILITY_UNSUPPORTED` | CLI 不支持 Workbench 所需契约 |
| `AISC_ERR_RUNTIME_NOT_FOUND` | runtime ID 无法映射到容器 |
| `AISC_ERR_RUNTIME_NOT_RUNNING` | session 要求的 runtime 未运行 |
| `AISC_ERR_RUNTIME_CONFLICT` | runtime ID 或 project workspace 与已有配置冲突 |
| `AISC_ERR_RUNTIME_NOT_READY` | 容器已创建但初始化未就绪 |
| `AISC_ERR_SESSION_NOT_FOUND` | session 元数据不存在 |
| `AISC_ERR_SESSION_FAILED` | exec/session wrapper 启动失败 |
| `AISC_ERR_STATE_LOCK_TIMEOUT` | registry/workspace 跨进程锁不可用或超时 |

规则：

- JSON envelope 的 `meta.exit_code` 必须与进程退出码一致。
- 受控错误必须提供稳定 code，Workbench 按 code 选择 UI，不对 message 做字符串匹配。
- 用户取消 runtime start/build 时，CLI 必须尽力终止 Docker 子进程并返回 130；已创建资源必须在 payload 中报告。

## 九、Workbench 进程与 IPC 契约

### 9.1 控制命令

- Tauri 启动阶段按 [02-startup-flow.md](./02-startup-flow.md) 发现并 pin 一个经过 capability 验证的 AISC 绝对 executable；同一进程的 control 与 PTY 命令必须使用该路径。
- Tauri 后端用 argv 数组启动 `aisc`，禁止 shell 拼接。
- stdout 上限必须受控，JSON parse 失败返回 Workbench 自身的 protocol error，并保留经脱敏的 stderr 摘要。
- 每个命令都有 timeout 与 cancellation token；Docker build 按第 4.1 节使用 `--events` 流式处理。
- Workbench 只接收结构化 error code，人类 message 用于“技术详情”。

### 9.2 PTY 数据

- 后端对每个 Session 维护独立 reader、writer、child handle 和 cancellation token。
- PTY 输出保持 bytes，按有序 chunk 经 Tauri Channel 发给前端，xterm.js 以 `Uint8Array` 写入。
- 前端 `onData` 输入以 UTF-8 编码后写入 PTY；大段粘贴必须有大小上限和背压。
- 输出事件至少包含 `session_id`、单调 `seq`、bytes 和 EOF/error 终止事件。
- resize 在窗口稳定后节流传递，不通过高频全局 Event 广播终端内容。

## 十、安全约束

1. workspace 必须 canonicalize，不允许前端传入未验证路径后直接拼接到 shell。
2. AISC executable 必须来自 backend discovery/pin，前端不得为单次调用传入 executable；runtime/session/agent ID 必须校验格式并作为独立 argv token 传递。
3. Tauri capabilities 只暴露命名的 Workbench commands，不暴露任意进程启动或任意文件读写。
4. 日志记录命令名、run ID、退出码和耗时，不记录 PTY 内容、Provider 密钥或完整环境。
5. WebLinksAddon 打开外部 URL 必须经过 Tauri opener 允许列表和用户动作，不自动执行终端链接。

## 十一、实现落点

CLI 预计修改：

- `src/aisc/cli/main.py`：新增 runtime/session/provider current 命令路由和参数。
- `src/aisc/domain/models.py`：新增 RuntimeSpec、RuntimeRecord、ProviderStatus 和稳定错误。
- `src/aisc/cli/commands/runtime.py`：只读 preflight 与 runtime 生命周期用例。
- `src/aisc/cli/commands/session.py`：session 解析、scope wrapper 和 terminate 用例。
- `src/aisc/adapters/docker_.py`：增加 runtime labels、批量查询和幂等操作，仍是唯一 Docker adapter。
- `src/aisc/adapters/container_registry.py`：向后兼容地扩展 runtime 元数据，补齐 POSIX/Windows 锁且不改变旧记录读取。
- `container/entrypoint.sh`：增加非交互 runtime ready 模式并原子写入非秘密 runtime context。
- `container/aisc-session-wrapper`：从 runtime context 安全重建作用域环境，原子维护 Session record，以 PID/PGID/start ticks 保证清理。

Workbench 预计落点：

- `workbench/src-tauri/src/cli.rs`：结构化 CLI runner 和 capability negotiation。
- `workbench/src-tauri/src/runtime.rs`：runtime Tauri commands 与状态对账。
- `workbench/src-tauri/src/pty.rs`：portable-pty Session supervisor。
- `workbench/src-tauri/src/error.rs`：AISC error code 到 Workbench domain error 的映射。

## 十二、契约验收门

进入 Workbench 功能开发前，以下项目必须全部通过：

- [ ] `runtime start` 在无 TTY 环境中创建 ready idle runtime，JSON stdout 纯净。
- [ ] `runtime preflight` 在 pass/warn/fail 下返回固定 checks 且零文件/Docker 副作用；start 不信任旧结果并在锁内重验。
- [ ] 相同 runtime ID 重试幂等，配置冲突返回稳定 error code。
- [ ] 同一 workspace 的第二个 project runtime 被拒绝。
- [ ] `session open` 可分别运行 Claude、Codex、Bash、cc-switch，project/temporary 作用域路径正确；Runtime 启动后修改 Provider 配置，新 Session 使用新值且契约输出不泄密。
- [ ] Ctrl+C、Ctrl+Z、EOF、resize、中文输入和大段粘贴经过完整 PTY 链路。
- [ ] `session terminate` 后容器内 Agent 进程与宿主子进程均不残留。
- [ ] PID identity 不匹配、重复 terminate 和快速 PID 复用测试不会误杀其他 Session/Runtime 进程。
- [ ] `runtime stop/restart/remove` 幂等，registry 与 Docker 状态一致。
- [ ] POSIX/Windows 的 registry 并发写不丢记录；两个进程并发 start 同一 workspace 时只有一个 project Runtime 成功。
- [ ] Workbench 从不直接写 registry，不调用 Docker API。
- [ ] Provider status 按 Agent 返回，所有输出不含密钥。
- [ ] `build --events` 增量输出有序、stdout 纯 JSONL，成功/失败/取消恰有一个 terminal event，取消不残留 Docker 子进程。
- [ ] Linux 与 Windows 实机通过端到端契约测试；macOS 至少完成 PTY/runtime smoke test。
