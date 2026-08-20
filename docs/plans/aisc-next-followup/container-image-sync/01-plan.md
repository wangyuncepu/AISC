# 容器随镜像同步更新（KI-4 挂账：fingerprint 纳入 image ID）

分支：`container-image-sync`（自 develop `55bee53`）。目标：镜像重建/升级后，
已有工作区容器不再被"原样复用"旧镜像——下次启动检测到 image ID 变化即按既有
runtime_conflict 引导重建（与订阅刷新 D1 同族机制）。

## 问题

`compute_config_fingerprint`（runtime.py:40）的 canonical dict 只含
`{image(名字), network, scope, workspace}`（proxy 模式另加订阅哈希）。镜像按
**名字**参与身份——同名 tag 重建后（`aisc build` 同 tag 覆盖），指纹不变 →
preflight 判"可复用" → 旧容器带着旧镜像内容继续跑。用户升级 aisc（新容器脚本/
bundle）后容器不跟随，即 KI-4 挂账的"如果能同步更新 container 就更好了"。

## 方案拍板：additive `image_id` meta 字段（不literal改指纹公式）

挂账原文写的是"fingerprint 纳入 image ID"，落地取等效但更稳的形状：

- **为什么不直接塞进指纹 canonical dict**：公式一变，所有存量容器（无论镜像
  变没变）立即全部指纹失配 → 升级 CLI 当天全员被迫一次性重建（假冲突风暴）。
- **additive 方案**：registry meta 增 `image_id` 字段（docker image inspect
  的 `.Id`，内容寻址）；冲突检测在"指纹已匹配"的复用分支上再比 image_id：
  - meta 无 `image_id`（存量记录）→ **放行**（unknown ≠ changed，不误报）；
  - 相等 → 照常复用；
  - 不等 → conflict，reason 精确（"image updated"），走既有 ConflictManager
    引导移除+重建（UI 零改动，reason 自由文本照渲染）；
  - 当前镜像 inspect 瞬时失败（None）→ 放行（不因探测抖动误报）。
- **自愈**（照 KI-3 stale-pin 哲学）：`start_runtime` 复用分支发现存量 meta
  无 `image_id` 时，顺手补写当前 image_id（register 全量覆写同条目，在
  workspace_lock 内，与 create 路径同模式）。存量工作区在下次成功启动后即
  进入保护圈，之后的镜像变化必被检出。

## 改动清单

1. `src/aisc/domain/models.py`：`ImageInspectResult` 增 `image_id: str = ""`。
2. `src/aisc/adapters/docker_.py`：
   - CLI 网关 `inspect_image` 成功路径解析 stdout JSON 的 `[0].Id` → `image_id`
     （失败路径保持空串）；SDK 网关 `images.get(name).id`；文件内 fakes 默认值同步。
3. `src/aisc/application/runtime.py`：
   - 新 helper `_resolve_image_id(image, executor) -> Optional[str]`（OK 才返回，
     空/异常 → None）；
   - `_check_runtime_conflict` 复用分支（fingerprint 匹配后）追加 image_id 三态
     比较（见上）；preflight 与 start 两条调用路径零签名变化自动生效；
   - `start_runtime` 复用分支 heal 写入（reuse_meta 无 image_id → register
     全量 meta + image_id）。
4. `src/aisc/adapters/container_registry.py`：`register()` 白名单键 + `image_id`
   （缺省 ""，向后兼容；文档字符串补一行）。
5. 测试（`tests/test_runtime_lifecycle.py` / conflict 相关 + registry 回环）：
   - 复用分支四态：同 id 复用 / 异 id 冲突（reason 含 image updated）/ 存量空
     id 放行 / inspect 失败放行；
   - start 复用被镜像变化阻断 → `AISC_EXIT_RUNTIME_CONFLICT` 且 data.conflicts
     带该条；
   - heal：复用成功后 registry meta 出现 image_id；
   - register/list roundtrip 保留 image_id。

## 明确不做

- 不改指纹公式、不迁移存量 meta、不动 Rust/Workbench 代码（冲突 UI 泛用）、
  不做自动删除重建（用户经冲突面板动作走，语义与订阅 D1 一致）。
- 镜像不存在（tag 被删）仍走既有 IMAGE_NOT_FOUND 预检，不在本 rounds 范围。

## 手测矩阵（实现完成后）

1. 正常启动工作区 → `aisc ps`/registry 文件确认 meta 带 `image_id`；
2. 复用：不改镜像再次启动 → 直接复用（无冲突）；
3. 重建镜像（`aisc build` 同 tag，内容有差异即可改 ID）→ 再启动 → 冲突面板
   列出 image-updated 条目 → 移除 → 再启动 → 新容器新镜像，meta image_id 更新；
4. 存量工作区（本改动前建的，meta 无 image_id）：首次启动直接复用 + heal 落
   image_id，第二次起受保护。

门禁：python 全测 / cargo 不涉及 / vitest 不涉及（UI 零改）；sidecar 重建同步
（Python 变更）；container/ 未动 → 无 vendor 刷新。收口 `--no-ff` + 四 CI。
