# Stage 6 实施计划

1. `6a-ki1`: 查因并修复 KI-1（向导环境步骤无法识别 Docker ready）——`engine_reachable`
   加诊断（spawn err/非零退出/超时），暴露给「诊断」；区分 `docker version` vs
   `docker info` 就绪语义；GUI 进程 PATH/spawn 解析验证。**用户点名的 Stage 6 优先项。**
2. `6b-tokens`: 视觉 token、组件映射、无关 diff 禁止。
3. `6c-responsive`: compact/standard/wide shell、Sidebar/Explorer/Tab/actions。
4. `6d-a11y`: dialog/menu/sidebar、reduced motion、axe/keyboard。
5. `6e-i18n-zoom`: raw string 清理；zoom baseline/feature flag/rem 迁移，terminal fit 证据。
6. `6f-observability`: operation timing、error action、redacted diagnostic bundle。
7. `6g-migration`: current/previous schema、upgrade/rollback/uninstall。
8. `6h-release`: 全测试、soak、三平台 bundle/NSIS、手测、release docs 和归档。

关键文件：styles/theme/App/Sidebar/dialog/menu/i18n/settings；Rust error/doctor/storage；CI/bundle/installer/release docs。每步独立提交，6e 可 NO-GO 保留 zoom，不能为”完成目标”强行迁移。