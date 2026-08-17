# Stage 3 决策

> 状态：Accepted planning

- `D3-01` Skill 是语义层，不是 artifact registry。
- `D3-02` 事实 schema 使用 workspace-relative path，不持久化宿主绝对路径。
- `D3-03` watcher 只能产生 unattributed/stale/invalidation。
- `D3-04` index 置于 Workbench app-data，不写工作区。
- `D3-05` Explorer 首版只读；编辑、删除、重命名后置。
- `D3-06` 文件操作由 Rust containment 后执行，Vue 不直接拿任意绝对路径。
- `D3-07` 发行包 artifact 和 Agent Artifact 使用独立 module/schema/文案。
- `D3-08` 不解析 Agent 自然语言作为事实；Skill/CLI/Watcher 各司其职。
