# Stage 10 实施顺序

## 0. `10a-baseline`：冻结基线与变更边界（0.5–1 天）

**目标**：建立可比较、可回退的现状证据，不改业务逻辑。

1. 确认干净基线、记录 `git status`、branch 和 commit；
2. 运行 `npm run test`、`npm run build`，保存日志；
3. 按暗/亮、Compact/Standard/Wide、font scale 0.8/1.0/1.5 记录核心流程截图/问题表；
4. 记录 terminal fit、Teleport menu、focus、Escape、tablist、长文案现状；
5. 输出本阶段允许修改文件清单。

提交：`docs(plan): establish stage-10 UI visual baseline`。

## 1. `10b-tokens`：Token v2 与静态门禁（1–2 天）

**目标**：先收敛语义，再迁移页面。

允许文件：`workbench/src/styles.css`、可选 `workbench/src/styles/{tokens,base,primitives,utilities}.css`、`workbench/src/lib/__tests__/tokens.test.ts`。

执行：

1. 补齐字体、line-height、spacing、control height、surface、border、state、focus、overlay、duration；
2. 保留旧 token 兼容别名，建立新旧映射表；
3. 统一 button/input/select/textarea/checkbox/range 的尺寸、placeholder、disabled、focus；
4. 增加 `.ui-button`、`.ui-icon-button`、`.ui-field`、`.ui-panel`、`.ui-badge`、`.ui-menu`、`.ui-feedback`、`.ui-section`；
5. 扩展 token 测试和静态扫描；
6. 只迁移至少一个低风险页面作为试点，验证 scoped/global 层叠。

门禁：token 引用全解析；暗/亮下试点控件一致；无 xterm 污染；测试/build 通过。

提交拆分：

- `style(tokens): close semantic token gaps`
- `style(primitives): add native UI primitives`
- `test(ui): enforce token reference contract`

## 2. `10c-shell`：Shell 与工作区层级（2–3 天）

**目标**：让用户理解应用壳、workspace、tab、explorer/status 与 terminal 的关系。

优先文件：

- `workbench/src/App.vue`
- `workbench/src/features/workspace/{WorkspaceBar,WorkspaceView,TabBar,RuntimeSidebar}.vue`
- `workbench/src/features/workspace-explorer/WorkspaceExplorer.vue`
- `workbench/src/features/terminal/{PaneTree,GuidePane,Terminal}.vue`

执行：

1. 顶栏品牌、workspace 状态、全局动作按 primary/secondary/quiet 分层；
2. WorkspaceBar 使用 selected surface 和统一 runtime badge；
3. TabBar 统一 active/hover/close/session state，保留横向滚动；
4. Explorer 统一 section、tree row、artifact badge、preview 和长路径处理；
5. Terminal 只改 toolbar/search/context menu/empty guide/pane divider 外观；
6. Status Drawer 统一标题、关闭动作、summary/details 和 overlay 层级；
7. 每修改一个组件立即运行相关测试并做 compact/standard/wide smoke。

提交：`style(shell): polish app workspace and tab hierarchy`、`style(workspace): polish explorer terminal chrome and drawer`。

硬门：terminal 输入/fit、menu 坐标、tab keyboard 和 drawer focus 无回归。

## 3. `10d-flows`：启动与业务流程统一（2–3 天）

**目标**：边缘流程与主工作区共享视觉语法，不改变业务状态和协议。

优先文件：

- `features/onboarding/OnboardingWizard.vue`
- `features/startup/*.vue`
- `features/settings/{SettingsForm,SettingsTab}.vue`
- `features/doctor/DoctorDialog.vue`
- `features/ccswitch/CcSwitchUiTab.vue`
- `features/usage/*.vue`

执行：

1. onboarding 步骤轨道、内容宽度、探测详情、footer actions；
2. startup picker/preflight/summary/progress/conflict/error 使用 panel + feedback + action；
3. settings field rows、分组、帮助文案、即时生效、保存 footer；
4. doctor check rows、traces、logs、redacted export；
5. Provider list/simple/custom/edit/delete/empty/loading/error/toast；
6. Usage cards、空/加载/错误、网络恢复动作；
7. 对中英文长文案和长 URL 做 `min-width: 0`、wrap、truncate 复核。

提交：`style(flows): align onboarding startup settings and diagnostics`、`style(provider): align provider and usage surfaces`。

硬门：form v-model/校验、IPC 调用、secret redaction、dialog/confirm 行为无变化。

## 4. `10e-a11y`：响应式、动效和无障碍复核（1–2 天）

**目标**：保证默认窗口之外也可交付。

1. 复核 Compact/Standard/Wide 的 drawer、tab overflow、action wrap、单列表单；
2. 复核所有状态的 hover/active/focus-visible/disabled/aria-expanded/aria-selected；
3. 统一 drawer/menu/dialog/toast/provider flash 的 enter/leave；
4. `prefers-reduced-motion` 下 duration/smooth scroll 静态化；
5. 复核 200% 系统缩放和 `ui.font_scale`，不迁移 CSS zoom；
6. 执行 keyboard/focus/Escape/menu/tablist/dialog 手测和既有测试。

提交：`style(a11y): normalize focus motion and compact rules`。

## 5. `10f-cleanup`：清理与完整验证（0.5–1 天）

1. 删除已迁移的重复控件规则、无用历史别名和无理由 fallback；
2. 更新 tokens/layout/theme/a11y/component tests；
3. 检查 diff 不含业务协议、store 状态机和 Tauri/Rust 越界变更；
4. 运行全量 Workbench test/build；
5. 生成对照截图、测试日志和已知差异；
6. 记录每个阶段提交的回滚点。

提交：`test(ui): add stage-10 acceptance matrix`、`docs(plan): record stage-10 evidence`。

## 6. `10g-release`：结论、交接和回滚

- 全部硬门通过：标记 `PASS`，可合入正式主线；
- 仅非阻断遗留：标记 `PASS-WITH-FOLLOWUPS`，附 issue/责任人/下一阶段；
- 终端、菜单、focus、主题首帧或业务契约任一回归：标记 `STOP`，按提交粒度回滚；
- 不做 squash 破坏阶段边界；归档前将验收台账、决策和截图路径写入 devlog/release 需要的位置。

## 7. 回滚策略

1. 优先回滚最接近问题的组件提交，不回滚整个主题机制；
2. Primitive 回归时，可暂时撤销该组件的 `.ui-*` 使用，保留 token 和测试；
3. Shell 与流程页独立回滚；图标资源/HTML 结构变更与行为变更不得混提交；
4. CSS zoom、Teleport、xterm renderer 任何问题都不通过扩大补丁范围解决，直接回滚对应视觉提交；
5. 若发现业务文件越界，先拆分提交，再决定视觉部分是否保留。
