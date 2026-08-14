# Stage 1 领域契约

## 1. 所有权与状态

Vue/Pinia 只保存用户交互、短期 UI 和 reducer 产出的 snapshot；Rust 保存 SessionRegistry、PTY、child、IPC 和宿主路径；Python 仍为 Runtime/Session/Provider 事实所有者。操作错误使用统一 `operation_id/source/phase/outcome/stable_error_code/retryable/action`，不得覆盖 snapshot。

## 2. 数据面

PTY read 进入 bounded channel，按 session 批处理；write 有 bytes cap 和背压；resize 输入为有限 `cols/rows`，按 session 去重并丢弃隐藏 pane 的零尺寸。取消只发一次，close 进入 Closing，完成后 wait/reap/ack。

## 3. 事件一致性

事件必须携带 `session_id`、generation、sequence；旧 sequence/generation 丢弃并计数。自然退出只产生一个 terminal result，前端提交后 ack；terminal metadata 有 TTL/数量上限。隐藏窗口暂停渲染但不能暂停 reader。

## 4. 前端投影

组件只消费 typed view model；高频 output 不进入深层响应式对象。`fresh/stale/unknown/unavailable` 保持可区分；aria-live 仅播报状态/auth/操作结果。所有 listener、timer、observer、addon 在 unmount 或 session close 时 dispose。

## 5. 上限

单 Runtime 的并发 opening/running/closing、pane/queue/buffer 上限由 Stage 0 fixture 注入；第 N+1 请求在资源预留前拒绝并返回可行动错误，不能半提交布局。
