"""serve fs.* ops — the remote-authoritative file plane (2.1.10 R3, D-9).

Every path is interpreted ON THE MACHINE THE SERVE PROCESS RUNS ON. The
Workbench never keeps a local copy: browsing, preview and writes all ride
these ops over the serve channel; watch events ride the reserved ``event``
frame.

Containment: paths are normalized (``..`` resolved) and rejected unless
inside the op's own root — the F1 browse-pinning lesson, server-side now.
watchdog is imported lazily; without it ``fs.watch`` degrades to a clean
"unsupported" error and the Workbench falls back to list polling (D-9).
"""

from __future__ import annotations

import os
import posixpath
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from aisc.domain.models import CliError

#: Page size aligned with the Workbench's Explorer cursor protocol (Rust
#: LIST_PAGE = 200).
LIST_PAGE = 200

#: Read budget aligned with the Workbench preview budget (512 KiB).
READ_BUDGET = 512 * 1024

#: Server-side ignore set — the equivalent of the Rust DEFAULT_IGNORE +
#: temp-file filter, so remote trees look exactly like local ones.
IGNORE_NAMES = {
    ".git", ".aisc", ".claude", ".codex", ".cc-switch", ".local",
    ".mcp.json", "node_modules", "target", "build", "dist", "tmp", "temp",
    "__pycache__", ".venv", "venv",
}


def _is_temp_name(name: str) -> bool:
    lower = name.lower()
    return (
        ".tmp." in lower
        or lower.endswith((".tmp", ".temp", "~", ".swp", ".swo", ".aisc-tmp"))
        or lower.startswith((".#", "~$"))
    )


def _ignored(name: str) -> bool:
    return name in IGNORE_NAMES or _is_temp_name(name)


def _resolve(root: str, rel: str) -> str:
    """Resolve a ROOT-RELATIVE path (the Explorer's relativePath concept)
    to a normalized absolute path inside *root*. Absolute-looking input and
    `..` escapes are rejected — containment is server-side."""
    root = posixpath.normpath(root)
    rel = rel or ""
    if rel.startswith("/") or rel.startswith("~"):
        # Absolute/home paths are NOT rooted — reject before stripping so
        # "/etc/passwd" can never silently become "<root>/etc/passwd".
        raise CliError(message=f"path must be relative to the workspace root: {rel!r}",
                       exit_code=2, error_code="AISC_ERR_FS_PATH")
    rel = rel.strip("/")
    if not rel:
        return root
    joined = posixpath.normpath(posixpath.join(root, rel))
    if joined != root and not joined.startswith(root.rstrip("/") + "/"):
        raise CliError(message=f"path escapes the workspace root: {rel!r}",
                       exit_code=2, error_code="AISC_ERR_FS_CONTAINMENT")
    return joined


def _rel(root: str, abs_path: str) -> str:
    root = posixpath.normpath(root).rstrip("/")
    rel = abs_path[len(root):].lstrip("/")
    return rel


# ---------------------------------------------------------------------------
# ops (uniform serve signature: (ns, payload, runtime) -> (data, exit, errs))


def op_fs_list(_ns, payload: Dict[str, Any], _runtime) -> Tuple[Any, int, list]:
    root = str(payload.get("root") or "/")
    target = _resolve(root, str(payload.get("path") or ""))
    if not os.path.isdir(target):
        raise CliError(message=f"not a directory: {payload.get('path') or '/'}",
                       exit_code=1, error_code="AISC_ERR_FS_NOT_DIR")
    try:
        names = sorted(os.listdir(target))
    except OSError as exc:
        raise CliError(message=f"listdir failed: {exc}", exit_code=1,
                       error_code="AISC_ERR_FS_IO") from exc
    offset = int(payload.get("offset") or 0)
    page = names[offset:offset + LIST_PAGE]
    entries = []
    for name in page:
        if _ignored(name):
            continue
        full = os.path.join(target, name)
        try:
            st = os.stat(full, follow_symlinks=False)
            kind = "dir" if os.path.isdir(full) else "file"
            entries.append({"name": name, "kind": kind, "size": st.st_size,
                            "modified": int(st.st_mtime)})
        except OSError:
            entries.append({"name": name, "kind": "file", "size": 0, "modified": 0})
    data: Dict[str, Any] = {"entries": entries}
    if offset + LIST_PAGE < len(names):
        data["nextOffset"] = offset + LIST_PAGE
    return data, 0, []


def op_fs_read(_ns, payload: Dict[str, Any], _runtime) -> Tuple[Any, int, list]:
    import base64

    root = str(payload.get("root") or "/")
    target = _resolve(root, str(payload.get("path") or ""))
    budget = int(payload.get("maxBytes") or READ_BUDGET)
    try:
        st = os.stat(target)
    except OSError as exc:
        raise CliError(message=f"stat failed: {exc}", exit_code=1,
                       error_code="AISC_ERR_FS_IO") from exc
    if os.path.isdir(target):
        raise CliError(message="path is a directory", exit_code=1,
                       error_code="AISC_ERR_FS_IS_DIR")
    truncated = st.st_size > budget
    with open(target, "rb") as f:
        blob = f.read(budget)
    return {
        "base64": base64.b64encode(blob).decode("ascii"),
        "size": st.st_size,
        "truncated": truncated,
        "modified": int(st.st_mtime),
    }, 0, []


def op_fs_write(_ns, payload: Dict[str, Any], _runtime) -> Tuple[Any, int, list]:
    import base64

    root = str(payload.get("root") or "/")
    target = _resolve(root, str(payload.get("path") or ""))
    blob = base64.b64decode(str(payload.get("base64") or ""))
    atomic = _atomic_writer(target, blob)
    if atomic is not None:
        raise atomic
    return {"bytes": len(blob)}, 0, []


def _atomic_writer(target: str, blob: bytes) -> Optional[CliError]:
    try:
        tmp = target + ".aisc-tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, target)
        return None
    except OSError as exc:
        try:
            os.unlink(target + ".aisc-tmp")
        except OSError:
            pass
        return CliError(message=f"write failed: {exc}", exit_code=1,
                        error_code="AISC_ERR_FS_IO")


def op_fs_mkdir(_ns, payload: Dict[str, Any], _runtime) -> Tuple[Any, int, list]:
    root = str(payload.get("root") or "/")
    target = _resolve(root, str(payload.get("path") or ""))
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        raise CliError(message=f"mkdir failed: {exc}", exit_code=1,
                       error_code="AISC_ERR_FS_IO") from exc
    return {}, 0, []


def op_fs_rename(_ns, payload: Dict[str, Any], _runtime) -> Tuple[Any, int, list]:
    root = str(payload.get("root") or "/")
    src = _resolve(root, str(payload.get("from") or ""))
    dst = _resolve(root, str(payload.get("to") or ""))
    try:
        os.replace(src, dst)
    except OSError as exc:
        raise CliError(message=f"rename failed: {exc}", exit_code=1,
                       error_code="AISC_ERR_FS_IO") from exc
    return {}, 0, []


def op_fs_delete(_ns, payload: Dict[str, Any], _runtime) -> Tuple[Any, int, list]:
    root = str(payload.get("root") or "/")
    target = _resolve(root, str(payload.get("path") or ""))
    if target == posixpath.normpath(root):
        raise CliError(message="refusing to delete the workspace root",
                       exit_code=2, error_code="AISC_ERR_FS_CONTAINMENT")
    try:
        if os.path.isdir(target):
            import shutil

            shutil.rmtree(target)
        else:
            os.unlink(target)
    except OSError as exc:
        raise CliError(message=f"delete failed: {exc}", exit_code=1,
                       error_code="AISC_ERR_FS_IO") from exc
    return {}, 0, []


# ---------------------------------------------------------------------------
# watch (watchdog, lazy) — events ride the reserved `event` frame


class WatchRegistry:
    """One watchdog observer per serve process; per-root handlers batch
    events (100ms debounce) into a single fs.change frame per burst."""

    def __init__(self, emit: Callable[[Dict[str, Any]], None]) -> None:
        self._emit_cb = emit
        self._lock = threading.Lock()
        self._observer: Any = None
        self._roots: Dict[str, Any] = {}
        self._pending: Dict[str, Dict[str, Tuple[str, str]]] = {}  # root -> {abspath: (change, kind)}
        self._flush_timer: Optional[threading.Timer] = None

    def _emit(self, frame: Dict[str, Any]) -> None:
        try:
            self._emit_cb(frame)
        except Exception:  # noqa: BLE001 — emit must never kill the watcher
            pass

    def available(self) -> bool:
        try:
            import watchdog  # noqa: F401

            return True
        except ImportError:
            return False

    def watch(self, root: str) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError as exc:
            raise CliError(message="fs.watch unsupported: watchdog unavailable",
                           exit_code=3, error_code="AISC_ERR_FS_WATCH_UNSUPPORTED") from exc
        root = posixpath.normpath(root)
        if not os.path.isdir(root):
            raise CliError(message=f"not a directory: {root}",
                           exit_code=1, error_code="AISC_ERR_FS_NOT_DIR")
        with self._lock:
            if root in self._roots:
                return
            if self._observer is None:
                self._observer = Observer()
                self._observer.start()

            reg = self

            # watchdog event_type -> the Workbench change vocabulary
            # (notify's classification). moved: from-half reports deleted,
            # to-half reports created — the same semantics as the local
            # watcher's rename handling (Stage 11).
            def _change_type(event: Any) -> str:
                et = getattr(event, "event_type", "")
                return {
                    "created": "created",
                    "deleted": "deleted",
                    "modified": "modified",
                    "moved": "created",
                    "closed": "modified",
                }.get(et, "modified")

            class Handler(FileSystemEventHandler):
                def on_any_event(self, event: Any) -> None:
                    path = getattr(event, "dest_path", None) or event.src_path
                    if not path:
                        return
                    name = os.path.basename(str(path))
                    if _ignored(name):
                        return
                    kind = "dir" if event.is_directory else "file"
                    reg._record(root, str(path), kind, _change_type(event))

            watch = self._observer.schedule(Handler(), root, recursive=True)
            self._roots[root] = watch

    def unwatch(self, root: str) -> None:
        root = posixpath.normpath(root)
        with self._lock:
            watch = self._roots.pop(root, None)
            if watch is not None and self._observer is not None:
                self._observer.unschedule(watch)
            if not self._roots and self._observer is not None:
                self._observer.stop()
                self._observer = None

    def _record(self, root: str, abs_path: str, kind: str, change: str) -> None:
        with self._lock:
            # last-write-wins on the change type; created is sticky so a
            # create+write burst surfaces as "created" (batcher parity)
            prev = self._pending.get(root, {}).get(abs_path)
            if prev == ("created", kind):
                change = "created"
            self._pending.setdefault(root, {})[abs_path] = (change, kind)
            if self._flush_timer is None:
                self._flush_timer = threading.Timer(0.1, self._flush)
                self._flush_timer.daemon = True
                self._flush_timer.start()

    def _flush(self) -> None:
        with self._lock:
            self._flush_timer = None
            batches = self._pending
            self._pending = {}
        for root, paths in batches.items():
            self._emit({
                "type": "event",
                "event": "fs.change",
                "data": {
                    "root": root,
                    "paths": [
                        {"path": p, "change": c, "kind": k}
                        for p, (c, k) in sorted(paths.items())
                    ],
                },
            })

    def shutdown(self) -> None:
        # Grace for in-flight inotify callbacks (events land a few ms after
        # the op result frame), then flush any debounced batch BEFORE
        # stopping — the serve loop's EOF teardown would drop the last burst
        # otherwise.
        time.sleep(0.15)
        if self._flush_timer is not None:
            self._flush_timer.cancel()
        self._flush()
        with self._lock:
            obs, self._observer = self._observer, None
            self._roots.clear()
        if obs is not None:
            obs.stop()


def op_fs_watch(_ns, payload: Dict[str, Any], runtime) -> Tuple[Any, int, list]:
    root = str(payload.get("root") or "")
    if not root.startswith("/"):
        raise CliError(message="fs.watch requires an absolute root",
                       exit_code=2, error_code="AISC_ERR_FS_PATH")
    runtime.fs_watches.watch(root)
    return {"root": posixpath.normpath(root)}, 0, []


def op_fs_unwatch(_ns, payload: Dict[str, Any], runtime) -> Tuple[Any, int, list]:
    root = posixpath.normpath(str(payload.get("root") or "/"))
    runtime.fs_watches.unwatch(root)
    return {}, 0, []


OPS: Dict[str, Callable[..., Tuple[Any, int, list]]] = {
    "fs.list": op_fs_list,
    "fs.read": op_fs_read,
    "fs.write": op_fs_write,
    "fs.mkdir": op_fs_mkdir,
    "fs.rename": op_fs_rename,
    "fs.delete": op_fs_delete,
    "fs.watch": op_fs_watch,
    "fs.unwatch": op_fs_unwatch,
}
