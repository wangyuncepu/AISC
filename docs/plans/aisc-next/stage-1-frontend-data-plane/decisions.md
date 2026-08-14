# Stage 1 决策记录

| ID | 决定 | 理由/影响 |
|---|---|---|
| F-D01 | Vue/Pinia 只做投影，Rust 持有 PTY/child/registry | 保持跨阶段所有权契约，避免前端自行清理。 |
| F-D02 | 高频输出批处理且 bounded | 逐 chunk 深响应式会卡顿；reader 不能因隐藏窗口阻塞。 |
| F-D03 | generation + session_id 是事件归属键 | 防止关闭、恢复、reopen 的迟到事件污染新 pane。 |
| F-D04 | snapshot 与 operation error 永不互相覆盖 | 用户既能看到最新已知事实，又能看到失败行动。 |
| F-D05 | a11y P0 与数据面同阶段交付 | 结构拆分若晚做可访问性，组件边界会固化错误。 |
| F-D06 | 用固定 fixture 和 soak 作为性能证据 | 让输出、内存、资源上限可跨提交比较。 |
| F-D07 | 不在本阶段引入 Explorer/Artifact/CLI 发布 | 遵守严格阶段串行，避免多个 owner 同时修改状态链。 |
| F-D08 | 结构拆分不得改变 `aisc.cli/v1` | Stage 2 依赖稳定公共控制面，前端重构只改变组织方式。 |
