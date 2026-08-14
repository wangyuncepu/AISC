# Stage 5：Installer 与首次启动向导

> 状态：Accepted planning
> 基线：`d2bdcd9`
> 分支：`stage-5-onboarding-installer`

## 目标台账

| ID | 目标 | 验收 |
|---|---|---|
| INS-01 | NSIS 安装/升级/卸载/硬依赖边界 | A-INS01 |
| INS-02 | 安装器视觉、文案、状态和失败恢复 | A-INS02 |
| ONB-01 | onboarding schema/state/resume/skip | A-ONB01 |
| ONB-02 | Environment readiness，安装与 Engine ready 分离 | A-ONB02 |
| ONB-03 | Workspace 选择/最近项/恢复 | A-ONB03 |
| ONB-04 | Agent readiness 用户语义映射 | A-ONB04 |
| ONB-05 | 可选网络/TUN 引导和验证 | A-ONB05 |
| ONB-06 | Runtime new/reuse/restart/restore | A-ONB06 |
| ONB-07 | 完成、稍后继续和重开向导 | A-ONB07 |
| ONB-08 | installer→Workbench 非敏感 handoff | A-ONB08 |

## 固定边界

```text
NSIS：语言 → 安装位置 → 硬依赖 → 安装/升级 → 启动 Workbench
Workbench：欢迎 → 环境就绪 → 工作区 → Agent → 网络/TUN（可选） → Runtime → 完成
```

NSIS 不配置 Provider、workspace 或 Runtime；“安装完成”不等于 Docker Engine ready。