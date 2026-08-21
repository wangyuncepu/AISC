# Stage 10 UI 契约

## 1. 运行时与业务边界

1. Vue 组件继续通过现有 props/emits/stores/composables 表达业务状态；不得为了换肤复制一份视觉状态 store。
2. 不增加或修改 Tauri command、Rust event、CLI 参数、Provider protocol、容器协议、持久化 schema。
3. `data-theme`、`data-tier`、`aria-*` 和既有 `ui.font_scale` 是本阶段允许使用的视觉/布局输入；新增属性须在本目录记录。
4. UI 文案继续走 i18n message key；用户层不得新增 raw enum、裸状态值或仅靠颜色表达状态。

## 2. Token 契约

Token 分为三层：

- **基础 token**：font family、font size、line height、spacing、control height、radius、shadow、z-index、duration；
- **语义 surface/text token**：canvas、surface、raised、interactive、hover、selected、divider、text-primary/secondary/tertiary/disabled；
- **语义 state token**：accent、success、info、warning、danger 及其弱背景、前景和 focus ring。

约束：

- 生产组件引用的每个 `var(--name)` 必须在全局 token 层定义；
- 不新增 `var(--x, #hex)` 作为生产视觉兜底；遗留 fallback 必须有白名单、原因和移除阶段；
- 暗/亮主题只覆盖语义 token，不在每个组件重新定义同一语义颜色；
- token 迁移首轮采用兼容别名，不批量删除历史 token；旧别名的移除需单独记录；
- token 单位继续适配现有 CSS zoom，首轮不把 px 改为 rem。

## 3. Primitive 契约

Primitive 只负责外观，不负责业务：

| 类/属性 | 用途 | 必须保持 |
|---|---|---|
| `.ui-button[data-variant]` | primary/secondary/ghost/danger/info | 原生 button 行为、disabled、键盘和 aria 不变 |
| `.ui-icon-button` | close/refresh/info/reopen/menu | 固定点击区、`aria-label`/title、可见 focus |
| `.ui-field`, `.ui-select` | input/select/textarea/range | 原有 v-model、校验和错误关联 |
| `.ui-panel` | card、summary、diagnostic、form surface | 不改变内容顺序和滚动所有权 |
| `.ui-badge[data-state]` | runtime/provider/session 状态 | 状态必须有文本或 aria 辅助 |
| `.ui-menu`, `.ui-menu-item` | context/tab/explorer menu | 不改变 Teleport、定位、键盘导航 |
| `.ui-feedback[data-state]` | loading/success/warn/error/empty | 提供标题、描述和明确 action 区域 |
| `.ui-section` | sidebar/settings/usage 分组 | 不改变折叠状态和语义 heading |

## 4. 布局契约

保留现有 `data-tier`：

- `compact`：有效宽度 `< 640px`；侧栏/Explorer 采用抽屉或详情层，TabBar 横向滚动，actions 允许换行；
- `standard`：有效宽度 `640px–1100px`；保持双栏工作区，终端优先；
- `wide`：有效宽度 `> 1100px`；可展示更多摘要/preview，但不得用装饰性空白侵占终端。

每个布局必须：

- 允许主要内容 `min-width: 0`；
- 长路径、URL、provider 名称不会挤出主要 action；
- drawer/menu/dialog 不因 zoom 或 viewport 边界出屏；
- terminal pane 有显式最小可用尺寸；不得通过隐藏终端内容“解决”溢出。

## 5. 不变量

- 主题首帧继续由现有 `theme.ts`/`index.html` 机制保证，无白屏或闪烁回归；
- xterm 的输入、复制、搜索、右键菜单、resize、fit、pane split 和流式渲染行为不变；
- dialog focus trap、opener restore、Escape；tablist/menu 的键盘路径不变；
- `prefers-reduced-motion: reduce` 下不存在必须依赖动画才能理解的状态；
- secret、完整环境变量、scrollback、provider key 不因视觉组件改造进入日志、history、diagnostic 或 artifact。

## 6. 证据格式

每个阶段提交在验收台账中记录：`commit`、变更文件、自动化命令及版本、手测环境、矩阵范围、已知差异、回滚点和结论。未实测项写 `N/A` 或 `待执行`，不得写 PASS。
