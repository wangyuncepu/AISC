# Stage 9 领域契约

## Solution layout

```text
workbench-csharp/
  Aisc.Workbench.sln
  src/
    Aisc.Workbench.WinUI/       # App, windows, navigation, resources
    Aisc.Workbench.Core/        # state machines, lifecycle, view models
    Aisc.Workbench.Protocol/    # aisc.cli/v1 and provider protocol DTOs
    Aisc.Workbench.Windows/     # process, PTY/native terminal, paths, job objects
  tests/
    Aisc.Workbench.Core.Tests/
    Aisc.Workbench.Protocol.Tests/
    Aisc.Workbench.Windows.Tests/
```

## Ownership

- `Core` 只保存 UI projection、operation state 和 cancellation；
- `Protocol` 只序列化/验证 versioned JSON envelope，不包含 Docker 或 Provider 规则；
- `Windows` 负责 process/pipe/PTY、DataRootResolver bridge、native terminal control、DPI 和 Windows job object；
- `WinUI` 负责视图、tab、菜单、focus/accessibility 和 redacted error presentation；
- Python CLI/container 继续是 Runtime、Docker、Provider 和 session 事实所有者。

## Functional equivalence matrix

| Tauri 能力 | C# POC 对应 |
|---|---|
| sidecar discovery/JSONL | `Protocol` + `Windows.ProcessRunner` |
| SessionRegistry/tab | `Core.SessionStore` + WinUI tab host |
| PTY terminal | `Windows.TerminalHost` + selected native control |
| data root/diagnostics | CLI command + redacted projection |
| cc-switch TUI tab | existing terminal tab |
| cc-switch Provider UI | `cc-switch-ui` embedded tab, Stage 8 protocol |

任何需要直接访问 Docker socket、SQLite 或 secret 的实现均违反契约。
