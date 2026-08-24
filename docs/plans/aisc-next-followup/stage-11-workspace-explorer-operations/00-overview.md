# Stage 11：Workbench 资源管理器操作升级

> 状态：Accepted planning
> 规划日期：2026-08-24
> 规划基线：当前 `develop`
> 现状入口：`workbench/src/features/workspace-explorer/WorkspaceExplorer.vue`
> 后端边界：`workbench/src-tauri/src/workspace.rs`

## 1. 阶段目标

将现有以浏览和预览为主的 Workspace Explorer 升级为可执行的轻量文件管理器，形成接近 VS Code Explorer 的核心工作流：

1. 文件单击只选择，不再触发文件预览；
2. 文件双击打开系统默认应用，目录单击展开/折叠；
3. Explorer 空白区、工作区根目录和目录节点支持新建文件、新建文件夹、粘贴、刷新；
4. 文件和文件夹右键菜单支持复制，文件和文件夹支持重命名；
5. 工具栏提供新建文件、新建文件夹和刷新按钮，按钮使用图标与 tooltip；
6. 文件、文件夹和目录展开状态使用稳定的 VS Code 风格类型图标；
7. 文件节点可长按拖入终端，在当前终端输入位置插入经过 shell quoting 的绝对路径；
8. 所有真实文件系统写操作在 Rust/Tauri 层执行，继续遵守 workspace containment。

## 2. 范围

### 2.1 包含

- `WorkspaceExplorer.vue` 的单击/双击、右键菜单、工具栏、图标、拖拽和名称输入交互；
- `workspaceExplorer` store 的 Explorer 操作状态、应用内文件剪贴板、刷新和错误反馈；
- `lib/ipc.ts`、`types/index.ts` 的新建、复制、粘贴、重命名 IPC 类型；
- `workbench/src-tauri/src/workspace.rs` 的 contained filesystem mutation commands；
- `lib` 或 workspace feature 下的 shell quoting/路径拖拽辅助函数；
- 中英文 Explorer 文案、菜单 tooltip、错误消息和状态反馈；
- Vue、Pinia、Rust 单元测试，必要的终端拖入集成 smoke；
- Windows 真实文件系统手测、暗/亮主题、Compact/Standard/Wide 和 CSS zoom 回归证据。

### 2.2 不包含

- 不实现编辑器、内置文件内容预览或文件保存；
- 不实现删除、剪切、批量多选、拖拽移动、拖拽复制或文件排序；
- 不替换系统文件管理器，不把文件复制到操作系统原生文件剪贴板；
- 不把任意绝对路径交给前端作为文件操作参数；前端仍只传 workspace-relative path；
- 不修改 PTY、xterm renderer、scrollback、resize/fit、终端输出协议；
- 不改变现有 artifact provenance、watcher 事件语义或 Explorer ignore 规则；
- 不引入新的 UI 组件库或图标依赖；
- 不借本阶段处理既有终端长输入、fit 迟滞或 tab 输出错乱问题。

## 3. 用户可见行为定义

| 场景 | 行为 |
|---|---|
| 文件单击 | 选中并显示 selected 状态，不读取文件、不更新 preview |
| 文件双击 | 调用现有 `workspace_open` |
| 目录单击 | 展开或折叠，不打开系统应用 |
| Explorer 工具栏 | 新建文件、新建文件夹、刷新；按钮有可访问名称和 tooltip |
| 根目录/空白区右键 | 新建文件、新建文件夹、粘贴、刷新 |
| 目录右键 | 新建文件、新建文件夹、粘贴、复制、重命名、刷新，以及现有打开/显示路径动作 |
| 文件右键 | 打开、显示路径、复制文件、复制路径、重命名 |
| 粘贴 | 将应用内复制缓冲区中的文件或文件夹复制到目标目录；不覆盖已有目标 |
| 拖入终端 | 插入该文件的绝对路径；不执行命令，不自动追加换行 |

## 4. 交付物与阶段门

| 交付物 | 说明 | 阶段门 |
|---|---|---|
| 行为基线与契约 | 冻结当前 Explorer/Terminal 边界，定义 IPC 和错误码 | `11a-contract` |
| Rust 文件操作 | 新建、复制、粘贴、重命名及 containment 测试 | `11b-fs-ops` |
| Explorer 交互 | 菜单、工具栏、名称输入、单击语义和 store 状态 | `11c-explorer-actions` |
| 图标与拖拽 | 文件图标、目录图标、终端 drop adapter 和 quoting | `11d-icons-dnd` |
| 全量验收 | 自动化、真机手测、性能、回滚和遗留项 | `11e-acceptance` |

每个阶段门必须能独立运行相关测试；涉及 Rust IPC 的提交必须同时包含成功、失败和越界测试。出现任意路径越界、覆盖用户文件、终端输入污染或键盘路径回归时，阶段结论为 `STOP`。

## 5. 成功定义

- `PASS`：所有自动化门禁、关键 Windows 手测和回滚检查通过；
- `PASS-WITH-FOLLOWUPS`：核心文件操作和终端拖入通过，仅有不阻断发布的视觉/文案遗留；
- `STOP`：出现 containment 失败、意外覆盖、错误执行终端命令、拖入后输入错位、xterm 回归或关键键盘不可达。

