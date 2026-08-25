# B-05 族终端三症专项:xterm/PTY 尺寸收敛

> 状态:**已完成**(2026-08-25,分支 `b05-terminal-stability`,十三轮手测闭环;用户确认)
> 来源:todo.md「UI10 终端非视觉缺陷」(B-05①长输入不换行 / B-06 fit 迟滞 / B-05③快速切 tab 行错乱)

## 1. 症状与用户实证(2026-08-25 确认)

- ①长输入:超过右缘后**新字符覆盖旧行内容**(非溢出不可见)→ 指向 xterm 窄、PTY 宽的列数失配(readline/TUI 按自己的列数做重绘数学)。
- ②fit 迟滞:拖拽窗口时列数不实时跟随,缓慢逐段挤压。
- ③行错乱:快速切 tab 时文本行串位(todo 证据 aaa.png)。
- 三症均在 **font_scale 1.0 默认字号**下出现(排除反 zoom 测量为主因)、**随机出现无稳定复现路径**、bash 与 agent TUI 均涉及。

## 2. 管线事实(代码核实)

1. PTY 以 80×24 spawn;Python sidecar 初次 `exec_resize` 后 **100ms 轮询** resize 文件(`docker_gateway.py`)。
2. 前端 `resizeSession` 唯一调用点在 `Terminal.vue doResize()`,guard `!visible||!term||!fit||!sessionLive` 直接 return,失败 `.catch(()=>{})` **静默吞**。
3. **会话变 live 时无任何 resize 触发**:mount 只 fit xterm 不通知 PTY ⇒ 打开 tab 后到第一次拖窗口/切 tab 之间,PTY=80 列、xterm=fit 宽度,**天然失配**。
4. resize 防抖 150ms **纯 trailing**:拖拽中每事件重置计时器,过程中完全不动。
5. 切 tab=v-show 回显:refresh(旧尺寸)→fit→resizeSession→100ms 后 exec_resize→SIGWINCH 重绘,2~3 轮异步重排交错;隐藏期容器尺寸漂移(display:none 时 ResizeObserver 报 0,被 guard 挡)攒到回显结算。

## 3. 根因模型

统一根因:**xterm 列数与 PTY 列数可在任意时刻失配,且无收敛保证**(初始不同步、失败无感知、同步要 250ms+)。三症是同一根因在不同时机的表象:①=失配持续期的行编辑错位;②=防抖+轮询链的迟滞;③=回显时多轮重排交错且失配可能修一半。

## 4. 修复设计(收敛机制,而非定点修)

症状随机不可主动复现 ⇒ 修复必须让失配**必然被自动纠偏**,验证靠观察期。

| # | 修复 | 针对症状 |
|---|---|---|
| F1 | 会话 `sessionState→running` 瞬间**立即 doResize**(绕过防抖),mount 时若已 running 也立即;只有 running 态才发 `resizeSession`(Starting/Closing 发了必失败) | ①(消除 80 列滞留窗口) |
| F2 | resize 失败**可观测 + 重试**:`logUiEvent("terminal_resize","error",code)` 落共享时间线;失败置位后由自愈 tick 重发 | ①③(静默吞错根除) |
| F3 | **2s 自愈 tick**:live+visible 期间周期检查,已收敛则零 IPC 空转,漂移/失败才重发 | ①③(随机性的结构性兜底) |
| F4 | 防抖改 **leading+trailing**:事件先立即 fit 一次再挂 150ms trailing,持续拖拽下 ≤150ms 跟随 | ② |
| F5 | 已确认尺寸幂等跳过(cols/rows 未变且无失败不发) | 全部(避免无谓 exec_resize 噪音) |

不改动:xterm/PTY 协议本身、sidecar 轮询机制(100ms 固有延迟接受)、`:key` 重挂/缓冲重放设计、10e r7 淡入(opacity 不改布局)。

## 5. 验收

- 自动化:组件级测试(xterm 假件)覆盖 F1/F2/F3/F4/F5 各路径;vitest/vue-tsc/build/cargo 全绿。
- 观察期(替代定点复现):用户日常使用(含 agent TUI、拖拽窗口、快速切 tab),三症不再出现;`aisc.log` 若出现 `terminal_resize error` 打点即证据留存。
- 回滚:本专项单分支,按提交粒度回滚。

## 6. 手测二轮(2026-08-25,F1–F5 之后)与探针证据

用户反馈:①拉伸窗口列数仍不实时跟随;②TUI 列数不足时结构混乱,扩大后不重绘(并提议:列数不足时显示提示而非立即渲染 TUI——已实现,`NARROW_TUI_MIN_COLS=60`,bash 豁免);③全屏→窗口恢复时终端逐段向左压缩逼近目标。

**容器侧定罪探针(本机 Docker 29.7.2,python:3.12-slim 临时容器)**:

- Phase A(单前台进程):2 次 exec_resize → 2 次 SIGWINCH ✓
- Phase B(精确复刻 wrapper:setpgid 子进程 + tcsetpgrp + waitpid):**agent 子进程收到 SIGWINCH,子进程 `stty size` 读到新尺寸(40×200)** ✓

结论:exec_resize → winsize → SIGWINCH → agent 这段链路在容器内**无断点**,"扩大后不重绘"的断点只能在宿主侧(前端未发 / resize 文件未写 / sidecar 轮询未跑)或 TUI 自身。待用户实机 `stty size` 探针(见验收)定罪。③的逐段压缩与 150ms 采样节流的中间态重排一致(方向不对称:bash 在拉伸方向不重绘历史,压缩方向 xterm reflow 全量可见)。

## 7. 最终修复台账(手测四~十三轮,分支提交序列)

| # | 根因层 | 修复 | 提交 |
|---|---|---|---|
| R1 | **sidecar 闭包陷阱**(真凶):`watch_resize` 对闭包变量 `last_size` 赋值无 `nonlocal` → 每次迭代 UnboundLocalError 被吞 → **初始读之后所有 resize 永不生效**,PTY 永远停在会话首尺寸 | 轮询步提为模块级 `_poll_resize_step`(连续变更全生效有回归测试),两条 open_interactive 路径线程改局部副本 | `c179606` |
| R2 | xterm↔PTY **从不收敛**:live 时无初始同步、失败静默吞 | F1 running 即同步 + F2 失败上时间线(经 store 收口点)+ F3 2s 自愈 tick + F5 幂等跳过 | `a891165` |
| R3 | resize **竞速乱序**:show 同步与 settle 双发在飞,文件终值停在旧尺寸而前端记新值,自愈被永久欺骗 | 发送串行化(在飞仅一,排队最新);网格 sanitize(2..512/1..256)+ 格宽合理域 | `889f6e4` |
| R4 | **fit↔布局反馈环**:FitAddon 混用 clientWidth(本地单位)与字符测量(跨 zoom 单位);`.main`/`.ready` 缺 `min-width:0` 使终端列被 xterm 屏幕内容定宽 → 14px/150ms 阶梯挤压(缩小方向) | zoom 免疫测量(同子树 rect);格宽行高自校准(从 `.xterm-screen` 反推);`.main/.ready` 补 min-width:0;容器 overflow:hidden | `c0bb938`/`9a80ec3`/`d559ada`/`5f9bb3f` |
| R5 | TUI 在 <60 列渲染卡死,且冻结式下限导致放大后无 WINCH 不重绘 | 双侧钳制:窄相 xterm 与 PTY 同钳 60 列(bash 豁免),放大必产生新尺寸→重绘;窄窗提示层 | `42ea557`/`da378c3` |
| R6 | **遮罩动效**(审查 terminal-render-review.md):createElement 节点无 scoped 属性(从未生效)/挂载晚于 reflow/陈旧释放 | 声明式节点 + pre-paint pin(每次 tab 切换与新建 tab)+ 发送时刻捕获的代次令牌 + 确认+宽限释放(300ms 同 app 曲线);终端 pane 独占动效,guide/settings 保留原渐变 | `5ff1661`~`72743f9` |
| R7 | 防抖形态:还原动画连发中间尺寸,leading 逐段全量重排闪烁 | 停稳即达(150ms 安静后一次 fit+send) | `11f2973` |

**定位方法沉淀**:容器侧 Docker 探针(复刻 wrapper 进程结构验证 SIGWINCH/winsize 送达)→ 宿主侧三证(stty 实测 + resize 文件 mtime + aisc.log)→ 前端全链路时间线探针(各环节打点)→ 祖先链宽度追踪。探针已全部移除,保留 `terminal_resize` 失败打点(永久可观测)。

**终局门禁**:vitest 342 / vue-tsc+build / pytest 796 / cargo --lib 217 全绿;十三轮手测全部 PASS(用户确认 2026-08-25)。

## 8. 遗留观察项

- 若观察期后①仍偶发:升级探针(屏显同时展示 xterm cols 与 `stty size`,由 `logUiEvent` 携带双侧值)再定位。
- ②的"逐段挤压"若在 F4 后仍明显:评估 xterm reflow(scrollback 5000)分块渲染的独立优化,不属本专项。
