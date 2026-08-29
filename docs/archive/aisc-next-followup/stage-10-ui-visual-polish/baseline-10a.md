# Stage 10 基线记录（10a-baseline）

> 基线分支：`stage-10-ui-polish`
> 基线 commit：`9c5aa37`（develop，规划文档入库后切分支）
> 记录日期：2026-08-21
> 用途：Stage 10 全部视觉变更与本基线对比；本文件只记录现状，不含任何修复。

## 1. 自动化基线

| 命令 | 结果 | 备注 |
|---|---|---|
| `cd workbench && npm run test` | ✅ 38 files / 277 tests 全过（vitest 4.1.10，4.46s） | 环境噪音：happy-dom 下 `HTMLCanvasElement.getContext` not implemented 警告，属既有现象 |
| `cd workbench && npm run build` | ✅ `vue-tsc --noEmit` + `vite build` 通过（vite 6.4.3，1.81s） | 产物：index.html 0.94 kB；**CSS 58.69 kB（gzip 10.96）**；JS 863.36 kB（gzip 247.88） |
| `npx vue-tsc --noEmit`（如 build 未含） | ✅（build 已含，未单独跑） | |

既有警告（基线噪音，非本阶段引入）：

- vite chunk >500 kB 警告（JS 单 chunk 863.36 kB）；
- `stores/onboarding.ts` 被 SettingsForm 动态导入但同时被 App/OnboardingWizard 静态导入，动态导入不生效；
- vitest 下 happy-dom `getContext` not implemented。

**Stage 10 CSS 体积追踪锚点：58.69 kB / gzip 10.96 kB。**

任何非绿结果先登记为现状问题，不在本阶段顺手修（规约 D10-12）。

## 2. 人工截图矩阵（用户执行）

目的：冻结"改造前"视觉现状，供 10c/10d 后对照。截图不要求像素级归档，重点是层级、溢出、状态可见性。

### 2.1 矩阵维度

| 维度 | 取值 |
|---|---|
| 主题 | dark、light |
| 布局 | Compact（有效宽度 <640）、Standard（640–1100）、Wide（>1100） |
| 字号 | `ui.font_scale` 0.8 / 1.0 / 1.5（系统缩放 100% 前提下） |

最小组合：dark+Standard+1.0 必截；其余维度按行采样（每行至少 1 张），共约 6–8 张核心 + 问题点加截。

### 2.2 核心流程清单

1. 主工作区（顶栏 + WorkspaceBar + TabBar + Explorer + Terminal 四者同框）
2. 多 tab（≥3 个，含 active/hover 态）
3. Settings 页
4. Doctor dialog（如当前环境可打开）
5. Onboarding / startup picker（如可复现；不可复现记 N/A）
6. Provider（cc-switch）页
7. Usage / 网络用量页
8. 状态 Drawer 打开态

### 2.3 现状问题表（2026-08-21 用户手测回填）

截图存档：18 张，`C:\Users\VE111\Documents\AISC\screenshoot\`（仓外目录，不入库）。

| # | 位置 | 维度 | 现象 | 证据/处置 |
|---|---|---|---|---|
| B-01 | 「选择工作区」界面 | 长文案 | 超长文件夹名超出 UI 边界 | 10d 修（truncate/wrap） |
| B-02 | WorkspaceBar/TabBar | 长文案 | 超长工作区名占满 tab 栏，挤压其他 tab | 10c 修 |
| B-03 | Provider 页 | 长文案 | 超长 provider 名与后续内容重叠 | `C:\Users\VE111\Pictures\Screenshots\C-08.png`；10d 修 |
| B-04 | 全局（tab/按钮/滑块） | 密度/观感 | tab 过小难点中；组件观感差（用户主观，诉求 iOS 风格） | 10b token 层解决；决策 D10-14 |
| B-05 | 终端输入 | 行为 | 长输入不换行、同线覆盖；布局恢复时 prompt 串行一次（root@...# 断行，未复现） | 非视觉缺陷，登记 todo，Stage 10 仅要求无回归 |
| B-06 | 终端 fit | 行为 | resize 列数不实时跟随，缓慢逐步挤压 | 同上 |
| B-07 | 全局 dialog/menu/drawer | 键盘 | Escape 全部无响应，无法键盘关闭 | UI 层缺陷，10e 独立行为修复提交收口 |
| B-08 | 键盘导航 | 键盘 | Tab 进入终端后被拦截无法穿越；Usage 页 Tab 仅在内部按钮循环 | 同上 |

## 3. 交互现状记录（用户执行，逐项 PASS/FAIL/备注）

| # | 检查项 | 步骤 | 结果 |
|---|---|---|---|
| C-01 | terminal 输入/粘贴 | 打开 session，键入与粘贴长行 | ❌ 长输入同线覆盖不换行；布局恢复时 prompt 串行一次（B-05，未复现） |
| C-02 | terminal fit | 拖拽窗口宽窄各一次，列数随宽度变化、无溢出 | ⚠️ 列数不实时跟随，缓慢挤压（B-06） |
| C-03 | terminal 复制/搜索 | 选中文本复制；Ctrl+F 搜索 | ✅ |
| C-04 | 右键菜单（Teleport） | 终端区与 tab 区各右键一次，菜单完整出现在视口内 | ✅ |
| C-05 | tablist 键盘 | Tab 进入 tab 栏，左右箭头切换，Enter 激活 | ❌ 终端拦截 Tab 无法穿越；Usage 页仅内部循环（B-08） |
| C-06 | Escape | dialog/menu/drawer 打开后 Escape 关闭，焦点回到触发元素 | ❌ 全部无响应（B-07） |
| C-07 | focus-visible | 键盘 Tab 遍历顶栏→workspace→tab→explorer→terminal，焦点环可见 | ❌ 同 C-05（B-08） |
| C-08 | 长文案 | 英文界面 + 长路径 workspace/长 provider 名，主操作不被挤压出视口 | ❌ 三处溢出/重叠（B-01/02/03，截图 C-08.png） |
| C-09 | 主题切换 | settings 切 dark/light/system，首帧无闪白/闪黑 | ✅ 一次成功 |
| C-10 | reduced-motion | 系统开启"显示动画效果=关"，无阻塞性动画 | ✅ 未出现阻塞动画 |

## 4. 本阶段允许修改文件清单

依据 `00-overview.md` §2.1 与 `05-implementation-plan.md`：

**样式层（10b）**
- `workbench/src/styles.css`
- `workbench/src/styles/*.css`（新增/修改：tokens、base、primitives、utilities）
- `workbench/src/lib/__tests__/tokens.test.ts`

**壳层（10c）**
- `workbench/src/App.vue`
- `workbench/src/features/workspace/{WorkspaceBar,WorkspaceView,TabBar,RuntimeSidebar}.vue`
- `workbench/src/features/workspace-explorer/WorkspaceExplorer.vue`
- `workbench/src/features/terminal/{PaneTree,GuidePane,Terminal}.vue`（仅 chrome，不触 renderer/PTY/fit 逻辑）

**流程页（10d）**
- `workbench/src/features/onboarding/OnboardingWizard.vue`
- `workbench/src/features/startup/*.vue`
- `workbench/src/features/settings/{SettingsForm,SettingsTab}.vue`
- `workbench/src/features/doctor/DoctorDialog.vue`
- `workbench/src/features/ccswitch/CcSwitchUiTab.vue`
- `workbench/src/features/usage/*.vue`

**测试与证据（10e/10f）**
- 上述组件对应 `__tests__`；`layout.test.ts`、`theme.test.ts`、accessibility tests
- `docs/plans/aisc-next-followup/stage-10-ui-visual-polish/` 内证据文件

**禁止**：`workbench/src-tauri/**`（Rust/IPC）、Python CLI、Docker/Provider 协议、Pinia store 状态机、xterm renderer/fit 内部、CSS zoom 机制、Teleport 坐标算法。发现业务 bug → 单独 issue/提交（D10-12）。

## 5. 日志摘录

```
> workbench@0.1.0 test
> vitest run

 RUN  v4.1.10 C:/Users/VE111/Documents/AISC/workbench
 Test Files  38 passed (38)
      Tests  277 passed (277)
   Duration  4.46s
```

```
> workbench@0.1.0 build
> vue-tsc --noEmit && vite build

vite v6.4.3 building for production...
✓ 142 modules transformed.
dist/index.html                   0.94 kB │ gzip:   0.53 kB
dist/assets/index-DsYdOHdb.css   58.69 kB │ gzip:  10.96 kB
dist/assets/index-uX8YTnpk.js   863.36 kB │ gzip: 247.88 kB
✓ built in 1.81s
```
