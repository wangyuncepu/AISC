# Stage 11 验收台账

> 结果状态：实施中
> 结论枚举：`PASS` / `PASS-WITH-FOLLOWUPS` / `STOP`
> 证据要求：记录 commit、Workbench 版本、Windows/WebView2、主题、语言、有效宽度、font scale、测试 workspace 和脱敏日志/截图路径。

## 基线记录（11a，2026-08-24）

- 分支：`stage-11-explorer-ops`（自 `develop` @ `dc27c52` 切出）
- `npm run test`（vitest）：39 files / 285 tests PASS
- `npm run build`（vue-tsc --noEmit + vite build）：PASS（chunk size 警告为既有状态）
- `cargo test`（src-tauri，--offline）：205 passed / 1 failed —— `env::tests::diag_engine_reachable_true_with_running_docker` 为 KI-1 临时复现测试，要求本机 Docker 正在运行；本机未装 Docker Desktop，属既有环境限制，与本阶段无关。阶段门以该测试外的全绿为准。

## 验收矩阵

| ID | 验收方法 | 结果 | 证据 |
|---|---|---|---|
| A-WX11-01 | Workbench/Vue/Rust 基线与结项测试通过 | 待执行 | 待填 |
| A-WX11-02 | 文件单击不预览，双击/Enter 打开 | 待执行 | 待填 |
| A-WX11-03 | 目录单击展开/折叠，懒加载和 watcher 不回归 | 待执行 | 待填 |
| A-WX11-04 | 工具栏新建文件、新建文件夹、刷新可用 | 待执行 | 待填 |
| A-WX11-05 | 根目录/目录/文件右键菜单按 target 展示正确 | 待执行 | 待填 |
| A-WX11-06 | 新建、复制、粘贴、重命名成功且刷新/选中正确 | 待执行 | 待填 |
| A-WX11-07 | 同名、非法名、无权限、越界操作失败且不改坏文件 | 待执行 | 待填 |
| A-WX11-08 | 文件和文件夹图标在暗/亮主题、长名称和 zoom 下稳定可见 | 待执行 | 待填 |
| A-WX11-09 | 文件拖入终端插入正确 quoted absolute path，不执行命令 | 待执行 | 待填 |
| A-WX11-10 | 无 session、无 active pane、目录 drop 时正确拒绝 | 待执行 | 待填 |
| A-WX11-11 | 键盘菜单、inline input、Escape、focus restore 可达 | 待执行 | 待填 |
| A-WX11-12 | xterm 输入、搜索、复制、split、resize/fit 无回归 | 待执行 | 待填 |
| A-WX11-13 | 不记录 secret、文件内容、完整绝对路径或终端 scrollback | 待执行 | 待填 |
| A-WX11-14 | 各阶段提交可独立测试、构建和按门回滚 | 待执行 | 待填 |

## 发布阻断复核

实施时必须确认：

- [ ] 所有 mutation 通过 Rust containment；
- [ ] 不覆盖同名用户文件；
- [ ] 复制失败无半成品；
- [ ] drop 不执行命令、不追加 Enter；
- [ ] xterm/PTY/fit/resize 无回归；
- [ ] 菜单和输入在 CSS zoom/Compact 下可见；
- [ ] 既有 artifact、watcher、ignore 和键盘树行为无回归。

## 回滚点

| 门 | commit | 回滚粒度 |
|---|---|---|
| 11a contract | 待填 | 纯 docs/类型契约 |
| 11b fs ops | 待填 | Rust helpers/commands/tests |
| 11c explorer actions | 待填 | store/menu/name input/i18n |
| 11d icons+dnd | 待填 | icon mapping/terminal drop adapter |
| 11e acceptance | 待填 | 测试/证据文档 |

## 遗留项

| 项 | 处置 |
|---|---|
| 目录递归复制上限或取消 | 实施前按实际性能测试确定；未确认前不得宣称无限复制 |
| shell 宿主识别不足 | 单独扩展 session/runtime 契约，不在 Terminal 中猜测 |
| 原生系统文件剪贴板 | 不属于本阶段；应用内 clipboard 已满足 Explorer copy/paste |

