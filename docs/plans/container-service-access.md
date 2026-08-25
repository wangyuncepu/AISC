# 容器内 Agent 服务访问方案

> 状态：Proposed implementation plan
> 规划日期：2026-08-25
> 规划基线：当前 `develop`
> 问题范围：Agent 在 Docker 容器内启动 Web 服务后，用户拿到 `localhost:<port>` 或 `127.0.0.1:<port>`，在宿主机浏览器中无法访问。

## 1. 结论

采用“每个 runtime 一个宿主机回环 Web gateway + 容器内服务注册”的方案：

1. runtime 启动时只向宿主机发布一个固定的容器内 gateway 端口，宿主机端绑定 `127.0.0.1`，并为它分配一个宿主机端口。
2. Agent 服务不需要直接发布 Docker 端口。服务可以继续监听容器内 `127.0.0.1`。
3. Agent 通过镜像内置的 `aisc-web-expose <port>` 注册服务端口。
4. gateway 根据请求 Host 中的端口标识，将请求转发到容器内对应的 `127.0.0.1:<port>`，保留原始路径，因此 Vite/Next/Flask 等根路径服务不需要改成子路径部署。
5. 对用户展示的 URL 统一为：

   ```text
   http://p<container-port>.localhost:<host-gateway-port>/
   ```

   例如容器内服务监听 `3000`，runtime 的宿主机 gateway 端口为 `47831`，用户打开：

   ```text
   http://p3000.localhost:47831/
   ```

6. Agent 全局指令明确：`localhost:<port>` 只表示容器内地址，不能作为用户 URL；启动服务后必须注册端口，并报告 gateway 生成的 URL。

该方案解决的是“容器网络命名空间与宿主机浏览器不一致”这一根因，同时避免：

- 把容器改成 `network=host`；
- 向局域网暴露服务；
- 为未知端口预先发布很大的端口段；
- 仅做文本替换而没有真实的转发通道；
- 强制所有框架都监听 `0.0.0.0`。

## 2. 当前实现证据

### 2.1 Docker 端口目前没有进入 runtime 合同

当前 Workbench runtime 的创建命令在 `src/aisc/application/runtime.py` 的
`start_runtime()` 中构造，包含容器名、labels、环境变量、workspace 和 Agent
状态目录挂载，但没有任何 `--publish/-p` 参数。

`src/aisc/domain/models.py` 的 `RunPlan.docker_argv` 也只处理 workspace、
Agent 状态挂载、proxy/TUN 和交互模式，没有端口字段。

因此，即使容器内服务监听 `0.0.0.0:3000`，宿主机仍然没有可访问的端口。

### 2.2 Workbench runtime 是 idle 容器，不是 Agent 进程容器

`container/entrypoint.sh` 在 `AISC_RUNTIME_MODE=idle` 下生成
`/run/aisc/runtime-context.json`，随后执行 `sleep infinity`。真正的 Claude、
Codex 或 bash 通过 `aisc session open` / `docker exec` 接入。

这意味着：

- 端口映射必须在 `runtime start` 创建容器时确定；
- 不能等 Agent 启动服务后再向现有容器追加 Docker port binding；
- gateway 应在 idle runtime 中常驻，而不是绑定某个单独 Agent session 的 PID。

### 2.3 Agent 指令没有定义宿主机 URL 合同

`container/global-claude.md` 会被同时复制为 Claude 的 `CLAUDE.md` 和 Codex 的
`AGENTS.md`，但当前只规定通用编码行为，没有以下约束：

- 容器内服务如何注册；
- 哪些服务可被宿主机访问；
- 用户应打开什么 URL；
- 服务停止或端口变更后如何更新状态。

因此 Agent 直接输出框架默认的 `http://localhost:<port>` 是当前系统允许的行为。

### 2.4 Workbench 没有服务状态模型

`workbench/src/types/index.ts` 的 `RuntimeSnapshot` 只有 runtime/container
生命周期和配置，没有 gateway、服务端口或用户 URL。

`workbench/src-tauri/src/runtime.rs` 和 `workbench/src/lib/ipc.ts` 目前只覆盖
runtime start/inspect/list/stop/restart/remove，没有服务查询或打开 URL 的 IPC。

终端使用 xterm.js 原始输出流，当前没有可靠的 URL 解析、端口映射或外部浏览器打开能力。

## 3. 问题链路

当前故障链路如下：

```text
Agent 在容器内启动服务
    -> 服务监听容器 namespace 内的 127.0.0.1:<port>
    -> Agent 输出 http://localhost:<port>
    -> 用户在宿主机浏览器打开
    -> localhost 指向宿主机，而不是容器
    -> runtime 没有 -p 映射
    -> 连接失败
```

即使只把 Agent 指令改成监听 `0.0.0.0`，仍然会因为没有 Docker port publish 而失败。
因此必须同时解决：

1. 服务发现和注册；
2. 容器到宿主机的实际传输；
3. URL 生成和展示；
4. runtime 重启、复用和销毁时的状态一致性。

## 4. 范围定义

### 4.1 本阶段包含

- Workbench managed runtime 的 HTTP/1.1-over-TCP 服务访问；
- WebSocket upgrade；
- 容器内任意非特权 TCP 端口的显式注册；
- 仅宿主机访问，gateway 只绑定宿主机 `127.0.0.1`；
- Claude、Codex、bash 三类 session 的一致行为；
- runtime reuse/restart/stop/remove 下的 gateway 生命周期；
- `aisc run` 一次性容器的同等能力；
- Workbench 中显示、复制和打开服务 URL；
- Agent 全局指令和服务 helper；
- 单元测试、CLI 契约测试、Docker 集成测试和 Windows Docker Desktop 手测。

### 4.2 本阶段不包含

- 局域网或公网访问；
- UDP 服务；
- 任意原始 TCP 服务的通用代理；
- 反向代理到容器外部网络；
- 自动修改应用源码中的 `localhost`、CORS、HMR 或 framework config；
- 让 gateway 暴露容器内所有端口；
- 通过 `network=host` 绕过 Docker 网络隔离；
- 端口共享给多个 runtime；
- 远程开发机或 SSH tunnel。

非 HTTP 的数据库、游戏服务器、TCP RPC 等场景先不承诺用户可访问；后续如果确有
需求，单独设计显式 TCP forwarding，而不是扩大本方案的隐式暴露面。

## 5. 目标行为合同

### 5.1 服务注册

镜像提供：

```text
aisc-web-expose <port> [--name <label>]
aisc-web-unexpose <port>
aisc-web-list
```

第一版约束：

- 只接受 `1024..65535`；
- 只注册 TCP；
- `<port>` 必须是十进制整数；
- `--name` 只允许安全的短文本，不能包含控制字符；
- 同一端口重复注册是幂等操作，后一次可以更新 label；
- 未注册端口不由 gateway 转发；
- 注册不代表服务已经 ready，只代表 gateway 允许尝试连接；
- helper 不记录 API key、cookie、完整 query string 或请求内容。

推荐 Agent 使用：

```bash
python3 -m http.server 3000 --bind 127.0.0.1 &
aisc-web-expose 3000 --name "docs preview"
aisc-web-list
```

Node/Python/Go 等框架可以绑定 `127.0.0.1`；如果框架自身需要
`0.0.0.0` 才能正常工作，也允许使用 `0.0.0.0`，但宿主机仍只通过 gateway 访问。

### 5.2 服务状态文件

容器内使用目录：

```text
/run/aisc/web-services/
  3000.json
  5173.json
```

单个记录建议为：

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

实现要求：

- 先写临时文件、fsync、再 `os.replace`；
- 目录和文件使用 `0700/0600`；
- 只允许安全端口文件名，拒绝路径穿越；
- gateway 读取失败时 fail closed；
- 服务退出后不要求 helper 自动感知，但 `aisc-web-list` 应显示
  `registered` 而不是假装 `ready`；
- 后续可增加 PID/health probe，但不把 readiness 和本阶段的端口暴露绑定在一起。

### 5.3 Gateway URL

URL builder 的唯一输入是：

```text
runtime gateway host port
container service port
```

输出：

```text
http://p<container-port>.localhost:<host-gateway-port>/
```

规则：

- scheme 第一版固定为 `http`；
- `p<port>.localhost` 是路由标识，不能由用户输入；
- 原始 path、query、fragment 由用户浏览器保留；
- gateway 必须校验 Host 格式，拒绝未知 hostname；
- 服务 label 只用于 UI 展示，不进入 URL；
- 后续 HTTPS、认证、远程访问不得复用此 URL 合同。

## 6. 推荐架构

### 6.1 宿主机端口分配

在 `runtime start` 创建 Docker 容器前，由宿主机选择一个空闲端口，例如默认范围
`47000..47999`。候选端口需：

1. 在当前进程中 bind `127.0.0.1:<port>` 做快速检查；
2. 关闭检查 socket；
3. 把端口写入本次 Docker argv；
4. 如果 Docker 返回 bind conflict，换下一个端口重试；
5. 成功后把最终端口写入 registry。

Docker argv 增加：

```text
--publish 127.0.0.1:<host-gateway-port>:45871/tcp
```

其中 `45871` 是容器内 gateway 固定监听端口，实际值放在共享常量中，不能散落在
Python、shell、Rust 和 TypeScript 中。

端口分配注意事项：

- host port 是运行时操作元数据，不参与 config fingerprint；
- 同一 runtime reuse 时必须复用 Docker 实际映射，不重新随机分配；
- legacy runtime 没有 gateway mapping 时，inspect 明确报告
  `web_access=unavailable`，不能伪造 URL；
- runtime remove/stop 不删除宿主机用户的其他端口；
- 只绑定 loopback，不使用 `0.0.0.0:<port>`。

### 6.2 容器内 Gateway

新增容器内小型 gateway，建议使用 Python 标准库 `asyncio` 实现，避免引入新的
Node/npm runtime 依赖。实现为 HTTP/1.1 首请求路由 + 双向字节转发：

1. 监听 `0.0.0.0:45871`；
2. 读取首个 HTTP request headers；
3. 从 `Host: p3000.localhost:<gateway-port>` 解析目标端口；
4. 校验该端口存在于 `/run/aisc/web-services/*.json`；
5. 连接 `127.0.0.1:3000`；
6. 将原始 request headers/body 转发；
7. 双向 relay response；
8. 对 `Upgrade: websocket` 保持连接并继续双向转发；
9. 对非法 Host、未注册端口、目标连接失败返回稳定的 4xx/5xx 页面。

gateway 不做 HTML 重写、不改 path、不注入 cookie、不转发到容器外部地址。
这样可以覆盖 SPA、HMR、WebSocket 和常见开发服务器，同时保持代理边界简单。

建议稳定错误：

| 场景 | HTTP 状态 | 标识 |
|---|---:|---|
| Host 格式错误 | 400 | `AISC_WEB_BAD_HOST` |
| 端口未注册 | 404 | `AISC_WEB_PORT_NOT_EXPOSED` |
| 端口非法/特权端口 | 400 | `AISC_WEB_PORT_INVALID` |
| 容器内目标未监听 | 502 | `AISC_WEB_TARGET_UNAVAILABLE` |
| manifest 读取失败 | 503 | `AISC_WEB_REGISTRY_UNAVAILABLE` |

### 6.3 Helper 与 Agent 交互

`container/aisc-web-expose` 只负责修改容器内 manifest，不直接访问 Docker API，
不需要容器获得 Docker socket 权限。

执行成功时输出机器可读且用户可读的最小信息：

```text
aisc web service registered: port=3000 name="docs preview"
```

不要让 helper 输出假 URL，因为容器内 helper 不应自行猜测宿主机 port；宿主机
URL 由 host CLI/Workbench 根据 runtime metadata 生成。

Agent 指令要求：

1. 先选择空闲端口并启动服务；
2. 调用 `aisc-web-expose`；
3. 用 `aisc-web-list` 确认注册；
4. 向用户说明“服务已启动”，但不要把容器内 `localhost` 当成用户 URL；
5. Workbench 会显示可打开的宿主机 URL；
6. 如果用户在纯 CLI 模式，Agent 应请求用户运行
   `aisc runtime services --runtime-id ...` 获取宿主机 URL，而不是猜端口。

### 6.4 Host CLI 契约

新增命令：

```text
aisc runtime services --runtime-id <uuid> --workspace <path> --format json
aisc runtime services expose --runtime-id <uuid> --workspace <path> --port <port> ...
aisc runtime services unexpose --runtime-id <uuid> --workspace <path> --port <port>
```

第一版推荐只把容器 helper 作为权威注册入口，host CLI 的 `expose/unexpose` 作为
运维和测试入口；两者最终都写入同一个容器内 manifest。

JSON data 建议：

```json
{
  "runtime_id": "uuid",
  "gateway": {
    "container_port": 45871,
    "host_port": 47831,
    "host": "127.0.0.1",
    "state": "ready"
  },
  "services": [
    {
      "port": 3000,
      "protocol": "http",
      "name": "docs preview",
      "state": "registered",
      "url": "http://p3000.localhost:47831/"
    }
  ],
  "observed_at": "2026-08-25T00:00:00Z"
}
```

host CLI 必须从 Docker inspect 读取真实 host port，不从 registry 单独猜测。registry
保存的是最近一次观察值，Docker inspect 是连接性相关事实源。

## 7. Workbench 行为

### 7.1 Runtime 数据模型

扩展以下类型：

- `RuntimeSnapshot.web_access`；
- `WebGatewayInfo`；
- `WebServiceInfo`；
- `RuntimeServicesResult`；
- capability negotiation 中增加可选能力 `runtime_services`。

旧 CLI/旧 runtime 返回缺少字段时按 `web_access=unavailable` 处理，不能因为
新增字段让整个 runtime inspect 失败。

### 7.2 UI

在 RuntimeSidebar 增加一个紧凑的 Services 区域：

- 每行显示 label、container port、registered/unavailable 状态；
- 提供复制 URL；
- 提供打开 URL；
- gateway 未就绪时显示原因，不显示不可用链接；
- runtime stop/remove 后立即清空可打开状态；
- refresh/inspect 后重新拉取服务列表；
- 不把完整 terminal 输出中的每个 URL 都自动变成链接。

当前项目曾主动移除 opener plugin。该功能需要重新引入受控的外部 URL 打开能力，
但不能恢复一个任意 URL opener。建议新增 Tauri command：

```text
open_runtime_service_url(runtime_id, workspace, port)
```

Rust 侧根据 runtime inspect/services 重新生成 URL，并只允许打开：

- 当前已注册的服务端口；
- 当前 runtime 的 `127.0.0.1` gateway；
- `p<port>.localhost` Host。

前端不直接把任意字符串交给系统 opener。

### 7.3 Terminal fallback

本阶段不在 xterm 的原始输出流上做全局字符串替换。作为第二个交付物，可以增加
只读 URL detector：

- 识别 `localhost:<port>`、`127.0.0.1:<port>`；
- 只有该 port 已注册时才显示“转换为 runtime service URL”操作；
- 不改 terminal scrollback；
- 不自动执行命令；
- 不对含 token 的 query string 做持久化；
- 复制时默认复制 canonical gateway URL。

如果 detector 的 ANSI/多字节边界处理不稳定，保留 sidebar 作为完整能力，不阻塞
gateway 发布。

## 8. 实施顺序

### 8.1 `svc-0-contract`：冻结合同（0.5–1 天）

目标：先固定跨 Python、shell、Rust、TypeScript 的字段和错误码。

执行：

1. 新建本文对应的 `decisions.md`；
2. 固定 `aisc.web-service/v1`、`aisc.runtime-services/v1`；
3. 固定 gateway 容器端口、host port 范围和 URL builder；
4. 固定 legacy runtime 的降级行为；
5. 固定 helper 参数和 manifest 权限；
6. 添加纯函数测试 fixture。

优先文件：

- `src/aisc/domain/models.py`
- `src/aisc/domain/...`（新增 web service model）
- `workbench/src/types/index.ts`
- `workbench/src-tauri/src/runtime.rs`
- `container/global-claude.md`

阶段门：Python/TypeScript/Rust 三端对同一 JSON fixture 解码一致。

### 8.2 `svc-1-container-gateway`：容器侧能力（1–2 天）

目标：在不依赖 Workbench 的情况下，容器内可注册端口并通过 gateway 访问。

执行：

1. 新增 `container/aisc-web-gateway`；
2. 新增 `container/aisc-web-expose`、`aisc-web-unexpose`、`aisc-web-list`；
3. Dockerfile 安装/复制并做 executable smoke；
4. `entrypoint.sh` 在 idle runtime 中启动 gateway；
5. 增加 manifest 原子写入、权限和 malformed input 测试；
6. gateway 覆盖 HTTP、WebSocket、未知端口、目标未监听。

阶段门：

- 容器内服务绑定 `127.0.0.1` 仍可从 gateway 访问；
- 未注册端口不可访问；
- gateway 退出不会让 idle runtime 假报 ready；
- gateway 不访问 Docker socket。

### 8.3 `svc-2-runtime-publish`：Host runtime 生命周期（1–2 天）

目标：runtime start/reuse/restart/inspect/stop/remove 正确管理 gateway mapping。

优先文件：

- `src/aisc/application/runtime.py`
- `src/aisc/cli/commands/runtime.py`
- `src/aisc/domain/models.py`
- `src/aisc/adapters/container_registry.py`
- `src/aisc/cli/main.py`
- `tests/test_runtime_lifecycle.py`
- `tests/test_runtime_commands.py`
- `tests/integration/docker/_session_helpers.py`

执行：

1. 增加 host port allocator；
2. runtime create argv 增加 loopback publish；
3. 解析 Docker inspect port mapping；
4. registry 增加 gateway metadata；
5. 实现 `runtime services` 查询；
6. reuse 时读取实际 mapping，不重新分配；
7. legacy runtime 清晰报告 unavailable；
8. port conflict 做有限重试并返回稳定错误。

阶段门：同一 runtime 重启后 URL 不漂移；新 runtime 不复用已占用的 host port。

### 8.4 `svc-3-agent-contract`：Agent 行为（0.5–1 天）

目标：减少 Agent 继续输出错误 `localhost` URL 的概率，并让违规输出仍可恢复。

执行：

1. 更新 `container/global-claude.md`；
2. 同步更新 Codex `AGENTS.md` 生成逻辑；
3. 添加“服务启动 checklist”；
4. 让 helper 的命令名和输出成为固定合同；
5. 增加 prompt fixture/静态检查，禁止文档中出现把容器 localhost
   直接交给用户的示例。

阶段门：Claude/Codex/bash 启动 Web 服务的指令路径都能发现 helper。

### 8.5 `svc-4-workbench`：Workbench 展示与打开（1–2 天）

目标：用户无需手工推导端口或修改 URL。

优先文件：

- `workbench/src/types/index.ts`
- `workbench/src/lib/ipc.ts`
- `workbench/src-tauri/src/runtime.rs`
- `workbench/src-tauri/src/lib.rs`
- `workbench/src/features/workspace/RuntimeSidebar.vue`
- `workbench/src/stores/workspaceRuntime.ts`
- `workbench/src/i18n/zh-CN.ts`
- `workbench/src/i18n/en-US.ts`

执行：

1. 加 runtime services IPC；
2. sidebar 展示服务行；
3. copy URL；
4. 受限 open URL；
5. stop/remove/refresh 状态同步；
6. 缺少能力时兼容旧 CLI；
7. 补 component/store/Rust IPC tests。

阶段门：服务启动后 UI 显示 canonical URL；打开动作不能绕过 URL allowlist。

### 8.6 `svc-5-run-path`：普通 `aisc run`（0.5–1 天）

目标：命令行直接运行容器时也不回到旧行为。

优先文件：

- `src/aisc/domain/models.py`
- `src/aisc/cli/commands/run.py`
- `src/aisc/cli/main.py`
- `tests/test_runtime_commands.py` 或新增 `tests/test_web_services.py`

执行：

1. `RunPlan` 复用 gateway mapping；
2. `docker_argv` 具备 loopback publish；
3. text mode 输出 gateway port；
4. `--format json` 返回 service access metadata；
5. `--rm` 容器退出后不遗留 registry 记录。

### 8.7 `svc-6-acceptance`：验证和交接（1 天）

执行：

1. Python、Rust、Vue 全量测试；
2. Docker Linux 集成测试；
3. Windows Docker Desktop 实机测试；
4. Claude/Codex/bash 各跑一次实际 Web 服务；
5. HTTP、WebSocket、HMR、SPA deep link；
6. runtime reuse/restart/stop/remove；
7. 端口冲突、Docker 重启、gateway 崩溃；
8. 填写 `acceptance.md`，记录命令、环境和证据路径。

## 9. 测试设计

### 9.1 纯函数测试

- `parse_expose_port()` 接受合法端口，拒绝负数、小数、特权端口、空值和尾随文本；
- service record schema round-trip；
- URL builder 生成稳定 URL；
- Host parser 只接受 `p<port>.localhost`；
- Host port allocator 跳过占用端口；
- legacy snapshot 缺少 web 字段时降级；
- service list 不暴露 secret/query。

### 9.2 CLI/runtime 测试

- runtime start argv 包含 `127.0.0.1:<host>:<container>/tcp`；
- runtime fingerprint 不因 host port 改变；
- reuse 使用原有 mapping；
- Docker inspect mapping 缺失时返回 unavailable；
- registry commit 失败会清理新容器；
- port conflict 重试后仍失败时返回稳定错误；
- runtime stop/remove 后 services 不再报告可打开；
- `aisc run --dry-run` 显示 publish 计划但不调用 Docker。

### 9.3 容器集成测试

容器内启动：

```bash
python3 -m http.server 3000 --bind 127.0.0.1
aisc-web-expose 3000 --name smoke
```

宿主机通过返回的 gateway URL 验证：

- HTTP 200；
- deep path；
- query；
- WebSocket echo；
- 未注册端口 404；
- 目标停止后 502；
- 第二个服务端口可并行访问；
- 不同 runtime 的同一容器端口互不串流。

### 9.4 安全测试

- 宿主机 `0.0.0.0` 端口扫描不能发现 gateway；
- gateway 不能访问 `127.0.0.1` 以外的任意目标；
- Host header 注入、路径穿越和非法端口被拒绝；
- manifest 为 malformed 时 fail closed；
- UI open command 不能打开任意外部 URL；
- 日志不出现 API key、cookie 和完整 URL query。

## 10. 观测和诊断

增加结构化事件：

```text
web_gateway_allocated
web_gateway_ready
web_service_registered
web_service_unregistered
web_gateway_unavailable
web_service_target_unavailable
```

事件字段只包含：

- runtime_id；
- container_name；
- container_port；
- host_port；
- protocol；
- result/error_code；
- observed_at。

不记录请求路径、query、header、body 和服务输出。

`aisc doctor` 后续可增加：

- gateway mapping 是否存在；
- gateway 进程是否存活；
- manifest 是否可读；
- loopback URL 是否可连接。

诊断失败不能阻断普通 runtime 的启动；只有 Docker mapping 创建失败才阻断
`web_access=required` 的未来模式。第一版不增加 required 开关。

## 11. 回滚策略

按阶段提交，允许独立回滚：

1. `svc-1` 回滚后，旧 runtime 仍可启动，但新 runtime 不应残留半套 gateway metadata；
2. `svc-2` 回滚前先停止创建带新 publish 参数的 runtime；
3. `svc-3` 可单独回滚 Agent 指令，不影响网络组件；
4. `svc-4` 回滚 UI opener 时保留 copy URL；
5. gateway 出现安全问题时，优先关闭 host publish 和 UI open，再保留终端能力；
6. 不通过放宽 Host 校验、改成 `0.0.0.0` 或开放全部端口来绕过失败；
7. 不删除或覆盖工作区现有未提交改动。

数据兼容：

- registry 新字段全部 optional；
- 旧 runtime 没有 gateway 时显示 unavailable；
- 不能自动把旧容器转换成新网络配置；
- 用户执行 restart/recreate 后才获得 gateway。

## 12. 默认决策与待确认边界

为了让开发可以直接开始，本方案默认：

| 议题 | 默认决策 |
|---|---|
| 访问范围 | 仅当前宿主机，不支持 LAN |
| 协议 | HTTP/1.1-over-TCP 和 WebSocket；HTTPS 延后单独设计 |
| 容器服务绑定 | 允许 `127.0.0.1`，不强制 `0.0.0.0` |
| URL | `http://p<port>.localhost:<host-gateway-port>/` |
| host publish | `127.0.0.1`，动态 host port |
| 未注册端口 | 拒绝转发 |
| host port 范围 | `47000..47999`，可后续配置化 |
| UI 打开 | 只允许 backend 生成并校验的 runtime service URL |
| legacy runtime | 可继续使用，但 web access 显示 unavailable |
| 远程/公网 | 不在本阶段 |

以下需求若存在，需要在开工前改合同，而不是在实现中隐式扩展：

1. 是否必须支持手机或同一局域网其他设备访问；
2. 是否必须支持任意原始 TCP/UDP 服务；
3. 是否允许用户自定义 host port 范围；
4. 是否需要多个 runtime 共享同一个用户可见域名；
5. 是否要求服务 URL 在 runtime restart 后保持不变；
6. 是否需要自动发现未调用 `aisc-web-expose` 的 Agent 服务。

## 13. 完成定义

满足以下条件才算完成：

- Agent 在容器内以 `127.0.0.1:3000` 启动 HTTP 服务，调用 helper 后，用户可在宿主机
  打开 canonical gateway URL；
- Agent 不再需要猜测宿主机 IP 或 host port；
- Workbench 显示、复制并可安全打开服务 URL；
- runtime reuse/restart/stop/remove 的服务状态一致；
- 未注册端口不可访问；
- gateway 只暴露宿主机 loopback；
- Claude、Codex、bash 路径均通过；
- Linux Docker 和 Windows Docker Desktop 关键集成测试通过；
- 旧 runtime/旧 CLI 缺少新字段时不崩溃；
- 安全测试、回滚检查和现有全量测试通过。

## 14. 调研参考

- Docker Engine `docker run` port publishing：
  `https://docs.docker.com/engine/network/`
- Docker Engine `docker run --publish` reference：
  `https://docs.docker.com/reference/cli/docker/container/run/`
- Docker Desktop networking：
  `https://docs.docker.com/desktop/features/networking/`
