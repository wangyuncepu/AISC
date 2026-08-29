# Stage 10 UX 流程与视觉规则

## 1. 总体视觉模型

保持“开发者工作台 / IDE command center”定位：高信息密度、平静表面、暗色优先但亮色等价、状态优先、动作有主次。

视觉层级固定为：

```text
Canvas → Surface → Raised → Interactive → Hover/Focus → Selected → Status
```

终端仍是工作区主视觉，不在终端外层叠加大卡片；顶栏、WorkspaceBar、TabBar、Explorer、Status Drawer 通过表面和分隔层次表达结构，而不是通过大面积渐变。

## 2. Shell 与工作区

### 启动后

1. 首帧保持当前主题，避免白色闪烁；
2. readiness 不可用时，显示稳定的错误标题、可执行的 Retry/Open diagnostics 动作和可展开 details；
3. ready 后用户一眼看到 workspace、active tab、runtime/session 状态和终端；
4. Compact 隐藏非必要摘要但保留按钮、tooltip、键盘可达性。

### 顶栏与 WorkspaceBar

- 品牌/产品名是弱视觉锚点，不能抢终端注意力；
- workspace 名称与状态 badge 相邻；启动、停止、错误、过期状态同时显示文本；
- primary action 只保留一个 accent，secondary/ghost 低强调，danger 与普通关闭动作分离；
- close/refresh/menu 统一 icon button 点击区和 focus ring。

### TabBar

- active tab 使用 selected surface + accent indicator，不只依赖一条边框；
- session state 使用统一 badge 或状态点加文本/tooltip；
- 多 tab 继续横向滚动，关闭按钮不会挤压标题；
- Tab 菜单保留鼠标、键盘、Escape、viewport safe position。

### Explorer 与 Status Drawer

- Explorer 分组标题、tree row hover/selected、artifact 类型 badge、preview 统一语法；
- 长路径默认截断，完整路径通过 title/详情呈现；
- Status Drawer 有明确标题、关闭按钮、摘要与 developer details 分层；危险操作仍需确认；
- drawer 只做 opacity/transform 反馈，不高频动画 width/height。

## 3. Terminal

- 只调整 toolbar、搜索层、右键菜单、空状态和 pane divider 的外观；
- 不改变 xterm canvas、字体、scrollback、renderer、fit、输入和输出节流；
- terminal toolbar 的按钮必须有 aria-label，搜索层有清晰的计数、关闭和键盘入口；
- 空状态既说明“当前没有 session/输出”，也给出下一步动作，不使用纯装饰插画。

## 4. 启动、引导和业务流程

### Onboarding

- 当前步骤、总步骤和可执行动作形成稳定的步骤轨道；
- 内容区设置合理最大宽度，探测结果/失败原因置于 feedback/panel；
- footer action 明确 primary/secondary，loading/disabled 不改变布局；
- 错误必须告诉用户下一步是重试、修改设置还是打开诊断。

### Startup

Workspace picker、preflight、summary、progress、conflict、error 统一使用 panel + feedback + action 结构：

```text
发生了什么 → 当前状态/证据 → 用户可以做什么 → 详细信息（可选）
```

不改现有启动、冲突解决和取消行为。

### Settings / Doctor / Provider / Usage

- Settings：field row、分组、帮助文案、即时生效提示和 footer action 统一；
- Doctor：summary、check row、trace/log details、导出动作使用统一 state badge；导出仍遵循脱敏 allowlist；
- Provider：list row、simple/custom form、编辑/删除确认、loading/error/empty/toast 统一；secret 仍只显示 mask；
- Usage：数据卡片和空/加载/错误状态沿用同一 surface/state 规则；网络失败必须有恢复动作。

## 5. 状态表达

| 状态 | 视觉 | 文案/结构要求 |
|---|---|---|
| loading | subtle progress/spinner | 说明正在执行的动作，不只显示转圈 |
| ready/success | success 前景/弱背景 | 提供结果或可继续动作 |
| info | info 前景/弱背景 | 用于解释，不伪装成警告 |
| warning/stale | warning 前景/弱背景 | 说明影响和恢复路径 |
| error | danger 前景/弱背景 | 稳定错误标题 + action + details |
| selected/active | selected surface + accent | aria-selected/当前项语义同步 |
| disabled | disabled text/surface | 不依赖低对比度隐藏原因 |

## 6. 响应式、键盘和动效

- Compact：单列表单、actions wrap、抽屉详情、tab overflow；
- Standard：终端保持最大面积，侧栏和抽屉边界清晰；
- Wide：增加信息摘要而非装饰空白；
- 所有可交互元素覆盖 hover/active/focus-visible/disabled/aria-expanded/aria-selected；
- dialog/menu/drawer/toast 只做短时反馈动画；reduced-motion 下静态化；
- Tab、Shift+Tab、Enter/Space、方向键、Home/End、Escape、Shift+F10/Menu key 的原路径必须保持。
