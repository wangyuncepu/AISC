# Stage 6 验收台账

- `A-UX01-1` tokens 覆盖颜色/间距/字体/控件/z/duration，组件无新增主题硬编码。
- `A-UX02-1` 320/600/800/1280、中文/英文、100/150% 无关键控件溢出。
- `A-UX03-1` tabs/dialog/sidebar/context menu/reduced-motion 键盘与读屏通过。
- `A-UX04-1` 用户层无裸字符串/raw enum，字典/长文案通过。
- `A-UX05-1` zoom 迁移有性能/视觉对照；不通过则记录 NO-GO 并保留旧路径。
- `A-UX06-1` Sidebar 常驻摘要、developer details、危险操作层级和 stale 语义通过。
- `A-REL01-1` operation timing/error action/diagnostic redaction allowlist 通过。
- `A-REL02-1` pytest/vitest/cargo/build/contract/soak/axe/visual 和三平台适用门禁通过。
- `A-REL03-1` settings/history/artifact/onboarding/CLI current/previous migration、upgrade/rollback/uninstall 通过。
- `A-REL04-1` devlog/release notes/手测证据/规划归档完整；用户确认后合并发布。
