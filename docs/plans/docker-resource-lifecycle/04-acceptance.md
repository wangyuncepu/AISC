# 验收标准

## 1. 核心单元测试

- `pytest tests/test_docker_lifecycle.py`
- `pytest tests/test_docker_gateway_contract.py`
- `pytest tests/features/test_runtime_compat.py`

具体验收：

- owned container 被删除；
- owned image 被删除；
- legacy owned container 按兼容规则被删除；
- unverified image/container 被保留并进入 `skipped_unverified`；
- running container 使用 force remove；
- image 有多个 tag 时只删除 AISC tag；存在非 AISC tag 时保留 image ID；
- Docker unavailable 返回正确退出码；
- 一个删除失败不会阻止其他资源处理；
- 结果 JSON 不包含 secret。

## 2. CLI 契约

验证：

```text
aisc maintenance docker-scan --format json
aisc maintenance docker-cleanup --format json
aisc maintenance docker-rebuild --help
```

要求：

- JSON envelope 可解析；
- stdout 没有 Docker build 噪声；
- 命令可在 frozen bundle 中运行；
- 命令从任意当前目录执行都不依赖 cwd；
- 重复 cleanup 是幂等的。

## 3. Windows Tauri NSIS

自动化与模板验收：

- KI-4 Docker checkbox 调用 lifecycle sidecar，不直接执行 container/image
  过滤和删除；
- lifecycle 调用发生在 external binary 和 `aisc-bundle` 删除前；
- container/image cleanup 默认选中，`/KEEPDOCKER` 可关闭；
- `/UPDATE` 不触发卸载式清理，但新版本安装完成后执行 rebuild；
- app-data、container/image、toolchain volume 是独立选项；
- toolchain volume 默认保留；
- silent/passive 模式有确定的非交互默认值和日志结果；
- Docker 不可达时卸载成功，结果为 skipped 而不是 cleaned。

真实 NSIS smoke 顺序：

1. 准备 AISC image、AISC container 和一个无关 image/container；
2. 使用 Tauri NSIS 首次安装；
3. 验证扫描结果；
4. 升级安装；
5. 验证旧 AISC container 已删除；
6. 验证新 `super-claude:latest` image 的 ID 已变化；
7. 验证无关资源仍存在；
8. 创建用户配置 marker；
9. 卸载；
10. 验证 AISC container/image 已清理；
11. 验证配置 marker、workspace、PATH sentinel 保留；
12. 关闭 Docker daemon 后重复卸载，确认应用文件仍被删除且日志有 warning。

## 4. Windows Inno Setup

重复执行上一节的核心资源保留矩阵，另验证：

- PATH 精确删除逻辑不回归；
- setup.exe 覆盖升级调用同一 lifecycle JSON 契约；
- Inno 与 NSIS 对同一 fake/real Docker fixture 产生等价分类结果。

## 5. Linux portable

验证：

- 首次 install 只 scan/清理可确认孤立资源，不自动 build；
- upgrade 执行 cleanup -> replace -> no-cache rebuild；
- uninstall 清理 container/image；
- `--keep-docker-resources` 保留 Docker 资源；
- Docker CLI 不存在时 install/uninstall 仍能完成文件操作；
- 包含空格的安装路径和 bundle 路径可用；
- cleanup helper 返回非零时脚本不误报“已清理”。

## 6. macOS PKG

在 Apple Silicon macOS 上验证：

- 首次安装；
- 覆盖升级；
- 升级后 image ID 发生变化；
- `sudo /usr/local/lib/aisc/uninstall.sh` 清理 AISC 资源；
- pkg receipt、symlink 和安装目录处理不回归；
- `~/.aisc`、workspace、volume 保留；
- alternate target 的 preinstall 不触碰目标卷之外的 Docker 或宿主文件；
- Docker 不可用时仍能卸载文件。

## 7. 跨计划验收

- Runtime、one-shot container 和 toolchain volume 使用同一组
  `io.aisc.*` 常量；
- Python/Rust fixture 对 label key/value 完全一致；
- rebuild 返回 old/new image ID，Runtime reconcile 能据此分类旧
  ephemeral Runtime；
- rebuild 与 Runtime start/reconcile 经过 maintenance lock 串行化；
- 普通 Docker cleanup 不删除 toolchain volume；
- 只有显式 volume 选项调用 workspace runtime-data cleanup；
- 活跃 lease 下 installer 不强删对应 Runtime/volume。

## 8. 安全验收

代码审查和测试必须确认：

- 搜索不到新增的 `docker system prune`；
- 不存在无条件的 `docker rm $(docker ps...)` 或 `docker rmi $(docker images...)`；
- 所有删除目标来自结构化 ownership classification；
- 没有递归删除用户 data-root/workspace 的路径；
- 安装器日志不输出 token、API key、完整配置或 workspace secret。

## 9. 发布门禁

阶段完成前必须通过：

- Python 单元和 feature tests；
- Docker gateway contract tests；
- Tauri NSIS static/render/real installer tests；
- Windows installer static tests；
- Windows real Docker smoke；
- macOS package static tests；
- macOS manual install/upgrade/uninstall；
- 至少一次真实 Docker daemon 下的跨平台资源保留验证。

任何平台无法验证时，发布说明必须明确列出未验证项，不得把静态测试结果描述为真实安装器通过。
