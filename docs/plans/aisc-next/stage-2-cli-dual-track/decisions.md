# Stage 2 决策记录

| ID | 决定 | 理由/影响 |
|---|---|---|
| CLI-D01 | Python CLI 是独立产品，sidecar 是并行分发形态 | 不进行 Rust 全量重写；用户可独立 pip/pipx 使用。 |
| CLI-D02 | pip 与 sidecar 共享 `aisc.cli/v1` 行为面 | GUI 不应因二进制来源不同而分叉；contract fixture 是发布阻断门。 |
| CLI-D03 | discovery 优先级固定且来源可见 | 显式 pin 优先于 PATH，避免旧/恶意命令被静默选中。 |
| CLI-D04 | capability 缺失 fail closed | 不猜测新命令支持情况，不把未知状态伪装成未配置。 |
| CLI-D05 | Rust 不复制 Python domain 规则 | Runtime/Session/Provider/DockerGateway 的事实所有权继续在 Python。 |
| CLI-D06 | 版本/架构/hash 校验后原子替换 | sidecar 升级失败必须保留可启动旧版本。 |
| CLI-D07 | 不自动修改用户 PATH 或读取凭据 | pip 与 GUI 双轨都遵守安全/隐私不变量；安装器另由 Stage 5 处理。 |
| CLI-D08 | 发布动作必须用户确认 | push、PyPI、tag、真实升级属于外发操作，不能在阶段文档完成时自动发生。 |
