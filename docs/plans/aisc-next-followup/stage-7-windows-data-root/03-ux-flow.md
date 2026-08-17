# Stage 7 UX 流程

## 首次启动

1. resolver 展示 canonical data root 和可用空间；
2. 检测旧布局时显示文件数量、估算大小、冲突数和目标路径；
3. 用户选择“迁移并继续”“稍后处理”或“导出诊断”；
4. 迁移显示可取消进度；取消只留下可恢复 manifest，不删除源文件；
5. 完成后 Workbench、CLI doctor 和容器信息显示同一 root。

## 设置

- 提供“打开数据目录”“复制诊断路径”“重新运行迁移检查”；
- 不提供无确认的“清空全部数据”；cache、diagnostics 和 quarantine 的清理分别确认并显示大小；
- 权限、磁盘不足和冲突消息给出用户动作，技术错误码放在可展开详情。

## 非交互 CLI

`aisc data-root doctor --json`、`aisc data-root migrate --dry-run`、`aisc data-root migrate --apply`、`aisc data-root rollback <manifest>`；非交互模式遇到冲突必须退出非零，不猜测覆盖。
