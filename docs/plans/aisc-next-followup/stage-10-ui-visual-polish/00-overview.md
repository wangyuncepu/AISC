# Stage 10：Workbench UI 视觉一致性与可交付性升级

> 状态：Accepted planning / 实施中（自 10a-baseline 起）
> 规划日期：2026-08-21
> 规划基线：当前 `develop`，计划参考提交 `172b291`
> 来源分析：[`docs/plan/ui-visual-polish-upgrade.md`](../../../plan/ui-visual-polish-upgrade.md)
> 正式主线：现有 Tauri 2 + Vue 3 + TypeScript Workbench

## 1. 阶段目标

把已有的 UI 美化分析转化为可独立提交、可测试、可人工验收和可回滚的实施阶段。重点不是重新设计产品，也不是引入组件框架，而是在保持现有 Workbench 交互、Tauri/Rust IPC、Pinia store、xterm 终端和 CSS zoom 机制不变的前提下，完成以下收口：

1. 关闭 CSS token 的语义缺口，消除跨组件重复的视觉硬编码；
2. 建立少量原生 CSS Primitive，统一按钮、字段、面板、菜单、badge 和反馈状态；
3. 重塑 Shell → workspace → tab → explorer/status → terminal 的视觉层级；
4. 统一 onboarding、startup、settings、doctor、Provider、Usage 等边缘流程；
5. 在 Compact / Standard / Wide、暗色 / 亮色、中文 / 英文和 `ui.font_scale` 下保持可用；
6. 把 focus、键盘、Escape、reduced-motion、Teleport 菜单定位和终端 fit 作为硬验收门，而非“美化后再看”；
7. 形成截图矩阵、自动化测试和验收证据，使本阶段结束后可以安全合并或独立回滚。

## 2. 范围

### 2.1 包含

- `workbench/src/styles.css` 和必要的 `workbench/src/styles/*.css`；
- 全局 token、主题语义映射、控件密度、排版、边框、阴影、z-index、duration；
- 原生 CSS Primitive 及其静态契约测试；
- `App.vue`、workspace、tab、runtime sidebar、explorer、terminal chrome/status drawer；
- onboarding、startup、settings、doctor、cc-switch Provider、network usage 的视觉统一；
- 现有 layout tier、主题、focus 和 motion 行为的增量复核；
- 本阶段测试、截图/手测记录、回滚点和发布说明。

### 2.2 不包含

- 不更换 Vue、Vite、Pinia、xterm 或 Tauri；
- 不引入 Tailwind、Bootstrap、Element Plus、Naive UI、Sass/Less/PostCSS 或第三方 Design System；
- 不修改 Rust/Tauri IPC、Python CLI、Docker/Provider 协议、数据 schema 和业务状态机；
- 不重写 CSS zoom，不迁移到 rem，不改 Teleport 菜单坐标算法；
- 不重写终端 renderer、PTY、流式输出和 terminal fit；
- 不做营销型 Dashboard、hero、玻璃拟态、重 blur、霓虹阴影或持续装饰动画；
- 不借视觉改造顺手修复未登记的业务 bug；发现业务问题须单独建 issue/提交。

## 3. 交付物与阶段门

| 交付物 | 说明 | 阶段门 |
|---|---|---|
| 视觉基线记录 | 主题、布局、字号、核心流程截图及问题清单 | `10a-baseline` |
| Token/Primitive 层 | 语义 token、兼容映射、通用控件样式和静态检查 | `10b-tokens` |
| Shell/Workspace 视觉收口 | 顶栏、workspace bar、tab、explorer、terminal chrome、drawer | `10c-shell` |
| 流程页视觉收口 | onboarding、startup、settings、doctor、Provider、Usage | `10d-flows` |
| 响应式/a11y 收口 | 三种布局等级、键盘、focus、motion、长文案 | `10e-a11y` |
| 验收台账 | 自动化结果、手测矩阵、截图差异、遗留项和回滚点 | `10f-acceptance` |

每个门必须是独立提交；每个提交都应能单独运行 `npm run test` 和 `npm run build`，或在提交说明中记录明确的暂时性门禁例外及补偿测试。任何门禁失败都不能通过“把测试删掉”或扩大 CSS fallback 白名单来消除。

## 4. 前置条件与并行关系

- 以 `develop` 的干净工作树作为实施起点；当前未提交变更不得被本阶段覆盖或假设已包含。
- 复用已归档 Stage 6 的 token、响应式、a11y 和 CSS zoom 决策；Stage 10 不重新打开 CSS zoom 迁移。
- Stage 7/8/9 的业务协议与 Provider/C# POC 不属于本阶段依赖；若其接口发生变化，先完成接口变更，再更新 UI 适配提交。
- `10a-baseline` 完成后，`10b-tokens` 才能开始；`10c-shell` 与 `10d-flows` 可以在 `10b-tokens` 稳定后由不同开发者并行，但不得同时修改同一 SFC 的同一 `<style>` 块。
- `10e-a11y` 必须在 shell 和流程页都完成后进行最终复核；局部键盘测试可以随各阶段并行。
- `10f-acceptance` 只能在所有视觉提交合入同一测试分支后执行。

## 5. 成功定义

阶段结论只能是：

- `PASS`：所有自动化门禁、关键人工矩阵和回滚演练通过；
- `PASS-WITH-FOLLOWUPS`：核心门通过，仅有不影响发布的明确遗留项，并有 issue、责任人和下一步；
- `STOP`：出现终端输入/fit、菜单定位、focus 可达性、主题首帧或数据/业务契约回归，停止视觉合并并回滚问题提交。
