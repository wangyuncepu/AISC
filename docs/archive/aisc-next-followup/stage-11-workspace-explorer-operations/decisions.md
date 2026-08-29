# Stage 11 决策记录

- `D11-01` 文件单击只选择，双击打开；目录单击保留展开/折叠。单击预览功能移除，避免文件树选择动作触发读取和布局变化。
- `D11-02` “复制文件”与“复制路径”是两个不同动作：前者写入应用内 Explorer clipboard，后者继续写入系统文本剪贴板。
- `D11-03` 本阶段只支持单项 copy/paste，不支持 cut、多选、覆盖、拖拽移动或跨 workspace 复制。
- `D11-04` 文件系统 mutation 统一由 Rust/Tauri 执行；Vue/Pinia 不直接读写文件，也不把绝对路径作为 mutation 参数。
- `D11-05` 默认拒绝同名目标，不自动覆盖、不自动添加 `(1)` 后缀；冲突通过稳定错误反馈恢复。
- `D11-06` 新建和重命名使用 Explorer inline name input；Enter 提交，Escape 取消，非法名称和冲突保留输入。
- `D11-07` 为保持 VS Code Explorer 语义一致，重命名和复制同时支持文件与文件夹；用户明确提出的文件重命名是硬验收项。
- `D11-08` 不新增图标包，不复制 VS Code 资源；使用本地受控 SVG/CSS 图标映射和 generic fallback。
- `D11-09` 拖入终端只支持文件，插入 shell-safe absolute path，不自动提交命令；目录拖入本阶段拒绝。
- `D11-10` drag payload 只使用 workspace-relative path；绝对路径在受控后端/终端适配边界生成。
- `D11-11` 继续复用现有 xterm、PTY、`writeSession`、CSS zoom、watcher 和 artifact projection；本阶段不扩大这些系统的职责。
- `D11-12` 本阶段不增加新的遥测；只记录必要的 operation outcome、error code 和脱敏测试证据。
- `D11-13` 发现 containment、终端输入或 watcher 数据契约回归时，按提交粒度 STOP/回滚，不以放宽安全规则换取功能通过。

## 实施确认（2026-08-24，11a 冻结）

- `D11-14` 终端宿主识别：当前 session 契约（`aisc session open` → `docker exec`）下所有终端都是 Linux 容器内 shell，不存在 PowerShell/cmd 宿主会话。quoting adapter 按宿主枚举分发，当前恒选 POSIX 单引号策略；PowerShell/cmd 策略作为纯函数实现并单测（契约完备性），当前不接入。
- `D11-15` 拖入终端插入的是**容器内绝对路径** `/root/app/<relative_path>`（挂载点来自 CLI RunPlan `-v <workspace>:/root/app`，`src/aisc/domain/models.py`）。挂载点以前端单一常量定义并注明来源，不逐处拼接。宿主路径在容器内不存在，不作为 drop 产物。用户 2026-08-24 确认。
- `D11-16` 单击预览移除范围：仅文件树（单击=选中，不读取不 preview）；产物（Artifacts）面板单击仍触发预览，preview pane 与 `workspace_preview` 命令保留。用户 2026-08-24 确认。
- `D11-17` 工具栏新建文件/文件夹的目标目录跟随当前选中节点：选中目录→在其中新建；选中文件→在其父目录新建；无选中→workspace 根。用户 2026-08-24 确认。
- `D11-18` 目录递归复制为有界复制：条目上限 10,000（文件+目录合计），超出返回 `workspace_io` 错误并清理临时目标；遍历遇到 symlink/junction/reparse point 时解析其目标，workspace 外的跳过（不跟随、不失败、不复制），workspace 内的按普通目标复制。用户 2026-08-24 确认。
- `D11-19` 键盘语义：Enter 与双击等价（文件打开、目录展开/折叠）；Space 仅选中不激活。与 APG tree 模式一致。
- `D11-20` 错误码落位：`workspace_invalid`→既有 `WB_ERR_WORKSPACE_INVALID`；新增 `WB_ERR_WORKSPACE_NOT_FOUND` / `WB_ERR_WORKSPACE_CONFLICT` / `WB_ERR_WORKSPACE_READ_ONLY` / `WB_ERR_WORKSPACE_IO`，均为稳定 code，UI 按 code 路由文案，不解析 `technical_detail`。
- `D11-21` “单击预览”测试预期的更新与行为变更同批落地（11c），11a 只冻结契约文档——阶段门必须独立保持测试可运行、全绿。
- `D11-22` Windows 保留设备名（CON/PRN/AUX/NUL/COM1-9/LPT1-9，含带扩展名形态）、尾部点/空格、控制字符在 Rust basename 校验中拒绝（`WB_ERR_WORKSPACE_INVALID`）；不做 Unicode normalization（文件系统自行处理大小写折叠），中文名按原样接受。

### 允许修改文件清单（冻结）

- Rust：`workbench/src-tauri/src/workspace.rs`、`error.rs`、`lib.rs`（仅 command 注册）
- 前端：`workbench/src/lib/ipc.ts`、`src/types/index.ts`、`src/stores/workspaceExplorer.ts`、`src/features/workspace-explorer/WorkspaceExplorer.vue`（含同目录 `__tests__/`、`src/stores/__tests__/workspaceExplorer.test.ts`）、`src/features/terminal/Terminal.vue`、terminal 目录下新增纯函数/测试、`src/i18n/zh-CN.ts`、`src/i18n/en-US.ts`
- 文档：`docs/plans/aisc-next-followup/stage-11-workspace-explorer-operations/*`
- 不越界到 PTY/xterm renderer/scrollback/resize-fit、watcher、artifact provenance、settings schema。

