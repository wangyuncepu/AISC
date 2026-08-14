# Stage 3 Domain Contract

> 基线：`d2bdcd9`

## Artifact schema v1

```json
{
  "schema_version": 1,
  "artifact_id": "uuid",
  "workspace_relative_path": "reports/result.md",
  "action": "created",
  "kind": "deliverable",
  "media_type": "text/markdown",
  "label": "性能报告",
  "open_with": "preview",
  "producer": {"agent":"claude","session_id":"...","runtime_id":"..."},
  "state": "present",
  "provenance": "manifest",
  "recorded_at": "RFC3339",
  "extra": {}
}
```

枚举：

- `action`: `created|modified|deleted|renamed`；rename 需要 `previous_path`。
- `kind`: `deliverable|source_change|generated_output`。
- `state`: `present|deleted|moved|missing`。
- `provenance`: authoritative 只允许 `manifest`; watcher 使用独立 `workspace_change` read model。
- `open_with`: `preview|system|reveal|none`，仅为建议，不绕过 Rust policy。

## 事实与投影

```text
Agent/Skill → aisc artifact record → session registry
                                      ↓ import/validate
                                Rust artifact index
                                      ↓
                         ArtifactStore / Explorer UI
watcher → WorkspaceChange(stale/unattributed) ──────┘
```

- Artifact record 不依赖 GUI；CLI 独立用户可 list/inspect。
- index 存入 Workbench app-data `<workspace-hash>/<session>.jsonl|json`，不保存 secret。
- watcher 事件不能修改 manifest provenance，只能使路径状态 stale 并触发验证。

## 路径安全

Rust 接收 canonical workspace + relative path：

1. 拒绝空、绝对、带 prefix/root、NUL 和 traversal；
2. join 后 canonicalize；不存在的 deleted path 按父目录 containment 验证；
3. Windows 大小写、UNC、junction 和 symlink 使用同一 identity policy；
4. target 必须仍在 canonical workspace；
5. open/reveal/preview 前再次验证；
6. 文件类型、大小、数量、preview bytes 受预算限制。

## Explorer read model

`WorkspaceNode { relative_path, name, kind, expandable, artifact_badges, change_state }`。目录按需列举；排序目录优先、locale-stable；ignore 默认覆盖 `.git`、依赖/cache/build 大目录，但允许用户显式展开受支持目录。

## IPC

```text
workspace_list(path, cursor)
workspace_open(relative_path, mode)
workspace_preview(relative_path)
artifact_list(filter, cursor)
artifact_inspect(id)
artifact_refresh(id)
workspace_watch_start/stop
```

所有返回有 schema/version、pagination 和稳定错误。