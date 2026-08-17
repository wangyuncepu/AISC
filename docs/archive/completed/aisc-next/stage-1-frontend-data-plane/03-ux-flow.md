# Stage 1 UX/流程

## 首帧与会话

启动先恢复 settings/capability，再渲染稳定 shell；Runtime snapshot 与 operation error 分区。创建 Session：预留资源→启动 PTY/CLI→绑定 generation→批处理输出→running；失败显示可重试 action，不伪造 snapshot。

## 高频终端

reader 持续读入 bounded queue；UI 每帧或固定批次消费。窗口隐藏时暂停 render、继续 drain；overflow 显示“输出已截断”及计数。切换 tab 只切 view projection，不暂停 child。关闭：拒绝新输入→terminate/cancel→wait/reap→ack→dispose。

## stale/unknown

poll 失败有旧快照时显示“上次已知”与重试；无旧快照显示“无法确认”，不进入 configured/运行态。aria-live 只播报状态变化和明确错误。

## a11y P0

Tablist、pane、终端、错误摘要和重试动作全键盘可达；focus ring 明确；状态同时有文本和图标/结构；screen reader 不朗读每个 output chunk。手测覆盖键盘导航、缩放 200%、对比度和 reduced motion。
