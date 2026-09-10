# UI 设计审查——对比 VS Code（2.1.11 规划输入）

> 2026-09-10，FIX-3 收官时点做的全 UI 交互面审查（代码级事实扫描 +
> 布局系统一手深耕知识）。基准取 VS Code 五条设计支柱：①可发现性
> 优先 ②一致的反馈语法 ③键盘一等公民 ④高信息密度 ⑤渐进披露。
> 用途：2.1.11（或 2.1.10 后续批次）UI 改进的规划排序依据。

## 已有的优势（保持，不要在重构中丢掉）

| 面 | 事实 |
| --- | --- |
| 设计令牌 | 双主题 ~40 语义 token 近全覆盖（light 单独调 shadow/scrim）；终端 palette 有 WCAG AA 对比度测试锁定；ui-button/menu/feedback/panel 原语类族成型 |
| 无障碍 | 24 文件 112 处 aria；焦点陷阱（useDialogA11y）/树与 tablist roving tabindex 均有测试；reduced-motion 全局折叠 + 局部守卫 |
| 交互细节 | resize settle-once 防抖（150ms）/veil 遮罩/sendResize 串行化；FIX-3 拖拽即时跟手 |
| i18n | 前端双语字典完整；CLI help 随 locale 输出层翻译 |

## A 级：结构性差距（影响「每天打开顺不顺手」）

- **A1 无命令面板 / 无 Ctrl+P / 无快捷键帮助**。功能发现面只有
  tooltip 与 ▾ 菜单；15 个快捷键全隐藏（全仓 `aria-keyshortcuts` 为 0，
  无 ?/F1 帮助面板）。VS Code 哲学是「任何功能三个入口：点、快捷键、
  palette」，本应用只有第一个。
- **A2 反馈语法不统一**。Toast 仅 cc-switch 局部自制一处
  （`CcSwitchUiTab.vue` Teleport+role=status——形态是对的，应提为全局
  原语）；loading 三种方言（纯文本「加载中…」/LaunchSummary 环形
  spinner/BuildProgress 结构化进度条）；空态全部纯文案无 CTA
  （`tabs.empty`/`explorer.empty.*`/`ccswitch.empty`/`usage.empty`）。
  VS Code 空态永远带 action。
- **A3 设置页无搜索无导航**。SettingsForm 七组单页纵滚
  （ui/terminal/window/hostTools/machines/performance/disk）；15 字段
  仅 4 个有帮助文案（helpKey）。组继续增长后找项成本指数放大。

## B 级：模式差距（影响「像不像专业工具」）

- **B4 信息架构缺 Activity Bar 层**。现为三层（dock→main→drawer），
  文件/会话/产物/服务四视图挤 dock 内 tabs。FIX-3 的 40px 折叠窄条
  已形似 activity bar——差一步：把四视图图标放上 rail（折叠态也能
  一键切视图），dock 内 tabs 腾给内容。
- **B5 快捷键与 VS Code 心智偏差**。缺 `Ctrl+W`（关标签，现仅点 ×）、
  `Ctrl+B`（切 Explorer，现仅 « 按钮）；`Ctrl+1..9` 映射 tab 而非编辑
  器组（IDEA-3 有意为之的不同隐喻——用户肌肉记忆不认「有意识」）。
- **B6 菜单每区自制**。五区（Terminal/GuidePane/Explorer/TabBar▾/
  WorkspaceBar▾）各自渲染 DOM/定位/键盘逻辑，仅共享 `.ui-menu` 视觉；
  菜单坐标系坑已修过多次（zoom 两空间模型）。应抽 useMenu composable。
- **B7 密度偏松**。基准 14px（VS Code 默认 13）；控件高 26/32/38 偏
  web 化。终端工具审美「紧凑=专业」，同屏信息量少约 15-20%。

## C 级：打磨差距

- C8 新用户路径变陡：向导 manual-only 后首开直达 Picker（GuidePane
  终端内引导补偿存在；Docker 环境类问题无梯子）。
- C9 无菜单栏（File/View/Help）——「运行诊断」「重开向导」低频入口
  缺体面住所。
- C10 右键菜单禁用项原因仅 title（hover 才可见）。

## 建议优先序（排期参考）

1. **A2 轻量版先行**：全局 Toast 原语（cc-switch 实例提升为 ui-toast）
   + 空态统一加 CTA——成本低、每天可见。
2. **B4 一箭双雕**：rail 图标化（FIX-3 窄条升级真 activity bar），
   顺势补 `Ctrl+B` 折叠切换。
3. **A1 完整命令面板**：Ctrl+Shift+P 列全部命令（菜单项即现成数据源）
   + `aria-keyshortcuts` 补注——「专业工具感」最大单点提升。
4. A3 / B6 / B7 按余力排。

## 事实来源（关键文件）

- 命令/快捷键：`App.vue:115-137`、`WorkspaceView.vue:256-316`、
  `Terminal.vue:801-850`（xterm handler）
- 反馈：`CcSwitchUiTab.vue:241-247`（toast 孤例）、`BuildProgress.vue`、
  `LaunchSummary.vue:215-222`、zh-CN.ts 空态键（:362/:543-552）
- 设置：`SettingsForm.vue:36-91`（FIELDS/GROUPS）
- 布局：`WorkspaceView.vue`（dock/rail/tabbar 分层）、`styles.css`
  （token :22-27/:77-173）
