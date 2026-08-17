# Stage 8 容器 UI 协议与实现策略

## API discovery gate

Stage 8a 必须对当前 latest stable 做一次黑盒预研，记录：是否有 daemon/API、监听方式、认证、schema version、SQLite lock、secret input、升级兼容性和许可证。结果存入 acceptance，不得根据旧版本猜测。

## 两条实现路径

### Path A：官方 machine-readable API

容器启动受控 cc-switch service/daemon，adapter 只做代理、schema 校验、超时和 redaction。Workbench 通过 Python `aisc` CLI 或受认证的 session channel 请求数据，UI tab 自己渲染表单。

### Path B：受控 adapter

如果没有稳定 API，在容器内实现最小 adapter，使用 cc-switch 官方命令/库可支持的 machine-readable 接口；若只能得到 TUI，先阻断 Stage 8，不解析屏幕文本。adapter 负责 DB lock、migration、事务和版本兼容，但不能被 Workbench 直接调用 SQLite。

两条路径均不启动 Linux desktop window，也不依赖宿主机 Desktop。

## Security protocol

- tab 建立短期 session token，绑定 workspace/session，过期和取消后立即失效；
- API key 通过 stdin 或内存 IPC，服务端写入后只返回 `has_api_key`/mask；
- 请求、响应、错误和诊断统一 redaction；禁止 query string、URL、telemetry 和 browser storage 保存 secret；
- CORS/Origin、tab 权限和 CSRF nonce 由 Workbench/sidecar 校验；
- 连接断开时不回滚已提交 provider，但不会留下临时明文文件。

## UI tab

tab type 为 `cc-switch-ui`，与现有 `cc-switch` TUI tab 并存。打开 tab 只启动容器 UI data plane/session，不弹窗；关闭 tab 释放 session、listener 和 timer。TUI 仍作为高级诊断入口，但 Provider 管理不依赖 TUI。
