# 领域契约

## 1. 资源归属

### 1.0 共享 ownership foundation

本契约与 `runtime-lifecycle-ux` 共用一套标签常量和资源分类，不得在
runtime、installer、Doctor、NSIS 中分别硬编码。

建议建立单一权威模块，例如：

```text
src/aisc/domain/docker_ownership.py
```

至少统一以下 labels：

```text
io.aisc.managed=true
io.aisc.kind=runtime|one-shot|toolchain
io.aisc.owner=workbench|cli
io.aisc.schema-version=1
io.aisc.workspace-key=<hash>       # workspace-scoped resource
io.aisc.runtime-id=<uuid>          # runtime container only
```

Python 是权威定义；Rust、TypeScript fixture 和安装器只消费结构化 CLI
结果，不自行解释 label。需要在 Rust 中查询 label 时，使用共享 fixture
做值一致性门禁。

### 1.1 Container 标签

所有新建的 AISC container 必须带以下 Docker labels：

```text
io.aisc.managed=true
io.aisc.kind=runtime|one-shot
io.aisc.owner=workbench|cli
io.aisc.schema-version=1
```

Workbench runtime 继续保留现有 labels：

```text
io.aisc.runtime-id=<uuid>
io.aisc.workspace-key=<hash>
```

标签是首选归属证明。名称前缀只用于旧版本兼容，不得作为新资源的唯一归属机制。

### 1.2 Image 标签

AISC 通过 `aisc build` 构建的 image 必须包含：

```text
org.aisc.managed=true
org.aisc.kind=workstation-image
org.aisc.schema-version=1
org.aisc.source-version=<AISC VERSION>
```

image 归属标签必须由 Dockerfile 或统一 build argv 注入，不能只保存在宿主日志中。

Runtime 创建时必须同时记录 image reference 和 content-addressed
`image_id`。`runtime-lifecycle-ux` reconcile 使用这里定义的 image ID，
不得再建立另一套镜像版本判定。

### 1.3 旧版本兼容

历史 container 可能没有完整 labels，允许以下只读兼容证据：

1. container registry 中存在对应名称和 image；
2. container 名称符合 `aisc-wb-<runtime-prefix>`；
3. container 名称符合历史 `super-claude-station-<suffix>`，且 image repository 为 `super-claude`；
4. 旧 AISC data-root/registry 记录明确引用该资源。

历史 image 的兼容规则具有上下文：

1. 升级或卸载已识别的 AISC 安装时，精确默认 tag `super-claude:latest` 可判定为 `legacy_owned`；
2. 首次安装只发现 `super-claude:latest`、但没有 AISC label、registry 或旧安装证据时，判定为 `unverified`，只报告；
3. 其他 `super-claude:<custom-tag>` 仅凭 repository 名称不能证明归属；
4. 升级前记录到的默认 image ID，是构建成功后处理旧 image 的临时归属证据。

## 2. 检测接口

新增一个集中式 Docker lifecycle service，所有安装器通过 CLI sidecar 调用，不在各平台脚本中复制 Docker 筛选逻辑。

建议内部命令：

```text
aisc maintenance docker-scan --format json
aisc maintenance docker-cleanup --format json
aisc maintenance docker-rebuild --format json
```

如果不希望公开 `maintenance` 命令，也可以使用安装器专用隐藏命令，但 JSON 契约必须稳定。

扫描返回：

```json
{
  "schema_version": 1,
  "docker": {
    "available": true,
    "reason": "ok"
  },
  "containers": {
    "owned": [],
    "legacy_owned": [],
    "unverified": []
  },
  "images": {
    "owned": [],
    "legacy_owned": [],
    "unverified": []
  },
  "dangling_owned": [],
  "warnings": []
}
```

每个资源至少包含：

```json
{
  "id": "sha256:...",
  "name": "aisc-wb-...",
  "image": "super-claude:latest",
  "ownership": "owned|legacy_owned|unverified",
  "state": "running|exited|missing|unknown",
  "reason": "label|registry|legacy-name|repository-only"
}
```

## 3. 清理接口

清理必须按 container -> image 的顺序执行：

1. 扫描并重新校验归属；
2. stop 有序 container；
3. force remove owned/legacy_owned container；
4. 重新扫描 image 引用；
5. 删除 owned/legacy_owned 的 AISC tag；
6. image ID 不再被任何 container 或非 AISC tag 引用时，才删除该 image ID；
7. 删除有 AISC label 或升级前 ID 证据的 dangling image；
8. 不调用 `docker system prune`；
9. 不删除 volume/network。

### 3.1 Toolchain volume 边界

通用 `docker-cleanup` 永远不删除 `io.aisc.kind=toolchain` volume。

卸载器中 container/image 清理与持久 toolchain 数据清理是两个独立动作：

- `删除 AISC Docker 容器与工作站镜像`：默认选中，只调用本阶段 cleanup；
- `删除持久化项目 Toolchain volumes`：默认不选中，调用
  `runtime-lifecycle-ux` 定义的 workspace runtime-data cleanup；
- 现有“删除应用数据”不能静默扩展为删除 Docker volume。

删除 toolchain volume 前仍必须验证 owner/kind/full workspace-key labels、
活跃 lease 和挂载关系。即使用户选择了普通 Docker cleanup，也不能绕过这些约束。

清理返回：

```json
{
  "schema_version": 1,
  "action": "cleanup",
  "containers": {
    "removed": [],
    "not_found": [],
    "failed": []
  },
  "images": {
    "removed": [],
    "not_found": [],
    "failed": []
  },
  "skipped_unverified": [],
  "warnings": []
}
```

单个删除失败不得中断其他资源处理。命令退出码建议：

| 情况 | 退出码 |
| --- | --- |
| 全部成功或资源不存在 | 0 |
| Docker 不可用但调用格式正确 | 3 |
| 部分资源失败 | 1 |
| 参数错误 | 2 |

## 4. 升级重建契约

重建服务输入：

```json
{
  "tag": "super-claude:latest",
  "root": "<bundle-root>",
  "old_image_id": "sha256:...",
  "no_cache": true,
  "pull": false
}
```

行为：

1. 验证 bundle 中的 Dockerfile 和版本配置；
2. 使用 `docker build --no-cache -t super-claude:latest`；
3. 构建成功后 inspect 新 image ID；
4. 新旧 ID 不同时，先删除旧 AISC tag；旧 ID 未被其他 tag/container 引用时才删除旧 ID；
5. 构建失败时保留旧 image；
6. 返回 build logs 的脱敏摘要和最终 image ID。

结果必须包含：

```json
{
  "old_image_id": "sha256:...",
  "new_image_id": "sha256:...",
  "image_changed": true,
  "old_image_action": "removed|untagged|kept_referenced|not_found",
  "reconcile_hint": "image_changed|unchanged"
}
```

该结果与 Runtime reconcile 配套：

- 新 Runtime 始终使用 `new_image_id`；
- 仍引用 `old_image_id` 的 ephemeral Runtime 进入 stale 分类；
- rebuild 和 runtime start/reconcile 必须受共享 Docker maintenance lock
  串行化，避免重建中途创建使用旧 tag 的新 container。

### 4.1 Docker maintenance lock

新增跨进程全局锁：

```text
<data-root>/locks/docker-maintenance.lock
```

以下操作必须持有该锁：

- installer scan/cleanup/rebuild；
- `aisc build` 对默认 workstation tag 的写操作；
- Runtime create/start 中解析默认 tag 到 image ID 的关键区；
- reconcile 删除旧 image/container 的关键区。

workspace lease/lock 仍负责 workspace 归属；maintenance lock 只负责宿主 Docker
资源变更顺序。两者同时需要时，固定顺序为先 maintenance lock、再 workspace
lock，禁止反向获取。

## 5. 安全不变量

以下规则必须成为代码和测试中的硬约束：

1. 不得调用全局 prune；
2. 不得按 image repository 单独删除未验证 image；
3. 删除 image 前必须先处理引用它的 AISC container；
4. 不得删除 volume、network、workspace 或 data-root；
5. Docker 不可用时不得写入“已删除”状态；
6. 删除前必须重新扫描，不能依赖安装开始时的旧列表；
7. 所有 Docker argv 通过现有 `DockerExecutor`/gateway 注入；
8. 不在 argv、日志或 JSON 结果中输出 token、配置内容或 workspace secret。
