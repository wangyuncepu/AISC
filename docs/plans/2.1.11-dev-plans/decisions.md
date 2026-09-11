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

## D-5 · 本地/远程 CLI 传输统一——两步走（2026-09-11 P1 手测 r7 裁决）

用户实测远程 provider 比本地快且全生效，根因：远程走驻留 serve
（D-10 池化），本地逐次 spawn aisc.exe 交 ~0.5-1s 启动税
（PyInstaller 解压+解释器+Defender）。裁决分两步，各自独立分支独立手测：

- **step 1（已交付，P1 内 `e1c9df5`）**：仅 provider 操作切池化
  serve。ServePool 扩 `local:<path>` 键、`cli_op_target` 双侧统一分发、
  drain_pool 挂 RunEvent::Exit。实测冷 534ms / 热 10ms。
- **step 2（已交付，2026-09-11，分支 unify-serve-step2，手测 PASS 已并 develop）**：
  1. 全部本地命令迁移（runtime preflight/start/stop/list、doctor、ps、
     usage、logs、config、conversation、artifact…）；
  2. **版本配对驱逐**——驻留 serve 把旧代码用到驱逐为止，banner
     `cli_version` 对比 pin 版本/mtime 不一致即驱逐重建（r8「旧闸门
     新路由」事故的根治）；
  3. `run_control_inner` 逐次 spawn 路径删除（serve bootstrap 自身保留）；
  4. **例外逐个裁决**：`--events` 流式命令（build/启动进度）serve 闸门
     拒收——继续专用通道或借 serve 事件流，设计时定；PTY 本地 pipe
     模式不动；
  5. dev 模式 CLI 频繁重建的陈旧性（版本配对驱逐应顺带覆盖）。

已知代价（用户已知悉）：串行 op 循环（fetch-models ~12s 网络期间其它
op 排队——远程现状已如此）；共享进程故障域（传输级失败已有驱逐重试）。
