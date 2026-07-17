"""Windows config reader — ctypes kernel32, injectable backend."""

from __future__ import annotations

import ctypes as _ct
import ctypes.wintypes as _wt
import os as _os
from pathlib import Path

from aisc.adapters.config_reader import MAX_FILE_BYTES, ReadError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GENERIC_READ = 0x80000000
FILE_READ_ATTRIBUTES = 0x0080
SHARE_RWD = 7
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
FILE_ATTRIBUTE_DIRECTORY = 0x0010
FILE_TYPE_UNKNOWN = 0x0000
FILE_TYPE_DISK = 0x0001
FILE_TYPE_CHAR = 0x0002
FILE_TYPE_PIPE = 0x0003

ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32

# ---------------------------------------------------------------------------
# Custom ABI — _FILETIME + _BY_HANDLE_FILE_INFO
# ---------------------------------------------------------------------------

class _FILETIME(_ct.Structure):
    _fields_ = [("dwLowDateTime", _ct.c_uint32),
                ("dwHighDateTime", _ct.c_uint32)]

class _BY_HANDLE_FILE_INFO(_ct.Structure):
    _fields_ = [
        ("dwFileAttributes",     _ct.c_uint32),       # offset 0
        ("ftCreationTime",       _FILETIME),           # offset 4
        ("ftLastAccessTime",     _FILETIME),           # offset 12
        ("ftLastWriteTime",      _FILETIME),           # offset 20
        ("dwVolumeSerialNumber", _ct.c_uint32),        # offset 28
        ("nFileSizeHigh",        _ct.c_uint32),        # offset 32
        ("nFileSizeLow",         _ct.c_uint32),        # offset 36
        ("nNumberOfLinks",       _ct.c_uint32),        # offset 40
        ("nFileIndexHigh",       _ct.c_uint32),        # offset 44
        ("nFileIndexLow",        _ct.c_uint32),        # offset 48
    ]  # total sizeof = 52


# ---------------------------------------------------------------------------
# Unified error mapping
# ---------------------------------------------------------------------------

def _raise_win_error(code: int, operation: str):
    if code in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
        raise FileNotFoundError(f"{operation} failed")
    if code in (ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION):
        raise PermissionError(f"{operation} failed")
    raise OSError(f"{operation} failed")


# ---------------------------------------------------------------------------
# Production backend
# ---------------------------------------------------------------------------

class _RealBackend:
    def __init__(self):
        k = _ct.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = _wt.HANDLE
        k.CreateFileW.argtypes = [_wt.LPCWSTR, _wt.DWORD, _wt.DWORD,
                                   _wt.LPVOID, _wt.DWORD, _wt.DWORD, _wt.HANDLE]
        k.CloseHandle.restype = _wt.BOOL
        k.CloseHandle.argtypes = [_wt.HANDLE]
        k.ReadFile.restype = _wt.BOOL
        k.ReadFile.argtypes = [_wt.HANDLE, _wt.LPVOID, _wt.DWORD,
                                _ct.POINTER(_wt.DWORD), _wt.LPVOID]
        k.GetFileType.restype = _wt.DWORD
        k.GetFileType.argtypes = [_wt.HANDLE]
        k.GetFileInformationByHandle.restype = _wt.BOOL
        k.GetFileInformationByHandle.argtypes = [_wt.HANDLE, _ct.POINTER(_BY_HANDLE_FILE_INFO)]
        self._k = k
        self._invalid = _ct.c_void_p(-1).value

    def CreateFileW(self, path: str, access: int, share: int,
                    security: int, creation: int, flags: int, template: int) -> int:
        return self._k.CreateFileW(path, access, share, None, creation, flags, None)

    def CloseHandle(self, handle: int) -> bool:
        return bool(self._k.CloseHandle(handle))

    def ReadFile(self, handle: int, size: int) -> bytes:
        buf = _ct.create_string_buffer(size)
        nread = _wt.DWORD(0)
        if not self._k.ReadFile(handle, buf, size, _ct.byref(nread), None):
            _raise_win_error(_ct.get_last_error(), "ReadFile")
        return buf.raw[:nread.value]

    def GetFileType(self, handle: int) -> int:
        return self._k.GetFileType(handle)

    def GetFileAttributes(self, handle: int) -> int:
        info = _BY_HANDLE_FILE_INFO()
        if not self._k.GetFileInformationByHandle(handle, _ct.byref(info)):
            _raise_win_error(_ct.get_last_error(), "GetFileInformationByHandle")
        return info.dwFileAttributes

    def GetLastError(self) -> int:
        return _ct.get_last_error()

    @property
    def INVALID_HANDLE_VALUE(self) -> int:
        return self._invalid


# ---------------------------------------------------------------------------
# Injectable backend
# ---------------------------------------------------------------------------

_backend = None

def _get_backend():
    global _backend
    if _backend is None:
        _backend = _RealBackend()
    return _backend

def set_backend(b) -> None:
    global _backend
    _backend = b


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_invalid(h: int, back) -> bool:
    return h == back.INVALID_HANDLE_VALUE


def _win_open_component(path: str, back, access: int, share: int, flags: int) -> None:
    h = back.CreateFileW(path, access, share, 0, OPEN_EXISTING, flags, 0)
    if _is_invalid(h, back):
        _raise_win_error(back.GetLastError(), "CreateFileW")
    primary = None
    try:
        attrs = back.GetFileAttributes(h)
        if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
            raise ReadError("structural_error", "Config component is a reparse point")
        if not (attrs & FILE_ATTRIBUTE_DIRECTORY):
            raise ReadError("structural_error", "Config component is not a directory")
    except Exception as exc:
        primary = exc
        raise
    finally:
        ok = back.CloseHandle(h)
        if not ok and primary is None:
            _raise_win_error(back.GetLastError(), "CloseHandle")


def _win_open_final(path: str, back) -> int:
    h = back.CreateFileW(path, GENERIC_READ | FILE_READ_ATTRIBUTES, SHARE_RWD,
                         0, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, 0)
    if _is_invalid(h, back):
        _raise_win_error(back.GetLastError(), "CreateFileW")
    return h


def _split_parents(fp: str) -> list:
    fp = fp.replace("/", "\\")
    for comp in fp.split("\\"):
        if comp in (".", ".."):
            raise ReadError("structural_error", "Path contains . or .. component")
    if fp.startswith("\\\\"):
        parts = fp.split("\\")
        if len(parts) < 5:
            raise ReadError("structural_error", "Invalid UNC path")
        root = f"\\\\{parts[2]}\\{parts[3]}"
        rest = parts[4:]
    elif len(fp) >= 2 and fp[1] == ":":
        if len(fp) == 2 or (len(fp) > 2 and fp[2] != "\\"):
            raise ReadError("structural_error", "Drive-relative path not allowed")
        root = fp[:2] + "\\"
        rest = fp[3:].split("\\") if len(fp) > 3 else []
    else:
        raise ReadError("structural_error", "Unsupported path format")
    if not rest:
        raise ReadError("structural_error", "Path has no file component")
    result = [root]
    accum = root
    for comp in rest:
        if not comp:
            continue
        accum = (accum + comp) if accum.endswith("\\") else (accum + "\\" + comp)
        result.append(accum)
    if result:
        result.pop()
    return result


def _win_safe_read(file_path: Path) -> bytes:
    back = _get_backend()
    fp = str(file_path)
    if not _os.path.isabs(fp) and not (len(fp) >= 2 and fp[1] == ":"):
        raise ReadError("structural_error", "Path must be absolute")

    parents = _split_parents(fp)
    for parent in parents:
        _win_open_component(parent, back, FILE_READ_ATTRIBUTES, SHARE_RWD,
                            FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS)

    h = _win_open_final(fp, back)
    primary = None
    try:
        attrs = back.GetFileAttributes(h)
        if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
            raise ReadError("structural_error", "Config file is a reparse point")
        if attrs & FILE_ATTRIBUTE_DIRECTORY:
            raise ReadError("structural_error", "Config file is a directory")
        ftype = back.GetFileType(h)
        if ftype == FILE_TYPE_UNKNOWN:
            if back.GetLastError() != 0:
                _raise_win_error(back.GetLastError(), "GetFileType")
            raise ReadError("structural_error", "Config file is not a disk file")
        if ftype != FILE_TYPE_DISK:
            raise ReadError("structural_error", "Config file is not a disk file")
        chunks = []
        total = 0
        while total <= MAX_FILE_BYTES:
            chunk = back.ReadFile(h, 4096)
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
        ok = back.CloseHandle(h)
        if not ok and primary is None:
            _raise_win_error(back.GetLastError(), "CloseHandle")
