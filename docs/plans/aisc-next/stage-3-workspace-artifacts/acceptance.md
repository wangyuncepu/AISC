# Stage 3 验收台账

> 未填证据不得标 PASS。

## 进行中补充（2026-08-15）

- Explorer 树从“仅一层展开”改为递归可见树，支持任意层级键盘/缩进。
- 目录列表与 Artifact 列表补充分页加载（`loadMore` / `loadMoreArtifacts`）。
- 修复 Workbench 从未调用 `artifact_refresh` 导致 Artifacts 面板长期为空的问题。
- Artifact 面板补充 Source changes / Generated outputs 分组及打开/显示/复制操作。
- 修复 Artifact 列表分页计算错误（原先超过 200 条也不会返回下一页）。
- 切换到 Artifacts 页时自动刷新 artifact index，避免面板长期空白/陈旧。
- 打开 Explorer 时总是刷新，避免隐藏期间新增文件不显示。
- Watcher 改为全局运行，不随 Explorer 面板开关而停止，隐藏时也能捕获新增文件。
- 强制刷新已加载目录时对比前后列表，把新增/消失文件补进 unattributed，避免 watcher 漏掉。
- 修复 watcher 根目录事件会删除已加载根树、导致 Explorer 点击刷新后闪现又消失的问题。
- Explorer 默认常显示，改为覆盖式抽屉，打开/关闭不再挤压或重排终端区域。
- Artifacts / Workspace changes 行只显示文件名，完整宿主机绝对路径放在 hover title。
- 增加 1.5s 目录轮询兜底：即使原生 watcher 未可靠上报，新建文件也会在 1.5s 内出现在已加载目录。
- watcher 路径换算增加 canonicalize 回退，兼容 Windows verbatim 前缀/大小写/前缀不一致。
- watcher 事件携带 kind；新建文件夹后会立即列出其子项并标记 unattributed，避免只显示文件夹、不显示其中新建文件。
- 右键菜单改用 Tauri 剪贴板插件、跟随鼠标位置，并在执行 Open/Reveal/Copy 后关闭菜单。
- CLI 支持把容器内绝对路径（如 `/root/app/...`）归一化为 workspace-relative；UI 产物列表显示宿主绝对路径。
- Watcher 忽略规则改为匹配任意层级 `node_modules` / `target` / `build` 等目录，减少噪音。
- 树节点增加 watcher `change_state` 与 artifact badge 展示。

> 以上代码已改，待自动化与真机手测后逐项填 PASS。

- `A-ART01-1` schema v1 fixture 在 Python/Rust/TS round-trip，unknown fields 保留。
- `A-ART01-2` unsupported/corrupt schema fail closed，不覆盖原数据。
- `A-ART02-1` record/list/inspect/clear-session 在 pip CLI 与 sidecar envelope 等价。
- `A-ART02-2` relative/create/modify/delete/rename/missing/duplicate 矩阵通过。
- `A-ART03-1` Skill 会登记并输出相对路径；未调用 Skill 时 watcher 仅显示未归因变化。
- `A-ART04-1` registry 不进入 workspace，Git status 无新增；session/workspace 隔离。
- `A-ART05-1` absolute/`..`/symlink/junction/UNC/case 越界全部拒绝。
- `A-ART05-2` secret/size/count/type/preview budget 生效且错误脱敏。
- `A-ART06-1` 并发 revision、lock timeout、replace failure recovery、corrupt isolation 通过。
- `A-WX01-1` 10 万文件 fixture 根目录 lazy，无全递归扫描；分页/ignore 正确。
- `A-WX02-1` text/Markdown/image/PDF/binary 的 preview/open/reveal/copy fallback 正确。
- `A-WX03-1` burst/rename/delete/overflow/dispose，bounded rescan 后最终一致。
- `A-WX04-1` manifest artifact 与 unattributed change 不混淆，状态更新正确。
- `A-WX05-1` keyboard/读屏/compact/150%/中英文/长路径通过。
- `A-WX05-2` Windows、Linux、macOS 实机 workspace 与系统文件管理器联动 PASS。

每项填写总 overview 规定的 commit/平台/步骤/结果/性能/证据格式。