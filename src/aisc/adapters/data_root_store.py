"""Unified data-root storage adapter (Stage 7, 7b).

One directory/lock/atomic API for every writer that moves under the data
root (state, config, artifact metadata, diagnostics; wiring happens in 7e).
Semantics come from the proven predecessors and are unified here:

- directories: idempotent ``prepare`` creates the contract skeleton exactly
  (no invented siblings), every write re-checks the target chain for
  reparse points (TOCTOU defense on top of the resolver's resolve-time
  validation);
- locks: cross-process fail-closed byte lock (``msvcrt``/``fcntl``,
  ``container_registry._registry_lock`` semantics) parked under
  ``state/locks/`` per the domain contract;
- atomic writes: UTF-8, temp file in the target directory, flush + fsync,
  ``os.replace`` (``_write_registry_unlocked`` semantics) — readers never
  see half-written files;
- corruption: a failing JSON read is isolated to ``*.corrupt`` (Rust
  ``storage.rs``/``settings.rs`` precedent), never truncated in place.

The store never decides WHAT to store — schema/version handling stays with
each feature module.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from aisc.domain.artifacts import validate_relative_path
from aisc.domain.data_root import (
    ERR_LOCK_TIMEOUT,
    ERR_REPARSE_POINT,
    LOCKS_SUBDIR,
    SHARED_SUBDIRS,
    WORKSPACE_SUBDIRS,
    ResolvedDataRoot,
)
from aisc.domain.models import CliError

SCOPE_SHARED = "shared"
SCOPE_WORKSPACE = "workspace"

_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400  # windows.h


def _is_reparse_point(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _check_reparse_chain(root: Path, target: Path) -> None:
    """Reject reparse points on any EXISTING segment between *root* and
    *target* (defense-in-depth: the resolver validated at resolve time)."""
    cur = target
    stop = root
    while True:
        if _is_reparse_point(cur):
            raise CliError(
                f"data root path component is a reparse point/symlink: {cur}",
                exit_code=1,
                error_code=ERR_REPARSE_POINT,
            )
        if cur == stop:
            return
        parent = cur.parent
        if parent == cur:
            return  # target outside root: reject via containment first
        cur = parent


@contextmanager
def file_lock(
    lock_path: "Path | str",
    timeout: float = 10.0,
    *,
    error_code: str = ERR_LOCK_TIMEOUT,
) -> Iterator[None]:
    """Hold a cross-process lock across a complete read-modify-write cycle.

    Fail-closed (bounded retry on Windows ``msvcrt.locking``; ``fcntl.flock``
    with SIGALRM timeout on POSIX). Raises CliError(*error_code*) on timeout
    — callers with legacy code contracts (e.g. STATE_LOCK_TIMEOUT at 7e
    wiring time) pass their own ``error_code``.
    """
    import time as time_module

    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = None
    locked = False

    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)

        if sys.platform == "win32":
            import msvcrt

            start_time = time_module.time()
            while True:
                try:
                    msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError as exc:
                    if time_module.time() - start_time >= timeout:
                        raise CliError(
                            f"lock timeout after {timeout}s: {lock_path}",
                            exit_code=1,
                            error_code=error_code,
                        ) from exc
                    time_module.sleep(0.1)
        else:
            import fcntl
            import signal

            def _timeout(signum: Any, frame: Any) -> None:
                raise CliError(
                    f"lock timeout after {timeout}s: {lock_path}",
                    exit_code=1,
                    error_code=error_code,
                )

            alarm_set = False
            old_handler = None
            try:
                old_handler = signal.signal(signal.SIGALRM, _timeout)
                signal.alarm(int(timeout) + 1)
                alarm_set = True
            except ValueError:
                pass  # not in main thread: fall back to blocking lock

            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                locked = True
            finally:
                if alarm_set:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)

        yield
    finally:
        if locked and lock_fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass


class DataRootStore:
    """Directory + lock + atomic-write API over one resolved data root."""

    def __init__(self, resolved: ResolvedDataRoot) -> None:
        self._resolved = resolved

    # -- paths ------------------------------------------------------------

    def _scope_base(self, scope: str) -> Path:
        if scope == SCOPE_SHARED:
            return self._resolved.root
        if scope == SCOPE_WORKSPACE:
            return self._resolved.workspace_dir
        raise ValueError(f"unknown scope: {scope!r}")

    def path_for(self, scope: str, rel: str) -> Path:
        """Validated absolute path: *rel* is a forward-slash relative path
        (no ``..``/absolute/backslash — ``domain.artifacts`` validator)."""
        normalized = validate_relative_path(rel)
        base = self._scope_base(scope)
        target = base / Path(*normalized.split("/"))
        if not (target == base or base in target.parents):
            raise ValueError(f"path escapes the {scope} tree: {rel!r}")
        return target

    def locks_dir(self) -> Path:
        return self._resolved.root.joinpath(*LOCKS_SUBDIR.split("/"))

    def lock_path_for(self, name: str, *, scope: str = SCOPE_SHARED) -> Path:
        """Lock file under ``state/locks/``; workspace-scoped locks get the
        workspace-hash prefix so both live in the contract's locks dir."""
        normalized = validate_relative_path(name)
        if scope == SCOPE_WORKSPACE:
            hash_dir = self._resolved.workspace_hash.replace(":", "-", 1)
            normalized = f"{hash_dir}-{normalized}"
        elif scope != SCOPE_SHARED:
            raise ValueError(f"unknown scope: {scope!r}")
        return self.locks_dir() / (normalized + ".lock")

    # -- lifecycle ----------------------------------------------------------

    def prepare(self) -> None:
        """Idempotently create the contract skeleton (shared + workspace
        subtrees + ``state/locks``); the resolver stays read-only, this is
        the lifecycle 'prepare' step."""
        targets = list(self._resolved.shared_dirs.values())
        targets.append(self._resolved.workspace_dir)
        targets.extend(self._resolved.workspace_dirs.values())
        targets.append(self.locks_dir())
        for target in targets:
            _check_reparse_chain(self._resolved.root, target)
            target.mkdir(parents=True, exist_ok=True)

    # -- locks ---------------------------------------------------------------

    @contextmanager
    def lock(
        self,
        name: str,
        timeout: float = 10.0,
        *,
        scope: str = SCOPE_SHARED,
        error_code: str = ERR_LOCK_TIMEOUT,
    ) -> Iterator[None]:
        with file_lock(self.lock_path_for(name, scope=scope), timeout, error_code=error_code):
            yield

    # -- atomic writes ---------------------------------------------------------

    def write_text(self, scope: str, rel: str, text: str, *, lock: Optional[str] = None) -> None:
        def _do_write() -> None:
            path = self.path_for(scope, rel)
            _check_reparse_chain(self._resolved.root, path.parent)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=f".{path.name}_", dir=str(path.parent), text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, str(path))
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

        if lock is not None:
            with self.lock(lock):
                _do_write()
        else:
            _do_write()

    def write_json(
        self, scope: str, rel: str, data: Any, *, lock: Optional[str] = None
    ) -> None:
        payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        self.write_text(scope, rel, payload, lock=lock)

    # -- reads (missing → None; corrupt → isolate, never truncate) -------------

    def read_text(self, scope: str, rel: str) -> Optional[str]:
        path = self.path_for(scope, rel)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def read_json(self, scope: str, rel: str) -> Optional[Any]:
        path = self.path_for(scope, rel)
        text = self.read_text(scope, rel)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Isolate (rename preserves bytes, nothing truncated) and fail
            # closed: the caller sees "absent", never a guessed value.
            corrupt = path.with_name(path.name + ".corrupt")
            try:
                os.replace(path, corrupt)
            except OSError:
                pass
            return None
