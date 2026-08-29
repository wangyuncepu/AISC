# Stage 10 可观测性与测试

## 1. 自动化门禁

### Token 与静态检查

- 扩展 `workbench/src/lib/__tests__/tokens.test.ts`：检查基础/语义/state token 族存在；
- 扫描 `workbench/src/**/*.vue`、`*.css` 中的 `var(--token)` 引用，引用必须可解析；
- 扫描新增裸 hex/rgb/hsl、`var(--x, #...)` 和未登记的字体/阴影值；
- 检查 Primitive 的 variant/state 清单与文档一致；
- 生产样式不能通过新增白名单绕过失败，白名单必须带文件、原因和到期阶段。

### Vue/component 行为

- 现有测试全量通过；
- 对 App、WorkspaceBar、TabBar、RuntimeSidebar、WorkspaceExplorer、GuidePane、Terminal chrome 增加/更新 smoke：状态 class、aria 属性、按钮动作和 slot 内容不回归；
- Onboarding/startup/settings/doctor/provider/usage 测试验证 loading/error/empty/success 的文案与 action；
- 不用 snapshot 替代行为断言，snapshot 仅可辅助检查稳定结构。

### 布局、主题与可访问性

- `layout.test.ts` 覆盖 639/640/1100/1101 以及 zoom 后有效宽度；
- `theme.test.ts` 覆盖 system/dark/light、首帧属性和切换；
- accessibility tests 覆盖 focus-visible、dialog trap/restore、menu keyboard、tablist、Escape、reduced motion；
- 长文案 fixture 覆盖中英文、长路径、URL、provider 名称和错误详情。

## 2. 人工验收矩阵

| 维度 | 最小矩阵 |
|---|---|
| 主题 | system、dark、light |
| 布局 | 320、600、639、640、800、1100、1101、1280px 有效宽度 |
| 字号 | `ui.font_scale` 0.8、1.0、1.5；系统显示缩放 100%、150%、200% |
| 语言 | zh-CN、en-US；长标题/长状态/长错误详情 |
| 流程 | onboarding、picker、preflight、launch success/error、ready workspace、多 tab、Explorer、Provider、Settings、Doctor、Usage |
| 输入 | 鼠标、Tab/Shift+Tab、Enter/Space、箭头、Home/End、Escape、Shift+F10/Menu key、终端输入/粘贴 |
| 可用性 | Docker ready/not-ready、网络断开、session 启动失败、空列表、loading、过期/stale、重试 |
| 性能 | 普通输出、长输出、terminal resize、drawer/menu 高频打开关闭 |

每个案例记录环境（Windows 版本、WebView2、Workbench commit、主题、语言、有效宽度、font scale）和结果。截图用于比较层级、溢出、状态和对比度，不要求像素级相同。

## 3. 终端与定位回归

必须明确执行：

- terminal 输入、复制、搜索、右键菜单、pane split、resize/fit；
- xterm canvas 未被 `.ui-*` 或全局 `button/input` 规则污染；
- `font_scale=0.8/1.0/1.5` 下列数、行数和光标位置合理；
- Teleport menu 在左/右/底部边界和高 DPI 下仍在视口内；
- dialog 打开后首焦点、Tab 循环、Escape 和 opener restore 正常；
- reduced-motion 开启时无必须等待的动画和 smooth scroll。

## 4. 性能与质量指标

本阶段不引入新遥测。至少记录：

- `npm run test` 的通过数；
- `npm run build` 与 `vue-tsc` 结果；
- 页面首帧无主题闪烁的手测结果；
- terminal resize/输出时是否出现明显掉帧、输入延迟或布局抖动；
- CSS 规则/资源变化是否引入异常 bundle 增长。

若性能差异无法量化，记录复现步骤、环境和结论，不把主观“感觉更快”写成证据。

## 5. 标准命令

```powershell
cd workbench
npm run test
npm run build
```

必要时单独执行：

```powershell
npx vue-tsc --noEmit
npx vitest run src/lib/__tests__/tokens.test.ts src/lib/__tests__/layout.test.ts src/lib/__tests__/theme.test.ts
```

Python、Rust、CLI、容器测试不因本阶段 UI 改动而重新定义；若变更审查发现越界，则回到对应模块的完整门禁。
