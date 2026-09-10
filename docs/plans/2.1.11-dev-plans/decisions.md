# 2.1.11 决策记录

## D-1 · P1 范围与形态（2026-09-10 审问裁决）

- **provider key 显隐**：现状 `ProviderEditPage` 的 key 字段
  `type="password"` 但编辑不回填（空框分不清「已配置」还是「未填」）。
  目标：已配置 provider 编辑时显示「已配置」占位态 + 眼睛按钮按需取回
  明文（默认隐藏）；取回走新 IPC（后端存储本为明文，缺的是显式取回
  通道——接口名与脱敏边界实施时定，列表快照保持 secret-free 不变）。
- **历史恢复顶部空白**：终端磁盘 spool 按需回放（O1）加载更早输出后
  顶部出现大片空白——先复现定位（xterm 回放后 buffer 高度/scrollTo
  行为），修法跟因走。
- **忘记工作区清理与导出**：forgetPreview 弹窗加勾选「同时清理生命
  周期文件」（数据根 `workspaces/<hash>/` 下 agent 记忆/配置/状态；
  默认勾选；**绝不触碰工作区目录内用户文件**）+「先导出 zip」按钮
  （内容=生命周期文件快照；导出位置用户选，走 Tauri save dialog）。

## D-2 · topbar 整行砍除（用户裁决 A）

静态品牌字样信息量为零且与 WorkspaceBar 内容重叠（VS Code 哲学：最
显眼位置放动态上下文）。实施：删 topbar 行；status 图标右移
WorkspaceBar；Tauri 窗口标题动态设为当前工作区名（picker/无工作区态
兜底文案）。注意 compact 档现依赖 `.topbar` 规则（App.vue 死规则清理
时保留的两条活规则）需随之迁移。

## D-3 · Slurm/PBS 与热切换 = 先调研

Slurm/PBS：等用户提供实际工作流（提交节点形态/认证/常用作业操作），
产方案文档后下轮实施。热切换：调研「不停当前会话」技术可行性（预期
不可行：进程启动读 env）与「新会话即时生效」现状差距，出结论文档。

## D-4 · UI 批实施顺序

反馈语法（toast+空态 CTA，最低成本最高可见）→ topbar 砍除 → rail
图标化（FIX-3 窄条升级 activity bar + Ctrl+B）→ 命令面板（菜单项为
数据源 + aria-keyshortcuts）→ 设置页搜索。每项独立分支独立手测；
底部状态栏/tab 活动指示/面板最大化视余力（P2 后评估）。
