# Stage 9 UX 流程

## Shell

- 启动后先显示 runtime/data-root readiness；不可用时提供稳定错误码和 retry/open diagnostics；
- Sidebar/Explorer/Tab/terminal 延续现有工作型高密度布局；不新增营销或装饰页；
- tab 支持新建、切换、关闭、重开失败 session；关闭先取消 operation，再等待 child/PTY 有界退出。

## Terminal

- 输入、粘贴、复制、搜索、滚动、resize、focus 和 keyboard navigation 与现有 Workbench 对齐；
- hidden tab 暂停渲染但继续读取 bounded output；overflow 有明显状态；
- native control 不可用时 POC 必须显示阻断原因，不自动降级为不兼容的文本框。

## Provider tab

新建 `cc-switch-ui` tab 后显示已配置 provider 列表和非敏感状态。添加入口提供 `简易添加` 与 `自定义添加` 两种模式；编辑/删除有确认和错误恢复；API key 只显示 mask，不能从界面复制完整值。
