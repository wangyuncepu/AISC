# Stage 10 验收台账

> 结果状态：待执行
> 结论枚举：`PASS` / `PASS-WITH-FOLLOWUPS` / `STOP`
> 证据要求：记录 commit、Workbench 版本、Windows/WebView2、主题、语言、有效宽度、font scale 和脱敏日志/截图路径。

| ID | 验收方法 | 结果 | 证据 |
|---|---|---|---|
| A-UI10-01 | 基线分支 `npm run test`、`npm run build`、`vue-tsc` 通过 | 待执行 | |
| A-UI10-02 | token 族完整、所有生产引用可解析、无新增未审计裸色/fallback | 待执行 | |
| A-UI10-03 | Primitive 覆盖 button/field/panel/menu/badge/feedback，variant/state 行为稳定 | 待执行 | |
| A-UI10-04 | dark/light/system 主题语义一致且首帧无闪烁 | 待执行 | |
| A-UI10-05 | Shell、WorkspaceBar、TabBar、Explorer、Status Drawer 层级和状态可辨 | 待执行 | |
| A-UI10-06 | terminal 输入、复制、搜索、右键菜单、pane split、resize/fit 无回归 | 待执行 | |
| A-UI10-07 | Compact/Standard/Wide：320/600/639/640/800/1100/1101/1280 有效宽度无关键溢出 | 待执行 | |
| A-UI10-08 | `ui.font_scale` 0.8/1.0/1.5 与系统 100/150/200% 下布局、菜单、终端可用 | 待执行 | |
| A-UI10-09 | onboarding/startup/settings/doctor/provider/usage 的 loading/error/empty/success 结构统一且动作可恢复 | 待执行 | |
| A-UI10-10 | 中文/英文、长路径、长 URL、长 provider 名称不挤压主要动作 | 待执行 | |
| A-UI10-11 | Tab、dialog、menu、drawer、Escape、focus-visible、opener restore、reduced-motion 手测通过 | 待执行 | |
| A-UI10-12 | secret redaction、Provider key mask、Doctor export 和业务数据边界无回归 | 待执行 | |
| A-UI10-13 | CSS diff 不污染 xterm renderer，普通输出和长输出无明显掉帧/输入延迟 | 待执行 | |
| A-UI10-14 | 每个阶段提交可独立构建、可定位回滚，未提交用户修改未被覆盖 | 待执行 | |
| A-UI10-15 | 结论、遗留项、issue、责任人、回滚点和文档链接齐全 | 待执行 | |

## 发布阻断条件

任一项出现以下情况，结论必须为 `STOP`，不得以视觉截图抵消：

- terminal 无法输入、复制、搜索、resize 或 fit；
- Teleport 菜单出屏、右键菜单无法用键盘打开/关闭；
- dialog focus trap、Escape 或 opener restore 失效；
- 主题首帧严重闪烁或状态对比度不可读；
- Compact/长文案导致主要操作不可见或不可达；
- 视觉提交改变 Tauri/Rust/CLI/Provider/Pinia 业务契约；
- secret、scrollback 或完整配置进入日志、历史或诊断产物。

## 结论记录

- 最终结论：待执行
- 通过提交范围：待执行
- 遗留项：待执行
- 下一步授权：待执行
