# F1/F2 手测期现场修复回溯归档（2.1.9 周期）

> 补记规约（用户 2026-09-05 裁决）：**所有突发加入的计划必须落地到本版本
> plans 目录**。本文件回溯归档 F1/F2 手测期间「直接执行、未先行立档」的
> 现场修复——每项按 问题描述 → 根因 → 方案 → 验证 → 提交 补齐设计记录；
> 实施细节以 devlog 对应条目为准（本档 = 设计视图，devlog = 流程视图）。

## FF-1 取消同步（用户：本地放不下这么多东西）— `abadce9`

- **问题**：几百 GB 远端目录全量涌入本地，无中止手段。
- **方案**：`sync_session_cancel`——terminate（容忍 scanning 态阻塞，10s
  预算）+ **删除已同步内容**（保元数据）+ 元数据标记 `sync_disabled`（launch
  永不自动重连）；`sync_session_enable` 显式恢复；terminate 失败的根除路径
  = 杀 daemon + grep 删本工作区持久化定义（其它会话定义存活，daemon 惰性
  重启重挂）。后续即时化：先标 disabled+清内容（UI 即时翻转）→ 后台线程
  清扫。
- **验证**：cargo 单测 + 真机（磁盘实测仅 6KB 无伤）。

## FF-2 传输 2x：退役 ssh.cmd wrapper — `f647147`

- **问题**：1GiB 内网传输 3m40s。
- **根因**：基准实测——裸 ssh 管道 8.4MB/s，经 cmd batch 转发 wrapper
  4.3MB/s（**吞吐砍半**）。
- **方案**：受管 `~/.ssh/config` 标记块（`# BEGIN/END AISC SYNC`）内别名
  `aisc-sync-<fnv(host|port|user)>` 承载连接参数 + `MUTAGEN_SSH_PATH` 直指
  真 ssh。实测 1GiB = 2m09s ≈ 裸管道（后续复测 123s）。
- **验证**：基准对比 + cargo（别名稳定且 profile 作用域）。

## FF-3 超大内容三层策略 — `8b602dd` + `4239636` + `a69eaa8` 部分

- **问题**：几百 GB 远端打开即全量涌入（树全空 + 磁盘炸）。
- **方案分层**：①排除规则 `ignore_patterns`（元数据 SSOT，create 与自愈
  重建都从 meta 取，picker 表单录入）②超量警示（远端总量 >10GB 侧栏建议）
  ③按需拉取 `ssh_pull_file`（`ssh cat` 二进制安全流式落盘影子目录根，落在
  排除范围外 = agent 立即可用且永不被同步删除）。
- **验证**：cargo + 手测（排除生效/拉取可用/不被删）。

## FF-4 磁盘防护三层 — `aa06bf5`

- **问题**（用户）：小文件总量把本地磁盘爆掉怎么办？——此前只有静态
  >10GB 警示与事后手动取消，无真实容量防护。
- **方案**：①SyncStatus 新 `freeBytes`（fs4 free_space 探数据根卷，零新
  依赖），侧栏在远端总量 > 本地可用时红字预警 ②`LOW_DISK_FLOOR_BYTES`
  =2GiB，once-per-process 守护线程每 30s 探一次，跌破对所有 live 会话
  自动 pause + 元数据盖 `low_disk_paused`（防打满系统盘；与用户显式恢复
  不打架）③恢复/新建门槛（free<floor 拒绝；launch 带标记保持 parked；
  空间回升自动清标记重连）。
- **已知边界（接受）**：守护随 Workbench 进程存亡；真实触发场景未强测
  （需 C 盘 <2GB 环境）。
- **验证**：cargo 决策矩阵 + meta roundtrip；CI 全绿。

## FF-5 mutagen agent 包共位根治 — `a69eaa8`

- **问题**：手测三反馈同源——本地 1GiB 推不上去 / 取消→恢复长异常 /
  排除工作区启动长异常。取证：四会话永久 `connecting-beta`。
- **根因**：mutagen 每次 beta 拨号要从二进制旁的 `mutagen-agents.tar.gz`
  （78MB）流式安装远端 agent——**vendor 链只搬裸 exe 把它丢了**；昨天能跑
  纯属 dev shell 残留 `AISC_MUTAGEN_PATH` 指向完整解包目录的侥幸。隔离
  实验实锤 `unable to locate agent bundle`。
- **方案**：`ensure_mutagen_ready()`——每次调用实际运行 `<数据根>/mutagen/bin/`
  托管副本（二进制+agent 包共位幂等安装）。**连带根治两潜在 bug**：Windows
  锁运行镜像（daemon 跑 target/debug 时任何 cargo build 必炸 tauri-build
  remove_file）；/usr/bin 只读安装位。agent 包发现链：二进制旁 → exe 目录
  → bundle resources（setup OnceLock 注入 resource_dir）→ 仓库 binaries/。
  分发链补齐：tauri.conf resources + NSIS/bundle workflow staging + CI 占位。
  顺带清扫退役 wrapper 残留（bin/ssh.cmd 地雷）+ `connecting-beta` 状态补
  「重连中」映射。
- **验证**：agent 包落位 10s 内四会话全 watching；用户 1GiB 确认推抵远端；
  cargo/vitest + 四 lane CI。

## FF-6 单测污染真实 ~/.ssh/config 根治 — `9b85ed0`

- **问题**：取证中发现 config 管理块被写成测试 profile（127.0.0.1:1/deploy）。
- **根因**：wrapper 隔离测试用 USERPROFILE/HOME 环境变量隔离 home，但
  Windows 上 `dirs::home_dir()` 走 SHGetKnownFolderPath **不认环境变量**
  ——每次 cargo test 都改写真实配置（历史「隔离」是无效的）。
- **方案**：`ensure_managed_ssh_config_at(path, profile)` 路径注入式拆分
  （生产读真实 home，测试传 tempdir config；测试绕开 ensure_transport——
  真实污染调用方）。
- **验证**：md5 前后比对 config 零触碰；cargo 290×3 连绿。

## FF-7 拉取浏览钉根 + 服务端 containment — `7a08efe`（含 `a69eaa8` 初版浏览）

- **问题**（用户）：拉取文件应与选工作区一样可浏览；且应直接定位工作区
  对应文件夹、拒绝访问其它路径。
- **方案**：侧栏拉取行「…」→ 远端浏览弹层（面包屑/上级/目录进入/文件
  点选回填）；`ssh_browse_workspace`（profile 取自元数据）+ 服务端
  containment——`resolve_workspace_browse_path` 纯函数（空/"/" 归一到
  工作区远端根；**段归一化防 `..` 穿越**——纯前缀挡不住
  `/root/../escape`；根外一律拒）；SyncStatus 新 `remotePath`；面包屑
  {label,path} 对且首屑=工作区文件夹名、↑ 在根处禁用。
- **分层裁决**：手输路径不限制（浏览引导、输入兜底）。
- **验证**：containment 矩阵测试（穿越/兄弟/父目录拒绝）。

## FF-8 多 profile ssh 受管块并存 — `51976f4`

- **问题**（收口后用户点名即修）：受管块「单 profile 整块重写」对多
  profile 用户是静默炸弹——打开第二个 profile 的工作区瞬间抹掉第一个的
  别名 → 其别名端点会话全部悬空（自愈只比对 beta 路径，看不见端点形态）。
  当前单 profile 场景被掩盖。
- **方案**：管理块按别名分节——`parse_block_sections`（Host 分节解析 +
  同别名去重折叠）+ ensure 重构（提取块→upsert 本 profile 节→重建；块外
  用户内容不动）。别名含 port——profile 改端口产生新别名旧节残留（无害：
  meta 快照语义下各工作区永远只确保自己创建时的别名）。
- **验证**：多 profile 测试（共存/只更新己节/重复节折叠/块外内容保全）。

## PP r8（附）：裸 Ctrl+C/V 接管 + 全局右键禁用（2026-09-03 晚）

用户两项临时指令（非 provider-parity-design 范围）：Ctrl+C 有选中→复制/
无选中→SIGINT、Ctrl+V 恒粘贴（Windows Terminal 语义）；document 级
contextmenu preventDefault。详见 devlog PP 节。
