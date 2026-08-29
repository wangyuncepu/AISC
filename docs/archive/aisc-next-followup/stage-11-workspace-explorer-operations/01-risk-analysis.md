# Stage 11 风险分析

| 风险 | 影响 | 缓解/门禁 |
|---|---|---|
| 新建、复制、重命名绕过 workspace containment | 任意路径写入或覆盖 | 所有 mutation 先在 Rust 中解析并校验；前端不传目标绝对路径；越界 fixture 必须失败 |
| symlink/junction/reparse point | 通过链接逃逸 workspace 或复制到外部 | 延续 `resolve_contained` 规则；对源、目标父目录和新建目标逐段检查；Windows junction/symlink 测试 |
| 目标同名 | 覆盖用户文件、数据丢失 | 默认拒绝覆盖，返回稳定 conflict 错误；前端展示重命名/换目录恢复动作 |
| 复制目录递归过大 | UI 卡顿、磁盘占满、操作不可取消 | 先实现单个文件和目录复制的受控版本；记录字节/条目数；明确超时和失败清理策略 |
| 复制中途失败 | 目标留下半成品 | 复制到同目录临时目标，成功后原子 rename；失败清理临时目标并返回错误 |
| 应用内复制缓冲区过期 | 粘贴到错误 workspace 或不存在源 | buffer 带 workspace、relative path、kind 和 generation；workspace 切换后清空或拒绝粘贴 |
| 名称包含 `..`、分隔符、保留名或控制字符 | 路径穿越、非法 Windows 文件名 | 只接受单一 basename；后端再次校验；拒绝空名、`.`、`..`、分隔符、保留设备名 |
| watcher 与 mutation 竞态 | 重复刷新、状态错乱、创建结果不出现 | mutation 成功后定向刷新父目录；watcher 事件仍为补充；刷新操作幂等 |
| 单击语义变更破坏旧测试/用户习惯 | 预览消失或双击打开失效 | 更新测试明确“单击不 preview、双击 open”；保留右键打开和系统 reveal |
| VS Code 风格图标引入版权/依赖/主题问题 | 构建膨胀、主题对比度差 | 不复制 VS Code 图标资源；使用本地受控 SVG/CSS icon mapping，图标仅表达类型 |
| 拖拽事件被 xterm 或 pane 外层吞掉 | 文件无法插入终端 | Explorer 只负责 drag payload，Terminal/WorkspaceView 负责 drop；加入 dragenter/drop preventDefault 和 e2e smoke |
| 路径 quoting 不正确 | 含空格、引号、括号的路径变成错误命令参数 | 以终端宿主平台为准实现 shell quoting；drop 只写入，不提交；覆盖 Windows PowerShell/cmd 和 Unix shell 策略 |
| 拖入时 active pane 不存在或终端不可用 | 路径丢失或写到错误 tab | drop 前解析当前 active terminal target；无可用 pane 时拒绝并显示反馈，不缓存到未知 pane |
| CSS zoom/Compact 下菜单或 inline input 溢出 | 操作不可见、无法确认 | 复用现有 menu 坐标模型；名称输入使用 min-width: 0；在 `font_scale` 0.8/1.0/1.5 和边界窗口验收 |

## 阻断条件

以下任一项出现即停止合并：

1. 任意 mutation 能接受 workspace 外路径；
2. 粘贴或重命名覆盖已有用户文件而没有明确确认；
3. 拖入文件后终端自动执行命令或插入未 quoting 的路径；
4. 终端输入、xterm canvas、PTY、resize/fit 出现回归；
5. 键盘菜单、名称输入、Escape 取消或 focus restore 不可用。

