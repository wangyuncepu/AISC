# Stage 6 风险分析

| ID | 风险 | 缓解 |
|---|---|---|
| R6-01 | 视觉重构引入可用性回归 | token/组件小步、截图和关键 flow smoke |
| R6-02 | compact/150% 内容溢出 | 320/600/800/150% 中英文矩阵 |
| R6-03 | a11y 修复破坏快捷键/终端 | keyboard component + manual WebView2 |
| R6-04 | CSS zoom 替换导致 terminal fit 抖动 | 先 baseline/feature flag，逐步迁移 |
| R6-05 | 诊断包泄露 secret/path/prompt | allowlist/redaction/preview before export |
| R6-06 | operation tracing 增加 I/O | bounded local ring/log sampling |
| R6-07 | schema 升级/卸载丢数据 | migration/backup/rollback matrix |
| R6-08 | 三平台环境差异 | 分层适用项，真实平台 smoke，不伪造 PASS |
| R6-09 | 质量门禁过重拖慢开发 | baseline 后增量阻止新增问题 |
