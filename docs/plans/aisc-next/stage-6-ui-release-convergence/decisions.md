# Stage 6 决策

- `D6-01` 保持 IDE/工具型视觉，不更换 UI 框架。
- `D6-02` responsive 先用布局等级，避免静默把 UI 缩到不可读。
- `D6-03` a11y 语义和键盘行为属于发布门，不是可选 polish。
- `D6-04` CSS zoom 只有在对照证据通过后才替换。
- `D6-05` operation tracing 本地有界、统一 redaction，不做未经同意的遥测上传。
- `D6-06` 诊断包导出前展示 allowlist 内容。
- `D6-07` migration/upgrade/rollback 通过后才能发布新 schema。
- `D6-08` 三平台未覆盖的项标记 N/A，不把未测试写成 PASS。
