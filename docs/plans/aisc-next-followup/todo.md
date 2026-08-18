# 待办与门禁

## v2.1.6-dev 预览手测阻塞项（2026-08-18，draft 暂不发布）

> 来源：v2.1.6-dev 安装包"全新机器"手测（用户 2026-08-18）。发布前需逐项
> 解决；原始记录在 `docs/todo.md`「手测异常/问题」。

- **KI-3 首次运行 CLI 发现竞态（P1+P2 同族）**：✅ **已修（2026-08-18，
  随 IDEA-3 分支合并 develop）**——真根因是 `resolve_pin` 抢跑：向导期间
  negotiate 被推迟 → 环境探测/预检读 pin 落空 → 裸 `cli_not_found`
  （`technical_detail: null` 实锤）；重检时 negotiate 已写 pin 故恢复。
  修复：`session::resolve_cli`（15 个命令调用点）无 pin 时当场自动发现并
  落盘（`cli::auto_select_and_pin`）；另探测超时 15s→45s + 超时重试一次
  （冷启动 sidecar 解包+杀软首扫兜底）+ `cli_not_found` 携带逐候选明细。
  **待最终复验**：从含修复的提交重建安装包后在干净环境复测安装→首跑
  全链路（当前 v2.1.6-dev draft 构建于 `65ba5d5`，不含本修复）。
- **KI-4 卸载/升级的配套资源管理**：aisc 卸载、升级时应同步处理 Docker
  镜像（super-claude 等）、数据根等配套资源（删除/重建）；如能同步
  更新已有 container 更好。需先定策略（默认清理 vs 询问保留——与
    docs/todo.md「退出前询问是否保留 runtime」同族，可合并设计）。

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

### IDEA-4 Provider 一键切换激活（2026-08-17 用户提出；**2026-08-18 实现并手测 PASS**）

- **已实现**（分支 `idea-4-provider-switch`）：adapter `switch` 操作（真配置行走官方
  非交互 CLI；空配置官方行走 pty+自动应答；id slug 校验防注入）+ `official` 伪目标
  （取消代理回官方直连）+ codex 切换自动开/关本地代理路由 + codex auth.json 无密钥
  占位管理（修 Codex 自身首跑向导；真实登录永不触碰）+ 行点击/使用中行取消代理确认/
  无密钥切换确认 + 隐藏不可切换占位行 + 侧栏状态联动。手测五轮 PASS
  （2026-08-18 用户确认）。打磨项拆到 IDEA-5。

### IDEA-5 Provider 管理打磨（2026-08-18 用户提出，IDEA-4 手测瑕疵）

- **模型映射**：claude 侧缺少模型映射设置项（MODEL/OPUS/SONNET/HAIKU/SUBAGENT 五个
  角色位）。建议增加「从 API 拉取可用模型列表 → 用户下拉选择映射」的可选功能
  （仿照 cc-switch 桌面版）。上游已有 `provider fetch-models` 子命令可作数据源；
  preset 的官方默认集（8c）保持为初始值，用户映射覆盖后按 ownership 规则保留。
- **切换视觉反馈**：切换 provider 时的视觉效果较差（当前只有 3 秒横幅）——需设计
  更明显的过渡（行高亮动画/当前 chip 平滑移动/顶部 toast 样式），参照 cc-switch
  桌面版观感。
- **归属**：与 Provider 管理相关的独立小迭代，可与 IDEA-2/3 同轮规划。

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

### IDEA-3 顶栏设置按钮去留 + 工作区级 tab（2026-08-17 用户提出；**2026-08-18 实现并手测 PASS**）

- **已实现**（分支 `idea-3-workspace-tabs`，3a..3f 六子阶段）：门面抽取
  （WorkspaceRuntime 工厂 + runtime store 可写 computed 逐键转发）→ Rust
  取消 token 键化 → workspaces 中枢（launcher 物化/上限 3/关闭即时摘
  chip+后台静默收尾/合并历史保存/退出聚合）+ 双层条（真并行，活跃 5s/
  后台 25s 轮询）→ 设置升工作区层（对话框退役、Ctrl+,、+ ▾ 入口、
  `ui.default_new_page`）→ 快捷键（Ctrl+PgUp/PgDn、Ctrl+Alt+数字，WebView2
  实测可用）+ watcher 事件带路径 + explorer per-path 缓存。条模型（用户
  三轮手测定稿）：**只显示真实打开的页**（启动器 chip 仅聚焦时显示），
  chip 显示文件夹名、同名冲突才显全路径。用户四轮手测确认收束。
- **对已批方案的一处偏离**：工作区容器用 `:key` 重挂载而非全挂 v-show
  （组件全绑门面，v-show 多实例全渲活跃区；Terminal 重挂重放缓冲是既有
  安全设计，还改善内存上界）。

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
      `container/lib/deepseek-official-facts.json`；详见
      `stage-8-cc-switch-provider-ui/8a-discovery-report.md` + D8-08..D8-12）；
- [x] 实现 stable latest resolver、资产架构校验、SHA-256 和 image labels（8b：domain 选择+application resolver（分页/限流/TTL cache/manifest 离线）+6 build-arg+OCI labels+21 测试；真机 dry-run 验证 latest→v5.10.1/digest 一致）；
- [x] 从官方 DeepSeek 文档生成 fixture，确认字段、模型 ID、endpoint 和 `[1m]`（8a 四页取证 + 8c fixture 驱动 preset + ownership 刷新 +13 测试；A-CS03/04 自动化绿）；
- [x] 冻结 Provider UI protocol，完成 list/add/edit/delete 和 secrets redaction（8d 容器 adapter + 宿主 CLI 23 测试；8e Workbench 虚拟 tab + Rust stdin 通道 + store 分层）；
- [x] 验证 UI/CLI 同库、并发写、preset refresh 用户覆盖和升级迁移（8f 真机 + 自动化：A-CS01..07 全 PASS，用户手测 PASS 2026-08-17；切换激活记 IDEA-4）。

## Stage 9

- [ ] 创建 `experiment/workbench-winui3`；
- [ ] 搭建 WinUI shell、native terminal control、session/tab 和 CLI bridge；
- [ ] 用同一 contract fixture 实现 Provider tab；
- [ ] 完成等价验收、性能/崩溃/高输出报告和替代决策建议。
