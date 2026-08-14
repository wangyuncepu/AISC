# Stage 5 实施计划

1. `5a-state`: onboarding schema/reducer/checkpoint/i18n/route shell。
2. `5b-installer`: NSIS 边界、视觉/文案、handoff、upgrade/uninstall smoke。
3. `5c-environment`: CLI/WebView2/Docker installed/engine readiness、retry/doctor/skip。
4. `5d-workspace-agent`: Explorer 最近项/恢复，Agent readiness 与 guide。
5. `5e-network`: direct/host proxy/TUN 可选流程、探针、回滚。
6. `5f-runtime`: preflight、new/reuse/restart/restore、cancel/recovery。
7. `5g-convergence`: 完成/重开/迁移、全矩阵真机、视觉/a11y。

代码落点：`workbench/src/features/onboarding/`、独立 onboarding store、settings schema、runtime/provider integration、NSIS template/config/workflows/i18n。每子步骤独立 commit 和用户手测；不在 5b 配置 workspace/provider/runtime。