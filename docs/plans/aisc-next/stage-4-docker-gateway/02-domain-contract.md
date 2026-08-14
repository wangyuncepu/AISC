# Stage 4 Domain Contract

## Gateway Protocol

```python
class DockerGateway(Protocol):
    preflight() -> DockerPreflightResult
    inspect_image(name) -> ImageInspectResult
    list_containers(all=False) -> ContainerListResult
    inspect_container(name) -> ContainerInspectResult
    create_runtime(plan) -> OperationResult
    start_runtime(name) -> OperationResult
    stop_container(name, timeout) -> OperationResult
    remove_container(name, force) -> OperationResult
    open_interactive(container, argv) -> InteractiveSession
    build_image(plan, on_event) -> OperationResult
```

结果必须包含 operation_id、backend、observed state、exit code、duration、stable error/cleanup status；stdout/stderr 只在调用方明确要求时携带并有大小上限。

## Backend

```text
application/domain
       ↓ DockerGateway
AutoGateway → SdkGateway | CliGateway
       ↓
Docker Engine
```

`Auto` 只根据 capability/feature flag 选择；application 不出现 `if sdk`。SDK 交互流必须支持 resize、cancel、wait/reap；CLI backend 保持 argv-only。

## 迁移顺序

1. query：preflight/inspect/list；
2. lifecycle：start/stop/remove/wait；
3. interactive：统一已存在 SDK 路径；
4. image/build：仅在 benchmark 通过后决定。

## 兼容

旧 `DockerExecutor` 名称、Fake 注入 API 和 CLI 命令保持兼容至少一个 release；错误码/JSON envelope 不因 backend 改变。