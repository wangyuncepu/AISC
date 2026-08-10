# Pipe Session Plan: Bypass ConPTY for Interactive Sessions

## Problem
ConPTY causes encoding garbling (fixed GBK codepage), character width misalignment
(Unicode width tables), slow response (console model overhead), and visible refresh
(VT regeneration). These are fundamental to the ConPTY layer and cannot be fixed
while the sidecar's stdin/stdout go through it.

## Solution
Replace ConPTY with plain pipes for the sidecar. Container UTF-8 bytes flow directly
to xterm.js with zero console processing.

## Changes

### 1. pty.rs — Add `spawn_pipe_session` + modify `PtySession`

**PtySession struct** — make `master` optional, replace `killer` with closure:
```rust
pub struct PtySession {
    writer_tx: mpsc::Sender<Vec<u8>>,
    master: Option<Arc<Mutex<Box<dyn MasterPty + Send>>>>,  // None in pipe mode
    resize_file: Option<PathBuf>,                            // Some in pipe mode
    kill_fn: Arc<dyn Fn() + Send + Sync>,                   // replaces killer
    cancel: CancellationToken,
}
```

**`resize()`** — check `resize_file` first (write `"<cols> <rows>\n"`), else `master.resize()`.

**`force_kill()`** — call `self.kill_fn()`.

**`spawn_pipe_session(executable, argv, cols, rows, event_tx)`**:
1. Create temp file `aisc-resize-<pid>-<counter>.txt`, write initial `"<cols> <rows>\n"`
2. `Command::new(executable).args(argv)`
   - `.env("AISC_RESIZE_FILE", &path)`
   - `.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null())`
   - Windows: `creation_flags(CREATE_NO_WINDOW)`
3. Extract `child.stdin`, `child.stdout`, `child.id()` (PID for kill)
4. Reader task: `stdout.read()` -> base64 -> `PtyEvent::Output` (same as pty reader)
5. Writer task: drain mpsc -> `stdin.write_all()` (same as pty writer)
6. Wait task: `child.wait()` -> `PtyEvent::Exit` (same as pty wait)
7. `kill_fn`: Windows `taskkill /PID /T /F`, Unix `kill -9`
8. Return `(PtySession { master: None, resize_file: Some(path), kill_fn, ... }, signal)`

**`spawn_pty_session`** — unchanged except struct construction (master: Some, resize_file: None, kill_fn wraps existing killer).

### 2. session.rs — One-line change

Line 319: `spawn_pty_session` → `spawn_pipe_session`.

### 3. docker_.py — Simplify `open_interactive`

**Remove**: `terminal_size()`, `watch_resize()`, `_forward_console_input()`,
all ctypes/WriteConsoleW/SetConsoleOutputCP/SetConsoleMode/transcoding code.

**New `drain()`**: `os.write(1, chunk)` — raw bytes, no processing.

**New `forward()`**: `os.read(0, 4096)` → `sock.sendall()` — raw bytes, no console.

**New resize thread**: poll `AISC_RESIZE_FILE` env var every 100ms, call `exec_resize`
on change. Initial `exec_resize` called before threads start (from file content).

### 4. Rebuild
- `cargo build` (Rust changes)
- PyInstaller (Python changes)
- Sync sidecar to dist/binaries/target/debug

## What This Fixes
1. ✅ Icons/emoji: raw UTF-8 to xterm.js (no GBK transcoding)
2. ✅ Enter key: raw pipe input (no ConPTY translation)
3. ✅ Speed: no console model overhead, no transcoding
4. ✅ Terminal size: correct initial size from resize file
5. ✅ Refresh: TUI's original VT sequences pass through directly

## Risk
- `PtySession` struct change affects pty tests — but tests don't access fields directly
- Resize file polling adds 100ms latency — acceptable for resize
- Temp file cleanup — best-effort delete on session close
