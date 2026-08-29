# Stage 11 可观测性与测试

## 1. 自动化测试

### Rust

在 `workbench/src-tauri/src/workspace.rs` 增加/更新测试：

- 新建空文件成功；
- 新建目录成功；
- 已存在文件/目录返回 `workspace_conflict`，不改变原文件；
- 文件复制成功；
- 目录复制成功或按实现限制返回明确结果；
- 重命名文件和目录成功；
- 新名称包含 `..`、分隔符、空名、保留设备名、控制字符时失败；
- source、destination、new target 越过 workspace、通过 symlink/junction 或使用不存在父目录时失败；
- 只允许在 workspace 内复制，不能跨 workspace；
- 复制失败后不留下临时目标；
- 中文、空格、括号、非 ASCII basename 正常工作。

### Vue/Pinia

在现有：

- `workbench/src/features/workspace-explorer/__tests__/workspaceExplorer.test.ts`
- `workbench/src/stores/__tests__/workspaceExplorer.test.ts`

覆盖：

- 文件单击不调用 `workspacePreview`；
- 文件双击调用 `workspaceOpen`；
- 目录单击仍展开/折叠；
- 工具栏三个按钮存在、调用正确 action、workspace 未就绪时 disabled；
- 根目录/目录/文件右键菜单项按 target 显示；
- 复制文件只更新应用内 clipboard，复制路径仍调用文本 clipboard；
- 粘贴调用正确 source/destination；
- conflict 错误保留输入并显示反馈；
- Enter/Escape/Shift+F10/Menu key 的名称输入和菜单路径；
- 文件/文件夹 icon mapping；
- drag payload 只包含 relative path；
- drop 成功向当前 active terminal 写入 quoted path 且不追加 Enter；
- 无 active pane/session 时 drop 被拒绝；
- 菜单和 input 在 CSS zoom 下仍在视口内。

### Shell quoting

将 quoting 逻辑提取为纯函数并单测：

```text
空格、中文、括号、美元符号、反斜杠、单引号、双引号、换行、尾部反斜杠
```

测试必须断言“生成 token”，不运行真实命令。

## 2. 人工验收矩阵

| 维度 | 最小矩阵 |
|---|---|
| 平台 | Windows 10/11；当前开发环境至少覆盖 WebView2 |
| 主题 | system、dark、light |
| 布局 | Compact、Standard、Wide；有效宽度 320/640/1100/1280 |
| 字号 | `ui.font_scale` 0.8、1.0、1.5；系统缩放 100%、150%、200% |
| 语言 | zh-CN、en-US |
| 路径 | 普通路径、中文、空格、括号、长路径、特殊字符 |
| 文件操作 | 新建文件、建目录、复制文件、复制目录、粘贴、重命名、冲突、权限失败、刷新 |
| 输入 | 鼠标单击/双击/右键/长按拖拽、Tab、Enter、Escape、Shift+F10、Menu key |
| 终端 | live session、无 session、split pane、不同 active pane；PowerShell/cmd 实际宿主 |
| 状态 | 空 workspace、空目录、loading、watcher stale、刷新中、操作成功、操作失败 |

每个案例记录 Windows 版本、WebView2、Workbench commit、workspace 临时目录、主题、语言、有效宽度、font scale 和结果。测试 workspace 使用临时 fixture，不使用真实用户目录。

## 3. 安全与隐私检查

- 日志只记录 operation、result、error code、相对路径 hash 或脱敏 basename；
- 不记录 API key、环境变量、终端 scrollback、完整绝对路径；
- 不把文件内容读入前端来完成 copy；
- 拖拽 payload 不含绝对路径和文件内容；
- 所有 mutation 参数在 Rust 再校验一次，即使前端已经校验。

## 4. 性能和稳定性证据

至少记录：

- 根目录和已展开目录刷新耗时；
- 复制小文件、深目录和大文件的结果与失败清理；
- 高频 watcher 事件下是否出现重复刷新或输入抖动；
- 拖入终端时的输入延迟；
- `npm run test`、`npm run build`、`cargo test` 结果；
- mutation 期间终端输出、resize/fit 和 tab 切换无回归。

## 5. 标准命令

```powershell
cd workbench
npm run test
npm run build

cd ..\workbench\src-tauri
cargo test
```

必要时单独执行：

```powershell
cd workbench
npx vitest run src/features/workspace-explorer/__tests__/workspaceExplorer.test.ts src/stores/__tests__/workspaceExplorer.test.ts
npx vue-tsc --noEmit
```

