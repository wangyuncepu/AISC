# Stage 8 领域契约

## Build input

```text
CC_SWITCH_CHANNEL=stable
CC_SWITCH_VERSION=latest | vX.Y.Z
CC_SWITCH_RESOLVED_VERSION=vX.Y.Z       # resolver 输出，不由用户手写
CC_SWITCH_RELEASE_COMMIT=<sha>
CC_SWITCH_ASSET_SHA256=<sha256>
```

`latest` 在构建前解析为 `ResolvedRelease`，包含 tag、release id/commit、发布时间、目标 triple、下载 URL、SHA-256 和 resolver schema。Dockerfile 只接受解析结果或显式版本，不在镜像层内自行猜测 latest。

## Provider UI protocol

协议名：`aisc.cc-switch-provider/v1`。

```json
{"schema":"aisc.cc-switch-provider/v1","operation_id":"...","ok":true,
 "providers":[{"id":"deepseek","name":"DeepSeek","app_type":"claude",
 "base_url":"https://...","model":"...","has_api_key":true,
 "api_key_mask":"sk-****abcd","is_current":false}]}
```

命令：

```text
aisc cc-switch list --agent claude|codex --json
aisc cc-switch add --mode simple|custom --provider <id> --secret-stdin
aisc cc-switch edit <id> --patch-stdin --secret-stdin
aisc cc-switch delete <id> --confirm
```

实际 argv 不得承载 secret。`list` 永不返回完整 key；edit 不接受从 list 返回的 key 作为隐式值。

## Add modes

- `simple`：Provider 下拉值、API key、确认；base URL、默认模型和 wire API 来自受版本保护的 preset；
- `custom`：Provider/name、base URL、API key、模型、wire API 及 cc-switch 当前官方可选字段；未知字段按 schema 策略处理；
- 两者都调用同一个容器 writer 和校验器，返回新的 redacted snapshot。

## DeepSeek fixture and mapping

fixture 字段：`docs_source_url`、`retrieved_at`、`fixture_revision`、官方 endpoint/auth/model 字段、`one_million_context_suffix`。实现必须逐项核对官方文档中的 `base_url`、API key/auth 字段、模型字段，以及 Claude Code 使用的 `ANTHROPIC_BASE_URL`、认证变量和 `ANTHROPIC_MODEL`；不能为了兼容而额外发明字段或同时写入多个未被官方要求的变量。

预期会被验证的配置形状是：OpenAI-compatible provider 的 `base_url`、`api_key`、`model`，以及 Anthropic-compatible provider 的官方 base URL、官方认证变量和模型字符串。具体 URL（例如是否使用 `/anthropic`）和认证变量名称必须以本次 fixture 为准；现有 preset 中的 `deepseek-v4-pro`、默认 pro 选择和任何旧 endpoint 都视为待迁移数据，不能未经 fixture 证明继续保留。

逻辑映射：

| 输入 alias | 默认目标 |
|---|---|
| 未指定/default | 官方 DeepSeek flash model + `[1m]` |
| `opus` / `claude-opus-*` | 官方 DeepSeek pro model + `[1m]` |
| `sonnet`、`haiku`、其它 | 官方 DeepSeek flash model + `[1m]` |

“官方 DeepSeek flash/pro model”必须由实施时锁定的 `api-docs.deepseek.com/zh-cn/` fixture 提供具体 ID；不得把未经 fixture 证明的 ID 写死。`[1m]` 只能按官方文档规定附加在模型名称后。用户显式模型、alias mapping 或关闭 `[1m]` 的设置拥有最高优先级，并在 preset refresh 后保留。

## Database ownership

UI backend/adapter 和 CLI 共享 `CC_SWITCH_CONFIG_DIR/cc-switch.db`。所有写事务通过同一 adapter：schema check、进程锁、`BEGIN IMMEDIATE`、busy timeout、revision check、commit 后重新读取 snapshot。Workbench 不挂载或修改 SQLite 文件。
