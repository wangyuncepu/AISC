# Stage 5 Domain Contract

## Onboarding state

```text
not_started → in_progress(step)
             ├→ skipped(reason)
             ├→ blocked(action)
             ├→ completed
             └→ abandoned(resumable)
```

schema：`onboarding.schema_version`, `flow_version`, `status`, `current_step`, `completed_steps`, `skipped_steps`, `last_error_code`, `source`。不保存 secrets。高版本只读/安全回退；升级保留完成状态但允许 flow version 重新运行需要验证的步骤。

## Readiness states

```text
cli: unknown|checking|ready|unavailable
Docker Desktop: unknown|not_installed|installing|installed|starting|ready|blocked
Engine: unknown|unavailable|starting|ready|permission_denied
WebView2: unknown|ready|missing
Agent: ready|needs_login|needs_configuration|unsupported
Network: direct|host_proxy|container_tun|skipped|failed
Runtime: new|reuse|restart|restore|blocked|running
```

内部 enum 只能映射为用户文案，技术 detail 可折叠。

## Handoff

NSIS 只能传非敏感：installer source、selected locale、installed version、dependency hints、first-run marker。Workbench 必须重新 query CLI/Docker；handoff 不构成事实。

## Docker readiness

安装成功 ≠ Engine ready。`start_docker` 后以 deadline+jitter poll preflight；超时保留可重试/doctor/稍后继续，不能把 stale snapshot 当 ready。

## Network/TUN

网络设置由用户显式选择；配置写入 scoped runtime launch config，保存前展示影响/回滚；禁止覆盖宿主代理。