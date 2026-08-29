# Stage 8 验收

> **总门：PASS（2026-08-17）**——自动化全绿（Python 631 / cargo 191+7×3 / vitest 233 /
> vue-tsc 干净）+ 真机门 A-CS01..A-CS07 全 PASS + 用户 Workbench「Provider 管理」tab
> 增删改查手测 PASS。Provider **切换激活**不在 v1 契约内，记 IDEA-4 后续迭代。

| ID | 验收方法 | 结果 |
|---|---|---|
| A-CS01 | fake/real release metadata 解析 latest stable 和 prerelease/draft 排除 | **PASS**（fake 矩阵 21 用例 + 真机：live latest→v5.10.1 digest 校验一致；上游 504 时 fail-closed 实测；manifest 离线可复现构建成功） |
| A-CS02 | 构建镜像并核对 manifest、OCI labels、asset checksum | **PASS**（labels `org.aisc.cc-switch.version=v5.10.1` / `asset-sha256=be6836eb…` 与 GitHub API digest 逐字节一致；`source: manifest` 诚实标注） |
| A-CS03 | 官方 DeepSeek fixture review：endpoint、auth、模型 ID、`[1m]` | **PASS**（四页官方文档逐字取证 fixture；真容器 DB 验证 SONNET→`deepseek-v4-pro[1m]`、HAIKU→flash、EFFORT=max、preset 不写 token；弃用 ID 永不生成） |
| A-CS04 | Claude default/opus/sonnet/haiku/unknown + user override + refresh | **PASS**（ownership 刷新 13 用例：历史预设值升级/用户 override 保留/外溢产物升级/退役键清除；D8-11 修正为官方 sonnet→pro[1m]） |
| A-CS05 | 容器内打开 `cc-switch-ui` tab，确认无独立窗口且关闭可清理 | **PASS**（虚拟 tab 无窗口；手测 2026-08-17 用户确认增删改查基本无误） |
| A-CS06 | UI/CLI 同库 list/add/edit/delete，两个 writer 并发和 crash recovery | **PASS**（SQLite 后端假 CLI 真 BEGIN IMMEDIATE 并发 4 线程零丢失 + 写锁下读存活；真容器 adapter E2E 全舞步含 key 保留与恢复路径） |
| A-CS07 | argv/log/history/diagnostic/browser storage secret scan | **PASS**（argv 零 secret 断言；CLI stdout 全量 redaction；信封 SECRET_IN_ENVELOPE=false 实测；表单瞬态即清） |

|---|---|---|

证据必须记录 cc-switch 精确版本、容器 digest、Workbench/CLI 版本、OS/arch、测试名和脱敏日志。
