# Stage 11 实施顺序

## 0. `11a-contract`：冻结行为和接口（0.5–1 天）

**目标**：在不改变现有行为的前提下，固定文件操作、clipboard、拖拽和终端输入契约。

执行：

1. 记录当前 `git status`、branch、commit、Workbench test/build 基线；
2. 删除“单击预览”作为目标行为，更新现有测试预期；
3. 定义 `WorkspaceMutationResult`、错误码和应用内 clipboard；
4. 确定 session/terminal 宿主类型如何提供给 quoting adapter；
5. 冻结允许修改文件清单和 IPC 命名；
6. 增加 `decisions.md` 中的实现决策。

提交：`docs(plan): define workspace explorer operations contract`

## 1. `11b-fs-ops`：Rust contained filesystem operations（1–2 天）

**目标**：先完成可单测、不可越界的后端文件操作。

优先文件：

- `workbench/src-tauri/src/workspace.rs`
- `workbench/src-tauri/src/lib.rs`
- `workbench/src/lib/ipc.ts`
- `workbench/src/types/index.ts`

执行：

1. 抽取/复用 contained target 和 basename validation；
2. 实现 create file/dir、copy entry、rename；
3. 默认拒绝覆盖，返回稳定错误码；
4. 对复制失败做临时目标清理；
5. 注册 Tauri commands；
6. 添加 Rust 单元测试和 IPC wrapper；
7. 审计日志字段，不记录敏感信息。

提交拆分：

- `feat(workspace): add contained file mutations`
- `test(workspace): cover mutation containment and conflicts`
- `feat(ipc): expose explorer mutation commands`

硬门：Rust 测试通过；越界、冲突和权限失败不能改变文件系统。

## 2. `11c-explorer-actions`：Explorer 状态与菜单（1–2 天）

**目标**：完成 VS Code 风格核心操作，不触碰终端 data plane。

优先文件：

- `workbench/src/stores/workspaceExplorer.ts`
- `workbench/src/features/workspace-explorer/WorkspaceExplorer.vue`
- `workbench/src/i18n/zh-CN.ts`
- `workbench/src/i18n/en-US.ts`

执行：

1. 将文件单击改为 select-only，保留目录 toggle 和文件双击 open；
2. 增加工具栏 new file/new folder/refresh icon buttons；
3. 将 context menu 拆分为 root/dir/file target；
4. 增加 inline name input、校验、Enter/Escape、错误保留；
5. 增加应用内 clipboard 状态和 paste target resolution；
6. 操作成功后定向刷新父目录并恢复 selected；
7. 保留 copy path 和 reveal 现有行为；
8. 增加 component/store tests。

提交拆分：

- `feat(explorer): align file activation with editor conventions`
- `feat(explorer): add create rename and copy paste actions`
- `test(explorer): cover context menu and inline naming`

硬门：单击不再触发 preview；原有目录懒加载、artifact、watcher 和键盘树行为不回归。

## 3. `11d-icons-dnd`：图标和终端拖入（1–2 天）

**目标**：增加类型识别和安全的文件路径输入，不改变 PTY 协议。

优先文件：

- `workbench/src/features/workspace-explorer/WorkspaceExplorer.vue`
- `workbench/src/features/terminal/Terminal.vue`
- `workbench/src/features/terminal` 下的纯函数/测试文件
- 必要时 `WorkspaceView.vue` 或 pane host

执行：

1. 建立 extension-to-icon mapping 和 folder open/closed icon；
2. 使用本地受控 SVG/CSS icon，不增加第三方依赖；
3. 增加 file drag payload 和 dragging/drop target 状态；
4. 实现 shell quoting 纯函数和宿主适配；
5. drop 时解析当前 active pane 并调用现有 `writeSession`；
6. 明确不追加 Enter，drop 后恢复 terminal focus；
7. 增加 drag/drop 和 quoting tests；
8. 手测 xterm 输入、复制、搜索、split、resize/fit 无回归。

提交拆分：

- `style(explorer): add stable file type icons`
- `feat(explorer): insert dropped file paths into terminal`
- `test(explorer): verify drag payload and shell quoting`

硬门：拖入不会执行命令，不接受目录，不把绝对路径放入 drag payload。

## 4. `11e-acceptance`：完整验证和交接（0.5–1 天）

执行：

1. 运行 Workbench/Vue/Rust 全量测试；
2. 执行 Windows 文件操作和终端手测矩阵；
3. 验证暗/亮、Compact/Standard/Wide、zoom 和长文案；
4. 检查 diff 未越界到 PTY、artifact provenance 和无关 UI；
5. 填写 `acceptance.md`、记录证据路径和遗留项；
6. 逐门记录回滚点。

提交：

- `test(explorer): add stage-11 acceptance matrix`
- `docs(plan): record stage-11 explorer evidence`

## 5. 回滚策略

1. Rust mutation、Explorer menu、icons、Terminal drop 按提交粒度独立回滚；
2. 若 mutation 出现安全问题，立即回滚 command 注册和前端入口，保留只读 Explorer；
3. 若 drag/drop 影响终端，先撤销 terminal adapter，不回滚文件操作；
4. 若图标导致主题/布局问题，撤销 icon mapping，保留已验收行为；
5. 不通过放宽 containment、错误码或测试来“修复”门禁失败；
6. 不使用 `git reset --hard` 或覆盖工作区现有未提交变更。

