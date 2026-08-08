# Workbench S3.3 - 可访问性

> 状态：提案
> 规范：06-implementation-plan.md §六 S3.3；02-startup-flow.md §十二（可访问性）；04-observability.md §九（状态文案）
> 编写日期：2026-08-08
> 分支：feature/workbench-phase3

## 1. 范围

S3.3 可访问性：全键盘操作 + 节流 aria-live + 平台快捷键 + focus-visible。已有基础：TabBar role=tab/aria-selected、PreflightGate/Sidebar 文本+色（非仅靠色）、picker Enter 提交。

### 本切片做（IN）

- **TabBar 键盘导航**：tablist 上 Left/Right 切标签、Home/End 首尾（ARIA tabs 模式，WAI-ARIA）。focus 管理：方向键移动焦点+激活，焦点可见。
- **aria-live 节流播报**（04 §九：只播报语义变化，普通 poll 不播报）：App.vue 加 `role="status"` 区域 + 节流 helper（~1s 合并）。播报：runtime 状态变化（running/stopped/not_found）、操作失败、session 退出（TabBar 已有可见文本，live 播报补充）。错误/失败用 `role="alert"`。
- **平台快捷键**（Ctrl=Win/Linux，Cmd=macOS）：`Ctrl/Cmd+1..4` 切 tab（ready 时）、`Ctrl/Cmd+Enter` 从摘要启动。路由优先级（06 §六.3.3）：终端聚焦时未修饰键归 xterm；应用快捷键为修饰键组合，全局捕获。
- **focus-visible 样式**：全局 `:focus-visible` 轮廓（键盘焦点可见，鼠标点击不显）。审计所有交互元素（button/input/select）键盘可达（原生元素已 Tab 可达）。
- **非仅靠色审计**：PreflightGate dot+Sate 文本 ✓、Sidebar state+freshness 文本 ✓、TabBar 状态文本 ✓--文档确认，无仅色项。

### 本切片不做（OUT）

- **屏幕阅读器完整 smoke test** -> release 实机（需真机 SR 环境，如 NVDA/VoiceOver）。
- **OS 级全局快捷键**（系统托盘等）-> 06 §六.3.3 明确 MVP 不做。
- **终端内快捷键**（xterm 自身 Ctrl+C 等）-> 已由 xterm/agent 处理。
- **焦点陷阱/复杂 roving tabindex** -> 本切片用简单方向键导航。

## 2. 关键设计

### 2.1 TabBar 键盘导航

tablist `@keydown`：ArrowLeft/ArrowUp -> 前一 tab（激活 + focus），ArrowRight/ArrowDown -> 后一，Home -> 首，End -> 末。wrap-around（首<->末）。激活即 `store.activateTab`（已有）。tab 元素 focus 移动用 `el.focus()`（ref 数组）。保留 role=tab/aria-selected（已有），加 `aria-controls`（可选）。

### 2.2 aria-live（App.vue）

```html
<div class="sr-only" role="status" aria-live="polite"></div>
<div class="sr-only" role="alert" aria-live="assertive"></div>
```
helper `announce(text, alert=false)`：写 textContent + 节流（~1s 内多次合并为最近一次，避免 poll 淹没）。触发点：`watch(store.runtimeState)`（变化时播报「Runtime Running/Stopped/Not found」）、`watch(store.error)`（操作失败 -> alert）、session exit（TabBar 退出事件 -> 播报「Claude 会话已退出」）。`.sr-only` 样式（clip，视觉隐藏但 SR 可读）。

### 2.3 快捷键（App.vue 或 composable）

`window.addEventListener("keydown", handler, { capture: true })`：
- `(ctrl||meta) + 1..4` && status=ready -> `store.activateTab(tabs[i].tabId)`（preventDefault）。
- `(ctrl||meta) + Enter` && status=summary -> `store.startFromSummary()`。
- 其他键不拦截（终端聚焦时未修饰键自然归 xterm；修饰键组合 xterm 不用）。文档注明路由优先级。
- onBeforeUnmount remove listener（cleanup，S3.1 审计延续）。

### 2.4 focus-visible

全局 styles：`button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid #0e639c; outline-offset: 2px; }`（或 `styles.css`）。键盘 Tab 导航时可见焦点，鼠标点击不显。

## 3. 改动文件

- `workbench/src/features/workspace/TabBar.vue`：键盘导航（@keydown + tab refs + focus 移动）。
- `workbench/src/App.vue`：aria-live 区域 + `announce` 节流 helper + 快捷键 handler（+ cleanup）+ watch 播报（runtimeState/error）。
- `workbench/src/styles.css`（或 App.vue style）：`:focus-visible` 全局轮廓 + `.sr-only`。

## 4. 步骤与验证

1. TabBar 键盘导航 -> verify: typecheck。
2. App.vue aria-live + announce + 快捷键 -> verify: typecheck。
3. focus-visible + sr-only 样式 -> verify: `npm run build` 过；`cargo build` 零改零错。
4. 实机手测 -> verify:
   - 键盘 Tab 全流程：picker 输入+下一步（Tab 可达）、summary Start/恢复布局/Cancel（Tab + Ctrl+Enter 启动）、ready 后 TabBar 方向键切 tab + Ctrl+1..4 切 tab、终端聚焦输入正常（未修饰键归 xterm）。
   - focus-visible：Tab 导航时按钮显轮廓。
   - aria-live：SR 工具（或 DevTools Accessibility）验证 runtime 状态变化有播报（可选，难手测；代码审查 + 元素存在验证）。
   - 常规回归不破。
5. `npm run build` + `cargo build` 零错误。

## 5. 验收（S3.3 局部）

- [ ] 全部应用操作键盘可达（Tab + 方向键 + 快捷键）。
- [ ] TabBar 方向键/Home/End 导航 + 激活。
- [ ] 平台快捷键 Ctrl/Cmd+1..4 切 tab、Ctrl/Cmd+Enter 启动；终端聚焦未修饰键归 xterm。
- [ ] aria-live 节流播报语义变化；状态非仅靠色（审计确认）。
- [ ] focus-visible 键盘焦点可见。
- [ ] `cargo test` + `npm run build` 零错误；67 测试不回归。
