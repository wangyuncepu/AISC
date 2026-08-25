# B-05 族终端三症专项:xterm/PTY 尺寸收敛

> 状态:实施中(2026-08-25,分支 `b05-terminal-stability`)
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

## 6. 遗留观察项

- 若观察期后①仍偶发:升级探针(屏显同时展示 xterm cols 与 `stty size`,由 `logUiEvent` 携带双侧值)再定位。
- ②的"逐段挤压"若在 F4 后仍明显:评估 xterm reflow(scrollback 5000)分块渲染的独立优化,不属本专项。
