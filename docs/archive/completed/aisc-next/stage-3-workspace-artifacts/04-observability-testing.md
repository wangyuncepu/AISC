# Stage 3 可观测性与测试

> 基线：`d2bdcd9`

## 指标（不记录路径正文）

- tree list duration/node count/truncated；
- watcher queue/debounce/overflow/rescan duration；
- artifact record/import/reject reason；
- preview bytes/duration/outcome；
- index revision conflict/retry/corruption。

workspace/path 仅记录不可逆短 hash；不记录文件内容、prompt、secret。

## 自动化矩阵

### Python

- `aisc artifact` parser、JSON envelope、schema v1、record/list/inspect/clear；
- relative path、missing、rename、duplicate id、session scope；
- pip CLI 和 sidecar fixture 等价。

### Rust

- Windows/POSIX canonical containment；`..`、absolute、symlink/junction/UNC/case；
- schema/unknown field/revision/lock/atomic recovery/corrupt isolation；
- lazy pagination、ignore、size/count/preview cap；
- watcher coalesce、rename、delete、overflow、bounded rescan、dispose。

### Vue

- tree keyboard/APG、lazy expand、loading/error/stale；
- artifact 分类、missing、unattributed；
- open/reveal/copy IPC success/failure；
- compact/中文长文案/150%。

## E2E/手测

- Claude、Codex、Bash/script 分别创建文件；前两者有 manifest，shell 仅 watcher 未归因。
- Windows junction、Linux/macOS symlink 越界拒绝。
- 10 万文件 fixture 首帧不递归扫描；大目录按需展开。
- watcher 中断/overflow 后最终一致。
- 重启 Workbench 后 artifact 恢复；Git status 不新增 registry。
- Markdown/图片/PDF/二进制 open/reveal fallback。

## 性能门

Stage 0 baseline 后冻结：首次根目录列表、单目录展开、watcher burst、artifact import、重启恢复的 p50/p95；测试不得以“感觉快”签收。
