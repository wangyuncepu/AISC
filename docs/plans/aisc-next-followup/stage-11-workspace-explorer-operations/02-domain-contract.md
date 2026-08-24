# Stage 11 领域契约

## 1. 路径模型

前端与 Tauri IPC 使用以下参数：

```text
workspace: canonical absolute workspace root
relative_path: workspace-relative file or directory path
relative_dir: workspace-relative destination directory
name: one basename only
```

规则：

- `workspace` 只来自当前 runtime/workspace 状态，不由用户通过 Explorer 输入；
- `relative_path` 和 `relative_dir` 使用 `/` 作为逻辑分隔符，Rust 负责转换平台路径；
- 前端不拼接绝对路径用于 mutation；展示绝对路径可以继续使用现有 `hostPath`，但不能成为 IPC 写操作参数；
- Rust 对现有目标使用 `resolve_existing`，对新目标使用 contained parent + basename 校验；
- source、destination、new name 都必须在同一 workspace 内；
- symlink/junction/reparse point 的最终处理沿用现有 containment policy，失败返回 `workspace_invalid` 或更具体的稳定错误码。

## 2. 文件操作命令

计划新增的 Tauri commands：

| command | 输入 | 输出 | 语义 |
|---|---|---|---|
| `workspace_create_file` | `workspace`, `relative_dir`, `name` | `WorkspaceMutationResult` | 创建空文件，不覆盖 |
| `workspace_create_dir` | `workspace`, `relative_dir`, `name` | `WorkspaceMutationResult` | 创建单层目录，不覆盖 |
| `workspace_copy_entry` | `workspace`, `source_relative_path`, `destination_relative_dir` | `WorkspaceMutationResult` | 在 workspace 内复制文件或目录，不覆盖 |
| `workspace_rename` | `workspace`, `relative_path`, `new_name` | `WorkspaceMutationResult` | 在原父目录下重命名，不覆盖 |

`workspace_copy_path` 保留为“复制路径到文本剪贴板”，与新的“复制文件”动作严格区分。

建议返回结构：

```rust
struct WorkspaceMutationResult {
    schema_version: u64,
    operation: String,       // create_file/create_dir/copy/rename
    relative_path: String,   // resulting path
    kind: String,            // file/dir
}
```

错误至少区分（D11-20 落位为稳定 `WB_ERR_*` code）：

```text
workspace_invalid       → WB_ERR_WORKSPACE_INVALID     workspace 或路径不合法
workspace_not_found     → WB_ERR_WORKSPACE_NOT_FOUND   source/parent 不存在
workspace_conflict      → WB_ERR_WORKSPACE_CONFLICT    destination/name 已存在
workspace_read_only     → WB_ERR_WORKSPACE_READ_ONLY   无写权限
workspace_io            → WB_ERR_WORKSPACE_IO          其他 I/O 失败（含复制超上限）
```

错误消息可以包含受控的 basename 或相对路径，但不得记录密钥、环境变量或完整终端内容。

## 3. 应用内文件剪贴板

复制文件不使用当前文本剪贴板插件，而使用 Explorer store 的短生命周期状态：

```ts
interface ExplorerClipboard {
  workspace: string;
  sourceRelativePath: string;
  kind: "file" | "dir";
  generation: number;
}
```

约束：

- 本阶段只支持 copy，不支持 cut；
- 只保存单个 source，不支持多选；
- workspace 切换、复制源消失或 mutation 失败后清除/失效；
- paste 的目标由右键位置决定：文件目标取其父目录，目录目标取该目录，空白区取 workspace 根；
- paste 通过 `workspace_copy_entry` 执行，成功后刷新目标目录和 artifact projection；
- 不覆盖同名目标，用户可通过重命名源或目标后重试。

## 4. Explorer 与终端拖拽契约

drag payload 只携带受控标识：

```text
application/x-aisc-workspace-path = workspace-relative path
```

不在 `dataTransfer` 中携带任意绝对路径。终端 drop 时：

1. 校验 payload 来源和当前 workspace；
2. 前端 adapter 将 relative path 映射为**容器内绝对路径** `/root/app/<relative_path>`（D11-15：挂载点来自 CLI RunPlan `-v <workspace>:/root/app`，单一常量定义；宿主路径在容器内不存在，不得作为 drop 产物）；
3. 按宿主生成 shell-safe token：当前全部会话为 Linux 容器 shell，恒选 POSIX 单引号策略（D11-14）；PowerShell/cmd 策略作为纯函数实现并单测，当前不接入；
4. 调用现有 `writeSession` 写入 drop 命中的 pane（drop 目标即接收 pane，无需猜测 active pane）；
5. 不发送 Enter，不执行命令；
6. drop 失败只显示反馈，不向 PTY 写入半截内容。

拖拽只支持文件节点；目录不接受拖入终端，避免用户误把目录当作文件参数。

## 5. 图标契约

`WorkspaceNode.kind` 仍保持 `dir | file`，文件类型图标由前端根据 basename/extension 计算，不增加后端耦合：

```text
directory-open / directory-closed
typescript / javascript / python / rust / json / markdown
image / archive / config / generic-file
```

图标仅是视觉提示，不作为唯一信息来源；名称、tooltip、选中状态和无障碍标签仍保留。

