# Stage 6 决策

- `D6-01` 保持 IDE/工具型视觉，不更换 UI 框架。
- `D6-02` responsive 先用布局等级，避免静默把 UI 缩到不可读。
- `D6-03` a11y 语义和键盘行为属于发布门，不是可选 polish。
- `D6-04` CSS zoom 只有在对照证据通过后才替换。
- `D6-05` operation tracing 本地有界、统一 redaction，不做未经同意的遥测上传。
- `D6-06` 诊断包导出前展示 allowlist 内容。
- `D6-07` migration/upgrade/rollback 通过后才能发布新 schema。
- `D6-08` 三平台未覆盖的项标记 N/A，不把未测试写成 PASS。
- `D6-09`（6e，UX-05）**CSS zoom 迁移 = NO-GO（2026-08-16）**：`ui.font_scale` 的
  `zoom` 补偿系统工作正常——800px 设计基线、终端 1:1 反缩、position:fixed 菜单坐标
  除以 live zoom、右键菜单修正均围绕它运转；6b 已把全部字号/间距收敛为 px 版
  `--font-*`/`--space-*` token（未来 rem 迁移的基底），6c 的 `data-tier` 布局
  等级也按有效 box 宽度（viewport/zoom）计算。**保留 zoom**：rem 全量迁移需重写
  每个组件的字号/内边距/宽高并重新验证终端 fit（xterm canvas / 反缩 / 对话框），
  无可量化的用户收益且回归风险高。证据不足之前按 D6-04 不替换。
