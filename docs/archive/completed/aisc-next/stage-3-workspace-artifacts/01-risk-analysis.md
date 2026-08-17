# Stage 3 风险分析

> 基线：`d2bdcd9`

| ID | 风险 | 影响 | 缓解与关闭证据 |
|---|---|---|---|
| R3-01 | `..`、绝对路径或 symlink/junction 越界 | 读取/打开 workspace 外文件 | Rust canonical containment；恶意矩阵 `A-ART05-*` |
| R3-02 | Skill 未调用或输出漂移 | 产物遗漏 | CLI 事实协议 + watcher 未归因兜底；`A-ART03-*` |
| R3-03 | watcher 把用户/构建变化误标 Agent 产物 | provenance 错误 | watcher 永远 `unattributed`；`A-WX03-*` |
| R3-04 | 大仓库递归扫描冻结 UI | GUI 不可用 | lazy listing、ignore、分页/上限、overflow rescan；`A-WX01-*` |
| R3-05 | registry 放进 workspace 污染 Git | 用户项目脏状态 | app-data/session scoped storage；`A-ART04-*` |
| R3-06 | artifact metadata 泄密 | 凭据/隐私泄露 | secret path policy、字段 allowlist、redaction；`A-ART05-*` |
| R3-07 | 多会话并发写丢记录 | 事实损坏 | revision/lock/merge/atomic replace；`A-ART06-*` |
| R3-08 | watcher overflow/丢事件 | Explorer 长期过时 | overflow 显式 stale + bounded rescan；`A-WX03-*` |
| R3-09 | 容器路径与宿主路径混用 | 打开失败/错误定位 | 只登记相对路径；Rust 映射宿主 workspace；`A-ART02-*` |
| R3-10 | `packaging artifact` 与 Agent Artifact 混淆 | API/文档冲突 | 完整命名和独立 schema/module；静态检查 |
| R3-11 | 预览超大/二进制文件 | 内存/安全问题 | MIME/size gate、只读 preview、外部打开 fallback |
| R3-12 | 文件 TOCTOU | 校验后路径被替换 | 打开前重新 canonicalize/metadata；失败可解释 |

残余风险：文件系统事件在不同平台不可完全一致；系统默认应用可能失败；网络盘性能不稳定。UI 必须显示 stale/unsupported，而非伪造成功。