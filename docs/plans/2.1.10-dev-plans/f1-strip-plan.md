# F1 SSH 工作区剥离与封存计划（S0）

> 背景：用户裁决（D-6，2026-09-07）——F1（mutagen SSH 工作区）是错误尝试，
> 2.1.10 首个任务即剥离并暂时封存。远程化（R1-R4）成为唯一的 SSH 故事。

## 1. 剥离范围（代码足迹盘点 @ `a526fb6`）

### Rust（workbench/src-tauri/src/）

| 文件 | 足迹 | 动作 |
| --- | --- | --- |
| `sync.rs` | 整模块 1577 行（10 个 tauri command + mutagen 生命周期 + 磁盘防护线程 + ssh config 管理） | 删除 |
| `lib.rs` | 6 处：10 个 command 注册 + `sync::MUTAGEN_RESOURCE_DIR.set()` 启动设置 | 摘除 |
| `settings.rs` | 14 处：`sshProfiles` 设置（host/port/user/keyPath） | 摘除字段与 UI 绑定 |
| `data_root.rs` | 7 处：mutagen 数据根托管目录 / 同步元数据目录函数 | 摘除 |
| `watcher.rs` | 6 处：`~mutagen~` 临时文件过滤 + 测试 | 摘除（含断言） |
| `workspace.rs` | 1 处注释 + F1 D-10「AISC-managed sync-workspace files」元数据块 | 摘除元数据读写 |

### TS / UI（workbench/src/）

| 位置 | 内容 | 动作 |
| --- | --- | --- |
| `lib/ipc.ts` | F1 块（`sshWorkspaceCreate/sshBrowse/sshBrowseWorkspace/sshPullFile` + `syncSession*` 七个 + `SyncStatus`/`SshDirEntry` 类型） | 删除 |
| `features/startup/WorkspacePicker.vue` | SSH 工作区入口（折叠表单：profile/remotePath/name/ignores） | 删除 |
| `features/workspace/RuntimeSidebar.vue` | 同步状态面板（暂停/恢复/取消/拉取文件） | 删除 |
| `types` + `stores/workspaces.ts` | `SshProfile` 类型、`createSshWorkspace` action、`createSshError` | 删除 |
| 设置页 | sshProfiles 管理表单 | 删除 |
| `i18n/{zh-CN,en-US}.ts` | F1 相关键 | 清扫 |
| 各 `__tests__` | 涉 SSH/sync 的用例与 mock 键 | 同步删改（i18n/键改动必跑全量 vitest） |

### 构建与分发

| 位置 | 内容 | 动作 |
| --- | --- | --- |
| `workbench/src-tauri/tauri.conf.json` | `externalBin: binaries/mutagen` + `resources: binaries/mutagen-agents.tar.gz` | 删除两键 |
| `.github/workflows/{workbench-ci,nsis-installer,bundle-linux-macos}.yml` | mutagen 二进制/agents.tar.gz staging 步骤（含 `touch` 占位） | 删除步骤 |

### Python 侧

影子目录=真工作区（身份链零改动）设计使 `src/aisc/` **不感知** F1——预期零改动，
执行时以 grep 复核 `ssh|mutagen|shadow` 确认。

## 2. 封存方式

- **代码**：git 历史 + tag `v2.1.9-dev`（F1 最后完整状态）即封存载体，
  不建维护分支。
- **设计文档**：已在 `docs/archive/2.1.9-dev-plans/`（f1-f2-design.md、
  f1-f2-field-fixes.md、decisions.md D-10）——在归档 decisions.md 追加
  封存注记指向 D-6。
- **复活路径**：若将来需要「本地代码 + 远端 runtime」语义，从 tag 提取
  sync.rs 参考；远程化（R3 FS API）落地后该需求大概率被远程模式吸收。

## 3. 用户数据处置（逐项确认，不自动清理）

剥离后机器上的孤儿数据**先盘点报告、逐项等用户拍板**（machine-cleanup-safety
规约）：

1. 数据根内 SSH 影子工作区目录（含同步内容副本）
2. 工作区同步元数据文件（F1 D-10 写的 managed 文件）
3. mutagen 二进制 + agents.tar.gz 数据根托管副本（~80MB+）
4. `~/.ssh/config` 中 AISC 受管别名段（带标注，剥离后成为死段）
5. settings.json 的 `sshProfiles` 值（含 keyPath 等敏感路径）

代码剥离本身不触碰以上任何数据。

## 4. 执行序与验证

S0a Rust → S0b TS/UI → S0c 构建链 → S0d 文档（README F1 节删除 +
`tools/check-docs.sh` + devlog 条目）→ S0e 用户数据盘点报告。

每批门禁：`cargo test`（lib + 集成）、`cd workbench && npx vitest run`、
`vue-tsc`、pytest 全量；S0c 后远程四 lane CI（workbench-ci / nsis /
bundle / cli-sidecar）必须全绿（workflows 被改动）。

## 5. 风险

- 删 `~mutagen~` 过滤后，若用户数据根仍留有旧影子目录被再次 watch，
  残留 `~mutagen~` 文件可能浮现为变更——孤儿目录处置（§3）之后即无源。
- workflows 改动只触发 cli-sidecar 的 path filter 旧例——需手动补跑
  Bundle/NSIS/Workbench CI（gui-fine-tune-env 已知坑）。
