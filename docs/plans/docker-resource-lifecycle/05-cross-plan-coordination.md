# 与 Runtime 生命周期阶段的协调

关联计划：

- [`runtime-lifecycle-ux`](../runtime-lifecycle-ux/README.md)

两个阶段共同操作 container、image、registry、lease 和 toolchain volume。
以下内容是共享契约，不属于任一计划可独立修改的内部细节。

## 1. 共享标签体系

`docker-resource-lifecycle` Stage A0 先建立统一 ownership foundation：

| 资源 | `io.aisc.kind` | owner | 删除策略 |
| --- | --- | --- | --- |
| Workbench Runtime container | `runtime` | `workbench` | lease/reconcile 或卸载 cleanup |
| CLI one-shot container | `one-shot` | `cli` | 退出或卸载 cleanup |
| Project toolchain volume | `toolchain` | `workbench` | 仅显式 runtime-data cleanup |

Runtime 阶段不得另建 label 常量。Docker 阶段不得仅凭名称删除新资源。

Image 使用 `org.aisc.*` provenance labels，但 image ID 的解析、存储和比较仍
属于同一个 ownership foundation。

## 2. 卸载协调

同一个卸载流程包含三个彼此独立的资源层：

1. 应用文件与 PATH；
2. AISC container 和 workstation image；
3. 用户数据与 project toolchain volume。

默认策略：

| 选项 | 默认 | 执行方 |
| --- | --- | --- |
| 删除应用文件 | 是 | installer |
| 删除 AISC container/image | 是 | Docker lifecycle service |
| 删除 app data | 否 | installer |
| 删除 toolchain volume | 否 | Runtime runtime-data cleanup |

container/image cleanup 不得顺带删除 volume。app-data 删除也不得通过目录
删除假装已经处理 Docker volume。

Tauri NSIS 现有 KI-4 checkbox 保留为 container/image 选项，但底层改用统一
service。若增加 toolchain volume 选项，必须单独展示影响范围、资源数量和
无法删除的 active lease。

## 3. Image ID 交接

升级 rebuild 返回 old/new image ID。Runtime reconcile 使用相同 ID：

```text
installer rebuild
  -> old_image_id / new_image_id
  -> current default tag 指向 new_image_id
  -> reconcile 发现 container.image_id == old_image_id
  -> stale ephemeral: stop/remove
  -> active other lease: skip/block
```

installer 不应绕过 lease 强删另一个活跃 Workbench 实例的 Runtime。无法清理
的旧 container 进入结构化 skipped 结果，由后续 reconcile 处理。

## 4. 并发和锁顺序

共享 Docker maintenance lock 防止以下竞态：

- upgrade 正在重建默认 image，另一个进程同时 start Runtime；
- uninstall 正在扫描 container，reconcile 同时 remove；
- rebuild 刚记录 old image ID，新的 container 又从旧 tag 创建。

固定锁顺序：

```text
docker-maintenance.lock
  -> workspace lock
  -> registry transaction
```

任何实现不得反向获取。

## 5. 实施顺序

建议顺序：

1. Docker Stage A0：共享 labels、结构化 inspect、image ID、maintenance lock；
2. Runtime Stage 1：lease/reconcile 使用共享 foundation；
3. Docker Stage A1/B：scan/cleanup/rebuild service 和 CLI；
4. Runtime Stage 3a：toolchain volume 使用共享 labels；
5. Docker Stage C/D/E：NSIS/Inno/portable/PKG 接入；
6. 两计划联合真实 Docker 和卸载测试。

若团队希望合并早期实施，可以把第 1 步作为独立的
`docker-ownership-foundation` 提交序列；后续两个计划分别消费，不复制代码。
