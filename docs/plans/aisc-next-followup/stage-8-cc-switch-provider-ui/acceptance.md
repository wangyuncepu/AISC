# Stage 8 验收

| ID | 验收方法 | 结果 |
|---|---|---|
| A-CS01 | fake/real release metadata 解析 latest stable 和 prerelease/draft 排除 | 待执行 |
| A-CS02 | 构建镜像并核对 manifest、OCI labels、asset checksum | 待执行 |
| A-CS03 | 官方 DeepSeek fixture review：endpoint、auth、模型 ID、`[1m]`；确认旧 `deepseek-v4-pro`/错误默认值不再生成 | 待执行 |
| A-CS04 | Claude default/opus/sonnet/haiku/unknown + user override + refresh | 待执行 |
| A-CS05 | 容器内打开 `cc-switch-ui` tab，确认无独立窗口且关闭可清理 | 待执行 |
| A-CS06 | UI/CLI 同库 list/add/edit/delete，两个 writer 并发和 crash recovery | 待执行 |
| A-CS07 | argv/log/history/diagnostic/browser storage secret scan | 待执行 |

证据必须记录 cc-switch 精确版本、容器 digest、Workbench/CLI 版本、OS/arch、测试名和脱敏日志。
