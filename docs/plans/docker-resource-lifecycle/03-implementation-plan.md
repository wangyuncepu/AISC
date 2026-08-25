# 实现计划

## 阶段 A：领域服务和测试

### A0. 与 Runtime 阶段共用 Docker ownership foundation

先完成：

- 统一 `io.aisc.*` container/volume labels 和 `org.aisc.*` image labels；
- 建立 Python 权威常量、Rust/fixture 一致性测试；
- 扩展结构化 inspect/list 结果，稳定返回 labels、image ref、image ID；
- 实现 `<data-root>/locks/docker-maintenance.lock`；
- 冻结 maintenance lock -> workspace lock 的锁顺序；
- 让 Runtime create 将解析后的 image ID 写入 metadata。

这是 `runtime-lifecycle-ux` reconcile 和 toolchain volume 实现的前置，不得在
两个阶段中重复开发。

### A1. 建立资源模型

新增 Docker lifecycle application service，集中实现：

- scan；
- ownership classification；
- cleanup；
- old image ID capture；
- post-build old image removal；
- structured result。

复用现有 `DockerExecutor` 的 preflight、list、inspect、remove 接口。若现有接口无法取得 labels 或 image ID，先扩展 executor 的结构化结果，不在业务层解析不稳定的人类文本。

### A2. 新资源打标签

修改统一的 container/build 入口：

- `aisc run` 的 one-shot container；
- Workbench runtime container；
- Dockerfile/build plan 的 workstation image。

保留现有 runtime labels，增加 schema/version 和 owner/kind 标签。

### A3. 单元测试

覆盖：

- 标签资源识别；
- legacy registry/名称兼容识别；
- unverified 资源不删除；
- container 先于 image；
- 删除失败继续处理；
- Docker unavailable；
- image ID 去重；
- 不调用 `system prune`；
- 不删除 volume/network。

## 阶段 B：CLI 生命周期入口

实现安装器可调用的稳定 JSON 命令。建议命令如下：

```text
aisc maintenance docker-scan --format json
aisc maintenance docker-cleanup --format json
aisc maintenance docker-rebuild --root <bundle> --tag super-claude:latest --no-cache --format json
```

要求：

- 支持 frozen executable；
- 支持 `--aisc-root` 或显式 bundle root；
- stdout 只输出 JSON envelope；
- Docker 子进程输出转发到 stderr 或结构化日志；
- 命令可重复执行；
- 不依赖当前工作目录；
- 失败码与 [02-domain-contract.md](02-domain-contract.md) 一致。

## 阶段 C：Windows 安装器

### C1. Tauri NSIS 主安装器

修改 `workbench/src-tauri/nsis/installer.nsi`。这是 Workbench 用户的主安装
路径，优先级高于 Inno Setup。

任务：

- 保留 KI-4 的 Docker cleanup UI，但把直接 `docker ps/rm/rmi` 替换为
  lifecycle service 调用；
- lifecycle helper 必须在 sidecar 和 `aisc-bundle` 被删除前运行；当前
  cleanup 位于文件删除之后，实施时必须前移到 `Section Uninstall` 开头或
  `NSIS_HOOK_PREUNINSTALL`；
- 不硬编码渲染后的 external binary 文件名，复用 Tauri `externalBin`
  生成的 sidecar 路径；
- 普通卸载的 container/image cleanup 默认选中；提供 `/KEEPDOCKER`
  显式保留选项；`/UPDATE` 不执行卸载式 image 删除；
- 保留现有 app-data checkbox，另设明确的 toolchain volume 删除选项，
  默认不选中；不能把 volume 删除并入 KI-4 container/image cleanup；
- 升级安装在新 sidecar 和 bundle 落盘后调用 no-cache rebuild，并消费
  old/new image ID 结果；
- Docker 不可用、活跃 lease 或部分清理失败不阻止 Workbench 文件卸载，
  但必须记录 `skipped/failed`，不能显示“已清理”；
- 删除 KI-4 内重复的 Docker CLI 搜索、容器名称过滤和 image 删除算法；
  Docker Desktop 是否安装/启动的 host integration 可继续留在 NSIS。

### C2. Windows Inno Setup

修改 `packaging/windows/installer.iss`：

#### C2.1 升级

- 从新版安装包提取或暂存 lifecycle helper，不能假设旧 `aisc.exe` 支持 cleanup；
- 在替换旧 `{app}` 内容前用新版 helper 扫描并记录旧资源；
- 新文件安装完成后调用新 `aisc.exe` rebuild；
- 用 Inno 的 `Exec`/等待机制捕获退出码；
- 不让 Docker failure 阻止宿主文件安装；
- 把 cleanup/rebuild 摘要写入安装日志。

#### C2.2 卸载

- 在删除 `{app}` 前调用当前 `aisc.exe` cleanup；
- 支持静默卸载；
- 保留 PATH 的安全逐项删除逻辑；
- Docker helper 缺失时继续删除应用文件。

### C3. Windows 测试

扩展现有静态测试和 Windows smoke：

- 验证 Tauri NSIS 不再直接执行资源筛选和 `docker rm/rmi`；
- 验证 NSIS 在删除 sidecar/bundle 前调用 lifecycle service；
- 验证 KI-4 container/image 选项与 toolchain volume 选项相互独立；
- 验证 `/UPDATE`、`/KEEPDOCKER`、silent/passive 模式；
- 创建带 AISC labels 的 fake Docker command；
- 验证升级调用 cleanup 和 rebuild；
- 验证卸载调用 cleanup；
- 验证 Docker failure 不阻止 uninstall；
- 验证 PATH 和用户配置仍保留。

## 阶段 D：portable Linux/macOS 脚本

修改：

- `packaging/install.sh`；
- `packaging/install.ps1`；
- `packaging/uninstall.sh`；
- `packaging/uninstall.ps1`。

脚本只负责：

1. 检测是否为升级；
2. 暂存并选择新版 sidecar；
3. 调用统一 JSON 命令；
4. 显示结果和 warning；
5. 继续文件安装或卸载。

脚本不自行实现 `docker ps`、`docker images` 的过滤规则。

升级脚本必须用新版暂存 sidecar 在替换旧安装前执行 container cleanup，并在替换后执行 no-cache rebuild。首次安装执行 scan；检测到可确认孤立资源时执行 cleanup，但不默认 build。

## 阶段 E：macOS PKG

修改 `packaging/macos/build_pkg.sh` 生成的 payload uninstaller：

- 卸载前调用 `/usr/local/lib/aisc/aisc maintenance docker-cleanup`；
- preinstall 只清理旧宿主文件，不执行 Docker 删除；
- upgrade rebuild 由安装后的新 sidecar 执行；
- 支持 `sudo`、静默安装和 alternate target 的现有约束；
- Docker 操作失败只输出 warning，不阻止文件卸载。

## 阶段 F：文档和发布验证

更新 README 的升级和卸载章节：

- 说明默认清理范围；
- 明确配置/workspace/volume 保留；
- 说明 Docker 不可用时的结果；
- 说明如何使用 keep 选项；
- 说明升级会执行 no-cache rebuild。

更新发布手册和 macOS/Windows 手测文档。

## 依赖顺序

```text
A0 共享 ownership / labels / image ID / maintenance lock
  ├─> runtime-lifecycle-ux Stage 1 reconcile
  ├─> runtime-lifecycle-ux Stage 3a toolchain volume
  └─> A1-A3 Docker lifecycle service
          -> B CLI JSON 入口
          -> C1 Tauri NSIS
          -> C2 Inno / D portable / E PKG
          -> F 文档、集成测试和发布验证
```

每个阶段完成后先运行对应测试，不把跨平台安装器修改和核心清理逻辑混在同一个未验证提交中。
