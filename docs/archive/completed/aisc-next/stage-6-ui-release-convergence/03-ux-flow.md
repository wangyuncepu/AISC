# Stage 6 UX Flow

## Layout

- Compact：Sidebar 抽屉、Explorer 抽屉、Tab 横向滚动、actions wrap、详情 dialog。
- Standard：当前双栏工作区。
- Wide：侧栏可展示摘要与 artifact facets，终端保持主要面积。

## Sidebar

常驻只显示 Runtime/provider/sessions 摘要；技术 ID、freshness、route、auth 放 developer details；停止/删除等危险操作隔离并确认。

## Dialog/menu

打开 → 首焦点 → Tab 循环 → Escape/Cancel → opener 恢复。Context menu 支持鼠标、Shift+F10、Menu key、上下键、Escape 和 viewport safe position。

## 诊断

错误 banner 显示用户动作；Details 展示 operation/source/stable code；Export 先显示可导出字段，再生成 redacted bundle。

## 视觉原则

主题 token、平静表面、明确状态色、低装饰；不使用多层卡片或营销 hero。中英文、长路径、长状态文案不得挤压操作。