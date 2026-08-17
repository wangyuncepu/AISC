# Stage 7 领域契约

## Canonical layout

```text
<data-root>/
  config/                         # AISC 全局设置和 sidecar pin
  state/                          # locks/indexes/onboarding state
  workspaces/<sha256-v1>/
    claude/ codex/ cc-switch/     # provider/agent config
    runtime/ logs/                # session runtime and bounded logs
  artifacts/                      # non-secret artifact index/payload metadata
  cache/                          # disposable downloads/build metadata
  diagnostics/                    # explicitly exported redacted bundles
  migrations/                     # manifests, quarantine, rollback markers
```

`<data-root>` 只能由 `DataRootResolver` 产生。`AISC_DATA_ROOT` 必须是绝对路径且通过权限和 containment 校验；生产安装默认不允许把它指向 workspace。

## Legacy layout 实测清单（fresh 初始化）

来源：用户提供的标准初始化 workspace 实例（2026-08-17，初始化后未执行任何操作）。路径以 `<workspace>` 脱敏。

```text
<workspace>/
  .aisc/                                # ~8KB / 3 文件 — AISC CLI 状态
    containers.json
    .containers.lock
    workspace-locks/<sha256-hex>.lock   # 现行 hash 为裸 64 位 hex，无版本前缀
  .claude/                              # ~43MB / 2171 文件 — 工厂态整体复制
    CLAUDE.md config.json settings.json settings.local.json
    backups/ commands/ plugins/ projects/ sessions/ skills/
  .codex/                               # ~13MB / 479 文件
    config.toml AGENTS.md .factory-version skills/
  .cc-switch/                           # ~13MB / 479 文件
    cc-switch.db cc-switch.db-shm cc-switch.db-wal cc-switch.db.init.lock
    settings.json session-scan-cache.db skills/
    .aisc-bundled-skills.{lock,sha256} .aisc-preset-providers-{claude,codex}.sha256
    state-mutation.lock
  .local/state/cc-switch/               # cc-switchd 运行态
    cc-switchd.log runtime/daemon.pid
```

设计相关观察：

- `.cc-switch` 含 **live SQLite（db+wal+shm）**：迁移前必须确认 daemon 停止/无写入者，迁移与锁的顺序要先于复制；
- `.local/state/cc-switch/runtime/daemon.pid` 表明 cc-switch daemon 把运行态也写进 workspace；
- `.claude/projects`、`.claude/sessions`、`.claude/backups` 是运行期会话数据，初始化即存在目录骨架；
- 三个大目录（.claude/.codex/.cc-switch）的 skills/ 内容高度重复（同一批 bundled skills 复制三份）。

## Migration manifest

```json
{
  "schema": "aisc.data-migration/v1",
  "workspace_hash": "sha256-v1:...",
  "source": "C:\\...\\workspace\\.aisc",
  "target": "C:\\...\\AISC\\data\\workspaces\\...",
  "entries": [{"relative":"config.json","sha256":"...","status":"copied"}],
  "state": "prepared|committed|rolled_back|quarantined"
}
```

迁移按 known-owned allowlist 执行。先复制到临时目录并校验 hash，再原子提交；source 只在用户确认且 target 完整后改名为 redirect marker。未知文件不删除。

## 生命周期

- `resolve`：只读返回 root、workspace hash、schema 和 legacy findings；
- `prepare`：创建目录、锁和 manifest；
- `commit`：原子替换、刷新 redirect、释放锁；
- `rollback`：只恢复本次 manifest 触及的目标；
- `quarantine`：冲突/损坏移入 migration quarantine，不覆盖源文件。

所有写入使用 UTF-8、临时同目录文件、flush/fsync（Windows 对应 API）和 replace；读者看不到半成品。
