# 跨阶段契约

> 基线：`f5a74e5`

## 1. 数据根目录

- Windows 默认根目录为 `%LOCALAPPDATA%\AISC\data`；`AISC_DATA_ROOT` 只用于明确的开发、测试或企业部署覆盖。
- workspace 根目录只保留用户源代码和用户明确创建的文件；AISC 自动生成的配置、锁、runtime、日志、cache、artifact、diagnostics 和 migration 文件必须落在 data root。
- 每个 workspace 使用规范化绝对路径的稳定 hash 隔离；禁止把原始绝对路径或 secret 放进目录名。
- 解析器返回带 schema/version 的结构化结果，CLI、Rust 和容器不得各自拼接路径。

建议布局：

```text
%LOCALAPPDATA%\AISC\data\
  config/ state/ workspaces/<workspace-hash>/
  artifacts/ cache/ diagnostics/ migrations/
```

## 2. CLI、Workbench 与容器

- 控制面协议继续使用 `aisc.cli/v1`；新增 `aisc cc-switch list|add|edit|delete`，输出 JSON envelope 和稳定错误码。
- Workbench 只能调用 CLI/sidecar 或约定的 Provider UI protocol，不直接调用 Docker Engine、cc-switch SQLite 或宿主进程。
- 容器 wrapper、CLI 和 UI adapter 必须通过同一个 `CC_SWITCH_CONFIG_DIR` 找到同一个 `cc-switch.db`。
- UI tab 不把 TUI 文本当作数据；优先使用 cc-switch 稳定 machine-readable API/daemon，没有 API 时才使用容器内受控 adapter。

## 3. Provider 数据与用户覆盖

- Provider schema 只使用 cc-switch 当前稳定版本支持的官方字段；未知字段按版本策略保留或 fail closed。
- 简易添加与自定义添加都经过同一校验和写入路径；API key 通过 stdin/受控 IPC 传递，不进入 argv、日志、shell history、artifact 或诊断包。
- preset 拥有的字段（官方 endpoint、默认模型、说明）可刷新；用户明确修改的字段、密钥和自定义 provider 不得被刷新覆盖。
- 读取接口只返回 `has_api_key`、掩码和非敏感元数据；编辑密钥必须重新输入。

## 4. cc-switch 版本

- `CC_SWITCH_CHANNEL=stable` 是默认值；`latest` 只表示最新 stable release，不允许 prerelease、draft 或无目标架构资产的 release。
- 本地开发可解析 latest；CI/Release 必须把 tag、release commit、下载 URL、架构、SHA-256 写入镜像 label 和构建 manifest。
- 显式 `CC_SWITCH_VERSION=vX.Y.Z` 用于回滚和复现；解析失败不得静默退回旧版本。

## 5. DeepSeek 与 Claude 映射

- 官方文档是 endpoint、认证字段、模型字段和 `[1m]` 语义的 SSOT；实现前生成带文档 URL、抓取日期和 revision 的 fixture。
- 默认 Claude 模型是官方 DeepSeek flash 模型并追加 `[1m]`；`opus`/`claude-opus-*` 映射 pro 并追加 `[1m]`；sonnet、haiku 和未识别 alias 映射 flash 并追加 `[1m]`。
- 模型 ID 必须来自当时官方文档 fixture，不在代码中假定未来版本名称；用户可用显式 override 覆盖 alias 映射和 `[1m]`。
- preset revision 变化时只更新仍属于 preset 的字段；用户 override 具有更高优先级。

## 6. C# POC

- POC 使用 Windows native/WinUI shell 和原生 terminal control；不引入第二套 Provider、Docker 或 session 领域实现。
- C# 只负责 UI、进程/协议调用、tab 生命周期和 Windows 适配；业务事实仍由 Python CLI/container 提供。
- POC 与 Tauri 的行为比较以同一组 contract fixtures、CLI 命令和 acceptance IDs 为准。

## 7. 通用安全与生命周期

- 所有 schema/protocol 带版本、未知版本行为、迁移、锁、原子替换、损坏隔离和回滚说明。
- child、PTY、timer、listener、watcher、HTTP connection 和 lock 必须有界清理。
- 错误日志只保留稳定错误码和脱敏技术详情；诊断导出前展示允许字段清单。
