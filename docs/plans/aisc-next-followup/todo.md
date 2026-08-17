# 待办与门禁

## 想法 / Ideas

### IDEA-1 Tab 新建 UX（Windows Terminal 式，2026-08-17 用户提出）

- **内容**：设置页增加「默认新 tab」选项；点 `+` 立即建默认 tab；`+` 旁加 `↓`
  展开完整列表选择（拆分按钮）；设置页本身改为一种 tab 类型。
- **现状**：**已实现**（分支 `ui-tab-ux-followup`，2026-08-17 用户手测基本 PASS；
  手测反馈「设置 tab 铺满去卡片」已当场修复）。`ui.default_tab_agent` 设置字段
  （Rust 校验/默认 bash/REL-03）、共享 `SettingsForm`（dialog/tab 双模式）、虚拟
  设置 tab（哨兵 id，不持久化/无会话/不计 8 上限）、`+` 拆分按钮（默认直建 + ▾
  菜单含设置项）。KI-2（向导复检）同轮 PASS；KI-1 仍未 exercised。
- **历史**：`+` 菜单被 tabbar 滚动容器裁剪的 bug 已单独修复（Teleport + zoom
  补偿；Stage 6 UX-02 回归，非 Stage 7 范围）。
- **KI-1 进展（2026-08-17 同轮，用户真机复验 PASS）**：已装未启动场景可正常唤起，但弹
  Dashboard 前台窗 ——已实现**静默启动**（唤起前写 Docker 自身设置
  `OpenUIOnStartupDisabled: true`，等价 GUI 取消勾选 "Open Docker Dashboard at
  startup"，启动进托盘；只增不反向、保留其它键、原子写、损坏文件不动；
  settings-store.json 新键型 + settings.json 旧 camelCase 双兼容）。连带修复唤起反馈
  UX：向导环境步骤与 summary 页均为「转圈+已等待秒数」连续进度 + 就绪绿色提示/播报，
  轮询改静默探测（不再整页闪动），引擎 3 分钟未应答进度态自动收起。副作用须知：该设
  置全局生效，手动启动 Docker 也不再弹 Dashboard；恢复方法 = Docker Desktop
  Settings → General 重新勾选。

### IDEA-2 容器 TUN 模式的 mihomo 订阅配置（2026-08-17 用户提出，待规划）

- **内容**：用户在启动配置选择 `network=proxy`（容器 TUN）后，应引导用户配置
  mihomo 所需代理——输入其**购买的代理配置文件（订阅）链接**，Workbench 下载后
  作为容器内 mihomo 的配置文件。
- **待规划问题**（拟定计划时逐项决策）：
  - 订阅链接属敏感凭据：存储位置（settings vs data root 专属文件）、脱敏展示、
    是否随诊断包导出（默认否）；
  - 下载链路归属（Rust reqwest vs CLI 子命令）与超时/重试/离线失败 UX；
  - 配置形态假设：Clash 订阅（可整份用作 mihomo config）vs 需要 Workbench 合成
    基础配置 + 注入节点（TUN 段、DNS 段必须由我们控制，不能全盘信任订阅内容）；
  - 刷新策略（每次启动拉新 vs 手动刷新 + 缓存于 data root）、完整性校验
    （YAML 可解析、必要段落存在）；
  - 与现有 `network: direct|proxy` preflight/UI 的衔接点。
- **归属建议**：独立小阶段或并入 Stage 8 前置（涉及网络面，不动 Provider UI）。

### IDEA-3 顶栏设置按钮去留 + 工作区级 tab（2026-08-17 用户提出，待规划）

- **内容**：有了设置 tab 后，右上角顶栏「设置」按钮是否可取消？用户自答：取消后
  预配置阶段（无 runtime/无 tab 栏）无法进入设置 UI。设想：**设置 tab 不在
  runtime 内，而与工作区同级**——即出现更高一层的 tab 层级（工作区 tab），设置
  与工作区同层；同一层级也可打开**多个工作区 tab**。
- **待规划问题**：
  - 现架构为单工作区单窗口状态机（status: picker→summary→ready），多工作区 tab
    = 多 runtime 并存的会话/轮询/快捷键模型重构（Ctrl+Tab 语义分层）；
  - 预备态设置入口：保留模态对话框 vs 快捷键（如 Ctrl+,）直开设置 tab；
  - 与现有 session tab 栏的视觉层级（嵌套 tab 条 vs 顶栏下拉切换工作区）；
  - 迁移路径（先支持多工作区窗口再收顶栏按钮，避免中间态失去唯一入口）。
- **归属建议**：大改动，需独立 spec（影响 startup flow / history / 快捷键 / 关闭
  协调器），不与当前小项轮混合。

## 进入 Stage 7 前

- [x] 确认归档 `aisc-next` 的最终提交和迁移说明（最终提交 `f5a74e5`；目录随 followup 计划入库整体移入 `docs/archive/completed/`）；
- [x] 记录现有 workspace 根目录中会被迁移的文件清单（fresh 初始化实测，见 `stage-7-windows-data-root/02-domain-contract.md` Legacy layout 实测清单）；
- [ ] 定义 `AISC_DATA_ROOT` 的开发/测试覆盖和权限策略（7a-contract 实现内容）。

## Stage 7

- [x] Windows path resolver、workspace hash、lock、atomic replace（7a/7b）；
- [x] legacy scan、迁移 manifest、dry-run、rollback 和损坏隔离（7c/7d）；
- [x] CLI、Workbench、container mount 全部改用 resolver（7e）；
- [x] fresh/upgrade/multi-instance/long-path/disk-full 真机验收（7f，A-DATA01..05 PASS，
      用户手测 PASS 2026-08-17；磁盘不足为 mock 门，OneDrive 目录留发布前矩阵）。

## Stage 8

- [x] 预研最新 stable cc-switch 的 daemon/API 和数据库锁行为（8a 完成 2026-08-17：
      latest=v5.10.1/DB schema v16/无 HTTP API→Path B adapter/官方 CLI CRUD 表面+
      secret stdin+stdout 回显风险全固化；DeepSeek 官方 fixture 落
      `tests/fixtures/deepseek/official-api-facts.json`；详见
      `stage-8-cc-switch-provider-ui/8a-discovery-report.md` + D8-08..D8-12）；
- [ ] 实现 stable latest resolver、资产架构校验、SHA-256 和 image labels；
- [ ] 从官方 DeepSeek 文档生成 fixture，确认字段、模型 ID、endpoint 和 `[1m]`；
- [ ] 冻结 Provider UI protocol，完成 list/add/edit/delete 和 secrets redaction；
- [ ] 验证 UI/CLI 同库、并发写、preset refresh 用户覆盖和升级迁移。

## Stage 9

- [ ] 创建 `experiment/workbench-winui3`；
- [ ] 搭建 WinUI shell、native terminal control、session/tab 和 CLI bridge；
- [ ] 用同一 contract fixture 实现 Provider tab；
- [ ] 完成等价验收、性能/崩溃/高输出报告和替代决策建议。
