# 2.1.8 决策与挂账记录

## D-1：ble.sh 幽灵文本默认停用（2026-08-30，T2 手测轮）

**结论**：`aisc-bashrc` 中 ble.sh 加载与 `ble-attach` 全部经 `AISC_BLE_EXPERIMENT=1`
门控（默认关）。镜像继续 vendor `ble-0.4.0-devel3.tar.xz` 供实验，不删。

**原因**：Workbench 终端链（xterm.js ↔ conPTY ↔ docker exec pty，双重转译）上
ble.sh attach 会**冻结 shell**——init 输出两次 `bash: 2: Bad file descriptor`，
此后按键/粘贴全部无响应（用户手测 2026-08-30；宿主侧 PTY 装置复现同症状）。
fail-open 设计底线：降级必须是"没有补全"，不能是"没有终端"。

**诊断假设**（待验证）：ble.sh attach 时向终端发 `ESC[6n`（光标位置查询）并等待
应答；双重 PTY 转译链上应答未返回 → 初始化阻塞。验证路径：容器内 tmux 面板开
bash（tmux 自身应答 `ESC[6n`）——若 `BLE_VERSION` 正常且幽灵文本工作，坐实裸
PTY 链不兼容。挂账任务 #50。

**T2 其余项不受影响**（2026-08-30 PTY 装置实测通过）：
- procps 补装后 ble.sh 能通过环境检查并完成 attach（冻结发生在 attach 之后），
  说明 vendor 的 ble.sh 本体完好
- wrapper `_rebuild_env` 重建 `AISC_BASH_HISTORY_FILE/DB` 后，SQLite 落库全链路
  正确（workspace_hash / terminal_session_id / cmd / cwd / started_at / exit_code）
- fzf Ctrl+R、yazi、nvim、HISTFILE 均不依赖 ble.sh

## D-2：docker exec 环境边界（T2 排障结论，防止复发）

`docker exec` 会话环境 = 镜像 ENV + `docker create -e`，**不含** entrypoint 运行时
export 的变量。凡 entrypoint 运行时导出的变量（如 `AISC_BASH_HISTORY_FILE/DB`），
需要被 exec 数据面（session wrapper / bashrc）使用时，必须：
1. entrypoint 写入 `/run/aisc/runtime-context.json`，且
2. wrapper `_rebuild_env` 从 context 显式重建。

`AISC_WORKSPACE_HASH` 走 `docker create -e`（runtime.py start argv），故无需重建。

## D-3：砍掉 fzf 模糊搜索历史（2026-08-30，T2 手测轮，用户产品决策）

**结论**：fzf 整体移出镜像（apt 行 + bashrc key-bindings 段）。`Ctrl+R` 回落
bash 原生 incremental search（`(reverse-i-search)`）。SQLite 命令落库**保留**
（设计期 Q4-A 决策未被撤销；无 UI 消费者但 T4+ 周期可复用；如需关闭，entrypoint
停导出 `AISC_BASH_HISTORY_DB` 一行即可）。HISTFILE 保留——开新标签后 `↑` 仍可
召回上次会话的命令，零开销且用户可感知。

**理由**：用户手测后判断搜索历史"使用感知不大、体验感不强"；补全（ble.sh）已因
D-1 停用，fzf 是该链条上最后一个仅炫技项。

**字体默认值**（同轮）：`settings.rs` 终端 `font_family` 默认链头部插入
`JetBrainsMono Nerd Font Mono, JetBrainsMono Nerd Font`（yazi 图标开箱即得；
未装 Nerd Font 的机器自动回落 Cascadia，无副作用）。已有设置文件的用户仍需在
设置 UI 改一次（已保存值优先于代码默认）。

## D-4：Workbench 交互 shell 切换为 zsh（2026-08-30，T2 手测轮）

**结论**：`agent=bash` 的交互 shell 改为 zsh，幽灵文本需求以此交付：
- 镜像新增 `zsh zsh-autosuggestions zsh-syntax-highlighting`（Debian 官方源）
- 托管配置 `container/aisc-zshrc` → 镜内 `/usr/local/share/aisc/zsh/.zshrc`，
  经 `ZDOTDIR` 加载（zsh 的 `--rcfile` 等价物）
- wrapper 启动分支：zsh+托管配置存在 → `zsh`；否则回落 `bash --rcfile`（旧镜像
  兼容）；历史路径经 context 透传 `AISC_ZSH_HISTORY_FILE`（`.zsh_history`，与
  bash 文件分离）
- zshrc 内容：HISTFILE 即时落盘（`inc_append_history`，与 bash `history -a`
  修复同因）、补全 `compinit`、灰色幽灵文本（→ 接受）、语法高亮（最后 source）、
  SQLite 钩子移植（`preexec`+`precmd` 调同一 Python helper，与 bash 落库同表）

**验证**：宿主 PTY 装置字节级确认（输入 `echo spi` → `^[[90m` 灰色建议 → `→`
接受重绘 → 执行输出 → 提示符回归无冻结）+ 用户真终端手测通过。同一装置当年可
复现 ble.sh 冻结，故通过信号强。

**兼容性说明**：`agent` 字段仍为 `bash`（Workbench API/会话记录不变）；tmux
面板仍走 bash 链（$SHELL=/bin/bash → bashrc），需要 zsh 时手动 `zsh`。

## D-5：conversation id 校验放宽为任意版本 UUID（2026-08-30，T3 实装发现）

**结论**：T3 的 preflight ID 校验与 codex 文件名正则从"UUID v4 严格"放宽为
"任意 RFC-4122 版本"（仍拒绝非 UUID 垃圾输入，保留"精确 ID 匹配、不做 glob
子串"的意图）。

**原因**：设计 §2 的校验正则钉死 v4，但 T0 冻结的 codex 真实探针 fixture
（`codex_normal.jsonl` 等）的会话 ID 是 `01a04ca9-d3f6-7021-…`——**v7**
（Codex CLI 使用时间序 UUIDv7）。按冻结正则，真实 codex 会话 100% 被
preflight 拒绝，T4 恢复功能对 codex 直接不可用。设计文档与冻结 fixture 自相
矛盾，fixture 来自真实探针，故以 fixture 为准。

**影响面**：`application/conversation.py` 的 `_UUID_RE` / `_CODEX_FILENAME_RE`
两处；claude 的 id（真实 v4）不受影响。错误码、exit code、envelope 契约均不变。
