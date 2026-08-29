# Docker 资源生命周期阶段

## 目标

为 AISC 的安装、升级和卸载建立一致的 Docker 资源生命周期，解决以下问题：

- 卸载时遗留 AISC container 和 image；
- 安装时无法发现旧版本或孤立的 AISC image；
- 升级后仍使用旧 image，必须手工执行 `aisc build`；
- 不同平台安装器的清理行为不一致；
- 清理逻辑缺少资源归属边界，存在误删用户 Docker 资源的风险。

本阶段只处理 AISC 自有的 Docker container 和 image。默认不删除：

- 用户工作区；
- AISC 用户配置和 data-root；
- Docker named volume；
- Docker network；
- 非 AISC 资源；
- 用户显式指定的自定义 image，除非该 image 有明确的 AISC 归属证明。

## 文档

| 文件 | 内容 |
| --- | --- |
| [01-product-behavior.md](01-product-behavior.md) | 安装、升级、卸载的产品行为和用户可见结果 |
| [02-domain-contract.md](02-domain-contract.md) | 资源归属、检测、清理和重建契约 |
| [03-implementation-plan.md](03-implementation-plan.md) | 分阶段实现顺序、代码边界和兼容策略 |
| [04-acceptance.md](04-acceptance.md) | 自动化、安装器和真实 Docker 验收标准 |
| [05-cross-plan-coordination.md](05-cross-plan-coordination.md) | 与 Runtime 生命周期计划的共享基础、顺序和卸载边界 |

## 安装器范围

本阶段必须覆盖全部正式分发入口，不能只处理 CLI 安装器：

- **Tauri NSIS**：AISC Workbench 的 Windows 主安装器，当前已有 KI-4 Docker 清理勾选框；
- Windows Inno Setup：CLI setup.exe；
- Windows/Linux/macOS portable 脚本；
- macOS PKG。

Tauri NSIS 当前在模板中直接执行 `docker ps/rm/rmi`。阶段完成后必须改为调用同一个 lifecycle service；NSIS 不再维护独立的资源识别规则。

## 非目标

本阶段不实现以下能力：

- `docker system prune` 或全局 image/container 清理；
- 自动删除用户 workspace 或配置；
- 自动删除所有 AISC Docker volume；
- 自动重新执行用户在容器内执行过的 apt/npm/pip/cargo 安装命令；
- 为所有自定义 image 建立迁移系统；
- 修改 Workbench runtime 的正常关闭策略。Workbench 已有的 runtime cleanup 继续遵循其自身生命周期契约。

## 实施前置条件

实现代码前必须先确认本方案，尤其是：

1. 卸载默认清理 AISC container 和 image；
2. Docker daemon 不可用时，卸载仍删除应用文件，但报告 Docker 清理未完成；
3. 升级默认使用 `--no-cache` 重建默认 workstation image；
4. 未能证明归属的旧 image 只检测和报告，不静默删除；
5. 默认保留用户配置、workspace、data-root 和 Docker volume。

## 与 Runtime 生命周期阶段的关系

本阶段的共享 Docker ownership foundation 是
[`runtime-lifecycle-ux`](../runtime-lifecycle-ux/README.md) reconcile、toolchain
volume 和 image ID 对账的前置。两个阶段不允许分别定义一套 `io.aisc.*`
labels 或卸载清理规则。详细协调契约见
[`05-cross-plan-coordination.md`](05-cross-plan-coordination.md)。
