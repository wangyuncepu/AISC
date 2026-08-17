# 阶段依赖与执行图

> 代码基线：`d2bdcd9`

## 串行主线

```text
Stage 0  基线与门禁
   │
   ▼
Stage 1  前端结构与高频数据面
   │
   ▼
Stage 2  Python CLI / GUI sidecar 双轨
   │
   ▼
Stage 3  Workspace Explorer / Agent Artifact
   │
   ▼
Stage 4  Python DockerGateway
   │
   ▼
Stage 5  Installer / 首次启动向导
   │
   ▼
Stage 6  UI / a11y / observability / release 收口
```

## 依赖理由

- Stage 1 必须在 Explorer/Artifact 前解决 `runtime.ts`、`App.vue` 和终端无界数据，否则新功能继续堆入单体协调器。
- Stage 2 先冻结 CLI/capability，Stage 3 才能安全增加 `aisc artifact`。
- Stage 3 先提供 workspace/readiness 能力，Stage 5 的 workspace onboarding 才不重复实现临时文件 UI。
- Stage 4 先稳定 Docker facts/errors，Stage 5 才能提供可靠的 Docker installed/starting/ready 引导。
- Stage 6 在所有新工作流落地后统一响应式、视觉和发布矩阵，避免重复调整组件。

## 分支与合并

```text
stage-0-baseline-gates
stage-1-frontend-data-plane
stage-2-cli-dual-track
stage-3-workspace-artifacts
stage-4-docker-gateway
stage-5-onboarding-installer
stage-6-ui-release-convergence
```

每个阶段从最新 `develop` 创建，阶段之间不并行。阶段完成后：用户确认 → `merge --no-ff` → push → 删除阶段分支。

## 阶段门

| 阶段 | 开始门 | 完成门 |
|---|---|---|
| 0 | 当前主线 CI 绿 | 基准可重复、契约 fixture 和门禁定义完成 |
| 1 | Stage 0 accepted | 资源有界、soak、a11y P0、结构拆分无行为回归 |
| 2 | Stage 1 accepted | pip/pipx + sidecar 三平台、兼容矩阵通过 |
| 3 | Stage 2 accepted | artifact/path/watcher/Explorer 安全与 E2E 通过 |
| 4 | Stage 3 accepted | SDK/CLI gateway 等价和 Docker 失败矩阵通过 |
| 5 | Stage 4 accepted | installer/onboarding fresh/upgrade/recovery 真机通过 |
| 6 | Stage 5 accepted | UI/a11y/diagnostics/迁移/三平台发布总门通过 |

## 允许的阶段内拆分

阶段过重时按其 `05-implementation-plan.md` 拆成 `Na/Nb/Nc`；每个子阶段都有独立验收、自动化和手测汇报。子阶段不能绕过阶段契约或提前合并未通过的后续步骤。
