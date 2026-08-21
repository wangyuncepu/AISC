# AISC Workbench UI 技术美化升级方案

> 状态：Draft / 可执行实施计划
> 编写日期：2026-08-20
> 适用基线：当前 `develop` 工作区（仅分析 `workbench/src`，不改动业务协议与 Tauri/Rust 契约）
> 目标路径：`docs/plan/ui-visual-polish-upgrade.md`

## 1. 结论先行

当前项目**不是“没有框架的前端”**：运行时是 **Vue 3 + TypeScript + Vite + Tauri 2**，状态层使用 Pinia，终端使用 xterm；但 UI 样式层确实是**原生 CSS**，没有 CSS Framework、没有 Sass/Less/PostCSS 预处理方案，组件样式主要放在 Vue SFC 的 `<style scoped>` 中。

因此本次美化不应引入 Tailwind、Element Plus、Naive UI、CSS Modules、Sass 或整套外部 Design System。推荐路线是：

> **保留 Vue/Tauri/Pinia/xterm 与现有交互契约，以 CSS Custom Properties 为 Design Token，以少量原生 CSS Primitive 统一控件，再按 Shell → 工作区 → 状态面板 → 启动/设置/诊断流程分阶段换肤。**

这会比“重写一套组件库”更适合当前项目：风险低、改动可回滚、不会破坏 terminal fit、CSS zoom、Teleport 菜单坐标和现有无障碍行为。

## 2. 当前项目审计

### 2.1 技术边界

| 项目 | 当前事实 | 升级约束 |
|---|---|---|
| 应用壳 | Tauri 2 + Vue 3 + TypeScript + Vite | 不改成 React/其他 UI 框架 |
| 状态/业务 | Pinia、Vue composables、现有 stores | 不把视觉状态复制到 CSS 之外的新状态层 |
| 样式组织 | `src/styles.css` + 22 个 Vue SFC 的 `<style scoped>` | 保持原生 CSS；允许新增原生 `.css` 文件，但不引入预处理器 |
| 终端 | `@xterm/xterm` 及 addons | 终端绘制区域和字号补偿不能被普通 UI 样式污染 |
| 主题 | `theme.ts` 写入 `data-theme`，`styles.css` 重定义暗/亮色变量 | 继续使用同一机制，避免首次渲染闪烁回归 |
| UI 缩放 | `ui.font_scale` → `.app { zoom }`，终端反向补偿 | 本轮不迁移 CSS zoom；这是已记录的高风险 NO-GO |
| 响应式 | `compact / standard / wide` + `data-tier` | 保留布局等级，补齐每一级的视觉密度和抽屉行为 |
| 测试 | Vitest、vue-tsc、Vite build，已有 token/a11y/layout/theme 测试 | 美化必须作为增量回归，不以截图替代行为测试 |

### 2.2 已有资产（应保留）

1. `styles.css` 已经有 spacing/type/radius/shadow/z-index/duration 设计令牌。
2. 暗色与亮色主题已有语义色入口，且 `index.html` 有首帧主题预绘制。
3. `button:focus-visible` 与 `prefers-reduced-motion` 已有全局基础规则。
4. `data-tier` 已按有效 box 宽度计算，TabBar 已支持横向滚动。
5. Dialog focus trap、菜单键盘打开、Terminal reduced-motion 等行为已有测试/实现，不能因为视觉重构而退化。
6. 组件就地样式使得局部回滚容易，适合先引入 Primitive 再渐进替换。

### 2.3 主要问题

#### A. Token 体系有基础，但没有完全闭环

当前全局定义了 `--surface`、`--text-*`、`--accent`、`--space-*` 等变量，但组件中仍出现多组未在全局正式定义的历史别名，例如 `--muted`、`--danger`、`--text-dim`、`--accent-soft`、`--accent-dim`、`--warn-dim`、`--accent-text`、`--mono`。

部分组件通过 `var(--token, #fallback)` 兜底。这种写法能避免测试环境空样式报错，但会导致：

- 同一语义在不同组件落到不同的颜色；
- 暗/亮主题不能真正统一覆盖；
- 当前 token 测试会主动剥离 fallback，无法发现“未定义 token + 视觉 fallback”问题；
- 后续修改只能逐组件找颜色，不能从设计令牌集中控制。

#### B. 基础控件重复实现

App、GuidePane、RuntimeSidebar、Onboarding、Provider、Network Usage 等多处各自定义 `button`、输入、菜单、卡片和间距。视觉上容易出现按钮高度、边框、圆角、hover、disabled、危险操作不一致。

#### C. 视觉层级仍偏“工程默认值”

当前整体是高密度、平面、低装饰的 IDE 风格，这个方向是正确的；但 Shell、WorkspaceBar、TabBar、Explorer、Status Drawer 和主终端之间的层级差异还不够明确，尤其是：

- 主次表面、分隔线和当前选中态不够系统；
- active tab、active explorer row、runtime state 的视觉语法没有完全统一；
- icon button 多使用 `+`、`▾`、`ⓘ`、`✕`、`↻`、`⚠` 等文本 glyph，跨平台字体/基线不稳定；
- 空状态、loading、错误、成功状态主要靠文字和颜色，缺少统一结构；
- 右侧 Status Drawer 的打开/关闭、菜单、toast 仅少量路径有动效，体验不成体系。

#### D. 组件内存在颜色 fallback 和原始视觉值

现有 token gate 对组件中的裸 hex 有约束，但允许 `var(--x, #...)`。这让代码看似“已 token 化”，实际上仍存在散落颜色。另有少量组件直接使用 rgba 阴影/遮罩和未抽象的 8px/10px/13px 等值。

#### E. 响应式已有结构，但不是完整的视觉策略

Compact 目前主要隐藏/收缩内容和让 TabBar 横向滚动；Standard/Wide 的空间利用、Explorer 预览、Status Drawer 宽度、长路径、长中文文案的截断规则还应统一。

另外，`App.vue` 的 scoped 样式中存在针对子组件内部 `.sidebar`、`.explorer-dock`、`.status-drawer` 的 Compact 选择器。Vue scoped CSS 不应依赖父组件选择器穿透子组件内部实现；这些规则应迁移到各自拥有 DOM 的组件中，使用 `:global(.app[data-tier="compact"])` 作为外部状态入口，或显式传递 tier。否则规则可能失效，也会让响应式责任边界模糊。

#### F. 应用品牌仍有脚手架痕迹

`index.html` 仍使用 `/vite.svg` 和 `Tauri + Vue + Typescript App`。这是低风险、高收益的首批清理项：替换为 AISC 本地 SVG/ICO 与正式标题，并保持离线可用，不加载网络字体或远程资源。

## 3. 推荐视觉方向

### 3.1 产品气质

推荐继续保持“开发者工作台 / IDE command center”，而不是改成营销型 Dashboard：

- **高信息密度，但不拥挤**：控制高度、间距、字体层级可预期；
- **暗色优先、亮色等价**：暗色适合终端，亮色不是简单反转，而是独立校准的语义表面；
- **平静表面、少量层次**：不使用大面积渐变、玻璃拟态、强发光和装饰性 hero；
- **状态优先**：运行、启动、停止、错误、警告、过期、选中必须一眼可区分；
- **动作有主次**：主操作只有一个 accent，次操作使用低强调，危险操作独立语义。

### 3.2 建议的视觉层级

```text
Canvas        应用/终端底色
Surface       顶栏、工作区条、TabBar、Explorer 背板
Raised        抽屉、菜单、浮层、表单卡片
Interactive   button/input/row 的默认表面
Hover         hover/focus/keyboard 操作反馈
Selected      active tab、active explorer row、当前 provider
Status        success / info / warning / danger 的前景与弱背景
```

原则是每个组件只选择一个层级，不在一个小区域叠三层卡片；终端仍是主视觉，不给终端外面增加大卡片边框。

### 3.3 首轮候选视觉基线

以下不是额外主题，而是首轮实现可直接落地的基线；评审时可以微调色值，但不改变语义结构：

| 语义 | Dark 候选 | Light 候选 | 用途 |
|---|---:|---:|---|
| canvas | `#101319` | `#f4f6f9` | 应用与终端外层底色 |
| surface | `#171b23` | `#ffffff` | 顶栏、TabBar、Explorer |
| raised | `#202631` | `#eef2f7` | 菜单、抽屉、表单卡片 |
| interactive | `#272e3a` | `#e7ecf3` | 按钮、输入、可交互行 |
| border | `#303846` | `#d7dee8` | 普通分隔线 |
| text | `#e8edf5` | `#18202b` | 主文字 |
| muted | `#9ba7b7` | `#647286` | 次要说明 |
| accent | `#4f8cff` | `#2869d8` | 主操作、选中和 focus |
| success | `#58c98b` | `#208353` | 成功/运行 |
| warning | `#e1ad52` | `#9a6400` | 等待/警告 |
| danger | `#ef737b` | `#bd3038` | 错误/危险操作 |

字体不下载外部资源。默认 UI 字体建议改为 Windows/中文友好的系统栈：

```css
--font-sans: "Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", system-ui, sans-serif;
--font-mono: "Cascadia Mono", "Cascadia Code", Consolas, monospace;
```

控件密度建议以桌面工具为准：普通按钮/输入 32px，高密度 icon button 28px，主向导动作 36px；不机械套用移动端 44px 高度，但必须保证键盘 focus 和点击区域清晰。

## 4. CSS 技术方案

### 4.1 样式入口与文件组织

不引入预处理器。建议保留 `src/styles.css` 作为唯一入口，并使用原生 CSS `@import` 拆分职责（若团队希望更少文件，也可以先合并到 `styles.css`）：

```text
workbench/src/
  styles.css                 # 唯一入口：reset、import 顺序、全局可访问性
  styles/
    tokens.css               # 主题无关 token + 暗/亮语义 token
    base.css                 # box-sizing、body、表单原生基线、selection
    primitives.css           # ui-button/ui-input/ui-panel/ui-menu 等通用类
    utilities.css            # sr-only、stack、cluster、truncate 等少量工具类
```

`<style scoped>` 继续用于组件布局和组件独有状态；跨组件重复的控件外观进入 `primitives.css`。不做“一次性把所有局部样式搬到全局”的大迁移。

### 4.2 Token v2

第一阶段先补齐而不是重命名现有 token，避免大面积无关 diff。建议新增以下族：

```css
:root {
  /* typography */
  --font-sans: Inter, "Segoe UI", Avenir, Helvetica, Arial, sans-serif;
  --font-mono: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
  --line-tight: 1.2;
  --line-normal: 1.45;
  --line-relaxed: 1.6;

  /* density / controls */
  --space-0: 0;
  --space-5: 20px;
  --space-7: 28px;
  --control-h-sm: 28px;
  --control-h-md: 32px;
  --control-h-lg: 36px;

  /* semantic aliases: old names remain during migration */
  --canvas: var(--bg);
  --panel: var(--surface);
  --panel-raised: var(--surface-2);
  --panel-interactive: var(--surface-3);
  --panel-hover: var(--surface-hover);
  --panel-selected: var(--surface-active);
  --divider: var(--border);
  --text-primary: var(--text);
  --text-secondary: var(--text-2);
  --text-tertiary: var(--text-muted);
  --text-disabled: var(--text-faint);
  --state-danger: var(--error);
  --state-danger-bg: var(--error-bg);
}
```

实际命名以实现时的 token 表为准，但必须做到：

- 颜色只在 `tokens.css`/`styles.css` 主题块中定义；
- 组件不再使用未定义历史别名；
- 组件不再使用 `var(--x, #color)` 作为生产视觉 fallback；
- `font-family`、line-height、control height、overlay shadow、focus ring 也纳入 token；
- 暗/亮主题分别校准 text/surface/border/status 对比度，不把暗色值机械取反。

### 4.3 Primitive，而不是组件框架

新增少量原生类，避免每个 SFC 再发明一套控件：

| Primitive | 使用范围 | 视觉责任 |
|---|---|---|
| `.ui-button` + `data-variant` | primary/secondary/ghost/danger/info | 高度、padding、border、hover、disabled、focus |
| `.ui-icon-button` | close、refresh、info、reopen、menu | 固定点击区、glyph/SVG 对齐、tooltip 依赖 title/aria-label |
| `.ui-field` / `.ui-select` | Settings、Provider、Subscription | label、input/select、错误、帮助文字 |
| `.ui-panel` | 表单卡片、诊断内容、启动摘要 | surface、border、radius、padding、阴影层级 |
| `.ui-badge` + `data-state` | runtime/provider/session/status | 状态背景、前景、密度和 text fallback |
| `.ui-menu` / `.ui-menu-item` | Tab 菜单、Explorer 菜单、Terminal 菜单 | raised surface、viewport 边界、hover/focus/disabled |
| `.ui-empty-state` / `.ui-feedback` | 空列表、loading、warning、error、success | 图标位、标题、描述、动作位置统一 |
| `.ui-section` | Sidebar、Settings、Usage、Explorer 分组 | 标题、分隔线、折叠/详情区域层级 |

Primitive 只负责外观，不负责业务和状态管理；组件通过 `data-variant`、`data-state`、`aria-*` 表达状态，避免把颜色语义编码进散乱 class 名。

### 4.4 图标策略

第一轮不引入图标依赖。先统一现有文本图标的 `.ui-icon-button` 点击区和基线；第二轮将高频 glyph（关闭、刷新、信息、重开、展开、警告）替换为项目内受控的 inline SVG 或本地 SVG mask 资源：

- 不用 emoji 作为功能图标；
- SVG 必须 `aria-hidden="true"`，按钮本身保留 `aria-label`；
- 终端输出内容不受 icon CSS 影响；
- 图标尺寸、stroke、颜色通过 token 控制。

### 4.5 动效策略

只引入“反馈型”动效，不做持续装饰：

- 允许 opacity/transform 的 120–180ms 过渡；
- Drawer/menu/dialog 使用 enter/leave；toast 使用轻微位移；当前 provider 切换保留短暂强调；
- 禁止对 width/height/top/left 等布局属性做高频动画；
- spinner、pulse、row flash 统一到 `--duration-*`，并在 `prefers-reduced-motion: reduce` 下变为无动画或静态状态；
- 不用 backdrop-filter、重 blur、霓虹阴影作为默认效果，保证 WebView2 性能和终端清晰度。

## 5. 分阶段实施顺序

### Phase 0 — 视觉基线与安全网（0.5–1 天）

**目标**：先固定现状，避免“美化后不知道破坏了什么”。

工作项：

1. 记录暗色/亮色、Compact/Standard/Wide、font scale `0.8/1.0/1.5` 的截图清单。
2. 覆盖核心路径：首次引导、workspace picker、启动成功/失败、ready workspace、Tab、Explorer、Status Drawer、Settings、Doctor、Provider UI、Network Usage。
3. 建立验收表：终端 fit、Teleport 菜单定位、focus ring、Escape 关闭、键盘 tablist、长路径/中文长文案。
4. 不改业务逻辑；只建立基线和问题清单。

**门禁**：`npm run test`、`npm run build`、`npx vue-tsc --noEmit`（或项目已有 build 脚本）在基线分支通过。

### Phase 1 — Token v2 与 Primitive 基础层（1–2 天）

**目标**：先解决视觉一致性，再动页面。

改动范围：

- `workbench/src/styles.css`，或新增 `workbench/src/styles/*.css`；
- `workbench/src/lib/__tests__/tokens.test.ts`；
- 新增 Primitive 样式与必要的通用 class；
- 迁移未定义别名和 `var(..., #fallback)`。

执行步骤：

1. 补齐 typography、line-height、control、panel、state、overlay tokens。
2. 建立旧 token → 新语义 token 的兼容映射，先不全量重命名。
3. 统一 button/input/select/textarea/checkbox/range 的尺寸、focus、disabled、placeholder。
4. 将 App、GuidePane、RuntimeSidebar、Onboarding、Usage、Provider 的重复控件逐步切换到 Primitive。
5. 为 token 定义增加自动检查：定义的 token 必须可解析；组件引用的 token 必须存在；生产样式禁止未审计颜色 fallback。

**验收**：组件样式中不再出现未定义 token；新增 token 测试；暗/亮主题下按钮、输入、状态 badge 的外观一致。

### Phase 2 — Shell 与工作区层级重塑（2–3 天）

**目标**：让用户第一眼理解“应用壳 → workspace → tabs → terminal → side panels”的层级。

优先文件：

- `App.vue`
- `features/workspace/WorkspaceBar.vue`
- `features/workspace/WorkspaceView.vue`
- `features/workspace/TabBar.vue`
- `features/workspace/RuntimeSidebar.vue`
- `features/workspace-explorer/WorkspaceExplorer.vue`
- `features/terminal/PaneTree.vue`
- `features/terminal/Terminal.vue`（仅 chrome/overlay，不碰 xterm renderer）

视觉改造：

1. 顶栏：品牌、workspace 状态、全局动作采用明确的 primary/secondary/quiet 层级；Compact 隐藏非必要状态但保留可达性。
2. WorkspaceBar：当前 workspace 使用 `selected` 语义，启动/错误/停止状态统一使用 badge 和辅助文字；关闭按钮固定点击区。
3. TabBar：active tab 使用 surface + accent indicator，不依赖单一底部边框；session state 使用统一 badge/状态点；Tab 过多仍横向滚动。
4. Explorer：分组标题、树行 hover/selected、artifact badge、preview 区域统一；长路径只在必要位置显示完整 tooltip。
5. Terminal：保持背景、padding、xterm canvas 和 pane divider 性能；只优化外部 toolbar、搜索层、右键菜单和空 guide。
6. Status Drawer：打开态增加明确标题/关闭动作/层级阴影，默认收起策略保持不变；状态摘要与 developer details 继续分层。

**验收**：ready workspace 在三种布局等级和两种主题下层级清楚；终端可用面积不下降到不可用；无交互契约变化。

### Phase 3 — 启动、引导、设置、诊断和业务页统一（2–3 天）

**目标**：消除“主工作区已美化，但边缘流程仍像另一套 UI”。

优先文件：

- `features/onboarding/OnboardingWizard.vue`
- `features/startup/*.vue`
- `features/settings/SettingsForm.vue`
- `features/doctor/DoctorDialog.vue`
- `features/ccswitch/CcSwitchUiTab.vue`
- `features/usage/*.vue`

执行重点：

1. Onboarding：增加明确的步骤轨道/当前步骤层级、内容区最大宽度、错误与探测详情面板、按钮组主次。
2. Startup：picker、summary、progress、conflict、error 复用 `.ui-feedback` / `.ui-panel`，让“正在做什么、下一步能做什么、失败怎么恢复”成为固定结构。
3. Settings：统一 field row、分组标题、即时生效提示、错误消息和 footer action；保持现有 schema/校验/保存行为。
4. Doctor：summary 状态、check rows、traces、logs 使用统一 state badge、details、scroll 区域；危险/导出动作保持确认与脱敏契约。
5. Provider/Usage：列表 row、form card、toast、empty/loading/error 使用同一套 surface/state/action 规则。
6. 对中文/英文长文案、窄窗口、长 provider 名称和 URL 做 flex shrink/min-width 复核。

### Phase 4 — 响应式、动效与无障碍复核（1–2 天）

**目标**：把视觉升级变成可交付的体验，而不是只在默认窗口看起来好看。

1. Compact：Explorer/Status Drawer 的宽度、菜单安全定位、Tab overflow、actions wrap、表单单列。
2. Standard：保持终端为主面积，侧栏/抽屉边界清晰。
3. Wide：允许 Explorer preview、状态摘要和信息密度增加，但不强行填满空间。
4. 所有交互状态补齐 `:hover`、`:active`、`:focus-visible`、`:disabled`、`[aria-expanded]`、`[aria-selected]`。
5. 对 drawer/menu/dialog/toast/provider flash 统一 enter/leave；reduced motion 下静态化。
6. 检查 200% 视觉缩放、`ui.font_scale` 范围、系统亮暗切换和主题首帧无闪烁。
7. 复跑 keyboard/focus/escape/menu/tablist/dialog/tooltip 的既有测试与手测。

### Phase 5 — 清理、验收和发布说明（0.5–1 天）

1. 删除已迁移的重复控件规则、历史别名和无用 fallback。
2. 更新 `tokens.test.ts`、必要的 layout/a11y/theme 测试和组件回归测试。
3. 运行：

```powershell
cd workbench
npm run test
npm run build
```

4. 对照 Phase 0 截图矩阵复核，不要求像素级完全相同；要求层级、状态、可读性、操作反馈和终端功能无回归。
5. 将实际变更、未解决问题、截图矩阵和回滚点写入 `docs/plan` 对应验收记录。

## 6. 建议的文件变更边界

### 首批允许修改

- `workbench/src/styles.css`
- `workbench/src/styles/*.css`（如采用拆分）
- `workbench/src/lib/__tests__/tokens.test.ts`
- `workbench/src/App.vue`
- `workbench/src/features/workspace/{WorkspaceBar,WorkspaceView,TabBar,RuntimeSidebar}.vue`
- `workbench/src/features/workspace-explorer/WorkspaceExplorer.vue`
- `workbench/src/features/terminal/{PaneTree,GuidePane,Terminal}.vue`

### 第二批允许修改

- `workbench/src/features/onboarding/OnboardingWizard.vue`
- `workbench/src/features/startup/*.vue`
- `workbench/src/features/settings/SettingsForm.vue`
- `workbench/src/features/doctor/DoctorDialog.vue`
- `workbench/src/features/ccswitch/CcSwitchUiTab.vue`
- `workbench/src/features/usage/*.vue`

### 明确不在本计划范围

- 不改 Rust/Tauri IPC、Python CLI、容器协议、Pinia 数据契约。
- 不更换 Vue、Vite、xterm 或状态管理方案。
- 不引入 Tailwind、Bootstrap、Element Plus、Naive UI、Sass/Less/PostCSS。
- 不以一次性全局重写替代增量迁移。
- 不在本轮迁移 CSS zoom 到 rem，也不重写 Teleport 菜单的坐标算法。
- 不做大面积装饰性渐变、玻璃拟态、背景插画或营销型 Dashboard。
- 不用 emoji 作为新功能图标。

## 7. 验收标准（Definition of Done）

### 7.1 技术一致性

- [ ] 所有生产组件引用的 CSS custom property 都在 token 层定义。
- [ ] Vue SFC 样式不新增裸颜色；历史 `var(--x, #...)` 已迁移或有明确白名单理由。
- [ ] button/input/select/menu/panel/badge/feedback 至少各有一个可复用 Primitive。
- [ ] 暗色、亮色的同一语义状态使用同一 token 名称，不通过组件内覆盖颜色实现。
- [ ] 无新增框架、预处理器或第三方组件库。

### 7.2 视觉与交互

- [ ] Shell、WorkspaceBar、TabBar、Explorer、Terminal、Status Drawer 的层级在默认窗口一眼可辨。
- [ ] primary/secondary/ghost/danger/info 动作具有稳定且可预测的视觉差异。
- [ ] active/hover/focus/disabled/loading/success/warn/error/selected 状态都有文本或结构辅助，不仅依赖颜色。
- [ ] Compact/Standard/Wide 均可用；中英文、长路径、长 URL 不会把主要动作挤出视口。
- [ ] Drawer/menu/dialog/toast 的动效不影响定位、焦点和终端输入；reduced motion 正确退化。
- [ ] `ui.font_scale`、主题切换、terminal fit、Teleport 菜单和 xterm 搜索/右键菜单无回归。

### 7.3 验证命令与手测矩阵

- [ ] `npm run test` 通过。
- [ ] `npm run build` 通过。
- [ ] 主题：system/dark/light；布局：compact/standard/wide；字体：0.8/1.0/1.5。
- [ ] 流程：首次引导、启动成功、启动失败恢复、ready workspace、多 Tab、Explorer、Provider、Settings、Doctor、Usage。
- [ ] 键盘：Tab、Shift+Tab、Enter/Space、方向键、Home/End、Escape、Shift+F10/Menu key。
- [ ] 无障碍：focus ring、dialog focus trap/opener restore、reduced motion、状态文字/i18n。

## 8. 回滚策略

1. 每个 Phase 一个独立提交，禁止把业务修复和视觉迁移混在同一个不可回滚提交中。
2. Token v2 先保留旧 token 映射，任何组件迁移失败可单独回退 Primitive 使用而不回退主题机制。
3. Shell 与业务页分开提交；若终端 fit、Teleport 坐标或窗口缩放回归，优先回退对应组件 CSS，不回退全局主题。
4. 图标替换与结构性 HTML 调整分开提交；图标回滚不应影响 aria-label 和动作逻辑。
5. 如果视觉截图与运行时行为冲突，以终端输入、焦点可达、菜单定位、主题首帧和现有测试为硬门禁，宁可保留旧视觉规则。

## 9. 需要在实施前确认的产品取舍

以下给出默认建议；若没有额外意见，按默认建议执行：

| 问题 | 默认建议 | 影响 |
|---|---|---|
| 是否继续 IDE/工具型风格 | 是 | 不做营销 Dashboard；重心放在终端和 workspace |
| 暗色主题是否作为主视觉 | 是，亮色等价校准 | 终端可读性最好，亮色仍作为完整主题验收 |
| 是否引入第三方 icon 库 | 否 | 首轮用受控 inline SVG/本地资源，减少依赖和字体差异 |
| 是否迁移 CSS zoom | 否 | 保留现有稳定补偿系统，避免大面积几何回归 |
| 是否做大规模 DOM 重构 | 否 | 先通过 Primitive 和 token 迁移改善视觉，保持业务行为 |
| 是否加入重装饰动效 | 否 | 只做状态反馈动效，保护终端性能和专业感 |

## 10. 推荐第一批实际提交拆分

1. `style(tokens): close semantic token gaps and add token contract checks`
2. `style(primitives): add native button field panel badge primitives`
3. `style(shell): polish app bar workspace bar and tab hierarchy`
4. `style(workspace): polish explorer terminal chrome and status drawer`
5. `style(flows): align onboarding startup settings doctor and provider surfaces`
6. `style(a11y): normalize focus states motion and compact responsive rules`
7. `test(ui): add visual acceptance matrix and update plan evidence`

这样拆分后，每一步都能独立编译、测试、人工验收和回退；也方便后续与你逐项讨论“要不要更大胆的视觉变化”，而不用先承担全量重构风险。
