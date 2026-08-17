# Stage 8 决策

| ID | 决策 | 说明 |
|---|---|---|
| D8-01 | 默认 `stable/latest`，发布锁定精确版本和 SHA-256 | latest 解决开发摩擦，manifest 保证可复现 |
| D8-02 | resolver 在构建前执行，Dockerfile 消费解析结果 | 避免 Dockerfile 隐式联网和版本漂移 |
| D8-03 | UI tab 不运行桌面窗口 | 容器没有宿主显示环境，且用户明确要求不得独立窗口 |
| D8-04 | 优先官方 API/daemon，无 API 才受控 adapter | 绝不解析 TUI 或让 GUI 直写数据库 |
| D8-05 | UI/CLI 共用一个 SQLite 和写入 adapter | 保证 provider 事实一致、并发可控 |
| D8-06 | DeepSeek 具体模型 ID 来自官方 fixture | 官方文档变更时可审计、可更新，不固化猜测 |
| D8-07 | preset refresh 尊重 user-owned fields | 用户覆盖优先于默认 preset |
| D8-08（8a） | **Path B 受控 adapter**：无官方 HTTP/IPC API（实测）；写=官方非交互 CLI，读=容器内 adapter 只读 SQLite 快照；Workbench 永不直连 DB | 见 8a-discovery-report.md §2/§5 |
| D8-09（8a） | secret 一律经 `--config-file /dev/stdin`（argv 零 secret）；**cc-switch CLI 全部 stdout 视为含 secret 的不可信文本**，redaction 后才可进 UI/日志/诊断（add 实测明文回显 key） | A-CS07 的直接依据 |
| D8-10（8a） | `provider edit` 为 TUI-only → adapter 的 edit = 快照合并 + switch-away→delete→re-add（同 `--id`）；delete/switch 的 current 守卫由 adapter 舞步处理（换走目标须为有实际配置的 provider） | 非 tty prompt 失败实测 |
| D8-11（8a） | DeepSeek preset 以官方 Claude Code 接入页**逐字环境变量集**为准：MODEL/OPUS/SONNET→`deepseek-v4-pro[1m]`，HAIKU/SUBAGENT→`deepseek-v4-flash`，`ANTHROPIC_AUTH_TOKEN`+`CLAUDE_CODE_EFFORT_LEVEL=max`；`[1m]` 为官方语法。**supersede 规划的 flash-default alias 表** | D8-06（fixture 优先于假设）；`tests/fixtures/deepseek/official-api-facts.json` |
| D8-12（8a） | resolver 选**版本化资产名** + GitHub API `digest`（sha256）为权威校验；`dds`/`deepseek` 上游模板与 DeepSeek 官方无关（ddshub 三方中转），不用于 preset | 实测 dds→www.ddshub.cc |
