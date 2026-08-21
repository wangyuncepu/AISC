# Stage 10 阶段日志

## 10a-baseline ✅（2026-08-21）

- `9c5aa37`（develop）规划入库：八件套 + 来源分析 + README 登记，状态转 Accepted
- `531caa1` 基线证据：277 tests 全过、build 绿、CSS 锚点 58.69 kB(gzip 10.96)
- `a9b8823` 手测回填：C-01..10（3 过 2 部分 5 败）、B-01..08、D10-14 iOS 取向、D10-15 缺陷处置
- 分支 `stage-10-ui-polish` 自 9c5aa37 切出

## 10b-tokens ✅（2026-08-21，用户三轮手测反馈后关门）

提交（分支 `stage-10-ui-polish`）：

| commit | 内容 |
|---|---|
| `83e7f39` | 语义 token 收口：leading/font-mono/control-h/border-w/focus-ring/duration-slow/scrim/soft 淡底族 + 8 别名（token-mapping.md） |
| `8cfb0cf` | 八 Primitive（.ui-button/icon-button/field/panel/section/badge/menu/feedback） |
| `26d70e0` | 静态门禁：var() 全解析 + rgba 白名单（5 条带到期）+ primitive 存在性，277→280 |
| `fc245ef` | 试点 SubscriptionForm（scoped/global 层叠验证） |
| `8c7d982` | 用户反馈①「圆角生硬」→ radius-sm 8/--ease/--shadow-soft/边框弱化 |
| `a835d50` | 用户反馈②「picker 圆角不统一」→ 根因=抽组件丢按钮样式（UA 默认矩形） |
| `a64abc3` | 同类 sweep：OnboardingWizard 22 钮 + WorkspaceView 6 钮补 primitive |

门禁结论：280 tests + build 绿；暗/亮试点一致（用户确认「还可以」+ 迭代两轮）；xterm 无污染（终端手测正常）；CSS 66.0 kB（+7.3 为 primitive 本体）。

遗留入 10c/10d：别名迁移、rgba 白名单 5 条、Settings chip 10px/TabBar icon 3px 等散点 radius。

## 10c-shell ✅（2026-08-21，用户手测「全过」关门）

| commit | 内容 |
|---|---|
| `4518adb` | 10c-1 TabBar：下划线 tab → pill（radius-sm/32 高/accent-soft active），图标钮 24px，横向滚动+tablist 键盘零改动 |
| `d8d3b61` | 10c-2 顶栏/工作区条/侧栏：状态色文字、chip pill 化、mini 行/按钮对齐 |
| `5394c6f`+`c1a1553` | 顶栏徽章过重回退为轻量彩色文字；**流程事故：grep 吞 build 退出码带病提交 5394c6f，c1a1553 修复**（后续一律显式 exit 检查） |
| `1285b87` | 无容器 chip（设置/网络用量/启动器）隐藏恒灰状态灯 |
| `c864b79` | 10c-3 Explorer 分段 tab/圆角行/pill badge/圆角阴影菜单；抽屉容器 surface-2+shadow-2；终端外围 chrome 统一；fallback 全清迁正主 token |

手测硬门：Explorer 右键菜单坐标正、抽屉开合、终端输入/搜索/右键/复制、分屏 ×——用户确认全过。tab 新增动画按用户决策并入 10e 统一动效。CSS 68 kB 上下。

## 10d-flows（待用户授权）
