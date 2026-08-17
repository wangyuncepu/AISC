# Stage 0 UX/流程

本阶段用户可见内容以“门禁可解释”为主：基线命令失败显示环境差异、稳定错误码、重试/查看日志；不展示 secret。流程：

1. `prepare`：确认分支为 `stage-0-baseline-gates`、工作树干净、commit 为 `d2bdcd9` 的派生提交。
2. `run baseline`：生成 manifest 和 fixture hash；失败停止，不覆盖上次 PASS。
3. `run contract`：执行 Python/Rust/Vue contract tests；协议差异显示字段路径和版本。
4. `run soak`：按固定时长/输入运行，输出 p50/p95/max、峰值队列和 cleanup report。
5. `manual gate`：用户在适用 OS 按清单复现，记录版本、步骤、日志/截图。
6. `sign-off`：逐项写入 acceptance 证据；缺任一证据即 BLOCKED。

可访问性：命令日志有标题/错误摘要/可复制路径；不依赖颜色；键盘可执行重跑和展开详情。Non-goal 是建设新的诊断 UI。
