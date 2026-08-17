# 全局决策记录

> 状态：Accepted（2026-08-14）
> 代码基线：`d2bdcd9`

| ID | 决策 | 理由 |
|---|---|---|
| D-01 | 保留 Python CLI，不做 Rust 全量重写 | pip 发布直接、既有领域逻辑成熟；当前热点在数据面/调用频率而非 CLI 语言 |
| D-02 | pip CLI 与 sidecar 是同一产品两种交付 | 防止 GUI 私有 fork 和行为漂移 |
| D-03 | Rust 不接管 Docker 业务 | 避免 Python/Rust 双份 Runtime/Provider 生命周期语义 |
| D-04 | Skill 只提供 Artifact 语义 | Skill 不能保证自动调用，也不能发现 shell/build 产生的所有文件 |
| D-05 | `aisc.artifact/v1` 是 Agent Artifact 事实协议 | CLI/GUI 双轨可消费，结构稳定且可验证 |
| D-06 | watcher 只兜底变化，不声明 provenance | 文件变化可能来自用户、编译器、Git 或 Agent |
| D-07 | Agent 只上报相对路径 | 容器 `/root/app` 与宿主路径不同；宿主绝对路径由 Rust 安全解析 |
| D-08 | Explorer 首版只读 | 优先解决发现/打开/定位；降低删除、改名和冲突风险 |
| D-09 | DockerGateway 在 Python 内渐进 SDK 化 | 复用现有 Protocol/Fake，保持 CLI 独立；Build 迁移需要证据 |
| D-10 | 轻量 NSIS + Tauri 首次向导 | NSIS 擅长安装/升级，不适合复杂可恢复产品流程 |
| D-11 | Docker 安装与 Engine ready 分离 | 许可、WSL、重启和首次初始化不能让安装器无限阻塞 |
| D-12 | 网络/TUN 为可选引导 | 提供验证和建议，不未经同意改写用户网络 |
| D-13 | 先治理无界数据面和单体协调器 | Explorer/onboarding 前必须建立可扩展结构和资源预算 |
| D-14 | 阶段严格串行 | 与既有开发规约一致，降低跨层大改并发风险 |
| D-15 | UI 保持 IDE/工具型方向 | 工作台优先高密度、可扫描、终端和重复操作，不做营销化界面 |

## 被否决方案

- Rust 重写全部 CLI；
- GUI 直接调用 Docker SDK/Engine；
- 只通过 Agent 最终自然语言解析产物路径；
- Skill 文件本身充当 Artifact 数据库；
- watcher 自动把所有变化标为 Agent 产物；
- NSIS 承担 Workspace/Provider/Runtime 配置；
- 未测量前引入常驻 daemon；
- 首期交付完整 IDE 文件编辑器。
