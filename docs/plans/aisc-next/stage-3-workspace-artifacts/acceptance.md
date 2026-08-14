# Stage 3 验收台账

> 未填证据不得标 PASS。

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