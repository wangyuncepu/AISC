# Stage 10 风险分析

| ID | 风险 | 触发信号 | 缓解措施 | 停止/回滚条件 |
|---|---|---|---|---|
| R10-01 | token 改名或兼容映射导致暗/亮主题语义错位 | 同一 state 在组件间颜色不同、token 测试失败 | 首轮补齐并保留旧别名映射；建立引用存在性扫描；按语义而非组件定义颜色 | 关键状态不可读或主题对比度明显下降时回滚 token 提交 |
| R10-02 | Primitive 全局选择器污染既有 scoped 样式 | 组件尺寸、button 默认行为或表单校验异常 | Primitive 只使用 `.ui-*` 类和 `data-*` 状态；不覆盖 xterm/terminal 内部节点；逐组件迁移 | 出现跨页面不可解释的尺寸/层叠回归时撤销对应 Primitive 使用 |
| R10-03 | terminal fit、canvas 或高频输出受普通 UI CSS 影响 | resize 后列数错误、光标漂移、输出卡顿 | Terminal renderer/PTY 文件只做 chrome 外层改动；不对 xterm canvas、字体和 scrollback 加全局规则 | 任一终端输入、resize、搜索或 100MB 输出回归即 STOP |
| R10-04 | CSS zoom 与新尺寸 token 组合造成几何回归 | `font_scale` 0.8/1.5、fixed menu、drawer 位置错误 | 延续现有 px/zoom 体系；不做 rem 迁移；用 live zoom 的边界矩阵验证 | 菜单无法定位或终端 usable area 下降时回滚，不强行修复 |
| R10-05 | Compact/长文案溢出主操作 | 中文/英文、长路径、长 URL 挤出按钮或横向滚动 | `min-width: 0`、可收缩区、actions wrap、tooltip/details；三档布局与长文案矩阵 | 关键动作不可见、不可键盘访问或出现未设计的页面级横滚 |
| R10-06 | a11y 视觉调整破坏键盘和焦点 | focus ring 消失、Escape 不关闭、dialog 无法恢复 opener | 保留既有 `useDialogA11y`、tablist/menu 语义；增加 component smoke 和手测 | focus 不可见、焦点陷阱失效、屏幕阅读器状态丢失即回滚 |
| R10-07 | 动效与终端/低性能 WebView2 冲突 | drawer/menu transition 掉帧、输入延迟 | 只动画 opacity/transform；duration token；`prefers-reduced-motion` 静态化 | 输入延迟、菜单关闭时序或 reduced-motion 失败 |
| R10-08 | 图标替换引入字体/跨平台差异 | Windows 中文环境基线错位、aria label 丢失 | 第一轮不引入依赖；仅统一点击区；第二轮 SVG 与行为变更分提交 | 图标缺失不应阻断功能；若 aria/键盘回归，撤销图标提交 |
| R10-09 | 业务逻辑与视觉提交混杂导致无法回退 | diff 同时改变 store、IPC、协议或操作时序 | 变更边界审查；每门独立提交；业务修复另开提交 | 发现协议或状态机变更时拆分/拒绝合入 |
| R10-10 | 静态检查过严拖慢迭代或诱发违规白名单 | 开发者大量绕过检查、fallback 白名单增长 | 先报告再阻断，逐阶段收紧；白名单必须带原因、文件和移除期限 | 白名单新增无理由、生产裸色持续增加 |
| R10-11 | 视觉截图被误当成行为验收 | 截图好看但键盘、resize、dialog 行为失败 | 行为测试和手测是硬门；截图只证明层级/溢出/对比度 | 任一行为门失败时结论不得 PASS |
| R10-12 | 未提交工作树内容被覆盖 | `git status` 中出现非本阶段修改被改写 | 开始前记录 status；只写入计划允许文件；提交前逐文件审查 | 任何用户已有修改被覆盖时立即停止并恢复现场 |
