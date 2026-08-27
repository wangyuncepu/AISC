# v2.1.7 开发计划（体验批次）

> 状态：Draft / 待用户审阅
> 规划日期：2026-08-27
> 基线：develop `4c7beb0`（v2.1.7.dev0 已开池，版本契约四件套已 bump）
> 适用范围：Workbench picker/首页历史/引导/构建流程/产物面板/终端首屏/Provider 页/文件标注

## 1. 结论摘要

v2.1.7 是 v2.1.6-dev 封版后的第一个开发周期，主题为**上手体验与运行可感**：让新用户第一次打开就看得懂（终端教学、Provider 表头、文件标注语义）、等得明白（构建进度条、Docker 安装心跳）、管得清楚（工作区历史删除/上限/失效校验、引导页让位于 picker）。同时清偿 v2.1.6 封版期挂账（#27/#28/#29、app_version 日志、睡眠恢复行手测）。

## 2. 阶段总览

| 阶段 | 主题 | 对应需求 | 任务 | 规模预估 |
|---|---|---|---|---|
| S1 | 快修批：黑框闪现×2 + app_start 版本日志 + Provider 表头 | ⑤ + 挂账#29 | #30 | 0.5 天 |
| S2 | 工作区历史：彻底忘记/上限8+内联展开/路径失效校验 | ⑦⑧ | #31 | 1-1.5 天 |
| S3 | 引导重定位：直入 picker，环境检测后移 | ⑥ + 睡眠行 | #32 | 1 天 |
| S4 | 构建进度条 + Docker 安装心跳 | ① + 挂账#27 | #33 | 1.5-2 天 |
| S5 | 产物面板转圈根因调查与修复 + 轮询重绘优化 | ② + 挂账#28 | #34 | 调查 0.5 天 + 修复视根因 |
| S6 | 终端教学：bash 首屏速查卡 + help 分页教学 + 互动练习 | ③ | #35 | 1.5 天 |
| S7 | 文件改动标注语义与感知重设计 | ④ | （待建任务） | 1 天 |

依赖关系：S1-S3 相互独立可任意顺序；S4 与 S5 共享"事件粒度/渲染批次"经验但不阻塞；S6/S7 独立。默认按编号顺序推进，每阶段结束汇报，用户决定是否继续（沿用 [[gui-fine-tune-workflow]] 规约）。

## 3. 文档索引

- [`01-goals.md`](01-goals.md) —— 用户原始需求逐条、挂账清单、目标与非目标
- [`02-implementation-plan.md`](02-implementation-plan.md) —— S1-S7 实现要点与涉及文件域
- [`03-acceptance.md`](03-acceptance.md) —— 验收清单（A-217xx）与手测矩阵
- [`decisions.md`](decisions.md) —— 已拍板决策记录

## 4. 非目标（本周期不做）

- 不删除引导向导代码，仅隐藏主动入口（设置页保留）。
- 不重做产物面板信息架构，仅解决性能问题；交互重设计留待后续。
- 不做 macOS/Linux 实机矩阵（沿袭 v2.1.6 已知限制）。
- 不解析 winget 输出流计算 Docker 安装百分比（决策 D8：心跳+已耗时，不碰不稳的输出格式）。

## 5. 审阅结论与六件套映射（2026-08-27）

> 本节为审阅补充；与前文冲突时，以本节、`decisions.md` 的“审阅后状态”及验收补充为准。

### 5.1 文档形态

当前目录是 **5 文件紧凑版**，并不严格等同仓库既有的 `00-overview / 01-risk-analysis / 02-domain-contract / 03-ux-flow / 04-observability-testing / 05-implementation-plan` 六件套。为避免实施时遗漏，本批次采用下列映射：

| 六件套职责 | 本目录承载位置 |
|---|---|
| Overview / scope | `README.md` + `01-goals.md` |
| Risk analysis | `01-goals.md` §5 + `02-implementation-plan.md` §“审阅补充” |
| Domain contract | `02-implementation-plan.md` 的跨阶段契约与各阶段安全不变量 |
| UX flow | `02-implementation-plan.md` 的 S2/S3/S4/S6 状态流 |
| Observability / testing | `03-acceptance.md` + 各阶段事件/证据要求 |
| Implementation order | `02-implementation-plan.md` |

若后续继续扩展范围，应拆回标准六件套；本周期不再新增并行 SSOT 文档。

### 5.2 总体可行性

结论：**有条件可行**。S1、S3 的路由调整、S4 的诚实进度、S5 的调查先行、S7 的视觉统一方向均可落地；但 S2、S4、S6 不能按原估时直接开工，必须先冻结删除边界、事件契约和教学注入机制。

关键修订：

1. S3 只能后移“工作区启动检查”；CLI 能力协商仍是应用启动前置，WebView2 更不可能在 Workbench 卡片内自检修复。
2. S4 不是单纯前端进度条：需要 Python CLI 产生结构化 build event、Rust 转发、前端状态机三端同步；不得由前端解析 Docker 人类文本。
3. S2 的“彻底忘记”是破坏性跨存储操作，必须 fail-closed、可重试，并明确 host-bind toolchain 与 Docker named volume 的边界。
4. S6 的 PTY 首屏只能负责展示，不能让真实 shell 响应后续 `help`；命令注入必须经受控 shell/profile 或独立命令完成。
5. S7 开工前先盘点 authoritative change/provenance 数据；数据源没有 rename/delete 时不得靠 watcher 猜测。

### 5.3 修订后的规模区间

| 阶段 | 修订预估 | 备注 |
|---|---:|---|
| S1 | 0.5-1 天 | `app_start` 需移入取得 `AppHandle` 后的 setup 点 |
| S2 | 2-3 天 | 含删除事务、跨进程冲突、a11y 与安全负测 |
| S3 | 1.5-2 天 | 复用 preflight/summary 状态链，不新建第二套检测逻辑 |
| S4 | 3-4 天 | CLI/Rust/TS 事件 v2 + UI + 两条 Docker 安装后端 |
| S5 | 调查 0.5-1 天 + 修复未知 | 未出根因报告前不承诺修复工期 |
| S6 | spike 0.5 天 + 实现 1.5-2 天 | 先过注入决策门 |
| S7 | 1.5-2.5 天 | 若缺 authoritative rename/delete 数据，需缩 scope 或另立协议阶段 |

总体约 **10-15 个工程日 + S5 根因相关修复**，原 7-9 天估计偏乐观。

### 5.4 跨计划依赖

- S2/S3 必须服从 `runtime-lifecycle-ux` 的 workspace key、lease、toolchain 与启动 reconcile 契约。
- S2 不得绕开 `data_root` resolver 自行拼接 `%LOCALAPPDATA%` 路径。
- S4 必须保持 `aisc.build-events/*` 为 Python 权威协议，Rust/TypeScript 只消费结构化字段。
- S5 对 runtime snapshot 的优化不得破坏 request sequence / freshness / lease heartbeat 语义。
- 任一阶段触及 Docker named volume 时，继续遵守 `docker-resource-lifecycle` 的 ownership classification，不按名称猜测后删除。

### 5.5 审阅发现分级

- **P0（不开工即有安全/正确性风险）**
  - S2 原稿把 history 摘除与 data-root 递归删除描述成串行动作，但没有半失败、路径身份、reparse/containment 和并发 lease 的完整契约；这会造成“界面已忘记、磁盘仍残留”或误删风险。
  - S4 原稿承诺真实百分比，但当前 `BuildEvent`/CLI 主要仍是 opaque `build.output`；在事件源未升级前不能交付 D9 的百分比语义。
- **P1（需在对应阶段前冻结）**
  - S3 原稿的“环境检测后移”不能覆盖 CLI negotiate、Tauri/WebView2 启动前置；当前 App 仍有 onboarding gate，需明确 picker、全局 blocked gate、workspace preflight 的路由优先级。
  - D8 只写了心跳频率，未写 operation identity、取消/超时 kill+reap、安装完成后 engine-start 的独立状态；已在补充契约中补齐。
  - D10 原稿把 PTY 首屏注入与后续 `help` 响应放在同一候选集合，技术语义不成立；已限定为静态卡或受控 Bash/独立命令 spike。
  - S7 原稿直接要求四类变更和 Agent 归因，但当前数据模型未证明 rename/delete/provenance 全部可得；必须先做数据源盘点。
- **P2（验收/交付质量不足）**
  - 原验收有“无尖峰”“无闪烁”“设计感”等不可重复描述；已补充基准机、p50/p95/max、计数器、a11y 和负向场景。
  - 当前是五文件紧凑版，不是仓库标准六件套的物理目录结构；已在 §5.1 做职责映射，但若本计划进入长期维护，建议拆出标准文件而不是继续堆叠补充段落。

代码交叉检查的关键事实：当前 `app_start` 使用 Cargo 包版本、当前构建 UI 仍把输出作为 `build.output` 日志、当前 Docker 安装等待调用是阻塞式 `child.wait()`，而工作区历史已有 data-root resolver、workspace hash 和 lease 基础设施。因此本次补充以“复用已有基础、补齐协议/事务/验收”而非另起一套实现为原则。
