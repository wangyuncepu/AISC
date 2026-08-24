# Stage 11 编码规范

## 1. 分层边界

- Vue 负责渲染、焦点、菜单、输入校验和用户反馈；
- Pinia 负责 Explorer selection、expanded state、clipboard、pending operation 和刷新协调；
- `lib/ipc.ts` 只负责类型化 invoke wrapper，不写文件系统逻辑；
- Rust `workspace.rs` 是所有文件系统 mutation 的唯一权威入口；
- Terminal 只接收已校验的 drop result，并复用现有 `writeSession`；
- quoting、basename 校验、icon mapping 使用纯函数，优先独立单测。

## 2. 路径和安全

- IPC mutation 永远传 workspace-relative path；
- 前端不得通过字符串拼接构造 mutation 的绝对路径；
- Rust 必须对前端输入重新做 containment 和 basename 校验；
- 不使用 `unwrap` 处理用户路径、文件系统和 Tauri 输入；
- 不覆盖目标文件，除非未来另有独立需求和确认流程；
- 错误返回稳定 code，详细 I/O 原因只用于受控日志/诊断，不直接拼成不稳定 UI 合同；
- 日志不含完整绝对路径、文件内容、secret 或终端输出。

## 3. Vue/TypeScript

- 事件 handler 使用显式 `MouseEvent`、`DragEvent`、`KeyboardEvent` 类型；
- async action 统一处理 loading、成功刷新、失败反馈和 finally 清理；
- 不在 template 内内联复杂路径、clipboard 或 quoting 逻辑；
- 新按钮优先使用 `.ui-icon-button`，必须有 `aria-label` 与 `title`；
- 菜单项使用 `role="menuitem"`，禁用状态同步 `disabled`/`aria-disabled`；
- inline input 必须处理 Enter、Escape、composition/input 状态和 focus restore；
- 任何新增状态都必须说明 workspace 切换时如何清理；
- 不用 snapshot 代替对 IPC 参数和行为的断言。

## 4. Rust

- 先解析并验证路径，再执行 metadata/read/write；
- 对新建目标检查父目录存在、父目录 contained、目标不存在；
- 复制目录时不得递归跟随 workspace 外部链接；
- 写入临时目标时使用目标目录内的临时名称，失败必须清理；
- mutation helper 与 Tauri command 分离，helper 可直接用 tempfile 单测；
- 对 Windows 长路径、Unicode、保留名和大小写冲突增加测试；
- command 注册、IPC wrapper、TypeScript result interface 必须同步提交。

## 5. 图标

- 不新增图标依赖，不复制第三方品牌图标文件；
- icon mapping 必须有 generic fallback；
- 目录展开/折叠图标是状态的一部分，文件扩展名只作辅助；
- 图标尺寸、行高和 hit area 固定，不能导致树节点跳动；
- icon 的颜色必须来自现有 token，暗色和亮色都可见；
- `aria-hidden="true"` 仅适用于旁路视觉图标，语义由文件名和 row label 提供。

## 6. 终端拖入

- drag payload 使用固定 MIME `application/x-aisc-workspace-path`；
- payload 不含绝对路径、文件内容或系统文件 URL；
- drop adapter 只调用现有 session write API，不直接访问 PTY；
- quoting 函数不得执行 shell，不得猜测用户 shell；
- drop 不追加换行，不触发 command submit；
- 终端已有 context menu、selection、search、resize/fit 行为不得改变；
- 修改 `Terminal.vue` 时必须运行 terminal 相关测试并做实际输入回归。

## 7. 提交与审查

- 行为、图标和文档尽量分提交；
- 每个提交说明允许修改的边界；
- Rust mutation 提交必须包含失败路径测试；
- UI 提交必须包含中英文文案和键盘路径；
- 不删除旧测试来消除失败；
- 不扩大现有 token/fallback 白名单绕过样式检查；
- 发现与本阶段无关的终端、watcher 或 artifact bug，登记 follow-up，不混入实现。

