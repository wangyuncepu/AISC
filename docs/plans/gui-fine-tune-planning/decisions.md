# GUI Fine-Tune 决策记录

> 状态：**Reviewed**（2026-08-09）  
> 作用：记录已接受决策及理由；实施细节以 `00`–`06` 正式规划文档为准。  
> 代码审阅基线：`1f15f8bbb6beeee0e9a6af8a4daa3310ee02747a`

## 一、目标决策台账

| ID | 状态 | 决策摘要 | 正式规格 |
|---|---|---|---|
| G-01 | ACCEPTED | 设置页范围固定为语言、UI 字号/缩放、终端参数、窗口记忆和关闭行为；本阶段不增加全局主题切换 | 02、06 Step 3/7 |
| G-02 | ACCEPTED | 先观测完整 resize 链路，找到第一处 rows/cols 偏差后再决定修改前端、Rust、CLI 或 cc-switch | 03、05、06 Step 9 |
| G-03 | ACCEPTED | 原始定义：「终端基础体验——搜索/复制/粘贴/滚动是否达标？」；实施范围冻结为 SearchAddon、剪贴板、scrollback/follow-output、输入与资源清理 | 03、06 Step 11 |
| G-04 | ACCEPTED | 原始定义：「主题——目前固定深色；MVP §6.2 不做大量主题，但明暗切换值得考虑」；范围冻结为 system/dark/light，不做主题市场或自定义 palette | 02、01 R-16、06 Step 17 |
| G-05 | ACCEPTED | 侧边栏拆为用户层和开发者详情；删除 1 秒 ticker，保留全部诊断字段 | 04、06 Step 8 |
| G-06 | ACCEPTED | WebGL 显式失败/context-loss 回退，优化字体、间距、颜色、scrollback 和 smooth scroll；ligatures 暂不作为本阶段强制交付 | 01 R-06、06 Step 6 |
| G-07 | ACCEPTED | CLI runtime stop 默认 10 秒、session terminate 默认 5 秒保持不变；Workbench 显式用较短参数和 Rust 有界回收；退出由统一 shutdown coordinator 完成 | 03、05、06 Step 2 |
| G-08 | ACCEPTED | Runtime ready 默认 1 个 Bash tab；`+` 始终提供四种 Session type；同 type 可重复；LaunchSummary 不再选择初始 Agent | 02、03、06 Step 5 |
| G-09 | ACCEPTED | `vue-i18n`，`zh-CN/en-US`；用户设置优先，`auto` 才读取安装器/系统语言；终端原始内容不翻译 | 02、06 Step 4 |
| G-10 | ACCEPTED | 使用 logical geometry、显示器夹取和 remember 开关；无记录时沿用 Tauri/OS 默认位置 | 02、06 Step 10 |
| G-11 | ACCEPTED | SearchAddon 当前未安装，需新增；右键菜单提供复制/粘贴/搜索/清屏并保持 PTY 输入边界 | 01 R-09、06 Step 11 |
| G-12 | ACCEPTED | 未配置 Claude/Codex 仍可从选择器进入引导态 tab；主 banner 位于 tab/pane 顶部，动作激活/创建 cc-switch | 02、04、06 Step 8 |
| G-13 | ACCEPTED | error/blocked 视图调用结构化 `aisc doctor --format json`；不解析人类文本，不自动执行修复 | 02、05、06 Step 12 |
| G-14 | ACCEPTED | 现有构建中计时迁移到 store，终态显示最终耗时；后台 complete/failed 使用 Tauri notification，权限失败仅降级 | 02、06 Step 13 |
| G-15 | ACCEPTED | 标题使用 workspace basename + 活动 Session type；活动 pane 优先，不展示 model/provider 或完整路径 | 02、06 Step 14 |
| G-16 | ACCEPTED | 目标定义为“可选最小化到托盘”；默认仍为 quit；tray 退出复用统一 shutdown | 03、06 Step 15 |
| G-17 | ACCEPTED | 一个 tab 拥有一个 PaneTree；每 Runtime/单 Workbench 的叶节点总数上限 8，opening/running/closing 另做资源原子计数；前端网格，不采用 tmux | 03、06 Step 16 |
| G-18 | ACCEPTED | Workbench sidecar 目录安全加入用户 PATH；不覆盖已有其他 `aisc`，使用 ownership marker，升级/卸载幂等 | 05、06 Step 1 |

## 二、跨目标决策

### D-01 控制面边界

Runtime 生命周期、Provider 查询和容器内 Session 创建/终止走 AISC CLI。Workbench Rust 可直接管理宿主 PTY 数据面及窗口、通知、托盘、settings/history、启动 Docker Desktop等宿主动作，但不得直接修改 Docker/registry/Provider 配置。

### D-02 退出性能与可靠性

不采用“前端 fire-and-forget 后立即 destroy，并假定后台继续执行”。必要 cleanup 由 Rust shutdown coordinator 持有并有总预算；完成/force-reap/flush 后才退出。

### D-03 数据安全表述

较短 `docker stop` grace 不会主动删除 container、image、volume 或 registry metadata，但不能承诺未刷盘的进程内状态零损失。CLI 默认值保持保守，Workbench 快路径只在显式用户动作中使用。

### D-04 History 兼容

G-08 不必为重复 Session type 升 schema，但必须迁移恢复算法为逐 `TabRecord` 重建。G-17 将 history schema 升为 v2，在锁内把 v1 平面 tab 原子迁移为单叶 PaneTree；旧版本对 v2 保持拒写保护。

### D-05 Settings 范围

本阶段 settings schema 是 GUI 偏好，不存 Session ID、PTY PID、scrollback、Provider 密钥或终端内容。Reset GUI settings 不清除 CLI pin、history、workspace 或 Runtime。

### D-06 可观察性用词

当前 ProviderStatus 契约没有 model 字段；UI 显示 provider 名、route 和 auth，不称其为模型。Bash/cc-switch/Claude/Codex 在 GUI 中统一称 Session type。

### D-07 自动化门禁

先补 Workbench 前端测试和 CI，再实施高风险功能。仅凭“实机正常”不能签收；实机证据必须关联验收 ID、commit、环境和结果。

## 三、被本次审阅明确取代的旧表述

以下旧说法不再有效：

- “正式规划文档未写”。
- “G-03/G-04 永久缺失”。两项目标已从 2026-08-09 原始规划对话恢复，并于本次审阅补齐正式规格、风险、步骤和验收。
- “docker stop 10→3 作为 CLI/Workbench 共享默认”。CLI 默认保持 10。
- “SIGKILL 快路径无数据损失”。
- “关窗并发发完即 destroy，后台收尾”。
- “history 多开直接兼容”。Schema 可兼容，但恢复算法必须迁移。
- “SearchAddon 已装无入口”。当前依赖未安装。
- “WebGL 插件自带自动回退”。应用必须显式处理失败和 context loss。
- “Provider 当前模型名”。现有契约只有 provider 元数据。
- “系统托盘常驻”暗示默认常驻。默认仍为 quit。

## 四、G-03/G-04 恢复依据

来源：2026-08-09 原始 GUI fine-tune 规划对话，最早候选表原文：

> `G-03 | 终端基础体验 | xterm.js 已装 FitAddon+SearchAddon——搜索/复制/粘贴/滚动是否达标？`
>
> `G-04 | 主题 | 目前固定深色；MVP §6.2 明确不做“大量主题”，但明暗切换值得考虑`

状态解释：该表初始属于“已知 GUI 痛点候选”，不是当时已签收规格。后续用户要求将讨论项纳入完整规划；因此本次恢复后标记 `ACCEPTED`，并在正式文档中冻结范围：

- G-03 与 G-11 共用 Step 11；G-03 管终端基础体验，G-11 管右键菜单入口，避免重复实现。
- G-04 仅做 system/dark/light，继续遵守“不做大量主题”。
