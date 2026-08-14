# Stage 6 实施计划

1. `6a-tokens`: 视觉 token、组件映射、无关 diff 禁止。
2. `6b-responsive`: compact/standard/wide shell、Sidebar/Explorer/Tab/actions。
3. `6c-a11y`: dialog/menu/sidebar、reduced motion、axe/keyboard。
4. `6d-i18n-zoom`: raw string 清理；zoom baseline/feature flag/rem 迁移，terminal fit 证据。
5. `6e-observability`: operation timing、error action、redacted diagnostic bundle。
6. `6f-migration`: current/previous schema、upgrade/rollback/uninstall。
7. `6g-release`: 全测试、soak、三平台 bundle/NSIS、手测、release docs 和归档。

关键文件：styles/theme/App/Sidebar/dialog/menu/i18n/settings；Rust error/doctor/storage；CI/bundle/installer/release docs。每步独立提交，6d 可 NO-GO 保留 zoom，不能为“完成目标”强行迁移。