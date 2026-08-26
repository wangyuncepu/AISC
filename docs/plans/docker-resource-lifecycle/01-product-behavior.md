# 产品行为

## 1. 资源分类

| 资源 | 默认归属 | 卸载 | 升级 |
| --- | --- | --- | --- |
| AISC 管理的 container | AISC | force remove | stop/remove 后重新创建 |
| AISC 构建的 workstation image | AISC | remove | 直接 no-cache rebuild |
| 未标记但被旧 registry 引用的 container | 兼容识别 | remove | stop/remove |
| 未标记、仅名称类似的 container | 未确认 | 只报告 | 不删除 |
| 未标记旧 image | 未确认 | 只报告，除非显式确认 | 记录旧 ID，成功重建后按 ID 清理 |
| workspace bind mount | 用户 | 保留 | 保留 |
| AISC data-root | 用户 | 保留 | 保留 |
| Docker named volume | 独立持久资源 | 保留 | 保留 |

## 2. 首次安装

首次安装指安装目标目录不存在，或无法确认其来自旧版本 AISC。

流程：

1. 验证安装包和 bundle；
2. 只读检查 Docker CLI、daemon 和 AISC 资源；
3. 检测旧的 AISC container、image、dangling image；
4. 清理可以证明属于 AISC 且已停止或可安全 force remove 的孤立 container；
5. 对未能证明归属的旧 image 输出检测结果，不默认删除；
6. 安装 CLI 和 bundle；
7. 不自动构建 image，保持当前首次安装行为；
8. 输出检测、清理和后续建议。

首次安装不能因为 Docker 未安装、daemon 未启动或权限不足而阻止 CLI 文件安装。

## 3. 升级安装

升级指安装目标目录已经存在，并且安装器识别到旧 AISC 安装。

流程：

1. 在替换旧文件前读取旧安装信息；
2. 使用新版安装包中暂存的 lifecycle helper，停止并删除 AISC 管理的 container；
3. 记录默认 image 的旧 image ID；如果旧 image 无法证明归属，只记录，不在构建前删除；
4. 原子替换 CLI 和 bundle；
5. 使用新版本 CLI 对默认 image 执行 `build --no-cache`；
6. 构建成功后清理旧 AISC tag；只有旧 image ID 不再被 container 或非 AISC tag 引用时才删除该 ID；
7. 再次扫描 AISC 资源，输出残留清单；
8. 构建失败时保留新 CLI 安装结果，并明确提示可执行的重试命令。

升级不应先删除默认 tag 后再构建。这样可以避免构建失败时用户完全失去可用 image，也便于记录旧 image ID。升级不能依赖旧版本 CLI 已经实现 lifecycle 命令，所有兼容扫描和清理均由新版安装包中的 helper 完成。

默认重建目标为 `super-claude:latest`。对于 `aisc build --tag` 创建的自定义 image：

- 有 AISC 归属标签或构建记录时，可纳入后续清理；
- 只有用户手工指定名称、没有归属证明时，不由安装器自动删除；
- 本阶段不自动重建所有自定义 image。

## 4. 卸载

卸载默认执行：

1. 停止并 force remove 所有可确认属于 AISC 的 container；
2. 删除 AISC workstation image；
3. 删除可以确认由 AISC 构建的 dangling image；
4. 删除应用文件、PATH entry、卸载注册信息；
5. 保留用户配置、workspace、data-root、volume 和 network；
6. 输出 Docker 清理结果和未处理资源。

卸载必须是幂等的。重复卸载、资源已经被用户手工删除、container 已不存在，都不应导致卸载器崩溃。

## 5. Docker 不可用

Docker 清理使用 best-effort 策略：

- CLI 不存在：跳过 Docker 操作，卸载应用文件继续；
- daemon 不可达：跳过 Docker 操作，卸载应用文件继续；
- 权限不足：跳过受影响资源，卸载应用文件继续；
- 单个资源删除失败：继续处理其他资源；
- 最终结果必须区分 `removed`、`not_found`、`skipped`、`failed`；
- 安装器日志不得把 Docker 不可用误报成“资源已清理”。

升级时 Docker 不可用或重建失败，不回滚宿主 CLI 文件。升级结果标记为 `application_updated_image_pending`，并显示：

```text
aisc build --no-cache --tag super-claude:latest
```

## 6. 用户确认与覆盖选项

默认行为按本阶段目标执行清理，但提供显式保留选项：

- portable uninstaller：`--keep-docker-resources`；
- macOS uninstaller：`--keep-docker-resources`；
- Windows uninstaller：Inno uninstall command line 传递等价选项；
- 安装器静默模式下不得弹出不可自动处理的交互确认。

保留选项只跳过 Docker container/image 清理，不影响应用文件卸载。
