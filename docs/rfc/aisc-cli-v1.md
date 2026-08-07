# RFC: AISC CLI v1 机器消费协议

> **协议标识**：`aisc.cli/v1`
> **状态**：**S1 草案（draft）**—本版本用于契约讨论与特征测试录制。协议细节在 [S9](../plans/PLAN-p3-unified-cli.md#s9cli-机器协议稳定化p32) 之前可能发生兼容性变更；稳定化后本文档正式归档。**当前不声称 CLI 已实现或协议已冻结。**
>
> **动机**：为 CI/脚本/第三方调用提供可机器消费的稳定接口，不服务于 GUI（GUI 为远景规划，非实施目标）。
>
> **范围**：本文仅定义协议 schema 与语义。具体命令实现分属 S2–S8；S1 只产出本文档与特征测试 harness。

---

## 1. 输出格式

CLI 支持三种输出格式，由全局参数控制：

| 格式 | 参数 | stdout | stderr | 用途 |
|------|------|--------|--------|------|
| `text` | `--format text`（默认） | 人类可读输出 | 诊断/日志/错误 | 交互使用 |
| `json` | `--format json` | JSON envelope | 诊断/日志/错误描述 | 脚本/CI 单次查询 |
| `jsonl` | `--events` | JSONL event 行 | Docker 原始日志、诊断 | 长命令（build/run）事件流 |

**关键规则**：

1. **stdout / stderr 严格隔离**：结构化数据只走 stdout；日志、诊断、错误描述只走 stderr。消费者可独立捕获。
2. **`--format json` 与 `--events` 互斥**：同时指定为 usage error（`AISC_EXIT_USAGE`）。
3. **`--format json` 下 stdout 只输出一条完整的 JSON 对象**（单行或 pretty-print）。
4. **`--events` 下 stdout 每行一个完整的 JSON 对象**（JSONL）。

---

## 2. JSON Envelope（`--format json`）

### 2.1 结构

适用于所有支持 `--format json` 的命令（`version`、`doctor`、`build`、`run`、`config validate`、`config effective`、`profile list`、`profile show`、`provider list`、`provider show`）。对于长命令（`build`、`run`），JSON envelope 返回单次结果摘要；Docker 原始日志走 stderr。失败时 `data` 保留完整字段（`build` 含 `image_tag,docker_exit_code`；`run` 含 `image,container_exit_code`）而非 null。

```jsonc
{
  "meta": {
    "protocol": "aisc.cli/v1",            // string，固定值
    "command": "doctor",                   // string，执行的子命令名
    "exit_code": 0,                        // number，与进程退出码一致
    "timestamp": "2026-07-17T12:00:00Z",  // string，ISO 8601 UTC
    "version": "3.0.0",                   // string，CLI 产品版本
    "run_id": "550e8400-e29b-41d4-a716-446655440000"  // string，UUID v4（便于与 event stream 关联）
  },
  "data": { /* 命令特定 payload */ },
  "errors": []                             // array，空表示成功
}
```

### 2.2 字段类型与约束

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `meta.protocol` | `string` | ✅ | 固定值 `"aisc.cli/v1"` |
| `meta.command` | `string` | ✅ | 执行的子命令名（如 `"doctor"`） |
| `meta.exit_code` | `number` (int) | ✅ | 必须与进程退出码一致 |
| `meta.timestamp` | `string` (ISO 8601) | ✅ | UTC 时间戳 |
| `meta.version` | `string` (semver) | ✅ | CLI 产品版本 |
| `meta.run_id` | `string` (UUID) | ✅ | 本次调用的唯一标识 |
| `data` | `object` 或 `null` | ✅ | 命令特定 payload；成功时包含业务数据，失败可为 `null` |
| `errors` | `array` | ✅ | 错误列表；成功时为空数组 `[]` |

### 2.3 Error 对象

```jsonc
{
  "code": "AISC_ERR_DOCKER_UNAVAILABLE",  // string，稳定错误码
  "message": "Docker daemon is not running. Start Docker and retry.",
  "hint": "systemctl start docker"        // string|null，修复建议
}
```

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `code` | `string` | ✅ | `AISC_ERR_*` 稳定符号（见 §4） |
| `message` | `string` | ✅ | 人类可读错误描述 |
| `hint` | `string` 或 `null` | ✅ | 可能的修复命令或建议；无可为 `null` |

### 2.4 成功示例

```json
{
  "meta": {
    "protocol": "aisc.cli/v1",
    "command": "version",
    "exit_code": 0,
    "timestamp": "2026-07-17T12:00:00Z",
    "version": "3.0.0",
    "run_id": "550e8400-e29b-41d4-a716-446655440000"
  },
  "data": {
    "cli_version": "3.0.0",
    "bundle_version": "3.0.0",
    "contract_version": "1",
    "image_version": "3.0.0",
    "claude_version": "1.0.37",
    "python_version": "3.11.10"
  },
  "errors": []
}
```

### 2.5 错误示例

```json
{
  "meta": {
    "protocol": "aisc.cli/v1",
    "command": "build",
    "exit_code": 3,
    "timestamp": "2026-07-17T12:00:00Z",
    "version": "3.0.0",
    "run_id": "550e8400-e29b-41d4-a716-446655440000"
  },
  "data": null,
  "errors": [
    {
      "code": "AISC_ERR_DOCKER_UNAVAILABLE",
      "message": "Docker daemon is not running. Start Docker and retry.",
      "hint": "systemctl start docker"
    }
  ]
}
```

### 2.6 密钥脱敏

API key / token 等密钥**绝不**以明文形式出现在 `data` 或 `errors` 的任何字段中。

脱敏策略：
- 完整 key 替换为 `****<last4>`（如 `****Ab3F`）。
- 仅当无法确定 last4 时替换为 `****`。
- 空 key / 缺失 key 不输出占位符，直接省略或 `null`。

---

## 3. JSONL Event Stream（`--events`）

### 3.1 结构

适用于长命令（`build`、`run`）。每行一个完整 JSON 对象，**每个 event 必须包含以下字段**：

```jsonl
{"protocol":"aisc.cli/v1","command":"build","run_id":"550e8400-e29b-41d4-a716-446655440000","seq":1,"type":"build.step.start","ts":"2026-07-17T12:00:01Z","data":{"step":"pull_base_image"}}
```

### 3.2 必填字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `protocol` | `string` | 固定值 `"aisc.cli/v1"` |
| `command` | `string` | 执行命令名（同一 stream 內不变） |
| `run_id` | `string` (UUID) | 本次调用唯一标识（同一 stream 內不变） |
| `seq` | `number` (int) | 单调递增序号，从 `1` 开始 |
| `type` | `string` | 事件类型：`<command>.<phase>[.<subtype>]` |
| `ts` | `string` (ISO 8601) | UTC 时间戳 |
| `data` | `object` | 事件特定 payload |

### 3.3 属性约束

1. **`seq` 单调递增**：同一次 `run_id` 内每个事件的 `seq` 必须严格递增（+1），不得重复或回退。
2. **`command` 不变**：同一次 stream 内所有事件的 `command` 字段值相同。
3. **`run_id` 不变**：同一次 stream 内所有事件的 `run_id` 字段值相同。
4. **`type` 命名空间**：`<command>.<phase>[.<subtype>]`，例如：
   - `build.step.start`
   - `build.step.complete`
   - `build.complete`
   - `run.container.start`
   - `run.container.complete`

### 3.4 强制终止事件

**每个 JSONL stream 必须以唯一一个终止事件结束**。合法终止 `type`：

| type | 含义 | `data.exit_code` |
|------|------|-------------------|
| `<command>.complete` | 命令成功完成 | `0` |
| `<command>.failed` | 命令执行失败 | 非零，与进程退出码一致 |
| `<command>.cancelled` | 被外部信号中断 (SIGINT/SIGTERM) | 非零（通常 `130` 或 `143`） |

终止事件后不得有任何后续 event 行。**`data.exit_code` 必须与进程退出码一致**。

### 3.5 完整 stream 示例

```jsonl
{"protocol":"aisc.cli/v1","command":"build","run_id":"550e8400-e29b-41d4-a716-446655440000","seq":1,"type":"build.start","ts":"2026-07-17T12:00:00Z","data":{"image_name":"aisc:3.0.0"}}
{"protocol":"aisc.cli/v1","command":"build","run_id":"550e8400-e29b-41d4-a716-446655440000","seq":2,"type":"build.step.start","ts":"2026-07-17T12:00:01Z","data":{"step":"pull_base_image"}}
{"protocol":"aisc.cli/v1","command":"build","run_id":"550e8400-e29b-41d4-a716-446655440000","seq":3,"type":"build.step.complete","ts":"2026-07-17T12:00:45Z","data":{"step":"pull_base_image","status":"ok","digest":"sha256:abc123..."}}
{"protocol":"aisc.cli/v1","command":"build","run_id":"550e8400-e29b-41d4-a716-446655440000","seq":4,"type":"build.step.start","ts":"2026-07-17T12:00:45Z","data":{"step":"build_context"}}
{"protocol":"aisc.cli/v1","command":"build","run_id":"550e8400-e29b-41d4-a716-446655440000","seq":5,"type":"build.step.complete","ts":"2026-07-17T12:04:00Z","data":{"step":"build_context","status":"ok"}}
{"protocol":"aisc.cli/v1","command":"build","run_id":"550e8400-e29b-41d4-a716-446655440000","seq":6,"type":"build.complete","ts":"2026-07-17T12:04:01Z","data":{"image_tag":"aisc:3.0.0","exit_code":0}}
```

### 3.6 Docker 原始输出

Docker build/run 的原始日志（build log、container stdout/stderr）**不裸输出到 stdout JSONL 行外**。处理方式：
- 编码为 `data.raw` event（`type` 包含 `.raw` 后缀）。
- 或转发到 stderr。

### 3.7 密钥脱敏

event stream 中不得出现明文密钥。脱敏规则同 §2.6。

---

## 4. 退出码与错误码

### 4.1 进程退出码（`AISC_EXIT_*`）

进程退出码与 JSON envelope 的 `meta.exit_code` 及 JSONL 终止事件的 `data.exit_code` 保持一致。

| 数值 | 常量名 | JSON `errors[].code` | 含义 |
|------|--------|----------------------|------|
| `0` | `AISC_EXIT_OK` | —（成功） | 命令成功完成 |
| `1` | `AISC_EXIT_GENERAL` | `AISC_ERR_GENERAL` | 未分类的通用错误 |
| `2` | `AISC_EXIT_USAGE` | `AISC_ERR_USAGE` | 命令行参数错误（如 `--format json --events` 同时指定） |
| `3` | `AISC_EXIT_DOCKER_UNAVAILABLE` | `AISC_ERR_DOCKER_UNAVAILABLE` | Docker CLI 或 daemon 不可用 |
| `4` | `AISC_EXIT_BUILD_FAILED` | `AISC_ERR_BUILD_FAILED` | 镜像构建失败（docker build 非零退出） |
| `5` | `AISC_EXIT_IMAGE_NOT_FOUND` | `AISC_ERR_IMAGE_NOT_FOUND` | 指定镜像不存在（需先 build） |
| `6` | `AISC_EXIT_CONFIG_INVALID` | `AISC_ERR_CONFIG_INVALID` | 配置文件格式/Schema 校验失败 |
| `7` | `AISC_EXIT_CONFIG_MISSING` | `AISC_ERR_CONFIG_MISSING` | 缺少必要配置（非交互模式；stderr 附带修复命令） |
| `8` | `AISC_EXIT_NETWORK_REQUIRED` | `AISC_ERR_NETWORK_REQUIRED` | 网络不可达但操作需要网络 |
| `9` | `AISC_EXIT_PERMISSION_DENIED` | `AISC_ERR_PERMISSION_DENIED` | 文件/目录权限不足 |
| `10` | `AISC_EXIT_CONTAINER_FAILED` | `AISC_ERR_CONTAINER_FAILED` | 容器启动后异常退出 |
| `11` | `AISC_EXIT_NEEDS_CONFIRMATION` | `AISC_ERR_NEEDS_CONFIRMATION` | 需用户确认（unsafe profile 未确认 / 其他需确认的操作） |
| `12` | `AISC_EXIT_CONTRACT_MISMATCH` | `AISC_ERR_CONTRACT_MISMATCH` | 容器 contract version 或 capability label 不兼容 |
| `13` | `AISC_EXIT_PROXY_FAILED` | `AISC_ERR_PROXY_FAILED` | `--network proxy` 显式请求但 TUN/preflight 失败 |
| `14` | `AISC_EXIT_RUNTIME_CONFLICT` | `AISC_ERR_RUNTIME_CONFLICT` | Runtime 配置冲突（preflight 检测到不兼容运行时） |
| `15` | `AISC_EXIT_INVALID_RUNTIME_ID` | `AISC_ERR_INVALID_RUNTIME_ID` | Runtime ID 格式无效（非 UUID v4） |
| `16` | `AISC_EXIT_RUNTIME_OPERATION_FAILED` | `AISC_ERR_RUNTIME_OPERATION_FAILED` | Runtime 操作失败（启动/停止/移除等） |
| `17` | `AISC_EXIT_STATE_LOCK_TIMEOUT` | `AISC_ERR_STATE_LOCK_TIMEOUT` | 跨进程 registry/workspace 锁获取超时（并发冲突无法在超时内解决） |
| `18` | `AISC_EXIT_SESSION_NOT_FOUND` | `AISC_ERR_SESSION_NOT_FOUND` | Session 元数据不存在（S0.3） |
| `19` | `AISC_EXIT_SESSION_FAILED` | `AISC_ERR_SESSION_FAILED` | session exec/wrapper 启动失败（S0.3） |
| `20` | `AISC_EXIT_RUNTIME_NOT_RUNNING` | `AISC_ERR_RUNTIME_NOT_RUNNING` | session/provider 要求的 runtime 未运行（S0.3） |
| `21` | `AISC_EXIT_PROVIDER_STATUS_FAILED` | `AISC_ERR_PROVIDER_STATUS_FAILED` | provider 状态检查 exec/解析失败（S0.4） |

> 注：`AISC_EXIT_NEEDS_CONFIRMATION(11)` 合并了原拟议的 `EX_PROFILE_REQUIRES_CONFIRM(11)` 和 `EX_NEEDS_CONFIRMATION(12)`。S1 草案统一使用表内的 `AISC_ERR_NEEDS_CONFIRMATION`；如未来需要增加更细的原因码，须先在 RFC 中登记后才能视为稳定符号。
>
> **退出码 14-16** 为 S0.2 Workbench Phase 0 引入，用于 `aisc runtime` 子命令族。`AISC_EXIT_RUNTIME_CONFLICT(14)` 用于 preflight 检测到配置冲突时的快速失败；`AISC_EXIT_INVALID_RUNTIME_ID(15)` 用于拒绝非 UUID v4 格式的 runtime ID；`AISC_EXIT_RUNTIME_OPERATION_FAILED(16)` 用于 runtime 生命周期操作的一般性失败（不属于其他更具体的错误类别）。**退出码 17** `AISC_EXIT_STATE_LOCK_TIMEOUT` 用于跨进程锁（registry `.containers.lock` 或 workspace lock）超时，映射为 `CliError` 而非原始 `TimeoutError`。
>
> **退出码 18-20** 为 S0.3 Workbench Phase 0 引入，用于 `aisc session` 子命令族（`SESSION_NOT_FOUND(18)`/`SESSION_FAILED(19)`），以及 session/provider 共用的 `RUNTIME_NOT_RUNNING(20)`。**退出码 21** `AISC_EXIT_PROVIDER_STATUS_FAILED` 为 S0.4 引入，用于 `aisc provider current` 的 exec/解析失败。

### 4.2 错误码稳定性

所有 `AISC_ERR_*` 字符串为稳定符号，**不会在 minor/patch 版本中变更或重编号**。新增退出码只在 minor 版本引入且仅分配新数值（≥22），不重用已定义值。

`AISC_EXIT_*` 数值 0–21 如表中定义；数值 22+ 为预留空间，当前未分配。客户端不得假设数值连续——应仅依赖表中列出的已知值，未识别值视为 `AISC_EXIT_GENERAL`。

> **退出码与错误码的多对一关系**：上表为退出码到「主要」`AISC_ERR_*` code 的映射，但一个退出码可承载多个细分 code（例如 exit 2 `USAGE` 也承载 `AISC_ERR_SCOPE_INVALID`/`NETWORK_INVALID`/`WORKSPACE_INVALID`/`INVALID_AGENT`/`INVALID_SESSION_ID` 等校验错误）。机器消费者必须按 JSON envelope 的 `errors[].code` 路由，不依赖退出码到 code 的一一映射，也不对 `message` 做字符串匹配。完整 code 清单见 `docs/gui-planning/05-cli-gui-contract.md` §八。

---

## 5. 交互与确认控制

### 5.1 Non-Interactive 模式

`--non-interactive` 标志下：

1. CLI **不读取 stdin**。任何需要用户输入的路径必须在缺少必要信息时快速失败。
2. 缺少必要配置（如 provider 密钥）→ 非零 exit + 明确修复命令到 stderr。
3. **不等于 unsafe profile**——`safe` 是默认 profile。

### 5.2 确认门（Confirmation Gate）

| 场景 | 交互模式 | `--non-interactive` |
|------|----------|---------------------|
| `--profile unsafe` | 显示安全警告 + `y/N` | 必须同时提供 `--accept-unsafe-risk`，否则 exit `AISC_EXIT_NEEDS_CONFIRMATION(11)` |
| `--yes` 的使用 | 可跳过非安全确认（如"已有镜像，是否重建？"） | 同交互模式 |
| `--yes` **不能批准 unsafe** | — | — |

### 5.3 交互提示输出

所有交互式 prompt 写入 **stderr**（非 stdout），确保 stdout 重定向时消费者不被阻塞。

---

## 6. 兼容性与演进规则

### 6.1 协议版本

`meta.protocol` 固定为 `"aisc.cli/v1"`。未来不兼容的协议升级（v2+）时将：

1. 新协议使用新的 `meta.protocol` 值（如 `"aisc.cli/v2"`）。
2. v1 协议在至少一个 major CLI 版本中保持可用（通过 `--protocol-version v1` flag）。
3. 废弃（deprecation）至少提前一个 minor 版本在 stderr 公告。

### 6.2 向后兼容保证（v1 范围内）

- 现有字段的**键名**不变。
- 现有字段的**语义**不变。
- **新增可选字段**允许（消费者应忽略未知字段）。
- **不再移除**标记为必需（✅）的字段。
- **不再更改**现有 `AISC_ERR_*` 字符串的值。

### 6.3 Legacy 兼容期

兼容期内：
- 无 contract label 的旧镜像仅在同时提供 `--allow-legacy-image --accept-unsafe-risk` 时放行。
- **safe profile 绝不降级**接受无 capability label 的镜像。
- `--allow-legacy-image` 有截止版本（S11 后移除）。

### 6.4 Container Contract

镜像通过 Docker LABEL 声明兼容版本与能力：

```dockerfile
LABEL aisc.contract.version="1"
LABEL aisc.supports.safe="1"
LABEL aisc.supports.proxy="1"
LABEL aisc.supports.non-interactive="1"
```

CLI 按请求检查 capability label。缺失 label 且非 legacy-compatible → `AISC_EXIT_CONTRACT_MISMATCH`。

---

## 7. S1 可测试的 Schema Sample

以下 schema sample 用于 S1 特征测试 harness，与 S2+ 实际命令实现**明确区分**：

### 7.1 JSON Envelope Schema（测试用）

S1 的 `tests/harness/test_runner.py` 可验证以下最小契约：

- `--format json` 下 stdout 为合法 JSON。
- `meta` 对象包含 `protocol`、`command`、`exit_code`、`timestamp`、`version`、`run_id`。
- `meta.exit_code` 与 `subprocess.returncode` 一致。
- `errors` 为数组。
- 成功时 `errors` 为空数组，`meta.exit_code == 0`。
- 失败时 `errors` 至少一项，每项含 `code`、`message`、`hint`。

### 7.2 JSONL Event Schema（测试用）

- `--events` 下 stdout 每行为合法 JSON。
- 每行包含 `protocol`、`command`、`run_id`、`seq`、`type`、`ts`、`data`。
- `seq` 在不同行间严格递增。
- `command` 和 `run_id` 在所有行间一致。
- stream 的最后一行 `type` 为 `*.complete`、`*.failed` 或 `*.cancelled`。
- 终止行 `data.exit_code` 与进程退出码一致。

### 7.3 S2+ 命令的 schema 约定（非 S1 交付物）

以下仅为文档化约定，具体 data 结构在对应切片实现时定义：

| 命令 | `data` 结构方向 |
|------|----------------|
| `version` | `cli_version`, `bundle_version`, `contract_version`, `image_version`, `claude_version`, `python_version` |
| `doctor` | `host` + `container` 诊断结果（check items 列表） |
| `config validate` | `valid` (bool) + `issues` 列表 |
| `config effective` | 脱敏合并配置对象 |
| `profile list` | `profiles` 数组 |
| `profile show` | 单个 profile 详情 |
| `provider list` | `providers` 数组 |
| `provider show` | 单个 provider 详情（脱敏） |
| `build` | `image_tag`, `dry_run`, `executed`, `docker_argv`, `docker_exit_code`(nullable) | 构建结果；`docker_exit_code` 保留 Docker 原始退出码（成功 0，失败保留原码如 37）；AISC 进程退出码映射为 4（`AISC_EXIT_BUILD_FAILED`） |
| `run` | `image`, `container_id`(nullable), `dry_run`, `executed`, `docker_argv`, `container_exit_code`(nullable) | 运行结果；`container_exit_code` 保留容器原始退出码；AISC 进程退出码映射为 10（`AISC_EXIT_CONTAINER_FAILED`） |

> **退出码映射规则**：对于 `build`/`run`，进程退出码不与 Docker/容器退出码直接透传。`docker build` 非零 → AISC exit 4（`AISC_EXIT_BUILD_FAILED`），data.docker_exit_code 保留原码；`docker run` 非零 → AISC exit 10（`AISC_EXIT_CONTAINER_FAILED`），data.container_exit_code 保留原码。14-125 为业务预留，128+ 表示信号终止（如 SIGINT 130）。`--dry-run` 不调用 Docker，data.executed=false。

**JSONL event `type` 命名空间约定**（S3+ 实现）：

| 命令 | 事件类型前缀 |
|------|-------------|
| `build` | `build.start`, `build.step.*`, `build.complete`, `build.failed` |
| `run` | `run.start`, `run.container.*`, `run.complete`, `run.failed`, `run.cancelled` |

---

## 8. 参考资料

- [PLAN-p3-unified-cli.md](../plans/PLAN-p3-unified-cli.md) — P3 统一 CLI 计划
- [ADR 001: Python stdlib CLI](../adr/001-python-stdlib-cli.md) — 运行时选型决策
- [S1 切片说明](../plans/PLAN-p3-unified-cli.md#s1契约与特征测试p31) — 契约与特征测试范围
- [S9 切片说明](../plans/PLAN-p3-unified-cli.md#s9cli-机器协议稳定化p32) — 协议正式稳定化

---

## 附录 A：与 GUI 的关系

GUI 是远景规划，非 P3 实施目标。CLI 协议仅为 CI/脚本/第三方调用而稳定化，不服务于 GUI 集成。P3 不产生任何 GUI 相关任务、依赖、DoD、时间表或框架选择。
