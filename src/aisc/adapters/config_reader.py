"""Safe config file reader — platform dispatch (S5.2)."""

from __future__ import annotations

import json as _json
import os
import stat
from pathlib import Path

MAX_FILE_BYTES = 16 * 1024
MAX_JSON_DEPTH = 20
MAX_JSON_NODES = 2000
MAX_JSON_STRING_BYTES = 8192


class ReadError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Platform dispatch
# ---------------------------------------------------------------------------

def safe_read_config_bytes(file_path: Path) -> bytes:
    if os.name == "nt":
        from aisc.adapters.windows_config_reader import _win_safe_read
        return _win_safe_read(file_path)
    return _posix_safe_read(file_path)


# ---------------------------------------------------------------------------
# Unified validators
# ---------------------------------------------------------------------------

def check_root_exists(root_path: str) -> None:
    """Verify *root_path* exists and is a directory.

    Raises:
      FileNotFoundError — root does not exist at all
      PermissionError — permission denied
      ReadError — exists but is symlink / reparse / not a directory
      OSError — general I/O error

    No second os.path.isdir/lexists fallback needed after this call.
    """
    if os.name == "nt":
        from aisc.adapters.windows_config_reader import (
            _get_backend, _win_open_component,
            FILE_READ_ATTRIBUTES, SHARE_RWD,
            FILE_FLAG_OPEN_REPARSE_POINT, FILE_FLAG_BACKUP_SEMANTICS,
        )
        back = _get_backend()
        flags = FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS
        _win_open_component(root_path, back, FILE_READ_ATTRIBUTES, SHARE_RWD, flags)
        return  # success
    # POSIX
    try:
        st = os.lstat(root_path)
    except FileNotFoundError:
        raise
    except PermissionError:
        raise
    except OSError:
        raise OSError("Cannot access config root")
    if stat.S_ISLNK(st.st_mode):
        raise ReadError("structural_error", "Config root is a symlink")
    if not stat.S_ISDIR(st.st_mode):
        raise ReadError("structural_error", "Config root is not a directory")


def check_dir_component(parent_path: str, name: str) -> None:
    """Verify *parent_path/name* is a directory, not a reparse point.

    Raises:
      FileNotFoundError — component does not exist
      PermissionError — permission denied
      ReadError — exists but reparse / not a directory
      OSError — general error
    """
    full_path = os.path.join(parent_path, name)
    if os.name == "nt":
        from aisc.adapters.windows_config_reader import (
            _get_backend, _win_open_component,
            FILE_READ_ATTRIBUTES, SHARE_RWD,
            FILE_FLAG_OPEN_REPARSE_POINT, FILE_FLAG_BACKUP_SEMANTICS,
        )
        back = _get_backend()
        flags = FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS
        _win_open_component(full_path, back, FILE_READ_ATTRIBUTES, SHARE_RWD, flags)
        return
    # POSIX
    try:
        st = os.lstat(full_path)
    except FileNotFoundError:
        raise
    except PermissionError:
        raise
    except OSError:
        raise OSError("Cannot access config component")
    if stat.S_ISLNK(st.st_mode):
        raise ReadError("structural_error", "Config component is a symlink")
    if not stat.S_ISDIR(st.st_mode):
        raise ReadError("structural_error", "Config component is not a directory")


# ---------------------------------------------------------------------------
# POSIX reader
# ---------------------------------------------------------------------------

def _posix_safe_read(file_path: Path) -> bytes:
    fp = str(file_path)
    try:
        st = os.lstat(fp)
    except FileNotFoundError:
        raise
    except PermissionError:
        raise
    except OSError:
        raise OSError("Cannot access config file")
    if stat.S_ISLNK(st.st_mode):
        raise ReadError("structural_error", "Config file is a symlink")
    if stat.S_ISDIR(st.st_mode):
        raise ReadError("structural_error", "Config file is a directory")
    if not stat.S_ISREG(st.st_mode):
        raise ReadError("structural_error", "Config file is not a regular file")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        fd = os.open(fp, flags)
    except PermissionError:
        raise
    except FileNotFoundError:
        raise
    except OSError:
        raise OSError("Cannot open config file")
    primary = None
    try:
        fd_st = os.fstat(fd)
        if not stat.S_ISREG(fd_st.st_mode):
            raise ReadError("structural_error", "Config file is not a regular file")
        chunks = []
        total = 0
        while total <= MAX_FILE_BYTES:
            try:
                chunk = os.read(fd, 4096)
            except PermissionError:
                raise
            except OSError:
                raise OSError("Cannot read config file")
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise ReadError("structural_error", "Config file exceeds size limit")
        return b"".join(chunks)
    except Exception as exc:
        primary = exc
        raise
    finally:
        _close_fd(fd, primary)


def _close_fd(fd: int, primary: Exception | None) -> None:
    try:
        os.close(fd)
    except OSError:
        if primary is None:
            raise OSError("Failed to close file descriptor")


# ---------------------------------------------------------------------------
# JSON parser
# ---------------------------------------------------------------------------

def _walk_iterative(obj, _path="$"):
    from collections import deque
    q = deque([(obj, "$", 1)]); nc = 0
    while q:
        item, path, depth = q.popleft(); nc += 1
        if nc > MAX_JSON_NODES: raise ValueError("JSON node limit exceeded")
        if depth > MAX_JSON_DEPTH: raise ValueError("JSON nesting too deep")
        if isinstance(item, dict):
            for k, v in item.items():
                if isinstance(k, str) and len(k.encode()) > MAX_JSON_STRING_BYTES:
                    raise ValueError("JSON key too long")
                _cs(v)
                if isinstance(v, (dict,list)): q.append((v,f"{path}.{k}" if path!="$" else f"$.{k}",depth+1))
                else: nc += 1
        elif isinstance(item, list):
            for i, v in enumerate(item):
                _cs(v)
                if isinstance(v, (dict,list)): q.append((v,f"{path}[{i}]",depth+1))
                else: nc += 1
    if nc > MAX_JSON_NODES: raise ValueError("JSON node limit exceeded")

def _cs(v):
    if isinstance(v,str) and len(v.encode())>MAX_JSON_STRING_BYTES: raise ValueError("JSON string too long")

def parse_config_json(raw: bytes) -> dict:
    text = raw.decode("utf-8")
    if len(text) > MAX_FILE_BYTES*4: raise ValueError("Config text too large")
    def _ph(pairs):
        seen=set()
        for k,v in pairs:
            if k in seen: raise ValueError("Duplicate key in JSON object")
            seen.add(k)
            if isinstance(k,str) and len(k.encode())>MAX_JSON_STRING_BYTES:
                raise ValueError("JSON key too long")
        return dict(pairs)
    r = _json.loads(text, object_pairs_hook=_ph)
    if not isinstance(r, dict): raise ValueError("Config must be a JSON object")
    _walk_iterative(r)
    return r
