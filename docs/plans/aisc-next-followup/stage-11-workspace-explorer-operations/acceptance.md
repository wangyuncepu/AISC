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
| A-WX11-01 | Workbench/Vue/Rust 基线与结项测试通过 | 自动化 PASS：vitest 42 files / 328 tests；vue-tsc + vite build 通过；cargo --lib 216 passed / 1 既有环境失败（KI-1 docker 探测，见基线记录） | 2026-08-24，分支 `stage-11-explorer-ops` |
| A-WX11-02 | 文件单击不预览，双击/Enter 打开 | 自动化 PASS（组件测试：click 不调 preview、dblclick/Enter 调 workspaceOpen）；真机手测待执行 | `__tests__/workspaceExplorer.test.ts` activation semantics |
| A-WX11-03 | 目录单击展开/折叠，懒加载和 watcher 不回归 | 自动化 PASS（dir click toggle 既有用例 + 11c 新用例）；watcher 用例未改动全绿 | 同上 |
| A-WX11-04 | 工具栏新建文件、新建文件夹、刷新可用 | 自动化 PASS（按钮存在/disabled/选择感知目标）；真机手测待执行 | toolbar describe |
| A-WX11-05 | 根目录/目录/文件右键菜单按 target 展示正确 | 自动化 PASS（三 target 的菜单 id 顺序断言） | context menus describe |
| A-WX11-06 | 新建、复制、粘贴、重命名成功且刷新/选中正确 | 自动化 PASS（store 定向刷新 + 组件提交路径）；真机手测待执行 | mutations describe |
| A-WX11-07 | 同名、非法名、无权限、越界操作失败且不改坏文件 | 自动化 PASS（Rust 18 个 mutation 测试：conflict/containment/预算清理/跨工作区拒绝）；真机手测待执行 | `workspace.rs mutation_tests` |
| A-WX11-08 | 文件和文件夹图标在暗/亮主题、长名称和 zoom 下稳定可见 | 自动化 PASS（icon 映射 + 每行固定图标）；暗/亮/zoom 真机手测待执行 | iconKind + drag&icons describe |
| A-WX11-09 | 文件拖入终端插入正确 quoted absolute path，不执行命令 | 自动化 PASS（payload 仅 relative path、POSIX quoting token、不追加 Enter——drop 只调用 writeSession 一次）；真机容器内手测待执行 | dropPath.test.ts |
| A-WX11-10 | 无 session、无 active pane、目录 drop 时正确拒绝 | 自动化 PASS（目录不 draggable；无 session 分支写本地提示不触 PTY）；真机手测待执行 | Terminal.vue onDrop + drag describe |
| A-WX11-11 | 键盘菜单、inline input、Escape、focus restore 可达 | 自动化 PASS（Shift+F10 菜单、Enter/Escape/blur/conflict 保留输入）；真机手测待执行 | inline naming describe |
| A-WX11-12 | xterm 输入、搜索、复制、split、resize/fit 无回归 | diff 未触及 PTY/xterm renderer/fit/scrollback；vitest 全量（含 terminal 既有测试）通过；真机手测待执行 | diff --name-only 清单 |
| A-WX11-13 | 不记录 secret、文件内容、完整绝对路径或终端 scrollback | 代码走查 PASS：mutation 日志仅稳定 code + technical_detail（受控 I/O 文本）；drag payload 不含绝对路径；前端不读文件内容完成 copy | workspace.rs / dropPath.ts / workspaceDnd.ts |
| A-WX11-14 | 各阶段提交可独立测试、构建和按门回滚 | 每门独立提交且测试随门提交（11b/11c/11d 均独立全绿后提交） | git log（见回滚点） |

## 发布阻断复核

实施时必须确认：

- [x] 所有 mutation 通过 Rust containment（resolve_contained / resolve_new_target 双重校验 + 越界测试）；
- [x] 不覆盖同名用户文件（create_new/存在检查 + conflict 测试）；
- [x] 复制失败无半成品（临时目标清理 + 预算超限清理测试）；
- [x] drop 不执行命令、不追加 Enter（writeSession 单次调用，无 \r\n）；
- [ ] xterm/PTY/fit/resize 无回归（真机手测待执行）；
- [ ] 菜单和输入在 CSS zoom/Compact 下可见（真机手测待执行）；
- [ ] 既有 artifact、watcher、ignore 和键盘树行为无回归（真机手测待执行）。

## 回滚点

| 门 | commit | 回滚粒度 |
|---|---|---|
| 11a contract | `03a3717` | 纯 docs 契约（无行为） |
| 11b fs ops | `94dda4b` + `58aa965` | Rust helpers/commands/tests + TS wrapper |
| 11c explorer actions | `03eedb7` + `095a36f` | store/menu/name input/i18n + 测试 |
| 11d icons+dnd | `fa70c24` + `59f9d14` + `71a719f` | icon mapping / terminal drop adapter / 测试 |
| 11e acceptance | 待手测后补 | 验收证据文档 |

## 遗留项

| 项 | 处置 |
|---|---|
| 目录递归复制上限或取消 | 实施前按实际性能测试确定；未确认前不得宣称无限复制 |
| shell 宿主识别不足 | 单独扩展 session/runtime 契约，不在 Terminal 中猜测 |
| 原生系统文件剪贴板 | 不属于本阶段；应用内 clipboard 已满足 Explorer copy/paste |

