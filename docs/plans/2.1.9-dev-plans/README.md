# 2.1.9 开发周期

首批：四条挂账统一清偿（完整设计见本目录 decisions.md 与会话计划存档）。

| 阶段 | 内容 | 状态 |
|---|---|---|
| T1 | #53 隔离测试修复（AISC_DATA_ROOT 钉第二 tempdir） | ✅ |
| T2 | #50 ble.sh 移除（vendor + 门控 + D-1 修订） | ✅ |
| T3 | #3 归因全量修复：a=R2 env 兜底 / b=R1 容器登记桥 / c=R3 推断归因（R3 呈现层后按 D-6 降级） | ✅ |
| T4 | #28 VM 闪烁主攻（三轮收敛 + fit 遥测/自诊断浮层保留） | ✅ |
| T5 | 收尾：全矩阵回归 + 手测 + 挂账关闭 | ✅ |
| T6 | 变更页朴素化（归因呈现降级，D-6） | ✅ |
| T7 | zsh 下 help 教学引导补齐（D-8） | ✅ |
| T8 | 构建网络韧性硬化：预拉镜像链/pip/npm/apt/yazi 兜底 + 离线逃生（D-9） | ✅ |

## 优化批次（opt-batch，规格 → [opt-batch-spec.md](opt-batch-spec.md)，D-11）——✅ 全部完成

| 阶段 | 内容 | 状态 |
|---|---|---|
| O1 | 分屏 × 被滚动条挡住（z 序修复） | ✅ |
| O3 | 渲染路径遥测（WebGL 激活状态打点） | ✅ |
| O9 | 取消懒布局 → r2 裁决升级为不恢复布局（恒全新默认单 bash tab） | ✅ |
| O2 | 输出截断 → 磁盘 spool + 按需回放 | ✅ |
| O5 | cc-switch daemon 定时巡检自愈 + reconcile 判定容错 | ✅ |
| O4 | provider 切换链重构（r2 舞步重排根治 8-9s；r6 codex catalog 接管；r7 codex 拉取） | ✅ |
| O6 | 轮询自适应退避 + WSL 内存引导 | ✅（O6b lease 直写归 PERF P5） |
| O7 | build cache 清理产品化 | ✅ |
| O8 | 冷启动提速（出厂增量复制 + 等待收紧） | ✅ |

外部证据待收集：8G 笔记本 doctor 导出（O5 复验）；长对话恢复复现样本（独立 bug）。

## 特性批次——✅ 全部交付（手测基本 PASS 2026-09-05）

| # | 特性 | 状态 |
|---|---|---|
| F2 | **容器内 Agent 调用宿主工具**（宿主 MCP：token 鉴权+白名单+只读筛；注入链 + mihomo TUN 对策）。[f1-f2-design.md](f1-f2-design.md)（D-10） | ✅ 三轮手测闭环 |
| F1 | **远程 SSH 工作区**（mutagen 双向同步，影子目录=真工作区；传输 2x/超大内容策略/取消同步/磁盘防护/按需拉取+浏览钉根/多 profile）。[f1-f2-design.md](f1-f2-design.md)（D-10） | ✅ 手测矩阵收口 |
| PP | **Provider 页对标 cc-switch 桌面端**（r1-r8 八轮手测收敛）。[provider-parity-design.md](provider-parity-design.md)（D-12） | ✅ r8 后封存深化 |
| FF | **手测期现场修复回溯归档**（8 项直接执行的设计记录补档，含 agent 包根治/测试污染/多 profile 等） | ✅ [f1-f2-field-fixes.md](f1-f2-field-fixes.md) |

## 性能批次（PERF，规格 → [perf-batch-spec.md](perf-batch-spec.md)，D-13）——✅ P1-P9 全部收官（2026-09-06）

| 阶段 | 内容 | 状态 |
|---|---|---|
| P1 | tick 合并：`runtime status` 单命令（spawn -50%/tick） | ✅ `ffc6564`+`9e698a5` |
| P2 | 会话税：EOF 驱动退出 + resize 降频（API 5/s→~0） | ✅ `841f207` |
| P3 | 容器内 spawn 削减三件套（历史批量写/env-inject 缓存/巡检 kill-0） | ✅ `2b1af85`（容器内实证） |
| P5 | lease 心跳 Rust 直写（O6b 清偿，-240 spawn/h/workspace；锁互操作实验先行） | ✅ `9d7fecf`（P5a 双向互斥成立）+`05f86b8`（P5b 直写） |
| P4 | SDK 执行器进命令层（docker.exe 子进程链归零） | ✅ `3058e1a`（真机冒烟） |
| P7 | 退避覆盖扩展 + 背景降级（后台 60s/失焦 30s/provider 挂梯子） | ✅ `1a1926d` |
| P6a | 热轮询 Rust 直连 named pipe（稳态 tick 0 spawn，空闲卡根治） | ✅ `ba4263d`（原始端点实证） |
| P8 | 低配模式（自动应用+弹窗告知；容器限额 + .wslconfig 保键合并） | ✅ `506eb43`（限额基础）+`cce3351`（自动探测/wslconfig/UI） |
| P9 | 冷启动残余（daemon 就绪等待去 spawn 化 + entrypoint 脚本合并） | ✅ `9e795e3`（容器实测 1775ms；PERF 收官） |

## 遗留 backlog（本周期明牌，未排期）

冲突双副本列表投影（等真实样本）· F2 host_exec 远端执行版 · F2 参数模板收紧 ·
远端 rsync 缺失引导实测 · F1 排除规则后改入口 · SSH 密码认证 · 长对话恢复
（独立 bug）· 分屏键盘导航（WebView2 限制封存）· 安装包实机冒烟（F1 全程
dev 模式）· 磁盘防护真实触发强测 · F2 codex 注入/git-ro 实机 · sidecar
onedir 评估（P10）· /events 流式订阅（P6b）。

规约：VERSION 冻结前保持 2.1.8.dev0；container/ 改动后必跑 vendor-refresh；
每 T 项独立提交 + 四条 CI 全绿进下一项；周期全部完成后 plans 归档；
**突发加入的计划必须落地到本目录**（2026-09-05 用户裁决）。
