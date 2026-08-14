# AISC Next Planning

> 状态：Active planning
> 代码基线：`d2bdcd9`（completed plans archive）
> 规划日期：2026-08-14
> 规范前身：`docs/archive/completed/gui-fine-tune-planning/`

## 目标

为 AISC 下一轮演进建立可分阶段执行的规划入口，覆盖：

1. 性能与可靠性底座；
2. Python CLI 独立 pip 发布与 GUI sidecar 双轨；
3. Workspace Explorer 与 Agent Artifact Contract；
4. Python DockerGateway 渐进 SDK 化；
5. 轻量安装器与可恢复首次启动向导；
6. UI、无障碍、可观测性和发布门禁收口。

## 已接受决策

- Python CLI 是独立产品；不进行 Rust 全量重写。
- GUI 不直接操作 Docker、registry 或 Provider 配置；控制面继续经结构化 `aisc` CLI。
- Rust 负责桌面生命周期、PTY/pipe 数据面、IPC、本地文件安全和持久化。
- Artifact Skill 只提供语义约束；`aisc.artifact/v1` 才是事实协议；watcher 只提供变化兜底。
- DockerGateway 属于 Python 内部基础设施；SDK/CLI backend 以等价契约逐步替换。
- NSIS 只做安装和硬依赖引导；复杂首次使用流程属于 Tauri Workbench。

## 阶段目录

| 阶段 | 目录 | 目标 | 前置 |
|---|---|---|---|
| 0 | `stage-0-baseline-gates/` | 基线、契约、性能和质量门禁 | 无 |
| 1 | `stage-1-frontend-data-plane/` | 终端数据面、前端结构、a11y P0 | Stage 0 |
| 2 | `stage-2-cli-dual-track/` | pip CLI、sidecar、JSON/capability 契约 | Stage 0/1 |
| 3 | `stage-3-workspace-artifacts/` | Artifact Contract、Explorer、路径安全 | Stage 2 |
| 4 | `stage-4-docker-gateway/` | Python DockerGateway 渐进 SDK 化 | Stage 2 |
| 5 | `stage-5-onboarding-installer/` | NSIS + Tauri 首次启动向导 | Stage 3/4 |
| 6 | `stage-6-ui-release-convergence/` | UI、可访问性、诊断、发布收口 | Stage 5 |

阶段严格串行。阶段内可拆子步骤，但不得跨阶段并行修改同一状态链。

## 全局不变量

1. CLI、GUI sidecar 和容器内 CLI 共享 `aisc.cli/v1` 行为面。
2. Runtime、Session、Provider、Docker 策略仍由 Python application/domain 所有。
3. Rust 不接管 Python CLI/Docker/Agent 业务。
4. Agent 只提交 workspace-relative path；宿主绝对路径由 Rust/Workbench 解析。
5. Skill 不等于 Artifact 事实；watcher 不得伪造 authoritative provenance。
6. 不把 token、API key、OAuth、prompt、PTY scrollback 写入 history、artifact index 或诊断包。
7. 所有 schema/protocol 都必须声明版本，并定义未知版本、迁移、回滚、损坏行为。
8. 所有 child、PTY、timer、listener、channel、watcher、lock 都必须有清理或有界策略。
9. 事实状态与操作错误分离；失败不能用伪造缓存覆盖最新事实。
10. 每阶段都必须有自动化测试、适用平台手测、证据记录和用户确认。

## 非目标

- 不用 Rust 重写 Python CLI、Docker、Runtime、Provider 或 Agent 业务。
- 不引入 GUI 直连 Docker。
- 不把发行包 `packaging/artifact.py` 与 Agent Artifact 混用。
- 不首期交付完整 IDE、编辑器、Git UI、调试器或全盘文件索引。
- 不在没有 benchmark 证据时引入常驻 daemon 或迁移 Docker Build。
- 不把所有文件系统变化或 Git diff 自动标记为 Agent 交付物。

## 通用阶段规约

每个阶段目录必须包含：

```text
00-overview.md
01-risk-analysis.md
02-domain-contract.md
03-ux-flow.md
04-observability-testing.md
05-implementation-plan.md
acceptance.md
decisions.md
```

每个最小单元独立提交，提交信息包含：

```text
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

阶段完成条件：

- 本地相关测试全绿；
- CI 门禁全绿；
- 适用平台手测 PASS；
- `acceptance.md` 有完整证据；
- devlog 更新；
- 用户确认后以 `--no-ff` 合并 `develop` 并推送。

## SSOT 优先级

1. 本目录 `00-overview.md` 的范围、术语、阶段依赖和全局不变量；
2. `01-cross-stage-contracts.md` 的跨阶段协议；
3. 各阶段 `02-domain-contract.md` 的阶段内细节；
4. 各阶段 `05-implementation-plan.md` 的执行顺序；
5. `decisions.md` 仅记录已接受决定及理由，不覆盖契约。

## 验收证据格式

```text
目标/验收 ID：
Commit：
OS/arch：
Workbench/CLI/Docker 版本：
前置条件：
步骤：
期望：
结果：
耗时 p50/p95/max（适用时）：
截图/日志/测试名：
结论：PASS | FAIL
```
