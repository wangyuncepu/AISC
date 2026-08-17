# Stage 9 验收

| ID | 验收方法 | 结果 |
|---|---|---|
| A-CSPOC01 | clean Windows VM 安装/启动/关闭/恢复 | 待执行 |
| A-CSPOC02 | session/tab/PTY 输入输出、取消、resize、child cleanup | 待执行 |
| A-CSPOC03 | native terminal golden transcript + 100MB output + CJK/IME/emoji | 待执行 |
| A-CSPOC04 | runtime/build/diagnostics/Provider CLI protocol fixture | 待执行 |
| A-CSPOC05 | `cc-switch-ui` tab 两种添加、编辑、删除、secret redaction | 待执行 |
| A-CSPOC06 | 8 小时 soak、sleep/resume、Docker restart、句柄/内存报告 | 待执行 |
| A-CSPOC07 | Tauri 对比：启动、吞吐、资源、a11y、维护成本和 crash recovery | 待执行 |

最终结论只能是 `REPLACE-CANDIDATE`、`PARALLEL` 或 `STOP`，并附证据、已知差异和下一阶段授权，不自动替换正式前端。
