# Stage 10 验收台账

> 结果状态：**PASS-WITH-FOLLOWUPS（已归档 2026-08-22：用户确认 + CI 三线全绿）**
> 结论枚举：`PASS` / `PASS-WITH-FOLLOWUPS` / `STOP`
> 证据要求：记录 commit、Workbench 版本、Windows/WebView2、主题、语言、有效宽度、font scale 和脱敏日志/截图路径。

## 验收矩阵（2026-08-21/22 执行）

| ID | 验收方法 | 结果 | 证据 |
|---|---|---|---|
| A-UI10-01 | 基线 `npm run test`、`npm run build`、`vue-tsc` 通过 | ✅ | 基线 277→结项 285 tests 全过；build/vue-tsc 绿（显式 exit 码验证） |
| A-UI10-02 | token 族完整、引用全解析、无新增未审计裸色/fallback | ✅ | tokens.test 引用解析+rgba 白名单 1 条+primitive 存在性（`26d70e0`/`62f5361`） |
| A-UI10-03 | Primitive 覆盖 button/field/panel/menu/badge/feedback | ✅ | 八件+30 变体断言；试点→全页面采纳（`fc245ef` 等） |
| A-UI10-04 | dark/light/system 主题语义一致且首帧无闪烁 | ✅ | 双 palette 同步扩 token；用户手测 C-09 PASS |
| A-UI10-05 | Shell、WorkspaceBar、TabBar、Explorer、Drawer 层级可辨 | ✅ | 10c 全门（用户「全过」）；stage-log 10c 表 |
| A-UI10-06 | terminal 输入、复制、搜索、右键菜单、split、resize/fit 无回归 | ✅（无回归） | 用户复测打字/复制/搜索/右键正常；xterm 零触碰（diff 审计）；⚠️ 基线既有 B-05/B-06/行错乱为出界挂账非回归 |
| A-UI10-07 | Compact/Standard/Wide 有效宽度无关键溢出 | ✅ | compact 规则沿用+新增组件全 min-width:0/截断；用户全程 1.0/1.5 双档使用 |
| A-UI10-08 | font_scale 0.8/1.0/1.5 布局可用 | ✅ | 用户主力 1.5 全程；菜单坐标两空间模型修正（`f0f797f`） |
| A-UI10-09 | 边缘流程 loading/error/empty/success 结构统一 | ✅ | 10d 三轮；feedback/badge/panel 语言统一 |
| A-UI10-10 | 长路径/长 URL/长 provider 名不挤压主操作 | ✅ | B-01/B-02/B-03 修复（`d9308eb`/`a9636dd`），用户复测确认 |
| A-UI10-11 | Tab、dialog、menu、drawer、Escape、focus-visible、reduced-motion 手测 | ✅ | B-07/B-08 根因修复（`bdf3771`/`7475c51`）；用户逐项 PASS；reduced-motion 系统 ✅ |
| A-UI10-12 | secret redaction、Provider key mask、业务数据边界无回归 | ✅ | 越界审计：零 store/协议改动；i18n 仅新增 explorer.change.* 三键 |
| A-UI10-13 | CSS 不污染 xterm；无掉帧/输入延迟 | ✅ | 全局层仅 color/cursor；用户终端回归 PASS |
| A-UI10-14 | 每阶段提交可独立构建、可定位回滚 | ✅ | 每提交独立 test+build 绿；回滚点见下 |
| A-UI10-15 | 结论、遗留项、回滚点、文档链接齐全 | ✅ | 本文件+stage-log.md+token-mapping.md |

## 发布阻断复核

全部阻断条件未触发：终端可用、菜单坐标正确（两空间模型+守卫）、dialog trap/Escape/restore 修复、主题无闪烁、长文案不遮挡、零业务契约改动、无 secret 入日志。

## 回滚点（按门）

| 门 | 起→止 commit | 回滚粒度 |
|---|---|---|
| 10a 基线 | `531caa1`→`a9b8823` | 纯 docs |
| 10b token | `83e7f39`→`a64abc3` | token/primitive/门禁/试点各自独立 |
| 10c Shell | `4518adb`→`c864b79` | TabBar/顶栏/Explorer+终端 chrome 分提交 |
| 10d 流程页 | `d9308eb`→`d9c6734` | startup/settings+doctor/provider+usage 分提交 |
| 10e a11y/动效 | `bdf3771`→`6bcf331` | trap 修复/动效库/各轮调优独立可回退 |
| 10f 清理 | `62f5361` | 白名单/别名清理，可独立撤销 |

## 遗留项（不阻断发布）

| 项 | 处置 |
|---|---|
| B-05 族终端三症（长输入不换行/fit 迟滞/快速切 tab 行错乱） | todo.md「UI10 终端非视觉缺陷」挂账，待专项排期（xterm/PTY 边界，D10-08） |
| tab 动效观感 | 用户「勉强通过」；motion token 已集中（--duration*/--ease*），后续调值一处生效。**已关闭（2026-08-25 用户确认）**：B-05 专项的终端切换遮罩动效（十三轮打磨）实质完成该项收口 |
| Settings chip 10px/DoctorDialog 残留散点 radius | 随 10f 清理已大部分收敛，余量低风险 |
| Vite HMR 失稳给陈旧代码 | 开发期坑已记录；重启 dev 即解 |

## 结论记录

- 最终结论：PASS-WITH-FOLLOWUPS（用户确认 2026-08-22；merge `d902374`；CI Workbench/Bundle/NSIS 全绿）
- 通过提交范围：`9c5aa37`（develop 规划）+ `stage-10-ui-polish` 38+ 提交（10a–10f）
- 遗留项：见上表，均已在 todo.md / stage-log.md 立案
- 下一步授权：用户确认 → 10g merge --no-ff 回 develop + push + CI
