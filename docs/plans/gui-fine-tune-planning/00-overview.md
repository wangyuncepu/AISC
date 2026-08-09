# GUI Fine-Tune 总览

> 状态：**已审阅 / 18 项目标定义完整**  
> 审阅日期：2026-08-09  
> 代码基线：`1f15f8bbb6beeee0e9a6af8a4daa3310ee02747a`  
> 基线规范：`docs/archive/gui-planning/00-overview.md` 至 `06-implementation-plan.md`

## 一、文档职责与冲突处理

本目录是 GUI fine-tune 阶段的规范入口。七份正式规划文档的职责如下：

| 文档 | 职责 | 规范性 |
|---|---|---|
| `00-overview.md` | 范围、术语、目标台账、全局门禁 | 产品与范围 SSOT |
| `01-risk-analysis.md` | 风险、缓解措施、残余风险与验证证据 | 风险登记 |
| `02-startup-flow.md` | 启动、默认标签、语言、窗口恢复、诊断和标题 | UX 规范 |
| `03-lifecycle-contract.md` | Runtime/Session/Tab/Pane/Window 生命周期 | Domain 规范 |
| `04-observability.md` | 侧边栏、Provider/auth、刷新与无闪烁要求 | UI 状态规范 |
| `05-cli-gui-contract.md` | CLI 控制面、PTY 数据面、PATH 与命令契约 | 技术 SSOT |
| `06-implementation-plan.md` | 实施顺序、代码落点、测试与 Definition of Done | 执行基线 |

`decisions.md` 仅记录决策及理由，**不是实施参数的权威来源**。

冲突处理顺序：

1. 产品范围和目标状态以本文档为准。
2. Runtime/Session/Tab/Pane/Window 状态冲突以 `03-lifecycle-contract.md` 为准。
3. CLI 命令、默认值、错误和 PATH 行为以 `05-cli-gui-contract.md` 为准。
4. 启动交互以 `02-startup-flow.md` 为准；展示和刷新以 `04-observability.md` 为准。
5. `06-implementation-plan.md` 不得覆盖上述不变量，只能安排实施顺序。
6. 归档基线固定为 commit `1f15f8bbb6beeee0e9a6af8a4daa3310ee02747a` 的 `docs/archive/gui-planning/`；只允许继承各当前文档头部“基线继承清单”明确列出的章节。未列出条款不构成隐式规范，归档后续改动也不会自动改变本计划。

## 二、目标完整性门

目标编号覆盖 `G-01` 至 `G-18`，共 18 项。G-03/G-04 已从 2026-08-09 原始规划对话恢复：

- G-03：**终端基础体验**——搜索、复制、粘贴、滚动达到可交付水平。
- G-04：**主题**——当前固定深色；不做“大量主题”，评估并交付明暗模式切换。

恢复证据和后续范围冻结记录在 `decisions.md`。18 项均须有风险、实施步骤和验收 ID，才能宣称全部完成。

## 三、范围

本阶段允许：

- 优化现有 workspace/runtime/session 工作流的性能、可理解性和可访问性。
- 增加设置、诊断、通知、右键菜单、窗口管理和安装器集成等宿主能力。
- 将固定四标签改为动态多标签，并在 P3 增加分屏会话组织模型。

本阶段不允许：

- 新增 Provider 配置编辑器、读取或展示密钥。
- 新增文件浏览器、编辑器、Git/调试器、资源图表或 Docker Dashboard。
- 恢复跨进程存活的 PTY/终端内容。
- 允许同一 canonical workspace 同时存在多个 `project` Runtime。
- 为 GUI 便利而改变现有 CLI 命令的默认语义或破坏 `aisc.cli/v1`。

## 四、术语

| 术语 | 定义 |
|---|---|
| Runtime | AISC CLI 管理的容器及其不可变 workspace/image/network/scope 配置 |
| Session type | GUI 中的 `Claude / Codex / Bash / cc-switch` 入口；CLI 参数名仍为 `agent` |
| Session | 一个独立 `session_id`、宿主 PTY、`aisc session open` 子进程和容器内进程组 |
| Tab | 顶层工作面；G-08 后可动态创建、重复使用同一种 Session type |
| Pane | G-17 分屏树的叶节点；一个叶节点至多绑定一个 Session |
| Provider | Claude/Codex 的脱敏 provider/route/auth 元数据；不是模型名 |
| User layer | 默认可见、面向用户的短状态和行动入口 |
| Developer details | 默认折叠的 ID、freshness、observed time、原始 route/auth 等信息 |

除引用 CLI 字段或代码符号外，GUI 文档使用 “Session type”，不把 Bash/cc-switch 统称为 Agent。

## 五、目标追踪矩阵

状态说明：`ACCEPTED` 可实施。

| 优先级 | ID | 目标 | 状态 | 主设计 | 风险 | 实施步骤 | 验收前缀 |
|---|---|---|---|---|---|---|---|
| P1 | G-01 | Workbench 设置页与 GUI 偏好 schema | ACCEPTED | 02、03 | R-03 | Step 3、7 | `A-G01-*` |
| P1 | G-02 | cc-switch/TUI resize 与显示修复 | ACCEPTED | 03、05 | R-08 | Step 9 | `A-G02-*` |
| P1 | G-03 | 终端基础体验 | ACCEPTED | 03 | R-09 | Step 11 | `A-G03-*` |
| P2 | G-04 | 明暗主题切换 | ACCEPTED | 02、03 | R-16 | Step 17 | `A-G04-*` |
| P1 | G-05 | 侧边栏信息分层、消除闪烁 | ACCEPTED | 04 | R-07 | Step 8 | `A-G05-*` |
| P1 | G-06 | 终端渲染升级 | ACCEPTED | 03 | R-06 | Step 6 | `A-G06-*` |
| P0 | G-07 | Session/Runtime/退出性能 | ACCEPTED | 03、05 | R-02 | Step 2 | `A-G07-*` |
| P0 | G-08 | 动态多 tab | ACCEPTED | 02、03 | R-04 | Step 5 | `A-G08-*` |
| P0 | G-09 | UI i18n | ACCEPTED | 02 | R-03 | Step 4 | `A-G09-*` |
| P2 | G-10 | 窗口尺寸与位置记忆 | ACCEPTED | 02、03 | R-05 | Step 10 | `A-G10-*` |
| P2 | G-11 | 终端右键菜单与搜索 | ACCEPTED | 03 | R-09 | Step 11 | `A-G11-*` |
| P2 | G-12 | Claude/Codex 未配置引导 | ACCEPTED | 02、04 | R-07 | Step 8 | `A-G12-*` |
| P2 | G-13 | 错误页一键诊断 | ACCEPTED | 02、05 | R-10 | Step 12 | `A-G13-*` |
| P2 | G-14 | 构建最终耗时与后台通知 | ACCEPTED | 02 | R-11 | Step 13 | `A-G14-*` |
| P2 | G-15 | 动态窗口标题 | ACCEPTED | 02 | R-12 | Step 14 | `A-G15-*` |
| P2 | G-16 | 可选最小化到托盘 | ACCEPTED | 03 | R-13 | Step 15 | `A-G16-*` |
| P3 | G-17 | Tab 内前端网格分屏 | ACCEPTED | 03 | R-14 | Step 16 | `A-G17-*` |
| P0 | G-18 | Workbench sidecar 加入用户 PATH | ACCEPTED | 05 | R-01 | Step 1 | `A-G18-*` |

## 六、全局不变量

1. **控制面单一**：Runtime 生命周期、Provider 查询及容器内 Session 创建/终止走结构化 `aisc` CLI；Workbench 不直接修改 Docker、registry 或 Provider 配置。
2. **PTY 数据面本地化**：Workbench Rust 可以直接管理宿主 PTY 的字节写入、resize、进程回收，以及窗口、托盘、通知、启动 Docker Desktop等宿主集成。
3. **CLI 独立可用**：CLI 默认值与纯终端场景不得因 GUI 快路径劣化；GUI 特殊行为使用显式参数。
4. **不泄密**：UI、日志、history、settings、通知和 crash detail 不包含 token、cookie、API key、OAuth 凭据或终端内容。
5. **事实与错误分离**：Runtime/Provider 事实状态来自有效 observation；操作错误不能覆盖事实状态。
6. **持久化可恢复**：settings/history 使用 schema、校验、原子替换和并发保护；不支持的 schema 不得被默认值覆盖。
7. **无隐式恢复承诺**：恢复 layout 只创建新 Session，不恢复旧 PTY、PID、scrollback 或 `session_id`。
8. **可测量验收**：禁止以“基本正常”“无明显闪烁”“实测后定”作为唯一验收标准。

## 七、发布门

全部可实施目标完成后，还必须同时满足：

- G-01 至 G-18 的全部验收 ID 均有 PASS 证据。
- Python、Rust、Vue/TypeScript、CLI 契约、bundle、NSIS smoke 全绿。
- Windows x86_64 完成 PATH、ConPTY resize、窗口/tray/通知实机证据；Linux x86_64 与 macOS arm64 完成不适用项之外的 smoke。
- 升级和卸载不破坏 settings/history、workspace、运行中的 Runtime 或用户已有 PATH 项。
- 每项验收证据包含平台、版本、步骤、结果、耗时/日志或截图及关联测试名。
