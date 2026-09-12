# Shell 重设计拆解——浮窗化 · 菜单栏 · 一窗一工作区（2026-09-11 用户裁决）

> **状态（2026-09-12）：W1-W3 全部交付，手测 PASS（W3 r1-r11 十一轮），
> 已并 develop。W4（收尾清扫：i18n 对账/多实例死代码/跨窗快捷键残留
> 键清理）并入 P2 收口批执行。

> 输入：P2-4 手测 r2 六条反馈中的 5/6 两项。裁决已定，实施分阶段、
> 每阶段独立分支独立手测（D-4 惯例）。

## 用户裁决原文（a/b/c）

- **a**：菜单栏跟 VS Code 默认一样**窗口内嵌条**；同时**当前最顶部的、
  随内容改名的条（工作区条）直接去掉**。
- **b**：第一个菜单**不叫「文件」**，叫「操作」或更直观的名字。条目：
  **新建窗口、从文件夹打开工作区、打开最近的工作区、从远程机器打开
  工作区**。「编辑」暂按拟制（设置、命令面板）；「帮助」暂按拟制
  （关于、文档）。
- **c**：工作区拆成独立窗口后，**窗口间切换交给操作系统任务栏**，
  应用不再管多工作区切换（Ctrl+PgDn / Alt+1..9 等跨工作区快捷键随之
  退役）。

## 阶段拆解（建议顺序）

### W1 · rail 底部图标 + 设置/数据看板浮窗化（原反馈 5，独立可先行）

现设置/网络用量是工作区条的**哨兵 tab**（SettingsTab/NetworkUsageTab
占据内容区、chips 里带 ×）。改：

- WorkspaceBar chips 拆除 settings/networkUsage 哨兵（含 × 关闭逻辑、
  cycle 跳过、▾ 菜单两入口删除）
- rail（activity bar）**最下方**两图标：⚙ 设置、📊 数据看板（VS Code
  activity bar 底部账号/齿轮位）
- 点击 → **浮窗**（scrim + 居中面板 + Esc/点背板关闭，DoctorDialog 形
  态复用）；SettingsTab/NetworkUsageTab 内容组件不变，宿主从 strip
  tab 换 overlay
- Ctrl+,、palette 条目、picker 内嵌按钮全部指向浮窗
- 工作区条本轮暂存（W2 才删），只去哨兵

风险：workspaces store 的 settingsTabOpen/networkUsageTabOpen 语义反转
为 overlay 开关；runtimeFacade 相关测试锚点同步。

### W2 · 菜单栏（操作/编辑/帮助）+ 工作区条退役（裁决 a/b）

- 窗口顶**内嵌菜单条**：`操作 | 编辑 | 帮助`（下拉菜单，键盘可达）
  - 操作：新建窗口 / 从文件夹打开工作区 / 打开最近的工作区 / 从远程
    机器打开工作区（最近列表与远程机器列表数据源 = 现有 history 与
    remote_machines 设置）
  - 编辑：设置 / 命令面板（Ctrl+Shift+P）
  - 帮助：关于（版本四件套）/ 文档（README 链接）
- **工作区条整行删除**（此时一窗仍可能多工作区 tab——见 W3 顺序权衡：
  若 W3 先行则 W2 的条删除并入 W3。**建议 W2/W3 合并实施**，避免出现
  「无菜单栏且无工作区条」的中间态断档）
- TabBar（会话标签行）保留不动

### W3 · 一窗一工作区（Tauri 多窗口，裁决 c）

- 「新建窗口 / 打开工作区」→ 新 `WebviewWindow`（每窗独立 SPA 实例、
  独立 pinia，天然一窗一工作区；launcher/picker 为窗口初始页）
- 主窗口角色：无工作区时即 launcher 窗；关最后一个工作区 = 回
  launcher，关 launcher 窗 = 退出（托盘在则驻留，G-16 现状）
- 跨工作区设施退役：workspaces store 多实例模型、Ctrl+PgDn、Alt+1..9、
  strip chips/facade 多实例路由（`fwdFn("...")` 的 ACTIVE 查找简化为
  单实例直呼）
- 窗口标题/托盘/关闭确认按窗自治；IPC 侧无改动（命令本就无窗口维度）
- 风险：窗口激增下的 Docker 资源（每窗一个 runtime 照旧，用户自管）；
  全局快捷键（Ctrl+, 等）注册在聚焦窗即可

### W4 · 收尾

- i18n 双语对账、死代码清扫（workspaces 多实例、chips 测试）、
  devlog/阶段表、todo 划项

## 顺序裁决建议

W1 独立先做（当下就有价值且在 W3 后仍成立）→ W2+W3 **合并为一个分支**
（避免中间态断档）→ W4。
