# 2.1.10-dev 裁决记录

格式沿 2.1.9 惯例：每条含日期、背景、裁决、影响面。

## D-1 池范围：散落挂账暂缓（2026-09-07）

todo.md 各节散落项（Pi/opencode agent、长对话恢复 bug、docker 缓存自动清理、
codesome 适配、provider 编辑拆分、agent 对话框补全、P6b、P10、冲突投影、
DEVELOP_WIKI 重写等）本周期**暂不处理**，不在 2.1.10 阶段表内。

用户原话：「散落项暂时都先不管，R0 调研先行」。

## D-2 Slurm/PBS：调研并入 R0，实施划出（2026-09-07）

todo.md「调研」节的远程调用场景（Slurm/PBS）并入 R0 调研范围（与 VS Code
远程调研同批产出）；**实施明确不属于 2.1.10**。理由与边界见
r0-vscode-remote-and-hpc.md §6：集群计算节点无 Docker，agent 上集群需要
runtime 抽象超越 Docker，是独立架构演进。

## D-3 R0 先行（2026-09-07）

远程特性按「调研 → 拍板 → 实施」推进，R0 产出可行性结论与 R1-R4 阶段
建议，经用户验收后才进入 R1。沿 gui-fine-tune-workflow「先报后做」。

## D-4 全特性在 2.1.10 内交付（2026-09-07，用户否决 MVP 切法）

用户裁决：远程 CLI 特性（R1-R4 全部，含文件面与机器管理）必须在本周期
内完成，不接受「R3/R4 推 2.1.11」的收窄。R0 文档 §4 的 MVP 边界建议作废。

## D-5 G3 文件面 = 远端 FS API（VS Code 权威远端模型）（2026-09-07）

用户确认理想模型与 VS Code Remote-SSH 一致：**远端权威，本地仅显示，不落
第二份**——工作区只能选 CLI 所在机器的路径；资源管理器显示远端文件；终端/
agent/改动全部发生在远端；「用本地软件打开」= 显式下载副本；大文件复制
需下载。不采用 mutagen 同步——**该语义随 D-6 一并剥离封存**，远程化成为
唯一的 SSH 故事。

## D-6 F1 SSH 工作区剥离并封存（2026-09-07）

用户裁决：之前实现的 F1（mutagen SSH 工作区）是**错误尝试**，2.1.10 首个
任务即剥离该功能并暂时封存。剥离计划见 f1-strip-plan.md（S0 阶段）。
远程化（R1-R4）成为唯一的 SSH 故事；R0 文档 §5 的「F1 互补并存」补记作废。
封存载体 = git 历史 + tag `v2.1.9-dev` + 归档设计文档；用户数据处置逐项
经用户确认，代码剥离不触碰任何用户数据。

## D-7 serve stdio 模式无 token，SSH 即认证（2026-09-07）

`aisc serve --stdio` 只与 ssh 会话的 stdin/stdout 通话、无监听面——SSH
认证即传输认证（VS Code Remote-SSH 同款），R1 不引入 token。**若日后加
TCP 直连模式**（局域网无 SSH 场景，调研节「局域网通信」相关）必须重新
裁决并引入 F2 式 per-process token + 回环绑定，不得复用 stdio 语义。
附带确立**双通道模型**：低频控制面走 per-op ssh、流式/高频面（R2 PTY、
R3 FS/事件）走 serve 长驻（见 r1-serve-transport.md §1）。

## D-8 终端面双路径（2026-09-07，R2）

本地保持 `spawn_pipe_session` 直连不动（B-05 十三轮手测打磨的稳定面 +
P2/P3 性能载体）；远程走 serve PTY 流帧。双路径在 Rust 侧汇合于
PtyEvent 通道抽象，`session.rs` 按 ActiveTarget 分流；resize 在 serve
路径天然带内（G1 根治，本地 resize 文件机制保持不变）。代价声明：serve
路径字节流经 JSON 帧（base64 ~33% 膨胀），局域网可接受（VS Code 同款
取舍）。详见 r2-remote-sessions.md §1。


## D-9 FS 面走 serve 长驻 + watchdog 引入 + 远端权威语义（2026-09-07）

R3 落地 D-5 模型的三条执行裁决：①fs.* op 复用 ServeSession 多路复用、
watch 事件用预留 event 帧（D-8 双通道归位）；②Python 侧引入 `watchdog`
依赖做远端 watcher（无 watchdog 环境优雅降级 unsupported，Explorer 回退
list 轮询）；③所有 fs path 以远端为根、服务端 containment 拒绝越界
（防穿越沿 F1 browse 钉根教训），本地软件打开=显式下载副本、拖入=上传，
本地永无工作区副本。详见 r3-remote-fs.md。

## D-10 控制面迁 serve 长驻（2026-09-09，修订 D-7）

D-7 的「低频控制面走 per-op ssh」在真实远程使用中代价过高：每 op 一次
全新 ssh 握手 ≈ 220ms（LAN 实测，公网按 RTT 放大），且 Windows OpenSSH
不支持 ControlMaster（实测 `getsockname failed`），连接复用无解。
修订：控制面 op 优先走 serve 长驻连接（ServePool 复用，通用 `cli` op
进程内复用命令分派）；per-op ssh 降级为 serve 不可用时的回退通道。
协议 v1.2 → v1.3（`cli` op + ready 帧 `home` 字段）；老远端机经
unknown-op 回退天然兼容。PTY/build 流维持既有通道。详见
fix2-design.md F2-A。

## D-11 CLI 更新方案封存（2026-09-09）

`aisc update`（CLI 自更新）本批不做——更新需要整体设计（CLI + Workbench
+ 侧车同步 + 发布通道），转下周期「更新方案」专题与用户专题讨论。
