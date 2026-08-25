# Terminal.vue 渲染问题审查

## 结论

用户描述的现象与 `src/features/terminal/Terminal.vue` 当前的 resize 遮罩实现一致：

1. 遮罩节点是通过 `document.createElement()` 动态创建的。
2. 遮罩样式写在 `<style scoped>` 中。
3. 动态节点没有 Vue SFC 自动附加的 `data-v-*` scope 属性。
4. 因此 `.resize-veil` 的定位、尺寸、层级、背景色和透明度过渡规则不会匹配。
5. xterm resize 仍然会执行，所以会先显示错乱帧，之后随着 PTY 重绘自动恢复。

这可以直接解释“过渡动画遮罩没有生效，但闪烁后会自动重绘正确”的复现结果。

本文仅记录审查结果和修复计划，当前不包含实现修改。

## 复现路径对应的时序

用户复现步骤：

1. 最大化窗口。
2. 打开多个 bash tab。
3. 缩小窗口。
4. 切换到新的 bash tab。
5. 看到终端内容错乱，闪烁后恢复。

对应代码时序：

### Tab 切换

`WorkspaceView.vue` 使用 `v-show` 保持所有 tab 的终端实例存活：

- `src/features/workspace/WorkspaceView.vue:273-282`
- 隐藏 tab 处于 `display: none`，其 xterm 网格不会随当前可见尺寸实时 fit。
- tab 显示时，`Terminal.vue` 的 `watch(visible)` 先调用 `veilHold()`，随后通过 `setTimeout(..., 0)` 调用 `doResize("show")`。

相关位置：

- `src/features/terminal/Terminal.vue:810-827`

### Resize / xterm 重排

`doResize()` 当前先执行 `fitGrid()`，而 `fitGrid()` 内部可能立即调用 `term.resize()`：

- `src/features/terminal/Terminal.vue:327-363`
- `src/features/terminal/Terminal.vue:494-540`

只有在 `fitGrid()` 返回后，代码才根据列行数变化调用 `veilHold()`：

```ts
const before = `${term.cols}x${term.rows}`;
fitGrid();
if (before !== `${term.cols}x${term.rows}`) {
  veilHold(veilGrace());
}
```

这意味着 resize 过程可能是：

1. 旧网格仍可见。
2. `term.resize()` 同步触发 xterm buffer reflow。
3. 中间状态进入浏览器绘制队列。
4. 代码才创建遮罩。

即使遮罩样式问题修复，这个顺序仍可能泄漏一帧错乱画面。

## 已确认问题

### P0：动态遮罩无法匹配 scoped CSS

位置：

- 动态创建：`src/features/terminal/Terminal.vue:390-407`
- 样式定义：`src/features/terminal/Terminal.vue:1092-1098`

当前逻辑：

```ts
const veil = document.createElement("div");
veil.className = "resize-veil";
host.appendChild(veil);
```

但样式位于：

```vue
<style scoped>
.resize-veil {
  position: absolute;
  inset: 0;
  z-index: 1;
  background: var(--bg);
}
</style>
```

Vue 对模板中的节点会附加类似 `data-v-xxxx` 的属性，并将 scoped 选择器编译为带该属性的选择器。通过 `document.createElement()` 创建的节点只有 `class="resize-veil"`，没有该 scope 属性。

实际结果：

- `position: absolute` 不生效。
- `inset: 0` 不生效。
- `z-index` 不生效。
- `background` 不生效。
- `opacity` 和 `transition` 不生效。
- 遮罩节点不会覆盖 xterm 画面。

这不是视觉参数问题，而是节点创建方式与 scoped CSS 的作用域机制不匹配。

### P1：遮罩挂载晚于 xterm 重排

位置：

- `src/features/terminal/Terminal.vue:494-540`

当前遮罩只在发现网格已经变化之后才创建，而网格变化发生在 `fitGrid()` 内部的 `term.resize()`。

即使改成全局 CSS，仍存在首帧泄漏风险。遮罩应当在可能导致 `term.resize()` 的操作之前进入可见渲染层，或者使用声明式节点在 show/resize 前预先固定。

### P1：旧 resize 的异步释放可能释放新一轮遮罩

位置：

- `src/features/terminal/Terminal.vue:419-442`
- `src/features/terminal/Terminal.vue:455-491`

`sendResize()` 成功后使用未保存的定时器调用 `releaseVeil()`：

```ts
window.setTimeout(releaseVeil, veilGraceMs);
```

随后如果发生新一轮 resize，`veilHold()` 会重新把现有遮罩设为不透明，但不会取消之前已经安排的 release timeout。旧请求的回调可能在新请求尚未完成时执行，导致新一轮 PTY 重绘过程提前暴露。

这不是当前“遮罩完全不生效”的首要原因，但会造成修复 scoped CSS 后仍然偶发闪烁。

### P2：缺少遮罩时序回归测试

现有 `terminalResize.test.ts` 覆盖了：

- running 状态首次 resize。
- resize settle debounce。
- resize 失败后的 heal。
- TUI 最小列数。
- 并发 resize 排队。

但没有覆盖：

- 遮罩节点是否真的具有覆盖终端的样式。
- 遮罩创建是否发生在 `term.resize()` 之前。
- 旧 resize 的延迟 release 是否会释放新一轮遮罩。
- tab 从 `display:none` 恢复显示时，首帧是否被遮挡。

## 建议修复方案

### 方案 A：优先改为声明式遮罩

在 `Terminal.vue` 模板中声明遮罩节点，通过响应式状态控制显示：

- 节点由 Vue 创建，可以正常获得 scoped 属性。
- 可直接用模板中的 `v-if` 或 `v-show` 控制。
- 遮罩的生命周期更容易和组件卸载绑定。
- 可保留 `ref` 供 release/fade 逻辑使用。

如果必须保留 imperative DOM 创建，则 `.resize-veil` 必须改为全局选择器，例如使用 `:global(.resize-veil)` 或移到全局样式文件。

### 方案 B：在 xterm resize 前固定遮罩

建议将逻辑调整为：

1. 判断当前 pane 是否可见、会话是否存活。
2. 先固定遮罩。
3. 执行 `fitGrid()` / `term.resize()`。
4. 如果网格没有变化，立即取消遮罩。
5. 如果网格变化，等待后端确认和 PTY redraw grace，再释放遮罩。

对于 tab show，现有 `watch(visible)` 的 pre-flush 方向是合理的，但必须确保遮罩样式实际生效，并且 `doResize("show")` 不会在遮罩尚未进入可见帧前执行。

### 方案 C：为遮罩释放增加代次或请求令牌

每次 `veilHold()` 产生新的 generation/token。异步释放时只允许最新 token 执行：

- 旧 `resize_session` 成功回调不能释放新一轮遮罩。
- 两次 `requestAnimationFrame` 回调也需要检查 token。
- 组件卸载时使 token 失效，避免延迟回调操作已销毁节点。

### 方案 D：补充针对性测试

建议新增以下回归用例：

1. **遮罩存在性**
   - 触发可见 tab 的 resize。
   - 断言遮罩节点已创建。
   - 若使用声明式节点，断言节点带组件 scope 属性。

2. **遮罩先于 resize**
   - mock `term.resize()`。
   - 记录遮罩创建和 `term.resize()` 的调用顺序。
   - 断言遮罩先创建。

3. **旧 release 不影响新 resize**
   - 触发第一次 resize 并保留其 grace timer。
   - 触发第二次 resize。
   - 执行第一次 timer。
   - 断言遮罩仍保持不透明。
   - 执行第二次 timer 后才允许淡出。

4. **tab show 首帧**
   - 初始将 tab 设置为隐藏。
   - 激活 tab。
   - 在 `v-show` 恢复和 `doResize("show")` 之间断言遮罩存在。

## 验证记录

已阅读：

- `src/features/terminal/Terminal.vue`
- `src/features/terminal/__tests__/terminalResize.test.ts`
- `src/features/workspace/WorkspaceView.vue`
- `src/features/terminal/PaneTree.vue`

尝试执行针对性测试：

```text
npm test -- --run src/features/terminal/__tests__/terminalResize.test.ts
```

测试未进入 Vitest，环境在加载 Vite 配置时出现：

```text
Error: spawn EPERM
```

因此目前没有运行时测试结果；上述结论来自代码路径和 Vue SFC scoped CSS 行为审查。

## 建议实施顺序

1. 先修复动态节点与 scoped CSS 的边界，或改为声明式遮罩。
2. 将遮罩固定动作移到 `term.resize()` 之前。
3. 为异步 release 增加 generation/token 校验。
4. 增加遮罩存在性、调用顺序和旧 release 竞态测试。
5. 在最大化、缩小、tab 切换和连续 resize 场景下进行手工回归。

## 修复记录（2026-08-25，`5ff1661`）

按方案 A+B+C+D 全部实施：

- **P0**：遮罩改为模板声明式节点（`v-if="veilOn"` + `.fading` class 驱动淡出过渡），获得 scoped 属性；旧的 `ensureVeil/createElement` 路径删除。
- **P1（挂载时机）**：`doResize` 中 `veilHold()` 移至 `fitGrid()`（内部 `term.resize()`）之前；2s 自愈 tick 不 pin（未变化的 fit 不得闪罩）；tab show 的 watcher pre-paint pin 保留，show 时网格未变则立即撤罩（未绘制过的遮罩瞬时移除，淡出自身会是闪光）。
- **P1（陈旧释放）**：`veilGen` 代次令牌在 **sendResize 调用时刻**捕获（审查方案 C 的补充：ok 时刻捕获会拿到新 hold 的 gen 反而错误放行——实现时发现并修正）；双 RAF 的 painted 标记、淡出完成回调、failsafe 均校验令牌；卸载时 `veilGen++` 使全部在途回调失效。
- **P2**：`terminalResize.test.ts` 新增 4 例——网格变化时遮罩出现/确认+宽限后清除、tab show 在 doResize 之前 pin、陈旧 ok-grace 不释放新 hold（含并发发送排队场景）。

门禁：vitest 340 全绿、vue-tsc clean。手工回归（最大化/缩小/多 tab 切换/连续 resize）待用户复测。
