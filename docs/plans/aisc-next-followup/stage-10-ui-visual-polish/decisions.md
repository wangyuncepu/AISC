# Stage 10 决策记录

- `D10-01` 保持 IDE/开发者工作台定位，不做营销 Dashboard，不更换 UI 框架。
- `D10-02` 保持原生 CSS + CSS Custom Properties；不引入 Tailwind、组件库或 CSS 预处理器。
- `D10-03` 先补 token、再做 Primitive、再迁移页面；不一次性全局重写所有 scoped CSS。
- `D10-04` 视觉状态使用 token + `data-*`/`aria-*` 语义；不把颜色语义写散在组件 class 和 fallback 中。
- `D10-05` 暗色作为主视觉方向，亮色必须独立校准并参与完整验收，不能机械反转。
- `D10-06` 第一轮不增加第三方 icon 依赖；图标替换如有需要，使用受控 inline/local SVG，并与行为变更分提交。
- `D10-07` 继续保留 CSS zoom。由于终端反向补偿、有效宽度计算和 Teleport fixed 菜单都依赖现有机制，本阶段不做 rem 迁移。
- `D10-08` 终端是硬边界：只改外围 chrome/overlay，不改 xterm renderer、PTY、scrollback、fit 和输出协议。
- `D10-09` 动效只用于短时反馈，优先 opacity/transform；reduced-motion 下静态化；不做高频布局属性动画。
- `D10-10` 行为测试、键盘可达性和终端可用性优先于截图像素相似度；两者冲突时保留行为正确的实现。
- `D10-11` 本阶段不增加遥测；性能证据使用本地测试日志和可复现手测记录。
- `D10-12` 阶段边界以独立提交为准；发现业务 bug 或协议变更必须另开提交，不借视觉任务合并。
- `D10-13` 失败策略为局部回滚或 `STOP`，不扩大 scope 以追赶视觉目标；NO-GO 事项必须保留证据。
