# 优化批次合并规格（opt-batch，2.1.9 周期）

> 规约产物（vibe Focused 路径）：本文 = PRD 内容 + 实施计划 + 约束清单合一。
> 事实基础：2026-09-01 三路只读探针（前端流/渲染/分屏 · provider 链/daemon ·
> 性能旋钮/缓存/冷启动），全部结论有 文件:行号 证据，见附录引注。
> 状态：**规格冻结待实施**；实施遵守全局约束（§G）。

## 背景与范围

用户报障五条（todo.md #用户体验）+ 探针衍生的补充项。**In**：O1-O9（下）。
**Out**（明确不做）：终端技术栈更换（xterm.js@6+WebGL 已是最优解，保留）；
宿主内存图表类观测面板；F1/F2 新特性（等本批次收口）。

## 用户裁决记录（2026-09-01）

| 决策点 | 裁决 |
|---|---|
| O2 截断终局 | **磁盘 spool**（全量落盘 + 按需回放，活标签永不弹常驻角标） |
| O4 provider 手术面 | **含舞步重构**（并行化 + 超时对齐 + 抓取移出主路径 + UI 进度） |
| O6 定性修正 | 用户裁定：UI 渲染非负载大头，**主要是 docker 负载** → O6 重新定义为轮询/容器侧治理，不做动画微调打包 |
| 批次增补 | 纳入 O7 缓存清理、O8 冷启动、O3 渲染遥测；**新增 O9 取消懒布局**（重新打开工作区不走懒恢复） |

## O1 · 分屏关闭按钮被滚动条挡住（S，直接修）

**根因（探针实证）**：`.pane-close` z-index 2（PaneTree.vue:217-224）与 xterm
滚动条 `.visible` z-index 11（xterm.css:245）同 stacking context 直接比较；
滚动条列（右 0-10px）与 ×（右 4-24px）有 6px 重叠带；截断角标 z 20 也在同角。
**修法**：× 让出滚动条带（right: 4px→14px+）或提 × 的 z 到 --z-overlay 之上并
给独立 stacking context；banner 与 × 错位。**约束**：全局样式不得触达 xterm
DOM（styles.css:216-221 层契约），改动只在 PaneTree/Terminal scoped 层。
**验证**：vitest 组件测试（点击命中区域）+ 手测（滚动条悬停淡入时点 ×）。

## O2 · 输出截断 → 磁盘 spool（M-L）

**现状**：每 pane 4MiB(base64)/4096 chunk 内存窗口（streamBuffer.ts:16-17），
溢出丢头 + 常驻角标（Terminal.vue:1049-1051）；活标签 xterm 内容不丢（无
clear 调用），丢的只是重挂载回放历史；服务端阻塞背压不丢字节。
**方案**：Rust 侧（或 store 侧）把 Output 流全量 spool 到
`<数据根>/sessions/<session-id>.spool`（追加写，会话结束保留至清理策略）；
内存窗口保留（护栏不变）；常驻角标删除；回放超窗时提供"加载更早输出"
（从 spool 读前段，分块 writeChunks）；重挂载默认仍只回放窗口。
**触点**：pty.rs Output 读泵/pty.rs stderr 泵 → 新 spool writer（背压语义：
磁盘写失败降级为现行内存-only 行为 + 事件日志）；streamBuffer.ts 预算不动；
Terminal.vue banner（:1049-1051,:1212-1225）改"加载更早"按钮 + i18n 双语；
新 ipc 命令 `session_read_spool(session_id, offset, limit)`。
**约束**：`streamCursor` 单调性不可破坏（Terminal.vue:924-930 注释）；flush
每帧单响应式替换路径不动（workspaceRuntime.ts:224-229）；spool 文件
secret-free 纪律豁免说明（终端流可能含用户键入的敏感内容 → 文件 0600 +
不进任何导出/诊断默认集）+ 清理（会话 ack 后删或 LRU 上限）。
**验证**：streamBuffer 单测扩展；>4MB 输出实测：角标消失、"加载更早"
回放出完整历史；断电/杀进程后 spool 完整性；Rust 单测（spool 写读回环）。

## O3 · 渲染路径遥测（S，纯观测）

**现状**：renderer "auto" 恒试 WebGL（webglAvailable 硬编码 true，
Terminal.vue:170），构造失败静默回退 DOM；零遥测。
**方案**：mountWebgl 成功/失败/context-loss 三态打点（经 store 层
logUiEvent——组件不得直接 import，workspaceRuntime.ts:1735-1740 层约定），
事件含 renderer 实际值 + 是否软渲染（WEBGL_debug_renderer_info 摘要）；
fit 遥测行加 renderer 字段。**验证**：app 日志出现 renderer 事件；低配设备
收集一轮数据供后续决策。

## O4 · provider 切换链重构（L，含舞步）

**实证**（全设备卡顿根因）：外层 Rust 30s < 内层可超 30s 的全串行舞步
（disable→switch→enable→show→TCP 探测×4→codex 在线模型抓取 6s×N→快照
回读）；每次操作 3 层进程冷启动；UI 仅按钮禁用无进度。
**方案**（三层）：
1. **主路径瘦身（container/aisc-cc-provider）**：codex 在线模型抓取
   （_live_fetch_catalog_ids，:1257）移出切换主路径（后台刷新，切换用
   缓存/无 catalog 快速路径）；幂等快路径跳过 TCP 探测环（已是 current
   时只查 show）；固定 sleep 缩短（1.5s 舞步内 sleep 依实测收紧）；
   op_list 快照回读并行于路由守卫
2. **超时层级对齐**：外层 PROVIDER_TIMEOUT 30s（runtime.rs:35）提到 ≥
   内层最坏和（或内层收严），避免"外层杀中层、容器内半途而废"的
   不一致态；逐跳超时进 trace（容器内 per-CLI 计时埋点，
   aisc-cc-provider run_cli 包一层 duration 日志）
3. **UI 进度反馈**：CcSwitchUiTab 切换中状态从"全局禁用"改步骤指示
   （切换中→路由自检→完成），busy 语义细化（ccSwitchUi.ts:18 单字符串
   → per-op）；超时错误指引重试按钮已有，保留
**约束**：上游行为不可改只能绕（claude switch 整文件替换 settings.json、
delete 需 TTY、re-add 重置 meta.apiFormat 需 merge 补写、enable 可静默
no-op——均见探针 B 节注释引注）；舞步重构不得引入新的中间不一致态
（每步失败恢复路径保持）。
**验证**：op_traces 分步耗时可见；本机切换 p50/p95 实测对比（改前基线
先采集！）；手测：切换→立即开 claude 会话可用；幂等切换（同 provider
再点）秒回。

## O5 · cc-switch daemon 自愈（M）

**实证**（8G 笔记本 proxy 全 off 根因链）：daemon 无 watchdog、容器无
restart、PID1=sleep infinity → daemon 被 OOM 杀后路由静默躺平；启动
reconcile 的 not-real 判定依赖 base_url 可解析，解析失败即每轮启动
disable。
**方案**：entrypoint 加周期健康巡检（后台循环：daemon status + 路由监听
探测，间隔 60s；异常 → daemon 重启 + 对受影响 agent 重新 enable + 事件
日志），复用 _recover_route 语义但定时化；reconcile 的 real 判定容错
（base_url 解析失败 ≠ 主动 disable，改为告警 + 保守不动）。**可选加固**
（低配机器）：docker create 加 `--memory` 上限的设置项（默认关闭，低配
档位开启时建议值）——防止单容器吃穿 WSL VM。
**验证**：容器内手动 kill cc-switch daemon → 60s 内自动恢复路由；
reconcile 单测（base_url 畸形输入不再 disable）；8G 笔记本实机复验。
**外部证据依赖**：需那台笔记本跑一次 doctor 导出 + 容器日志（确认 OOM
与 reconcile 路径归属）。

## O6 · 轮询/容器负载治理（M，重定义后）

**定性修正（用户裁定 + 探针证实）**：负载大头在 docker 侧——每 5s 的
runtime inspect 每次拉起完整 aisc.exe + docker info + ps + inspect + 网关
探测链（nairong 单次 1.5-2.8s，占空比 40-60%），叠加 lease 15s 心跳与
provider 15s 轮询。
**方案**：**自适应退避**——按最近 runtime op 实测耗时动态调整轮询间隔
（快机 5s 不变；慢机自动退到 10s/20s，恢复后回落；复用 useRuntimePolling
现有三档结构 + 新增自适应层）；同 tick 的 inspect+webServices 双链合并
评估；lease 心跳对齐轮询档。**WSL 内存引导**：doctor 新增检查项——
检测 WSL2 配置与物理内存（新探测，现状零基础），8G 及以下且未配
.wslconfig 上限时给出建议指引（不自动改系统配置）。
**验证**：慢引擎模拟（限流）下轮询占空比下降的日志证据；doctor 在
测试机输出内存建议；快机行为零变化。

## O7 · build cache 清理产品化（M）

**实证**：本机 build cache 6.697GB（4.079GB 可回收）= 最大磁盘占用；
docker_lifecycle 能力完全覆盖不到 builder cache（"no global prune"不变式
只禁全局 prune，未禁带过滤的 builder prune）；maintenance 三件套零 UI
入口。
**方案**：docker_lifecycle 新增 `docker_cache_cleanup`（`docker builder
prune --filter until=…` + dangling 镜像，保留 label/until 过滤、绝不碰
active）；CLI 子命令 + Rust command + 设置页"磁盘与缓存"卡片（占用
展示 docker system df 摘要 + 一键清理 + 清理日志）；doctor 检查项（超
阈值提示）。
**验证**：本机实测释放量报告；清理后镜像可正常重建；单测（argv 构造、
过滤参数、拒绝全局 prune 语义）。

## O8 · 冷启动提速（M）

**实证**（nairong 70s 分解）：.claude/.codex 全量 `cp -rL` 复制 29s
（有跳过门但无增量）+ daemon 启动等待上限 10s + mihomo 探测 12s+。
**方案**：出厂复制改**增量**——以 .factory-version 差异判定（相同跳过
已有；不同仅 rsync 式同步 skills/plugins 子集，镜像内已有 rsync? 无则
cp -u 逐目录比对）；daemon 等待轮询间隔自适应（Windows bind mount 首次
慢的注释场景保留上限）；mihomo 探测轮次收紧。**约束**：不破坏"保护
用户自定义修改"语义（跳过门注释 entrypoint.sh:139）。
**验证**：同工作区二次冷启动时间对比（目标 <30s）；首启全量路径不回归。

## O9 · 取消懒布局（S-M，用户直接下令）

**需求**：重新打开工作区不走懒恢复方案，直接完整恢复布局。
**现状**：layoutLazyRestore（stores 测试同名）——tab 恢复为 dormant 惰性
态。**方案**：重开工作区 = 全量恢复 tab/pane（会话按既有 dormant→唤醒
语义处理或直接重建），删除懒布局分支。**验证**：重开工作区布局完整
呈现（多 tab/分屏）；相关单测改写；启动耗时回归测量（确认全量恢复的
代价可接受，若显著回退再回报权衡）。

## T 序列（建议）

O1 → O3 → O9 → O2 → O5 → O4 → O6 → O7 → O8。
原则：快赢先行（O1/O3）；O3 遥测数据反哺后续；大手术（O4）放在稳定性
项（O5）之后；O8 依赖镜像改动走 vendor-refresh 链。

## 全局约束（§G，实施红线）

1. 规约：分支纪律（develop）、每 O 项独立 commit、手测先行 PASS 后推送、
   四条 CI 全绿、失败先比对 flake 史再定性
2. container/ 改动后必跑 vendor-refresh（后台）+ bundle 三处同步 +
   镜像重建验证；镜像侧改动（O5/O8）需容器内验证
3. 设置 SSOT 在 Rust settings.rs；i18n zh/en 双语同改；vitest+vue-tsc+
   cargo+pytest 四矩阵
4. 层契约：全局样式不触 xterm DOM（styles.css:216-221）；renderer 不写
   term.options；组件不直接 import logUiEvent
5. streamCursor 单调性 / 每帧单响应式替换 / 服务端阻塞背压——O2 不得
   破坏这三条既有不变式
6. spool/缓存清理一切新文件遵守 secret-free 或 0600 纪律；清理命令
   永不全局 prune、永不删 unverified 资源（docker_lifecycle 既有不变式）
7. 上游（cc-switch CLI）行为只绕不改；舞步每步失败恢复路径必须保持
8. 探针报告里的 文件:行号 为实施前的快照——动第一刀前校对漂移

## 外部证据依赖（并行收集，不阻塞其它项）

- 8G 笔记本：doctor 导出 + 容器日志（O5 的 OOM/reconcile 归属确认）
- 长对话无法恢复：复现样本（哪条对话/多长/报错截图或日志）——独立
  bug，暂不在本批次实施，证据到位后单独开项
