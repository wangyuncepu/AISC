# 跨阶段契约

> 代码基线：`d2bdcd9`

## 1. 进程与所有权

| 层 | 所有权 |
|---|---|
| Vue/Pinia | 用户交互、视图投影、短期 UI 状态；不持有 Docker/文件事实 |
| Rust/Tauri | app/window、SessionRegistry、PTY、IPC、宿主路径安全、原子持久化、watcher |
| Python CLI/application | Runtime、Session 业务、Provider、DockerGateway、Artifact CLI 事实写入 |
| Docker/container | Runtime 执行环境、Agent 和 cc-switch；不拥有宿主 GUI 状态 |

## 2. CLI 与 IPC

- 公共 CLI 协议命名为 `aisc.cli/v1`；JSON envelope 和 JSONL events 必须版本化。
- Workbench 只依赖 capability 和结构化输出，不解析用户文本输出。
- pip CLI 与 sidecar 的同名命令必须保持参数、退出码、错误码和 envelope 等价。
- sidecar discovery 保持 `explicit > saved pin > bundled sidecar > PATH > platform discovery`。
- Rust 对 CLI 负责 spawn/cancel/timeout/size limit/decode/error mapping，不复制领域规则。

## 3. Workspace 与路径

- Rust 是 GUI 侧 canonical workspace 唯一生产者。
- Agent/CLI 只传 workspace-relative path；拒绝绝对路径、`..`、越界 symlink/junction。
- open/reveal/copy absolute path 只能在 Rust containment 校验后执行。
- Explorer 只扫描当前 workspace，禁止全盘索引；大目录必须 lazy + bounded。

## 4. Agent Artifact

- 事实协议：`aisc.artifact/v1`。
- Artifact Skill 负责分类、标题、说明和推荐打开方式；不作为数据库。
- watcher 只发 invalidation/change/overflow，不声明 Agent provenance。
- authoritative precedence：显式 artifact record/index > watcher 未归因变化。
- Agent Artifact 与发行包 artifact 使用完整名称区分；代码命名不得复用同一 schema。
- Artifact index 不放在 Git workspace；按 workspace/session 隔离，具备 revision/lock/atomic replace。

## 5. DockerGateway

- Gateway 是 Python adapter；application/domain 不依赖具体 `sdk|cli` backend。
- Rust/GUI 不直接调用 Docker Engine。
- SDK 与 CLI backend 返回相同业务结果、稳定错误码和清理语义。
- `shell=True` 永久禁止；CLI backend 保持 argv-only。
- Docker Build 在 benchmark 和兼容矩阵通过前保持 CLI/BuildKit 路径。

## 6. 高频数据面

- PTY 输出、Build log、artifact/watcher queue 必须有 per-resource 和 global budget。
- 高频字节流不得逐 chunk 进入深响应式状态。
- overflow/truncation 必须可观察，不得静默丢数据后仍标记完整。
- 隐藏窗口/Tab 可暂停渲染，但不得阻塞 reader 或导致 child deadlock。

## 7. 状态与错误

统一 operation/error 语义：

```text
operation_id, source, phase, duration_ms, outcome,
stable_error_code, retryable, action, technical_detail(redacted)
```

- snapshot 是事实；operation failure 是错误，两者不能互相覆盖。
- `never-known`、`fresh`、`stale`、`unavailable` 必须区分。
- UI 显示用户动作，技术详情默认折叠。

## 8. 持久化

所有 settings/history/artifact/onboarding schema 均要求：

- schema version；
- unknown-field round-trip；
- unsupported-version fail closed；
- expected revision/conflict；
- cross-process lock；
- atomic replacement and recovery；
- corrupt isolation；
- migration + rollback fixture。

## 9. 安装与首次引导

- NSIS 的“安装成功”不代表 Docker Engine ready。
- installer handoff 只传语言、来源和非敏感依赖事实。
- onboarding 可中断、恢复、跳过和从设置重开。
- 网络/TUN 是可选建议；不得未经明确同意改写宿主代理或网络配置。

## 10. 安全与隐私

禁止持久化或导出：API key、OAuth、cookie、prompt、terminal scrollback、完整环境变量。日志和诊断包统一 redaction；诊断包导出前展示清单。
