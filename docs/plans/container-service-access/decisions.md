# 容器内 Web 服务访问 — 冻结合同（decisions）

> 对应实施计划：`docs/plans/container-service-access.md`（svc-0 产物，2026-08-25）
> 状态：**Frozen**。改动本文件任何一条 = 改合同，须同步 Python / Rust / TypeScript
> 三端与共享 fixture，并在下表追加一行变更记录。

## 1. 权威源与镜像

| 层 | 文件 | 角色 |
|---|---|---|
| Python | `src/aisc/domain/web_services.py` | **权威**（常量 + 纯函数 + 数据模型） |
| TypeScript | `workbench/src/lib/webServices.ts` + `workbench/src/types/index.ts` | 镜像 |
| Rust | `workbench/src-tauri/src/web_services.rs` | 镜像 |
| 共享 fixture | `tests/fixtures/web-services/*.json` | 三端解码一致性的阶段门 |
| 容器内 | `container/aisc-web-gateway`、`container/aisc-web-expose` 等（svc-1） | 独立实现，遵守同一常量 |

fixture 消费者：`tests/test_web_services.py` / `workbench/src/lib/__tests__/webServices.test.ts`
/ `workbench/src-tauri/tests/web_services.rs`。

## 2. 冻结常量

| 常量 | 值 | 说明 |
|---|---|---|
| gateway 容器端口 | `45871` | 容器内 gateway 固定监听口（`0.0.0.0`） |
| 宿主端口范围 | `47000..47999`（含端点） | runtime start 时动态分配，仅绑 `127.0.0.1` |
| 可注册服务端口 | `1024..65535` | 十进制整数、仅 TCP |
| manifest 目录 | `/run/aisc/web-services/` | 每服务一个 `<port>.json` |
| URL scheme | `http`（v1 固定） | HTTPS 延后单独设计 |
| 路由 Host | `p<container-port>.localhost[:<gateway-port>]`（大小写不敏感，允许 FQDN 尾点） | 唯一路由标识，用户不可自定义 |
| 用户 URL | `http://p<port>.localhost:<host-gateway-port>/` | label 不进 URL；path/query/fragment 归浏览器 |

## 3. Schema

### 3.1 `aisc.web-service/v1`（容器内 manifest 单条记录）

```json
{
  "schema_version": "aisc.web-service/v1",
  "port": 3000,
  "protocol": "http",
  "name": "docs preview",
  "state": "registered",
  "registered_at": "2026-08-25T00:00:00Z",
  "pid": null
}
```

- `state` v1 只有 `registered`（注册 ≠ ready，永不假装 ready）；
- `name` ≤64 字符、无控制字符、允许空；仅用于 UI 展示；
- `pid` v1 恒为 `null`（预留，不与暴露绑定）；
- 写入：临时文件 + fsync + `os.replace`；目录 `0700`、文件 `0600`；
- 文件名只允许 `^[0-9]{4,5}\.json$`（即端口本身），拒绝路径穿越；
- 解码 fail closed：未知 schema / 非法字段 → 拒绝，绝不降级猜测。

### 3.2 `aisc.runtime-services/v1`（`aisc runtime services` 输出）

```json
{
  "schema_version": "aisc.runtime-services/v1",
  "runtime_id": "…",
  "gateway": {
    "state": "ready",
    "container_port": 45871,
    "host_port": 47831,
    "host": "127.0.0.1",
    "reason": ""
  },
  "services": [
    { "port": 3000, "protocol": "http", "name": "docs preview",
      "state": "registered", "url": "http://p3000.localhost:47831/" }
  ],
  "observed_at": "2026-08-25T00:00:00Z"
}
```

- `gateway.state` ∈ `ready | unavailable`；`reason` 仅在 `unavailable` 时出现；
- `unavailable` 原因封闭集：`legacy_runtime` / `runtime_not_running` /
  `gateway_unreachable` / `docker_unavailable` / `no_mapping`；
- `host_port` 只来自 `docker inspect`（连接性事实源），registry 仅存最近观察值；
- 三端解码均 fail closed 于未知 schema_version；
- 旧 CLI 不输出 `RuntimeSnapshot.web_access` → 消费端按 `unavailable(legacy)` 处理，
  绝不因新增字段让 inspect 整体失败。

## 4. Gateway HTTP 错误合同

| 场景 | HTTP | 标识 |
|---|---:|---|
| Host 非 `p<port>.localhost` 形态 | 400 | `AISC_WEB_BAD_HOST` |
| 端口非 1024..65535 | 400 | `AISC_WEB_PORT_INVALID` |
| 端口未注册 | 404 | `AISC_WEB_PORT_NOT_EXPOSED` |
| 容器内目标未监听 | 502 | `AISC_WEB_TARGET_UNAVAILABLE` |
| manifest 读取失败 | 503 | `AISC_WEB_REGISTRY_UNAVAILABLE` |

判定顺序：BAD_HOST → PORT_INVALID → PORT_NOT_EXPOSED → 连接目标 →（转发期断开按 502）。

## 5. Helper 命令合同（容器内）

```
aisc-web-expose <port> [--name <label>]     # 幂等注册；重注册可更新 label
aisc-web-unexpose <port>                    # 幂等注销（缺失 = 成功）
aisc-web-list [--json]                      # 人读行式 / JSON 数组（--json）
```

- 成功输出固定格式（svc-3 冻结为 Agent 合同）：
  `aisc web service registered: port=3000 name="docs preview"`；
- helper 不猜宿主端口、不输出任何 URL（URL 只由 host CLI/Workbench 生成）；
- helper 不触碰 Docker socket；
- 日志/输出不得出现 API key、cookie、完整 query string 或请求内容。

## 6. 能力协商

- capability 键：`runtimeServices`（camelCase，与 `providerStatus` 同风格）；
- 值：`aisc.runtime-services/v1`；
- 随 svc-2（`runtime services` 命令落地）加入 `WORKBENCH_CAPABILITIES`，
  Workbench 侧 UI 以该能力门控，缺失时 Services 区显示"当前 CLI 不支持"。

## 7. 宿主端口分配

1. 进程内 bind `127.0.0.1:<port>` 探测空闲 → 关闭探测 socket → 写入 Docker argv；
2. Docker 返回 bind conflict → 顺序换下一个候选（范围内线性推进，有限次数）；
3. 成功后把**实际映射**写入 registry（`web_gateway_host_port`，optional 字段）；
4. host port 是运行时元数据，**不参与 config fingerprint**；
5. runtime reuse/restart 复用 Docker 实际映射，绝不重新随机分配；
6. 只绑 loopback；`0.0.0.0` 永久禁止。

## 8. 默认决策（承接计划 §12，均已定案）

| 议题 | 决策 |
|---|---|
| 访问范围 | 仅本机 loopback；LAN/公网不在 v1 |
| 协议 | HTTP/1.1 + WebSocket upgrade；HTTPS 延后 |
| 服务绑定 | 允许 `127.0.0.1`（推荐）或 `0.0.0.0`，宿主一律只经 gateway |
| 未注册端口 | 拒绝转发（404），不做自动发现 |
| UI 打开 | 仅后端重生成并校验过的 runtime service URL |
| legacy runtime | `web_access=unavailable(reason=legacy_runtime)`，可继续用 |
| 远程/SSH | 不在 v1 |

## 9. 变更记录

| 日期 | 阶段 | 变更 |
|---|---|---|
| 2026-08-25 | svc-0 | 初版冻结（常量 / 双 schema / 错误合同 / helper 合同 / 能力键 / 分配规则） |
