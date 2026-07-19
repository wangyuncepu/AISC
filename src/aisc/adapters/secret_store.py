"""Secure store adapter — create and validate private directories/files (S5.3).

Provides a narrow stdlib-only API for creating secure directories and
private files with platform-appropriate permissions.

API
---
- ``StorePaths`` — dataclass holding resolved store directory paths.
- ``SecureStorePermissionError`` — raised when security requirements are not met.
- ``resolve_store_paths(platform_name, home, env)`` — pure function, no I/O.
- ``ensure_secure_directory(path)`` — create/validate a secure directory.
  Callers must bootstrap parent directories before calling this on the
  final component.
- ``create_private_file(directory, leaf_name)`` — create a private file,
  returning an int file descriptor (caller must ``os.close``).

Security decisions are based on *fstat* of opened fds (POSIX) or
handle-verified DACL (Windows).  No pathname check-then-create.
"""

from __future__ import annotations

import ctypes as _ct
import ctypes.wintypes as _wt
import os as _os
import posixpath as _posixpath
import ntpath as _ntpath
import stat as _stat
from dataclasses import dataclass

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None


# ============================================================================
# Public types
# ============================================================================


@dataclass(frozen=True)
class StorePaths:
    """Resolved store directory paths for a platform / home combination."""

    config: str
    state: str
    data: str
    secrets: str


class SecureStorePermissionError(PermissionError):
    """Raised when a path or object fails security requirements.

    The adapter never repairs permissions automatically — it always fails
    closed.  Callers should treat this as a hard, non-recoverable error.

    All instances carry a ``cleanup_errors`` attribute — an empty tuple
    unless ``_attach_cleanup_errors`` has appended cleanup failures.
    """

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.cleanup_errors: "tuple[BaseException, ...]" = ()


class SecureStoreResidualError(SecureStorePermissionError):
    """Rollback failed or left a residual object.

    Carries ``primary`` (the original failure) and ``cleanup_errors``
    (close/free/rollback failures encountered during unwinding).
    """

    def __init__(
        self,
        *args: object,
        primary: BaseException | None = None,
        cleanup_errors: "tuple[BaseException, ...]" = (),
    ) -> None:
        super().__init__(*args)
        self.primary = primary
        self.cleanup_errors = cleanup_errors


def _attach_cleanup_errors(
    exc: BaseException,
    errors: "tuple[BaseException, ...]",
) -> BaseException:
    """Append *errors* to *exc* in stable order and return *exc*.

    All exceptions receive a ``cleanup_errors`` attribute (a flat tuple).
    Subsequent calls to this function on the same exception accumulate
    new errors at the end.  This intentionally replaces a prior
    non-empty tuple with the combined one.
    """
    if not errors:
        return exc
    existing: "tuple[BaseException, ...]" = getattr(exc, "cleanup_errors", ())
    exc.cleanup_errors = existing + errors  # type: ignore[attr-defined]
    return exc


def _raise_no_primary_cleanup(
    errors: "tuple[BaseException, ...]",
    operation: str = "",
) -> None:
    """Raise ``SecureStorePermissionError`` for cleanup failures with no
    primary error.
    """
    if not errors:
        return
    msg = f"Cleanup failure{' during ' + operation if operation else ''}: " \
          + "; ".join(str(e) for e in errors)
    exc = SecureStorePermissionError(msg)
    exc.cleanup_errors = errors  # type: ignore[attr-defined]
    raise exc


# ============================================================================
# resolve_store_paths  (pure function — no I/O)
# ============================================================================


def resolve_store_paths(
    platform_name: str,
    home: str,
    env: "dict | None" = None,
) -> StorePaths:
    """Resolve the four standard store directories.

    *platform_name* must be one of ``"linux"``, ``"darwin"``, ``"windows"``.

    *home* is the user home directory; must be an **absolute** path not
    containing ``~``, ``.``, or ``..`` components.

    *env* is an optional ``os.environ``-like mapping.  When omitted the
    real process environment is used.

    Empty-string environment values are treated as *unset* (the fallback
    is used).

    This is a **pure** function — it performs no disk I/O.

    Raises ``ValueError`` for invalid inputs.
    """
    if env is None:
        env = _os.environ

    platform = platform_name.lower()
    _validate_home(home, platform)

    # Select the correct path module based on platform, not host OS
    if platform == "windows":
        _pathmod = _ntpath
    else:
        _pathmod = _posixpath

    if platform == "linux":
        cfg = _env_or(env, "XDG_CONFIG_HOME") or _pathmod.join(home, ".config")
        st_ = _env_or(env, "XDG_STATE_HOME") or _pathmod.join(home, ".local", "state")
        dat = _env_or(env, "XDG_DATA_HOME") or _pathmod.join(home, ".local", "share")
        cfg = _pathmod.join(cfg, "aisc")
        st_ = _pathmod.join(st_, "aisc")
        dat = _pathmod.join(dat, "aisc")
        sec = _pathmod.join(dat, "secrets")  # secrets under DATA, not STATE
    elif platform == "darwin":
        base = _pathmod.join(home, "Library", "Application Support", "aisc")
        cfg = st_ = dat = base
        sec = _pathmod.join(base, "secrets")
    elif platform == "windows":
        appdata = _env_or(env, "APPDATA")
        local = _env_or(env, "LOCALAPPDATA")
        if not appdata:
            raise ValueError("APPDATA is not set")
        if not local:
            raise ValueError("LOCALAPPDATA is not set")
        cfg = _pathmod.join(appdata, "aisc")
        st_ = _pathmod.join(local, "aisc")
        dat = _pathmod.join(local, "aisc")
        sec = _pathmod.join(local, "aisc", "secrets")
        # Normalize to backslashes on non-Windows platforms
        cfg = cfg.replace("/", "\\")
        st_ = st_.replace("/", "\\")
        dat = dat.replace("/", "\\")
        sec = sec.replace("/", "\\")
    else:
        raise ValueError(f"Unsupported platform: {platform_name!r}")

    for p in (cfg, st_, dat, sec):
        _validate_absolute_path(p, platform)

    return StorePaths(config=cfg, state=st_, data=dat, secrets=sec)


# ---------------------------------------------------------------------------
# Path / input validation helpers
# ---------------------------------------------------------------------------


def _validate_home(home: str, platform: str = "linux") -> None:
    if not home:
        raise ValueError("home must be a non-empty absolute path")
    if platform == "windows":
        is_abs = _is_windows_local_drive_absolute(home)
    else:
        is_abs = _os.path.isabs(home)
    if not is_abs:
        raise ValueError(f"home must be absolute: {home!r}")
    if "~" in home:
        raise ValueError(f"home must not contain '~': {home!r}")
    parts = home.replace("\\", "/").split("/")
    for part in parts:
        if part in (".", ".."):
            raise ValueError(f"home must not contain '{part}' component: {home!r}")


def _is_windows_local_drive_absolute(path: str) -> bool:
    """Strict local-drive absolute check: ``C:\\foo`` only.

    Rejects UNC (``\\\\server\\share``), device namespaces
    (``\\\\?\\``, ``\\\\.\\``, ``\\??\\``), NT object namespace,
    drive-relative (``C:relative``), and root-relative (``\\foo``).
    """
    if not path:
        return False
    # Must start with a letter drive, colon, separator
    if len(path) < 3:
        return False
    if not (path[0].isalpha() and path[1] == ":" and path[2] in ("\\", "/")):
        return False
    return True


def _validate_absolute_path(path: str, platform: str = "") -> None:
    """Raise ValueError if *path* is not an absolute safe path."""
    if not path:
        raise ValueError("path must not be empty")
    if platform == "windows":
        if not _is_windows_local_drive_absolute(path):
            raise ValueError(
                f"path must be a strict local drive absolute path: {path!r}"
            )
    elif not _os.path.isabs(path):
        raise ValueError(f"path must be absolute: {path!r}")
    if "~" in path:
        raise ValueError(f"path must not contain '~': {path!r}")
    # Check the ORIGINAL path for . and .. components
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part in (".", ".."):
            raise ValueError(f"path must not contain '{part}' component: {path!r}")


def _env_or(env: dict, key: str) -> str | None:
    """Return env[key] or None when missing / empty string."""
    v = env.get(key)
    if v is None or v == "":
        return None
    return v


def _validate_leaf_name(leaf_name: str, platform: str = "") -> None:
    """Validate *leaf_name* is a simple filename component.

    Rejects: empty, ``.``, ``..``, separators (``/``, ``\\``),
    NUL, ASCII control characters.
    On Windows additionally rejects: ADS colons, trailing dot/space,
    reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9).
    """
    if not leaf_name:
        raise ValueError("leaf_name must not be empty")
    if leaf_name in (".", ".."):
        raise ValueError(f"leaf_name must not be '.' or '..': {leaf_name!r}")
    if "/" in leaf_name or "\\" in leaf_name:
        raise ValueError(f"leaf_name must not contain path separators: {leaf_name!r}")
    if "\x00" in leaf_name:
        raise ValueError("leaf_name must not contain NUL")
    for ch in leaf_name:
        if ord(ch) < 0x20:
            raise ValueError(f"leaf_name contains control character U+{ord(ch):04X}")

    # Windows-specific checks
    if platform == "windows" or (platform == "" and _os.name == "nt"):
        if ":" in leaf_name:
            raise ValueError(f"leaf_name must not contain colon (ADS): {leaf_name!r}")
        if leaf_name.rstrip(" .") != leaf_name:
            raise ValueError(
                f"leaf_name must not have trailing dot/space: {leaf_name!r}"
            )
        # Reject Win32-disallowed characters: < > " | ? *
        for ch in "<>\"|?*":
            if ch in leaf_name:
                raise ValueError(
                    f"leaf_name contains disallowed character {ch!r}: {leaf_name!r}"
                )
        _reserved = {
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        }
        _upper = leaf_name.upper().rstrip(".")
        if _upper in _reserved:
            raise ValueError(
                f"leaf_name is a reserved Windows device name: {leaf_name!r}"
            )
        # Also reject reserved basenames with extensions (CON.txt, NUL.dat, etc.)
        _base = _upper.split(".")[0]
        if _base in _reserved:
            raise ValueError(
                f"leaf_name has reserved Windows device basename: {leaf_name!r}"
            )


# ============================================================================
# Platform dispatch — public functions
# ============================================================================


def ensure_secure_directory(path: str) -> None:
    """Create *path* as a secure directory, or validate an existing one.

    - Creates the directory with owner-only permissions (0700 on POSIX).
    - Validates that an existing directory meets security requirements.
    - Rejects symlinks, insecure modes, and wrong ownership.
    - Raises ``SecureStorePermissionError`` when security cannot be proved.
    - Raises ``ValueError`` for malformed paths.

    **Parent directories must already exist.**  Callers must bootstrap the
    path tree themselves.  Only the final leaf component may be created.
    """
    _validate_absolute_path(path)
    if _os.name == "nt":
        _get_win_backend().ensure_secure_directory(path)
    else:
        _posix_ensure_secure_directory(path)


def create_private_file(directory: str, leaf_name: str) -> int:
    """Create a private file inside *directory* and return its file descriptor.

    The caller owns the returned file descriptor and **must** close it with
    ``os.close(fd)`` after writing.

    - Creates the file with owner-only permissions (0600 on POSIX).
    - ``FileExistsError`` is raised when the file already exists.
    - All security validation happens before the fd is returned.
    - Raises ``SecureStorePermissionError`` when security cannot be proved.
    """
    _validate_absolute_path(directory)
    _validate_leaf_name(leaf_name)
    if _os.name == "nt":
        return _get_win_backend().create_private_file(directory, leaf_name)
    return _posix_create_private_file(directory, leaf_name)


# ============================================================================
# POSIX implementation — handle-relative (dir_fd based)
# ============================================================================

# Build flags once
_O_RDONLY_DIR = _os.O_RDONLY
if hasattr(_os, "O_NOFOLLOW"):
    _O_RDONLY_DIR |= _os.O_NOFOLLOW
if hasattr(_os, "O_DIRECTORY"):
    _O_RDONLY_DIR |= _os.O_DIRECTORY
if hasattr(_os, "O_CLOEXEC"):
    _O_RDONLY_DIR |= _os.O_CLOEXEC

_O_RDWR_DIR = _os.O_RDWR
if hasattr(_os, "O_NOFOLLOW"):
    _O_RDWR_DIR |= _os.O_NOFOLLOW
if hasattr(_os, "O_CLOEXEC"):
    _O_RDWR_DIR |= _os.O_CLOEXEC

_O_CREAT_FILE = _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY
if hasattr(_os, "O_NOFOLLOW"):
    _O_CREAT_FILE |= _os.O_NOFOLLOW
if hasattr(_os, "O_CLOEXEC"):
    _O_CREAT_FILE |= _os.O_CLOEXEC


def _posix_open_root() -> int:
    """Open the root directory as a file descriptor."""
    try:
        return _os.open("/", _O_RDONLY_DIR)
    except OSError:
        return _os.open("/", _os.O_RDONLY)


def _posix_walk_to_parent(path: str) -> tuple[int, str]:
    """Walk from root to the **parent** of *path* using dir_fd.

    Returns ``(parent_fd, leaf_name)``.  The caller **must** close
    *parent_fd*.

    Every intermediate component is opened with ``O_NOFOLLOW``,
    rejecting symlinks.  Intermediate fds are closed as we advance.
    """
    norm = _os.path.normpath(path)
    parts = [p for p in norm.split(_os.sep) if p]
    if not parts:
        raise ValueError(f"Cannot walk empty path: {path!r}")

    leaf = parts[-1]
    parent_parts = parts[:-1]

    root_fd = _posix_open_root()
    current_fd = root_fd
    fds = [root_fd]

    try:
        for comp in parent_parts:
            if not comp:
                continue
            try:
                next_fd = _os.open(comp, _O_RDONLY_DIR, dir_fd=current_fd)
            except FileNotFoundError:
                raise SecureStorePermissionError(
                    f"Parent component does not exist: {comp!r}"
                )
            except PermissionError:
                raise SecureStorePermissionError(
                    f"Permission denied on parent component: {comp!r}"
                )
            except OSError as exc:
                raise SecureStorePermissionError(
                    f"Parent component not a directory/symlink: {comp!r}"
                ) from exc
            fds.append(next_fd)
            current_fd = next_fd

        # Close all intermediate fds except the final parent_fd
        for fd in fds[:-1]:
            try:
                _os.close(fd)
            except OSError:
                pass

        return current_fd, leaf

    except BaseException:
        for fd in fds:
            try:
                _os.close(fd)
            except OSError:
                pass
        raise


def _posix_ensure_secure_directory(path: str) -> None:
    """POSIX: ensure *path* is a secure directory using handle-relative ops.

    State machine (P3‑A corrected):
      1. Walk to parent, validate parent trust (0700, euid).
         Parent-trust failure → preserve primary + append parent close error.
      2. Atomic creation: relative mkdir(0700, dir_fd).
         - Created: immediate relative chmod(0700, follow_symlinks=False).
         - Exists: skip chmod (never modify existing objects).
      3. Open leaf O_NOFOLLOW|O_DIRECTORY from parent_fd.
      4. fstat → capture identity (st_dev,st_ino) immediately.
      5. Validate type/mode/owner + stat cross-check.
      6. Every failure after atomic creation routes through
         identity‑checked rollback.  Chmod / open / fstat / validation
         failures all follow the same path.
      7. Rollback failure → SecureStoreResidualError(primary=primary)
         with stable ordered cleanup: rollback err, leaf close, parent close.
      8. Successful rollback → re‑raise exact same primary object, append
         fd close failures to primary.cleanup_errors.
      9. Finally: close all remaining fds; append errors or raise
         no‑primary cleanup.

    Production code never calls os.umask().
    """
    parent_fd, leaf = _posix_walk_to_parent(path)
    identity: "tuple[int, int] | None" = None
    primary: BaseException | None = None
    created = False
    leaf_fd = _FD_UNOWNED

    # ── Step 1: parent trust validation ──────────────────────────────────
    try:
        _validate_dir_fd_simple(parent_fd)
    except Exception as _pe:
        primary = _pe
        parent_close_err = _posix_close_fd(parent_fd)
        parent_fd = _FD_UNOWNED
        if parent_close_err is not None:
            _attach_cleanup_errors(primary, (parent_close_err,))
        raise primary

    try:
        # ── Step 2: atomic creation ──────────────────────────────────
        try:
            _os.mkdir(leaf, 0o700, dir_fd=parent_fd)
            created = True
        except FileExistsError:
            created = False
        except PermissionError as exc:
            primary = SecureStorePermissionError(
                f"Permission denied creating directory leaf: {leaf!r}"
            )
            raise primary
        except OSError as exc:
            primary = SecureStorePermissionError(
                f"Cannot create directory leaf {leaf!r}: {exc}"
            )
            raise primary

        # ── Step 2b: chmod (created only) ────────────────────────────
        if created:
            try:
                _os.chmod(leaf, 0o700, dir_fd=parent_fd,
                          follow_symlinks=False)
            except OSError as exc:
                primary = SecureStorePermissionError(
                    f"Cannot chmod directory to 0700: {leaf!r}: {exc}"
                )
                # Blocker 1: identity from live created-dir fd
                try:
                    tmp_fd, cap_id = _posix_capture_dir_fd_and_identity(
                        parent_fd, leaf,
                    )
                except OSError:
                    # open failed → no fd, no identity → forbidden
                    ambiguity = SecureStorePermissionError(
                        f"Rollback: cannot open created directory "
                        f"{leaf!r} after chmod failure"
                    )
                    residual = _build_residual_and_close(
                        primary=primary, rollback_err=ambiguity,
                        leaf_fd=_FD_UNOWNED, parent_fd=parent_fd,
                        leaf=leaf,
                    )
                    parent_fd = _FD_UNOWNED
                    raise residual from primary
                # Opened successfully; check if fstat captured identity
                if cap_id is None:
                    # fstat failed → close tmp_fd, capture close error
                    tce = _posix_close_fd(tmp_fd)
                    ambiguity = SecureStorePermissionError(
                        f"Rollback: fstat failed for created directory "
                        f"{leaf!r} after chmod failure"
                    )
                    errs = [ambiguity]
                    if tce is not None:
                        errs.append(tce)
                    pce = _posix_close_fd(parent_fd)
                    parent_fd = _FD_UNOWNED
                    if pce is not None:
                        errs.append(pce)
                    raise SecureStoreResidualError(
                        f"Rollback identity ambiguous for {leaf!r}",
                        primary=primary,
                        cleanup_errors=tuple(errs),
                    ) from primary
                rb_err = _posix_rollback_dir_from_fd(
                    tmp_fd, parent_fd, leaf,
                )
                if rb_err is not None:
                    residual = _build_residual_and_close(
                        primary=primary, rollback_err=rb_err,
                        leaf_fd=tmp_fd, parent_fd=parent_fd,
                        leaf=leaf,
                    )
                    parent_fd = _FD_UNOWNED
                    raise residual from primary
                # successful rollback — close tmp_fd, close parent
                tce = _posix_close_fd(tmp_fd)
                if tce is not None:
                    _attach_cleanup_errors(primary, (tce,))
                pce = _posix_close_fd(parent_fd)
                parent_fd = _FD_UNOWNED
                if pce is not None:
                    _attach_cleanup_errors(primary, (pce,))
                raise primary

        # ── Step 3: open leaf ────────────────────────────────────────
        try:
            leaf_fd = _os.open(leaf, _O_RDONLY_DIR, dir_fd=parent_fd)
        except OSError as exc:
            primary = SecureStorePermissionError(
                f"Cannot open directory for validation: {leaf!r}"
            )
            if created:
                # Blocker 1: identity from live created-dir fd
                try:
                    tmp_fd, cap_id = _posix_capture_dir_fd_and_identity(
                        parent_fd, leaf,
                    )
                except OSError:
                    ambiguity = SecureStorePermissionError(
                        f"Rollback: cannot open created directory "
                        f"{leaf!r} after open failure"
                    )
                    residual = _build_residual_and_close(
                        primary=primary, rollback_err=ambiguity,
                        leaf_fd=_FD_UNOWNED, parent_fd=parent_fd,
                        leaf=leaf,
                    )
                    parent_fd = _FD_UNOWNED
                    raise residual from primary
                if cap_id is None:
                    tce = _posix_close_fd(tmp_fd)
                    ambiguity = SecureStorePermissionError(
                        f"Rollback: fstat failed for created directory "
                        f"{leaf!r} after open failure"
                    )
                    errs = [ambiguity]
                    if tce is not None:
                        errs.append(tce)
                    pce = _posix_close_fd(parent_fd)
                    parent_fd = _FD_UNOWNED
                    if pce is not None:
                        errs.append(pce)
                    raise SecureStoreResidualError(
                        f"Rollback identity ambiguous for {leaf!r}",
                        primary=primary,
                        cleanup_errors=tuple(errs),
                    ) from primary
                rb_err = _posix_rollback_dir_from_fd(
                    tmp_fd, parent_fd, leaf,
                )
                if rb_err is not None:
                    residual = _build_residual_and_close(
                        primary=primary, rollback_err=rb_err,
                        leaf_fd=tmp_fd, parent_fd=parent_fd,
                        leaf=leaf,
                    )
                    parent_fd = _FD_UNOWNED
                    raise residual from primary
                tce = _posix_close_fd(tmp_fd)
                if tce is not None:
                    _attach_cleanup_errors(primary, (tce,))
                pce = _posix_close_fd(parent_fd)
                parent_fd = _FD_UNOWNED
                if pce is not None:
                    _attach_cleanup_errors(primary, (pce,))
            raise primary

        # ── Steps 4‑5: fstat → capture identity → validate ──────────
        try:
            fd_st = _os.fstat(leaf_fd)
            # B2: capture identity immediately after fstat
            identity = (fd_st.st_dev, fd_st.st_ino)

            if not _stat.S_ISDIR(fd_st.st_mode):
                raise SecureStorePermissionError(
                    f"Not a directory (fstat): {leaf!r}"
                )
            actual_mode = _stat.S_IMODE(fd_st.st_mode)
            if actual_mode != 0o700:
                raise SecureStorePermissionError(
                    f"Directory mode {actual_mode:04o} != 0700: {leaf!r}"
                )
            if fd_st.st_uid != _os.geteuid():
                raise SecureStorePermissionError(
                    f"Directory owner uid={fd_st.st_uid} "
                    f"!= euid={_os.geteuid()}: {leaf!r}"
                )
            # Cross-check stat via dir_fd
            try:
                path_st = _os.stat(leaf, dir_fd=parent_fd,
                                   follow_symlinks=False)
            except OSError as exc:
                raise SecureStorePermissionError(
                    f"Cannot stat for identity check: {leaf!r}"
                ) from exc
            if (fd_st.st_ino != path_st.st_ino
                    or fd_st.st_dev != path_st.st_dev):
                raise SecureStorePermissionError(
                    f"stat/fstat identity mismatch for directory: {leaf!r}"
                )
        except Exception as _ve:
            primary = _ve
            if created and identity is not None:
                rb_err = _posix_rollback_dir(parent_fd, leaf, identity)
                if rb_err is not None:
                    residual = _build_residual_and_close(
                        primary=primary, rollback_err=rb_err,
                        leaf_fd=leaf_fd, parent_fd=parent_fd,
                        leaf=leaf,
                    )
                    leaf_fd = _FD_UNOWNED
                    parent_fd = _FD_UNOWNED
                    raise residual from primary
                # Successful rollback — close leaf, re-raise same primary
                lce = _posix_close_fd(leaf_fd)
                leaf_fd = _FD_UNOWNED
                if lce is not None:
                    _attach_cleanup_errors(primary, (lce,))
            elif created and identity is None:
                # Blocker 1: fstat failed before identity capture —
                # deletion forbidden, raise residual with ambiguity
                ambiguity = SecureStorePermissionError(
                    f"Rollback: cannot establish identity for "
                    f"directory {leaf!r} (fstat failed before capture)"
                )
                residual = _build_residual_and_close(
                    primary=primary, rollback_err=ambiguity,
                    leaf_fd=leaf_fd, parent_fd=parent_fd,
                    leaf=leaf,
                )
                leaf_fd = _FD_UNOWNED
                parent_fd = _FD_UNOWNED
                raise residual from primary
            raise primary

        # ── Success: nothing more to do; fds closed in finally ───────

    finally:
        # ── Step 9: close all remaining fds ──────────────────────────
        cleanup_errs: "list[BaseException]" = []
        if leaf_fd >= 0:
            err = _posix_close_fd(leaf_fd)
            leaf_fd = _FD_UNOWNED
            if err is not None:
                cleanup_errs.append(err)
        if parent_fd >= 0:
            err = _posix_close_fd(parent_fd)
            parent_fd = _FD_UNOWNED
            if err is not None:
                cleanup_errs.append(err)
        if primary is not None:
            if cleanup_errs:
                _attach_cleanup_errors(primary, tuple(cleanup_errs))
        elif cleanup_errs:
            _raise_no_primary_cleanup(
                tuple(cleanup_errs), f"ensure_secure_directory {leaf!r}"
            )


def _posix_validate_dir_fd(dir_fd: int, parent_fd: int, leaf_name: str) -> None:
    """Validate an opened directory fd via fstat.  All decisions from fstat."""
    fd_st = _os.fstat(dir_fd)

    # Type check (O_DIRECTORY should have already enforced this)
    if not _stat.S_ISDIR(fd_st.st_mode):
        raise SecureStorePermissionError(
            f"Not a directory (fstat): {leaf_name!r}"
        )

    # Exact mode 0700
    actual_mode = _stat.S_IMODE(fd_st.st_mode)
    if actual_mode != 0o700:
        raise SecureStorePermissionError(
            f"Directory mode {actual_mode:04o} != 0700: {leaf_name!r}"
        )

    # Owner == euid
    if fd_st.st_uid != _os.geteuid():
        raise SecureStorePermissionError(
            f"Directory owner uid={fd_st.st_uid} != euid={_os.geteuid()}: {leaf_name!r}"
        )

    # Cross-check: stat via dir_fd for identity evidence only
    try:
        path_st = _os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise SecureStorePermissionError(
            f"Cannot stat for identity check: {leaf_name!r}"
        ) from exc
    if fd_st.st_ino != path_st.st_ino or fd_st.st_dev != path_st.st_dev:
        raise SecureStorePermissionError(
            f"stat/fstat identity mismatch for directory: {leaf_name!r}"
        )


def _posix_create_private_file(directory: str, leaf_name: str) -> int:
    """POSIX: create a private file via handle-relative ops (dir_fd).

    State machine (P3‑A corrected):
      1. Walk to directory, validate trust (0700, euid).
         Trust failure → preserve primary + append dir close error.
      2. Atomic creation: relative exclusive open(0600, dir_fd).
      3. Immediate fchmod(0600).
      4. fstat → capture identity (st_dev,st_ino) immediately.
      5. Validate type/mode/owner/nlink + stat cross-check.
      6. Every failure after creation routes through identity‑checked
         rollback.  fchmod / fstat / validation failures all follow the
         same path.
      7. Rollback failure → SecureStoreResidualError(primary=primary)
         with stable ordered cleanup: rollback err, file close, dir close.
      8. Successful rollback → close file_fd, re‑raise exact same primary,
         append close failures.
      9. Internal cleanup before return: close dir_fd first while file_fd
         owned.  If dir close fails, close file_fd and raise cleanup error.
         Only commit return ownership after internal cleanup succeeds.
     10. Finally: close all remaining fds.

    Production code never calls os.umask().
    """
    dir_fd = _posix_walk_to_directory(directory)
    identity: "tuple[int, int] | None" = None
    primary: BaseException | None = None
    file_fd = _FD_UNOWNED

    # ── Step 1: parent trust validation ──────────────────────────────────
    try:
        _validate_dir_fd_simple(dir_fd)
    except Exception as _pe:
        primary = _pe
        close_err = _posix_close_fd(dir_fd)
        dir_fd = _FD_UNOWNED
        if close_err is not None:
            _attach_cleanup_errors(primary, (close_err,))
        raise primary

    try:
        # ── Step 2: atomic create ────────────────────────────────────
        flags = _O_CREAT_FILE
        try:
            file_fd = _os.open(leaf_name, flags, 0o600, dir_fd=dir_fd)
        except FileExistsError as _fe:
            # Blocker 2: capture as active primary so dir close
            # failure appends to it
            primary = _fe
            raise
        except PermissionError:
            primary = SecureStorePermissionError(
                f"Permission denied creating file: {leaf_name!r}"
            )
            raise primary
        except OSError as exc:
            primary = SecureStorePermissionError(
                f"Cannot create file {leaf_name!r}: {exc}"
            )
            raise primary

        # ── Step 3: fchmod ───────────────────────────────────────────
        try:
            _os.fchmod(file_fd, 0o600)
        except OSError as exc:
            primary = SecureStorePermissionError(
                f"Cannot fchmod file to 0600: {leaf_name!r}: {exc}"
            )
            # Blocker 1: identity from fstat(file_fd) only, never path stat
            try:
                fd_st = _os.fstat(file_fd)
                identity = (fd_st.st_dev, fd_st.st_ino)
            except OSError:
                identity = None
            if identity is not None:
                rb_err = _posix_rollback_file(dir_fd, leaf_name, identity)
                if rb_err is not None:
                    residual = _build_residual_and_close(
                        primary=primary, rollback_err=rb_err,
                        leaf_fd=file_fd, parent_fd=dir_fd,
                        leaf=leaf_name,
                    )
                    file_fd = _FD_UNOWNED
                    dir_fd = _FD_UNOWNED
                    raise residual from primary
                fce = _posix_close_fd(file_fd)
                file_fd = _FD_UNOWNED
                if fce is not None:
                    _attach_cleanup_errors(primary, (fce,))
            else:
                # Identity unavailable → forbidden to delete → residual
                ambiguity = SecureStorePermissionError(
                    f"Rollback: cannot establish identity for file "
                    f"{leaf_name!r} after fchmod failure"
                )
                residual = _build_residual_and_close(
                    primary=primary, rollback_err=ambiguity,
                    leaf_fd=file_fd, parent_fd=dir_fd,
                    leaf=leaf_name,
                )
                file_fd = _FD_UNOWNED
                dir_fd = _FD_UNOWNED
                raise residual from primary
            raise primary

        # ── Steps 4‑5: fstat → capture identity → validate ──────────
        try:
            fd_st = _os.fstat(file_fd)
            # B2: capture identity immediately after fstat
            identity = (fd_st.st_dev, fd_st.st_ino)

            if not _stat.S_ISREG(fd_st.st_mode):
                raise SecureStorePermissionError(
                    f"Not a regular file (fstat): {leaf_name!r}"
                )
            actual_mode = _stat.S_IMODE(fd_st.st_mode)
            if actual_mode != 0o600:
                raise SecureStorePermissionError(
                    f"File mode {actual_mode:04o} != 0600: {leaf_name!r}"
                )
            if fd_st.st_uid != _os.geteuid():
                raise SecureStorePermissionError(
                    f"File owner uid={fd_st.st_uid} "
                    f"!= euid={_os.geteuid()}: {leaf_name!r}"
                )
            if fd_st.st_nlink != 1:
                raise SecureStorePermissionError(
                    f"File nlink={fd_st.st_nlink} != 1: {leaf_name!r}"
                )
            # Cross-check stat via dir_fd
            try:
                path_st = _os.stat(leaf_name, dir_fd=dir_fd,
                                   follow_symlinks=False)
            except OSError as exc:
                raise SecureStorePermissionError(
                    f"Cannot stat file for identity check: {leaf_name!r}"
                ) from exc
            if (fd_st.st_ino != path_st.st_ino
                    or fd_st.st_dev != path_st.st_dev):
                raise SecureStorePermissionError(
                    f"stat/fstat identity mismatch for file: {leaf_name!r}"
                )
        except Exception as _ve:
            primary = _ve
            if identity is not None:
                rb_err = _posix_rollback_file(dir_fd, leaf_name, identity)
                if rb_err is not None:
                    residual = _build_residual_and_close(
                        primary=primary, rollback_err=rb_err,
                        leaf_fd=file_fd, parent_fd=dir_fd,
                        leaf=leaf_name,
                    )
                    file_fd = _FD_UNOWNED
                    dir_fd = _FD_UNOWNED
                    raise residual from primary
                # Successful rollback: close file_fd, re-raise primary
                fce = _posix_close_fd(file_fd)
                file_fd = _FD_UNOWNED
                if fce is not None:
                    _attach_cleanup_errors(primary, (fce,))
            else:
                # Blocker 1: fstat failed before identity capture —
                # deletion forbidden, raise residual with ambiguity
                ambiguity = SecureStorePermissionError(
                    f"Rollback: cannot establish identity for file "
                    f"{leaf_name!r} (fstat failed before capture)"
                )
                residual = _build_residual_and_close(
                    primary=primary, rollback_err=ambiguity,
                    leaf_fd=file_fd, parent_fd=dir_fd,
                    leaf=leaf_name,
                )
                file_fd = _FD_UNOWNED
                dir_fd = _FD_UNOWNED
                raise residual from primary
            raise primary

        # ── Step 9: Internal cleanup before return ───────────────────
        # Close dir_fd first while file_fd still owned.
        dce = _posix_close_fd(dir_fd)
        dir_fd = _FD_UNOWNED
        if dce is not None:
            # Dir close failed → close file_fd, raise cleanup
            fce = _posix_close_fd(file_fd)
            file_fd = _FD_UNOWNED
            errs = [dce]
            if fce is not None:
                errs.append(fce)
            _raise_no_primary_cleanup(
                tuple(errs), f"create_private_file {leaf_name!r}"
            )

        # Only now commit return ownership — zero file_fd so finally
        # does not close it.
        result = file_fd
        file_fd = _FD_UNOWNED
        return result

    finally:
        # ── Step 10: close remaining fds ─────────────────────────────
        cleanup_errs: "list[BaseException]" = []
        if file_fd >= 0:
            err = _posix_close_fd(file_fd)
            file_fd = _FD_UNOWNED
            if err is not None:
                cleanup_errs.append(err)
        if dir_fd >= 0:
            err = _posix_close_fd(dir_fd)
            dir_fd = _FD_UNOWNED
            if err is not None:
                cleanup_errs.append(err)
        if primary is not None:
            if cleanup_errs:
                _attach_cleanup_errors(primary, tuple(cleanup_errs))
        elif cleanup_errs:
            _raise_no_primary_cleanup(
                tuple(cleanup_errs), f"create_private_file {leaf_name!r}"
            )


def _validate_dir_fd_simple(dir_fd: int) -> None:
    """Validate directory fd: must be dir, mode 0700, owner == euid."""
    fd_st = _os.fstat(dir_fd)
    if not _stat.S_ISDIR(fd_st.st_mode):
        raise SecureStorePermissionError("Not a directory")
    actual_mode = _stat.S_IMODE(fd_st.st_mode)
    if actual_mode != 0o700:
        raise SecureStorePermissionError(
            f"Directory mode {actual_mode:04o} != 0700"
        )
    if fd_st.st_uid != _os.geteuid():
        raise SecureStorePermissionError(
            f"Directory owner uid={fd_st.st_uid} != euid={_os.geteuid()}"
        )


def _posix_walk_to_directory(path: str) -> int:
    """Walk from root to *path*, return a validated directory fd.

    The caller must close the returned fd.
    """
    norm = _os.path.normpath(path)
    parts = [p for p in norm.split(_os.sep) if p]
    if not parts:
        raise ValueError(f"Cannot walk empty path: {path!r}")

    root_fd = _posix_open_root()
    current_fd = root_fd
    fds = [root_fd]

    try:
        for comp in parts:
            if not comp:
                continue
            try:
                next_fd = _os.open(comp, _O_RDONLY_DIR, dir_fd=current_fd)
            except FileNotFoundError:
                raise FileNotFoundError(
                    f"Directory component does not exist: {comp!r}"
                )
            except PermissionError:
                raise SecureStorePermissionError(
                    f"Permission denied on directory component: {comp!r}"
                )
            except OSError as exc:
                raise SecureStorePermissionError(
                    f"Component not a directory/symlink: {comp!r}"
                ) from exc
            fds.append(next_fd)
            current_fd = next_fd

        # Close all intermediate fds except the final one
        for fd in fds[:-1]:
            try:
                _os.close(fd)
            except OSError:
                pass

        return current_fd

    except BaseException:
        for fd in fds:
            try:
                _os.close(fd)
            except OSError:
                pass
        raise


def _posix_validate_file_fd(file_fd: int, dir_fd: int, leaf_name: str) -> None:
    """Validate an opened private file fd.  All decisions from fstat."""
    fd_st = _os.fstat(file_fd)

    if not _stat.S_ISREG(fd_st.st_mode):
        raise SecureStorePermissionError(
            f"Not a regular file (fstat): {leaf_name!r}"
        )

    actual_mode = _stat.S_IMODE(fd_st.st_mode)
    if actual_mode != 0o600:
        raise SecureStorePermissionError(
            f"File mode {actual_mode:04o} != 0600: {leaf_name!r}"
        )

    if fd_st.st_uid != _os.geteuid():
        raise SecureStorePermissionError(
            f"File owner uid={fd_st.st_uid} != euid={_os.geteuid()}: {leaf_name!r}"
        )

    if fd_st.st_nlink != 1:
        raise SecureStorePermissionError(
            f"File nlink={fd_st.st_nlink} != 1: {leaf_name!r}"
        )

    # Cross-check stat via dir_fd for identity evidence only
    try:
        path_st = _os.stat(leaf_name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError as exc:
        raise SecureStorePermissionError(
            f"Cannot stat file for identity check: {leaf_name!r}"
        ) from exc
    if fd_st.st_ino != path_st.st_ino or fd_st.st_dev != path_st.st_dev:
        raise SecureStorePermissionError(
            f"stat/fstat identity mismatch for file: {leaf_name!r}"
        )


# Sentinel for unowned fd: -1.  fd 0 is valid (stdin).
_FD_UNOWNED = -1


def _posix_close_fd(fd: int) -> BaseException | None:
    """Close *fd* once.  Return close error or None.  Never retry on EINTR."""
    try:
        _os.close(fd)
    except OSError as e:
        return SecureStorePermissionError(f"Failed to close file descriptor: {e}")
    return None


def _posix_stat_identity(parent_fd: int, leaf: str) -> "tuple[int, int]":
    """DEPRECATED: identity must come from created-fd fstat, not path stat.

    Kept only as internal helper name; callers must use
    ``_posix_capture_dir_identity_from_fd`` for rollback authority.
    """
    st = _os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
    return (st.st_dev, st.st_ino)


def _posix_capture_dir_fd_and_identity(
    parent_fd: int, leaf: str,
) -> "tuple[int, tuple[int, int] | None]":
    """Open the created directory, fstat it, and return
    ``(live_fd, (st_dev, st_ino))``.

    On **open failure**: raises ``OSError`` — caller has no fd to close.
    On **fstat failure**: returns ``(live_fd, None)`` — the caller MUST
    close *live_fd* itself (one attempt) and capture any close error
    into the residual's ``cleanup_errors``.  Never discards close errors.
    """
    tmp_fd = _os.open(leaf, _O_RDONLY_DIR, dir_fd=parent_fd)
    try:
        fd_st = _os.fstat(tmp_fd)
        return (tmp_fd, (fd_st.st_dev, fd_st.st_ino))
    except Exception:
        # fstat failed — return fd so caller closes it; identity is None
        return (tmp_fd, None)


def _posix_rollback_dir_from_fd(
    live_fd: int, parent_fd: int, leaf: str,
) -> BaseException | None:
    """Rollback: fstat *live_fd* for identity, stat relative to
    *parent_fd*, compare, one relative rmdir.  Returns ``None`` on
    success or a ``SecureStorePermissionError``.  Caller must close
    *live_fd* afterward.
    """
    try:
        fd_st = _os.fstat(live_fd)
        identity = (fd_st.st_dev, fd_st.st_ino)
    except OSError as e:
        return SecureStorePermissionError(
            f"Rollback: cannot fstat created dir fd for {leaf!r}: {e}"
        )
    try:
        st = _os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as e:
        return SecureStorePermissionError(
            f"Rollback: cannot stat directory {leaf!r} from parent_fd: {e}"
        )
    if (st.st_dev, st.st_ino) != identity:
        return SecureStorePermissionError(
            f"Rollback: directory identity mismatch for {leaf!r}; "
            f"expected dev={identity[0]} ino={identity[1]}, "
            f"got dev={st.st_dev} ino={st.st_ino}"
        )
    try:
        _os.rmdir(leaf, dir_fd=parent_fd)
    except OSError as e:
        return SecureStorePermissionError(
            f"Rollback: rmdir failed for {leaf!r}: {e}"
        )
    return None


def _posix_rollback_dir(
    parent_fd: int, leaf: str, identity: "tuple[int, int]",
) -> BaseException | None:
    """Legacy: identity-checked rollback (identity captured from already-open fd).
    For chmod/open failures use ``_posix_rollback_dir_from_fd`` instead."""
    try:
        st = _os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as e:
        return SecureStorePermissionError(
            f"Rollback: cannot stat directory {leaf!r} from parent_fd: {e}"
        )
    if (st.st_dev, st.st_ino) != identity:
        return SecureStorePermissionError(
            f"Rollback: directory identity mismatch for {leaf!r}; "
            f"expected dev={identity[0]} ino={identity[1]}, "
            f"got dev={st.st_dev} ino={st.st_ino}"
        )
    try:
        _os.rmdir(leaf, dir_fd=parent_fd)
    except OSError as e:
        return SecureStorePermissionError(
            f"Rollback: rmdir failed for {leaf!r}: {e}"
        )
    return None


def _posix_rollback_file(
    dir_fd: int, leaf: str, identity: "tuple[int, int]",
) -> BaseException | None:
    """Identity-checked rollback of a newly-created private file.

    Same contract as ``_posix_rollback_dir`` but uses relative ``unlink``.
    """
    try:
        st = _os.stat(leaf, dir_fd=dir_fd, follow_symlinks=False)
    except OSError as e:
        return SecureStorePermissionError(
            f"Rollback: cannot stat file {leaf!r} from dir_fd: {e}"
        )
    if (st.st_dev, st.st_ino) != identity:
        return SecureStorePermissionError(
            f"Rollback: file identity mismatch for {leaf!r}; "
            f"expected dev={identity[0]} ino={identity[1]}, "
            f"got dev={st.st_dev} ino={st.st_ino}"
        )
    try:
        _os.unlink(leaf, dir_fd=dir_fd)
    except OSError as e:
        return SecureStorePermissionError(
            f"Rollback: unlink failed for {leaf!r}: {e}"
        )
    return None


def _build_residual_and_close(
    *,
    primary: BaseException,
    rollback_err: BaseException,
    leaf_fd: int,
    parent_fd: int,
    leaf: str,
) -> "BaseException":
    """Build a ``SecureStoreResidualError`` with stable ordered cleanup errors:

    1. rollback_err
    2. leaf_fd close error (if any)
    3. parent_fd close error (if any)

    ``.primary`` and ``__cause__`` remain the exact original *primary*.
    Closes both fds as side effect.
    """
    errs: "list[BaseException]" = [rollback_err]
    if leaf_fd >= 0:
        leaf_close_err = _posix_close_fd(leaf_fd)
        leaf_fd = _FD_UNOWNED  # noqa: F841
        if leaf_close_err is not None:
            errs.append(leaf_close_err)
    if parent_fd >= 0:
        parent_close_err = _posix_close_fd(parent_fd)
        parent_fd = _FD_UNOWNED  # noqa: F841
        if parent_close_err is not None:
            errs.append(parent_close_err)
    return SecureStoreResidualError(
        f"Rollback failed for {leaf!r}",
        primary=primary,
        cleanup_errors=tuple(errs),
    )


# ============================================================================
# Windows implementation — ctypes backend
# ============================================================================


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Access / share / creation
_FILE_ALL_ACCESS = 0x001F01FF  # STANDARD_RIGHTS_REQUIRED | SYNCHRONIZE | all file rights
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_CREATE_NEW = 1
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

# File / directory attributes
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_FILE_ATTRIBUTE_DIRECTORY = 0x0010

# File type
_FILE_TYPE_UNKNOWN = 0x0000
_FILE_TYPE_DISK = 0x0001

# Token
_TOKEN_QUERY = 0x0008
_TOKEN_USER_INFO = 1  # TokenUser TOKEN_INFORMATION_CLASS

# Security descriptor
_SECURITY_DESCRIPTOR_REVISION = 1
_ACL_REVISION_DS = 4
_SE_DACL_PROTECTED = 0x1000

# ACE types / flags
_ACCESS_ALLOWED_ACE_TYPE = 0x00
_ACCESS_DENIED_ACE_TYPE = 0x01
_CONTAINER_INHERIT_ACE = 0x02
_OBJECT_INHERIT_ACE = 0x01
_NO_PROPAGATE_INHERIT_ACE = 0x04
_INHERITED_ACE = 0x10
_INHERIT_ONLY_ACE = 0x08

# SE_OBJECT_TYPE
_SE_FILE_OBJECT = 1

# Security information flags
_DACL_SECURITY_INFORMATION = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_ACL_SIZE_INFORMATION_CLASS = 2  # AclSizeInformation

# Well-known SID authorities & RIDs
_SECURITY_NT_AUTHORITY = _ct.c_ubyte * 6
_SECURITY_NT_AUTHORITY_VAL = _SECURITY_NT_AUTHORITY(0, 0, 0, 0, 0, 5)
_SECURITY_LOCAL_SYSTEM_RID = 0x12  # 18
_SECURITY_WORLD_RID = 0x00
_SECURITY_AUTHENTICATED_USER_RID = 0x0B  # 11
_SECURITY_BUILTIN_DOMAIN_RID = 0x20  # 32

# Error codes
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_ERROR_ACCESS_DENIED = 5
_ERROR_FILE_EXISTS = 80
_ERROR_ALREADY_EXISTS = 183
_ERROR_PRIVILEGE_NOT_HELD = 1314
_INVALID_HANDLE_VALUE = _ct.c_void_p(-1).value

# LMEM
_LMEM_FIXED = 0x0000


# ---------------------------------------------------------------------------
# NT Native API constants  (NtCreateFile, RtlNtStatusToDosError)
# ---------------------------------------------------------------------------

# NTSTATUS — well-known values (signed 32-bit)
_STATUS_SUCCESS = 0x00000000
_STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034
_STATUS_OBJECT_PATH_NOT_FOUND = 0xC000003A
_STATUS_ACCESS_DENIED = 0xC0000022
_STATUS_OBJECT_NAME_COLLISION = 0xC0000035
_STATUS_SHARING_VIOLATION = 0xC0000043
_STATUS_NOT_A_DIRECTORY = 0xC0000103
_STATUS_FILE_IS_A_DIRECTORY = 0xC00000BA
_STATUS_REPARSE = 0x00000104
_STATUS_REPARSE_POINT_NOT_RESOLVED = 0xC000028C
_STATUS_PRIVILEGE_NOT_HELD = 0xC0000061

# NT_SUCCESS macro
def _NT_SUCCESS(status: int) -> bool:
    """Return True if *status* is a success NTSTATUS (signed >= 0)."""
    return _ct.c_int32(status).value >= 0

# RtlNtStatusToDosError error code when mapping is unavailable
_ERROR_MR_MID_NOT_FOUND = 317

# NtCreateFile disposition values
_FILE_SUPERSEDE = 0x00000000
_FILE_OPEN = 1
_FILE_CREATE = 2
_FILE_OPEN_IF = 3
_FILE_OVERWRITE = 4
_FILE_OVERWRITE_IF = 5

# NtCreateFile / CreateFile options
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_WRITE_THROUGH = 0x00000002
_FILE_SEQUENTIAL_ONLY = 0x00000004
_FILE_NO_INTERMEDIATE_BUFFERING = 0x00000008
_FILE_SYNCHRONOUS_IO_ALERT = 0x00000010
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_CREATE_TREE_CONNECTION = 0x00000080
_FILE_COMPLETE_IF_OPLOCKED = 0x00000100
_FILE_NO_EA_KNOWLEDGE = 0x00000200
_FILE_OPEN_REMOTE_INSTANCE = 0x00000400
_FILE_RANDOM_ACCESS = 0x00000800
_FILE_DELETE_ON_CLOSE = 0x00001000
_FILE_OPEN_BY_FILE_ID = 0x00002000
_FILE_OPEN_FOR_BACKUP_INTENT = 0x00004000
_FILE_NO_COMPRESSION = 0x00008000
_FILE_OPEN_REQUIRING_OPLOCK = 0x00010000
_FILE_DISALLOW_EXCLUSIVE = 0x00020000
_FILE_SESSION_AWARE = 0x00040000
_FILE_RESERVE_OPFILTER = 0x00100000
_FILE_OPEN_REPARSE_POINT = 0x00200000
_FILE_OPEN_NO_RECALL = 0x00400000
_FILE_OPEN_FOR_FREE_SPACE_QUERY = 0x00800000

# OBJECT_ATTRIBUTES flags
_OBJ_INHERIT = 0x00000002
_OBJ_PERMANENT = 0x00000010
_OBJ_EXCLUSIVE = 0x00000020
_OBJ_CASE_INSENSITIVE = 0x00000040
_OBJ_OPENIF = 0x00000080
_OBJ_OPENLINK = 0x00000100
_OBJ_KERNEL_HANDLE = 0x00000200
_OBJ_FORCE_ACCESS_CHECK = 0x00000400
_OBJ_IGNORE_IMPERSONATED_DEVICEMAP = 0x00000800
_OBJ_DONT_REPARSE = 0x00001000
_OBJ_VALID_ATTRIBUTES = 0x00001FF2

# Standard access rights (used with NtCreateFile)
_STANDARD_RIGHTS_READ = 0x00020000
_DELETE = 0x00010000
_READ_CONTROL = 0x00020000
_SYNCHRONIZE = 0x00100000
_FILE_READ_DATA = 0x0001  # file read access
_FILE_WRITE_DATA = 0x0002  # file write access
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_WRITE_ATTRIBUTES = 0x0100
_FILE_TRAVERSE = 0x0020  # directory traversal
_FILE_EXECUTE = 0x0020

# Drive types (GetDriveTypeW)
_DRIVE_UNKNOWN = 0
_DRIVE_NO_ROOT_DIR = 1
_DRIVE_REMOVABLE = 2
_DRIVE_FIXED = 3
_DRIVE_REMOTE = 4
_DRIVE_CDROM = 5
_DRIVE_RAMDISK = 6

# FileDispositionInfo (SetFileInformationByHandle)
_FileDispositionInfo = 13
_FileBasicInfo = 4

# IO_STATUS_BLOCK.Information values for FILE_OPEN_IF
_FILE_CREATED_INFO = 1  # created
_FILE_OPENED_INFO = 2   # opened-existing
_FILE_OVERWRITTEN_INFO = 3

# Win32 error mapping helpers
def _is_ntstatus_name_collision(status: int) -> bool:
    """Check if *status* is a name-collision / already-exists NTSTATUS."""
    return _ct.c_int32(status).value == _STATUS_OBJECT_NAME_COLLISION

def _is_ntstatus_not_found(status: int) -> bool:
    """Check if *status* is a not-found NTSTATUS."""
    v = _ct.c_int32(status).value
    return v in (_STATUS_OBJECT_NAME_NOT_FOUND, _STATUS_OBJECT_PATH_NOT_FOUND)


# ---------------------------------------------------------------------------
# ctypes structures
# ---------------------------------------------------------------------------


class _FILETIME(_ct.Structure):
    _fields_ = [
        ("dwLowDateTime", _ct.c_uint32),
        ("dwHighDateTime", _ct.c_uint32),
    ]


class _BY_HANDLE_FILE_INFO(_ct.Structure):
    _fields_ = [
        ("dwFileAttributes", _ct.c_uint32),
        ("ftCreationTime", _FILETIME),
        ("ftLastAccessTime", _FILETIME),
        ("ftLastWriteTime", _FILETIME),
        ("dwVolumeSerialNumber", _ct.c_uint32),
        ("nFileSizeHigh", _ct.c_uint32),
        ("nFileSizeLow", _ct.c_uint32),
        ("nNumberOfLinks", _ct.c_uint32),
        ("nFileIndexHigh", _ct.c_uint32),
        ("nFileIndexLow", _ct.c_uint32),
    ]


class _SID_IDENTIFIER_AUTHORITY(_ct.Structure):
    _fields_ = [("Value", _ct.c_ubyte * 6)]


class _SID_AND_ATTRIBUTES(_ct.Structure):
    _fields_ = [
        ("Sid", _ct.c_void_p),
        ("Attributes", _ct.c_uint32),
    ]


class _TOKEN_USER(_ct.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _ACL(_ct.Structure):
    _fields_ = [
        ("AclRevision", _ct.c_byte),
        ("Sbz1", _ct.c_byte),
        ("AclSize", _ct.c_uint16),
        ("AceCount", _ct.c_uint16),
        ("Sbz2", _ct.c_uint16),
    ]


class _ACE_HEADER(_ct.Structure):
    _fields_ = [
        ("AceType", _ct.c_byte),
        ("AceFlags", _ct.c_byte),
        ("AceSize", _ct.c_uint16),
    ]


class _ACCESS_ALLOWED_ACE(_ct.Structure):
    _fields_ = [
        ("Header", _ACE_HEADER),
        ("Mask", _ct.c_uint32),
        ("SidStart", _ct.c_uint32),
    ]


class _ACCESS_DENIED_ACE(_ct.Structure):
    _fields_ = [
        ("Header", _ACE_HEADER),
        ("Mask", _ct.c_uint32),
        ("SidStart", _ct.c_uint32),
    ]


class _ACL_SIZE_INFORMATION(_ct.Structure):
    _fields_ = [
        ("AceCount", _ct.c_uint32),
        ("AclBytesInUse", _ct.c_uint32),
        ("AclBytesFree", _ct.c_uint32),
    ]


class _SECURITY_DESCRIPTOR(_ct.Structure):
    _fields_ = [
        ("Revision", _ct.c_byte),
        ("Sbz1", _ct.c_byte),
        ("Control", _ct.c_uint16),
        ("Owner", _ct.c_void_p),
        ("Group", _ct.c_void_p),
        ("Sacl", _ct.c_void_p),
        ("Dacl", _ct.c_void_p),
    ]


class _SECURITY_ATTRIBUTES(_ct.Structure):
    _fields_ = [
        ("nLength", _ct.c_uint32),
        ("lpSecurityDescriptor", _ct.c_void_p),
        ("bInheritHandle", _ct.c_int32),
    ]


# ---------------------------------------------------------------------------
# Native NT ABI structures  (NtCreateFile, relative open/create)
# ---------------------------------------------------------------------------


def _build_unicode_string(name: str) -> "tuple[_UNICODE_STRING, object]":
    """Build a UNICODE_STRING for *name* plus its **ctypes backing buffer**.

    Returns ``(us, ctypes_buf)`` where *ctypes_buf* is the
    ``ctypes.create_string_buffer`` that owns the native memory.
    The caller **must** keep *ctypes_buf* alive through the native call.

    ``us.Length`` is the UTF-16LE byte length **excluding** the
    terminating NUL; ``us.MaximumLength`` is ``Length + 2`` (includes NUL).
    The buffer carries a two-byte NUL terminator.
    """
    _wide = name.encode("utf-16-le") + b"\x00\x00"
    _buf = _ct.create_string_buffer(_wide)
    us = _UNICODE_STRING()
    us.Length = len(_wide) - 2
    us.MaximumLength = len(_wide)
    us.Buffer = _ct.cast(_buf, _ct.c_void_p).value
    return us, _buf  # ctypes buffer — caller must keep alive


def _build_object_attributes(
    name: str,
    root_dir: int,
    security_descriptor: int = 0,
    *,
    _keep_bufs: "list | None" = None,
) -> "tuple[_OBJECT_ATTRIBUTES, _UNICODE_STRING]":
    """Build OBJECT_ATTRIBUTES + UNICODE_STRING for a relative name.

    *root_dir* is the parent HANDLE (RootDirectory).
    *security_descriptor* points to an absolute SECURITY_DESCRIPTOR or 0.

    If *_keep_bufs* is a list, the UNICODE_STRING backing buffer
    (a ctypes object) is appended so callers can assert lifetime through
    the native call.
    """
    us, cbuf = _build_unicode_string(name)
    if _keep_bufs is not None:
        _keep_bufs.append(cbuf)
    oa = _OBJECT_ATTRIBUTES()
    oa.Length = _ct.sizeof(_OBJECT_ATTRIBUTES)
    oa.RootDirectory = _wt.HANDLE(root_dir)
    oa.ObjectName = _ct.pointer(us)
    oa.Attributes = _OBJ_CASE_INSENSITIVE
    oa.SecurityDescriptor = security_descriptor or 0
    return oa, us


class _UNICODE_STRING(_ct.Structure):
    _fields_ = [
        ("Length", _ct.c_uint16),
        ("MaximumLength", _ct.c_uint16),
        ("Buffer", _ct.c_void_p),
    ]


class _OBJECT_ATTRIBUTES(_ct.Structure):
    _fields_ = [
        ("Length", _ct.c_uint32),
        ("RootDirectory", _wt.HANDLE),
        ("ObjectName", _ct.POINTER(_UNICODE_STRING)),
        ("Attributes", _ct.c_uint32),
        ("SecurityDescriptor", _ct.c_void_p),
        ("SecurityQualityOfService", _ct.c_void_p),
    ]


# ULONG_PTR — pointer-width unsigned integer
_uwt = _ct.c_uint64 if _ct.sizeof(_ct.c_void_p) == 8 else _ct.c_uint32


class _IO_STATUS_BLOCK_u(_ct.Union):
    """Anonymous union: Status (4B) / Pointer (pointer-width)."""
    _fields_ = [
        ("Status", _ct.c_int32),
        ("Pointer", _ct.c_void_p),
    ]


class _IO_STATUS_BLOCK(_ct.Structure):
    """IO_STATUS_BLOCK — exact native layout.

    Layout: anonymous union{NTSTATUS; PVOID} at offset 0,
    then ULONG_PTR Information.

    x64 (16 bytes): union(8) + Information(8)
    x86 ( 8 bytes): union(4) + Information(4)
    """
    _anonymous_ = ("u",)
    _fields_ = [
        ("u", _IO_STATUS_BLOCK_u),
        ("Information", _uwt),
    ]

    def get_info(self) -> int:
        """Read Information as pointer-sized unsigned value."""
        return self.Information

    def set_info(self, value: int) -> None:
        self.Information = value


class _FILE_DISPOSITION_INFO(_ct.Structure):
    _fields_ = [
        ("DeleteFile", _ct.c_ubyte),
    ]


# ---------------------------------------------------------------------------
# LARGE_INTEGER (for NtCreateFile AllocationSize)
# ---------------------------------------------------------------------------


class _LARGE_INTEGER(_ct.Structure):
    _fields_ = [
        ("QuadPart", _ct.c_int64),
    ]


# ---------------------------------------------------------------------------
# Prototype configuration helpers  (Linux-testable)
# ---------------------------------------------------------------------------


def _configure_ntdll_prototypes(n) -> None:
    """Configure ntdll prototypes for NtCreateFile + RtlNtStatusToDosError.

    This is the single source of truth for the NtCreateFile ABI.
    Callers may inspect ``n.NtCreateFile.argtypes`` to assert types.
    """
    n.RtlNtStatusToDosError.restype = _ct.c_uint32
    n.RtlNtStatusToDosError.argtypes = [_ct.c_int32]
    n.NtCreateFile.restype = _ct.c_int32
    n.NtCreateFile.argtypes = [
        _ct.POINTER(_wt.HANDLE),            # FileHandle
        _ct.c_uint32,                       # DesiredAccess
        _ct.POINTER(_OBJECT_ATTRIBUTES),    # ObjectAttributes → POBJECT_ATTRIBUTES
        _ct.POINTER(_IO_STATUS_BLOCK),      # IoStatusBlock → PIO_STATUS_BLOCK
        _ct.POINTER(_LARGE_INTEGER),        # AllocationSize → PLARGE_INTEGER
        _ct.c_uint32,                       # FileAttributes
        _ct.c_uint32,                       # ShareAccess
        _ct.c_uint32,                       # CreateDisposition
        _ct.c_uint32,                       # CreateOptions
        _ct.c_void_p,                       # EaBuffer
        _ct.c_uint32,                       # EaLength
    ]


def _configure_advapi32_prototypes(a) -> None:
    """Configure advapi32 prototypes for security descriptor inspection.

    This is the single source of truth for the DACL inspection ABI.
    """
    a.GetSecurityInfo.restype = _wt.DWORD
    a.GetSecurityInfo.argtypes = [
        _wt.HANDLE, _ct.c_int, _wt.DWORD,
        _ct.POINTER(_ct.c_void_p), _ct.POINTER(_ct.c_void_p),
        _ct.POINTER(_ct.c_void_p), _ct.POINTER(_ct.c_void_p),
        _ct.POINTER(_ct.c_void_p),
    ]
    # GetSecurityDescriptorControl: (SD, WORD*, DWORD*)
    a.GetSecurityDescriptorControl.restype = _wt.BOOL
    a.GetSecurityDescriptorControl.argtypes = [
        _ct.c_void_p, _ct.POINTER(_wt.WORD), _ct.POINTER(_wt.DWORD),
    ]
    a.GetAclInformation.restype = _wt.BOOL
    a.GetAclInformation.argtypes = [
        _ct.c_void_p, _ct.c_void_p, _wt.DWORD, _ct.c_int,
    ]
    a.GetAce.restype = _wt.BOOL
    a.GetAce.argtypes = [
        _ct.c_void_p, _wt.DWORD, _ct.POINTER(_ct.c_void_p),
    ]
    a.GetLengthSid.restype = _wt.DWORD
    a.GetLengthSid.argtypes = [_ct.c_void_p]
    a.IsValidSid.restype = _wt.BOOL
    a.IsValidSid.argtypes = [_ct.c_void_p]


# ---------------------------------------------------------------------------
# DACL snapshot types  (for owned inspection through the low-level wrapper)
# ---------------------------------------------------------------------------


class DaclAceSnapshot:
    """Read-only snapshot of a single ACE."""
    __slots__ = ("ace_type", "ace_flags", "mask", "sid_bytes")

    def __init__(self, ace_type: int, ace_flags: int, mask: int, sid_bytes: bytes) -> None:
        self.ace_type = ace_type
        self.ace_flags = ace_flags
        self.mask = mask
        self.sid_bytes = sid_bytes

    def __repr__(self) -> str:
        return (
            f"DaclAceSnapshot(type=0x{self.ace_type:02X}, "
            f"flags=0x{self.ace_flags:02X}, mask=0x{self.mask:08X})"
        )


class DaclSnapshot:
    """Owned, read-only DACL snapshot.

    Carries the control word, DACL-present flag, protected flag, and
    a **frozen tuple** of ``DaclAceSnapshot`` entries.
    """
    __slots__ = ("control", "dacl_present", "protected", "aces")

    def __init__(
        self,
        control: int,
        dacl_present: bool,
        protected: bool,
        aces: "tuple[DaclAceSnapshot, ...]",
    ) -> None:
        self.control = control
        self.dacl_present = dacl_present
        self.protected = protected
        self.aces = aces

    def __repr__(self) -> str:
        return (
            f"DaclSnapshot(protected={self.protected}, "
            f"aces={len(self.aces)})"
        )


# ---------------------------------------------------------------------------
# Shared DACL parse helper  (production seam, Linux-testable)
# ---------------------------------------------------------------------------

# Type aliases for injectable reader callables
# _SDCtrlFn: (sd_ptr) -> (control, revision)
# _AclInfoFn: (dacl_ptr) -> (ace_count, bytes_in_use)
# _GetAceFn: (dacl_ptr, index) -> ace_ptr_value
# _ValidSidFn: (sid_ptr) -> bool
# _SidLenFn: (sid_ptr) -> int


def _parse_dacl_snapshot_from_sd(
    *,
    sd_ptr: int,
    dacl_ptr: int,
    get_sd_control: "callable",
    get_acl_info: "callable",
    get_ace: "callable",
    is_valid_sid: "callable",
    get_sid_length: "callable",
) -> DaclSnapshot:
    """Parse an already-acquired security descriptor into a DaclSnapshot.

    All Windows API calls are injected as callables so this function is
    pure‑Python testable on Linux without real advapi32 DLLs.
    """
    ctrl_raw, _rev = get_sd_control()
    protected = bool(ctrl_raw & _SE_DACL_PROTECTED)
    dacl_present = bool(dacl_ptr)

    _ACES: "list[DaclAceSnapshot]" = []
    if dacl_present:
        dacl_addr = dacl_ptr
        _ACL_SZ = _ct.sizeof(_ACL)
        acl = _ACL.from_address(dacl_addr)
        acl_total_size = int(acl.AclSize)
        if acl_total_size < _ACL_SZ:
            raise SecureStorePermissionError(
                f"AclSize ({acl_total_size}) < sizeof(ACL) ({_ACL_SZ})"
            )

        ace_count, acl_bytes_used = get_acl_info()
        if acl_bytes_used < _ACL_SZ:
            raise SecureStorePermissionError(
                f"AclBytesInUse ({acl_bytes_used}) < sizeof(ACL) ({_ACL_SZ})"
            )
        if acl_bytes_used > acl_total_size:
            raise SecureStorePermissionError(
                f"ACL bytes in use ({acl_bytes_used}) > size ({acl_total_size})"
            )

        _ACE_HDR_SZ = _ct.sizeof(_ACE_HEADER)
        for i in range(ace_count):
            ace_base = get_ace(i)  # returns raw address
            ace_in_acl_start = ace_base - dacl_addr
            if ace_in_acl_start < 0 or ace_in_acl_start >= acl_bytes_used:
                raise SecureStorePermissionError(
                    f"ACE[{i}] pointer outside ACL used range"
                )
            if ace_in_acl_start + _ACE_HDR_SZ > acl_bytes_used:
                raise SecureStorePermissionError(
                    f"ACE[{i}] header extends beyond ACL used range"
                )
            header = _ACE_HEADER.from_address(ace_base)
            ace_size = int(header.AceSize)
            min_ace = _ACE_HDR_SZ + _ct.sizeof(_ct.c_uint32)
            if ace_size < min_ace:
                raise SecureStorePermissionError(
                    f"ACE[{i}] AceSize={ace_size} too small"
                )
            ace_end = ace_in_acl_start + ace_size
            if ace_end > acl_bytes_used:
                raise SecureStorePermissionError(
                    f"ACE[{i}] end ({ace_end}) > ACL used ({acl_bytes_used})"
                )

            ace_type = int(header.AceType)
            ace_flags = int(header.AceFlags)
            mask_offset = _ACE_HDR_SZ
            mask = _ct.c_uint32.from_address(ace_base + mask_offset).value

            if ace_type != _ACCESS_ALLOWED_ACE_TYPE:
                raise SecureStorePermissionError(
                    f"ACE[{i}] type=0x{ace_type:02X} (only ALLOW accepted)"
                )

            sid_offset = mask_offset + _ct.sizeof(_ct.c_uint32)
            if ace_size < sid_offset:
                raise SecureStorePermissionError(
                    f"ACE[{i}] AceSize={ace_size} cannot hold SID"
                )
            sid_space = ace_base + sid_offset
            remaining = ace_size - sid_offset
            if remaining < 8:
                raise SecureStorePermissionError(
                    f"ACE[{i}] remaining {remaining} < 8 (minimum SID header)"
                )

            # --- Safe SID header read (Fix #3) ---
            _rev_byte = _ct.c_ubyte.from_address(sid_space).value
            _sub_auth_count = _ct.c_ubyte.from_address(sid_space + 1).value
            _required_sid = 8 + 4 * int(_sub_auth_count)
            if _required_sid > remaining:
                raise SecureStorePermissionError(
                    f"ACE[{i}] SID requires {_required_sid} bytes, "
                    f"only {remaining} remaining"
                )
            if not is_valid_sid(sid_space):
                raise SecureStorePermissionError(
                    f"ACE[{i}] SID is not valid"
                )
            sid_len = get_sid_length(sid_space)
            if sid_len == 0:
                raise SecureStorePermissionError(
                    f"ACE[{i}] SID has zero length"
                )
            if sid_len != _required_sid:
                raise SecureStorePermissionError(
                    f"ACE[{i}] SID reported length {sid_len} != "
                    f"required {_required_sid} (8+4*{_sub_auth_count})"
                )
            if sid_len > remaining:
                raise SecureStorePermissionError(
                    f"ACE[{i}] SID length {sid_len} > ACE remaining {remaining}"
                )

            sid_buf = _ct.create_string_buffer(sid_len)
            _ct.memmove(sid_buf, sid_space, sid_len)
            _ACES.append(DaclAceSnapshot(
                ace_type=ace_type, ace_flags=ace_flags,
                mask=mask, sid_bytes=bytes(sid_buf),
            ))
    return DaclSnapshot(
        control=ctrl_raw, dacl_present=dacl_present,
        protected=protected, aces=tuple(_ACES),
    )


# ---------------------------------------------------------------------------
# NTSTATUS classification + raise boundary  (pure, cross-platform)
# ---------------------------------------------------------------------------


def _classify_ntstatus_exc(
    status: int,
    disposition: int | None = None,
) -> BaseException:
    """Classify a signed NTSTATUS into a Python exception (never raises)."""
    _st = _ct.c_int32
    st = _st(status).value

    _not_found = {_st(_STATUS_OBJECT_NAME_NOT_FOUND).value,
                  _st(_STATUS_OBJECT_PATH_NOT_FOUND).value}
    _collision = _st(_STATUS_OBJECT_NAME_COLLISION).value
    _access_denied = _st(_STATUS_ACCESS_DENIED).value
    _sharing = _st(_STATUS_SHARING_VIOLATION).value
    _not_dir = _st(_STATUS_NOT_A_DIRECTORY).value
    _is_dir = _st(_STATUS_FILE_IS_A_DIRECTORY).value
    _reparse = _st(_STATUS_REPARSE_POINT_NOT_RESOLVED).value

    if st in _not_found:
        exc = FileNotFoundError(f"NT object not found (0x{st & 0xFFFFFFFF:08X})")
        exc.ntstatus = st  # type: ignore[attr-defined]
        exc.cleanup_errors = ()  # type: ignore[attr-defined]
        return exc

    if st == _collision:
        exc = FileExistsError(f"NT object already exists (0x{st & 0xFFFFFFFF:08X})")
        exc.ntstatus = st  # type: ignore[attr-defined]
        exc.cleanup_errors = ()  # type: ignore[attr-defined]
        return exc

    if _NT_SUCCESS(st):
        exc = SecureStorePermissionError(
            f"Unexpected NT success status 0x{st & 0xFFFFFFFF:08X}"
        )
        exc.ntstatus = st  # type: ignore[attr-defined]
        exc.cleanup_errors = ()  # type: ignore[attr-defined]
        return exc

    if st == _access_denied:
        msg = "NT access denied"
    elif st == _sharing:
        msg = "NT sharing violation"
    elif st == _not_dir:
        msg = "NT not a directory"
    elif st == _is_dir:
        msg = "NT file is a directory"
    elif st == _reparse:
        msg = "NT reparse point not resolved"
    else:
        msg = f"NT error 0x{st & 0xFFFFFFFF:08X}"

    exc = SecureStorePermissionError(msg)
    exc.ntstatus = st  # type: ignore[attr-defined]
    exc.cleanup_errors = ()  # type: ignore[attr-defined]
    return exc


def _convert_and_raise_ntstatus(
    ntstatus: int,
    winerror_mapper,
) -> None:
    """Unified helper: map NTSTATUS→winerror, classify, attach, raise.

    *winerror_mapper* is a callable ``(int) -> int | None`` that either
    returns a Win32 error code or raises.  Conversion exceptions are
    swallowed (winerror becomes None).  ``ERROR_MR_MID_NOT_FOUND`` (317),
    ``None``, and self-mapping never set the ``winerror`` attribute.

    This is the single raising boundary for NTSTATUS-based operations.
    """
    try:
        we = winerror_mapper(ntstatus)
    except Exception:
        we = None

    exc = _classify_ntstatus_exc(ntstatus)
    if we is not None:
        w32 = _ct.c_uint32(we).value
        nt32 = _ct.c_uint32(ntstatus).value
        if w32 != _ERROR_MR_MID_NOT_FOUND and w32 != nt32:
            exc.winerror = w32  # type: ignore[attr-defined]
    raise exc


def _raise_from_ntstatus(
    ntstatus: int,
    winerror: int | None = None,
    operation: str = "",
    path: str = "",
) -> None:
    """Classify *ntstatus*, attach *winerror* if valid, and raise.

    Fix #6: ``ERROR_MR_MID_NOT_FOUND`` (317), ``None``, and self-mapping
    (winerror == ntstatus as uint32) never set the ``winerror`` attribute.
    """
    exc = _classify_ntstatus_exc(ntstatus)
    if winerror is not None:
        w = _ct.c_uint32(winerror).value
        n = _ct.c_uint32(ntstatus).value
        if w != _ERROR_MR_MID_NOT_FOUND and w != n:
            exc.winerror = w  # type: ignore[attr-defined]
    raise exc


def _classify_ntstatus(
    status: int,
    disposition: int | None = None,
    info: int | None = None,
) -> BaseException:
    """Legacy alias — returns exception without raising.  Prefer
    ``_raise_from_ntstatus`` for the unified boundary.
    """
    return _classify_ntstatus_exc(status, disposition)


# ---------------------------------------------------------------------------
# Injectable Windows low-level API wrapper  (P2-A)
# ---------------------------------------------------------------------------


class _WinLowLevelAPI:
    """Private injectable wrapper for all security-critical native Windows calls.

    Every raw ctypes call in the production Windows backend must cross this
    wrapper.  The real implementation uses kernel32 / ntdll / advapi32 / msvcrt.
    A trace/fault fake records every call for Linux-side invariant testing.

    Operations covered:
    - ``drive_type`` — GetDriveTypeW(root)
    - ``open_root`` — CreateFileW for drive root (full path only)
    - ``nt_create_file`` — relative NtCreateFile
    - ``ntstatus_to_winerror`` — RtlNtStatusToDosError
    - ``get_file_info`` — GetFileInformationByHandle
    - ``get_file_type`` — GetFileType
    - ``get_handle_identity`` — volume serial + file index
    - ``acquire_dacl`` — GetSecurityInfo(DACL)
    - ``release_dacl`` — LocalFree on returned SD
    - ``set_delete_disposition`` — SetFileInformationByHandle(FileDispositionInfo)
    - ``close_handle`` — CloseHandle
    - ``open_osfhandle`` — msvcrt.open_osfhandle
    """

    def drive_type(self, root: str) -> int:
        """Return GetDriveTypeW(*root*).  Must be ``DRIVE_FIXED`` for use."""
        raise NotImplementedError

    def open_root(self, root: str) -> int:
        """Open a drive root (full path, e.g. ``C:\\``).  Returns HANDLE."""
        raise NotImplementedError

    def nt_create_file(
        self,
        relative_name: str,
        root_directory: int,
        desired_access: int,
        share_access: int,
        create_disposition: int,
        create_options: int,
        security_descriptor: int = 0,
    ) -> tuple[int, int, int]:
        """Relative NtCreateFile.  Returns ``(handle, ntstatus, info)``.

        *security_descriptor* is a pointer to an absolute SECURITY_DESCRIPTOR
        or 0 (NULL).  When non-zero it is passed through
        ``OBJECT_ATTRIBUTES.SecurityDescriptor``.
        """
        raise NotImplementedError

    def ntstatus_to_winerror(self, ntstatus: int) -> int:
        """Convert NTSTATUS to Win32 error via RtlNtStatusToDosError."""
        raise NotImplementedError

    def get_file_info(self, handle: int) -> _BY_HANDLE_FILE_INFO:
        """Return ``BY_HANDLE_FILE_INFO`` for *handle*."""
        raise NotImplementedError

    def get_file_type(self, handle: int) -> int:
        """Return GetFileType(*handle*)."""
        raise NotImplementedError

    def get_handle_identity(self, handle: int) -> tuple[int, int, int]:
        """Return ``(volume_serial, file_index_high, file_index_low)``."""
        raise NotImplementedError

    def read_dacl_snapshot(self, handle: int) -> DaclSnapshot:
        """Acquire, inspect, and release DACL — return an owned ``DaclSnapshot``.

        This is the only DACL inspection seam.  It atomically acquires the
        security descriptor, reads control flags, the DACL pointer, and every
        ACE (type, flags, mask, raw SID bytes), then immediately releases
        the SD.  Acquire failure does not release; inspection/release failures
        follow the frozen cleanup_errors contract.
        """
        raise NotImplementedError

    def set_delete_disposition(self, handle: int) -> None:
        """Request deletion via SetFileInformationByHandle(FileDispositionInfo)."""
        raise NotImplementedError

    def close_handle(self, handle: int) -> None:
        """CloseHandle."""
        raise NotImplementedError

    def open_osfhandle(self, handle: int) -> int:
        """Convert NT HANDLE to CRT fd via msvcrt.open_osfhandle."""
        raise NotImplementedError

    # -- Security context (Blocker #1) --

    def acquire_security_context(self) -> int:
        """Acquire current-user and LocalSystem SID bytes.

        Returns an opaque context handle.  Caller must release via
        ``release_security_context``.  The context owns the native SID
        resources; the caller may extract SID bytes for DACL validation
        via ``get_context_user_sid`` / ``get_context_system_sid``.
        """
        raise NotImplementedError

    def get_context_user_sid(self, ctx: int) -> bytes:
        """Return the current-user SID bytes from a live security context."""
        raise NotImplementedError

    def get_context_system_sid(self, ctx: int) -> bytes:
        """Return the LocalSystem SID bytes from a live security context."""
        raise NotImplementedError

    def release_security_context(self, ctx: int) -> None:
        """Release all resources owned by *ctx* (no‑op if zero)."""
        raise NotImplementedError

    # -- Security descriptor (Blocker #2) --

    def build_file_security_descriptor(self, security_context: int) -> int:
        """Build an absolute security descriptor for a private file.

        *security_context* was acquired from ``acquire_security_context``
        and provides the SID identities embedded in the descriptor.

        Returns a caller-owned opaque handle that must be released via
        ``free_security_descriptor``.  The descriptor carries a protected
        two‑ACE policy (current user + LocalSystem), file‑level ACE
        inheritance flags zero, FILE_ALL_ACCESS mask for both.
        """
        raise NotImplementedError

    def free_security_descriptor(self, sd_handle: int) -> None:
        """Release a security descriptor handle returned by
        ``build_file_security_descriptor``.

        Must be idempotent: releasing a zero or already‑released handle
        is a no‑op.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Low-level API injection
# ---------------------------------------------------------------------------

_low_level_api: _WinLowLevelAPI | None = None


def _get_low_level_api() -> _WinLowLevelAPI:
    """Return the current low-level API (real or fake)."""
    global _low_level_api
    if _low_level_api is None:
        _low_level_api = _RealLowLevelAPI()
    return _low_level_api


def _set_low_level_api(api: _WinLowLevelAPI | None) -> None:
    """Replace the low-level API for testing."""
    global _low_level_api
    _low_level_api = api


class _RealLowLevelAPI(_WinLowLevelAPI):
    """Production low-level API — real ctypes to kernel32 + ntdll + advapi32."""

    # Injectable native callable seam (Fix #1 + Fix #7)
    # Set to a callable that receives (file_handle_ptr, desired_access,
    # oa_ptr, iosb_ptr, ...) → returns int32 ntstatus_raw.
    _native_callable = None

    def __init__(self) -> None:
        self._init = False
        self._k = None
        self._n = None
        self._a = None
        self._invalid_handle = _ct.c_void_p(-1).value

    def _ensure_init(self) -> None:
        if self._init:
            return
        k = _ct.WinDLL("kernel32", use_last_error=True)
        n = _ct.WinDLL("ntdll", use_last_error=True)
        a = _ct.WinDLL("advapi32", use_last_error=True)

        # kernel32
        k.GetDriveTypeW.restype = _ct.c_uint
        k.GetDriveTypeW.argtypes = [_wt.LPCWSTR]
        k.CreateFileW.restype = _wt.HANDLE
        k.CreateFileW.argtypes = [
            _wt.LPCWSTR, _wt.DWORD, _wt.DWORD,
            _ct.c_void_p, _wt.DWORD, _wt.DWORD, _wt.HANDLE,
        ]
        k.CloseHandle.restype = _wt.BOOL
        k.CloseHandle.argtypes = [_wt.HANDLE]
        k.GetFileInformationByHandle.restype = _wt.BOOL
        k.GetFileInformationByHandle.argtypes = [
            _wt.HANDLE, _ct.POINTER(_BY_HANDLE_FILE_INFO),
        ]
        k.GetFileType.restype = _wt.DWORD
        k.GetFileType.argtypes = [_wt.HANDLE]
        k.LocalFree.restype = _wt.HLOCAL
        k.LocalFree.argtypes = [_wt.HLOCAL]
        k.SetFileInformationByHandle.restype = _wt.BOOL
        k.SetFileInformationByHandle.argtypes = [
            _wt.HANDLE, _ct.c_int, _ct.c_void_p, _wt.DWORD,
        ]
        k.GetLastError.restype = _wt.DWORD
        k.GetLastError.argtypes = []
        # Security-context / SD construction (Blocker #1 / #2)
        k.LocalAlloc.restype = _wt.HLOCAL
        k.LocalAlloc.argtypes = [_wt.UINT, _ct.c_size_t]
        k.GetCurrentProcess.restype = _wt.HANDLE
        k.GetCurrentProcess.argtypes = []

        # ntdll
        _configure_ntdll_prototypes(n)
        # advapi32 (core DACL ops)
        _configure_advapi32_prototypes(a)
        # advapi32 — security context / SD construction (Blocker #1 / #2)
        a.OpenProcessToken.restype = _wt.BOOL
        a.OpenProcessToken.argtypes = [
            _wt.HANDLE, _wt.DWORD, _ct.POINTER(_wt.HANDLE),
        ]
        a.GetTokenInformation.restype = _wt.BOOL
        a.GetTokenInformation.argtypes = [
            _wt.HANDLE, _ct.c_int, _ct.c_void_p, _wt.DWORD,
            _ct.POINTER(_wt.DWORD),
        ]
        a.AllocateAndInitializeSid.restype = _wt.BOOL
        a.AllocateAndInitializeSid.argtypes = [
            _ct.POINTER(_SID_IDENTIFIER_AUTHORITY), _ct.c_byte,
            _wt.DWORD, _wt.DWORD, _wt.DWORD, _wt.DWORD,
            _wt.DWORD, _wt.DWORD, _wt.DWORD, _wt.DWORD,
            _ct.POINTER(_ct.c_void_p),
        ]
        a.FreeSid.restype = _ct.c_void_p
        a.FreeSid.argtypes = [_ct.c_void_p]
        a.CopySid.restype = _wt.BOOL
        a.CopySid.argtypes = [_wt.DWORD, _ct.c_void_p, _ct.c_void_p]
        a.InitializeAcl.restype = _wt.BOOL
        a.InitializeAcl.argtypes = [_ct.c_void_p, _wt.DWORD, _wt.DWORD]
        a.AddAccessAllowedAceEx.restype = _wt.BOOL
        a.AddAccessAllowedAceEx.argtypes = [
            _ct.c_void_p, _wt.DWORD, _wt.DWORD, _wt.DWORD, _ct.c_void_p,
        ]
        a.InitializeSecurityDescriptor.restype = _wt.BOOL
        a.InitializeSecurityDescriptor.argtypes = [_ct.c_void_p, _wt.DWORD]
        a.SetSecurityDescriptorDacl.restype = _wt.BOOL
        a.SetSecurityDescriptorDacl.argtypes = [
            _ct.c_void_p, _wt.BOOL, _ct.c_void_p, _wt.BOOL,
        ]
        a.SetSecurityDescriptorControl.restype = _wt.BOOL
        a.SetSecurityDescriptorControl.argtypes = [
            _ct.c_void_p, _wt.DWORD, _wt.DWORD,
        ]

        self._k = k
        self._n = n
        self._a = a
        self._init = True

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def drive_type(self, root: str) -> int:
        self._ensure_init()
        return self._k.GetDriveTypeW(root)

    def open_root(self, root: str) -> int:
        self._ensure_init()
        h = self._k.CreateFileW(
            root,
            _FILE_READ_ATTRIBUTES | _FILE_TRAVERSE | _SYNCHRONIZE,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if h == self._invalid_handle:
            raise OSError(f"open_root failed for {root!r}: {self._k.GetLastError()}")
        return h

    def nt_create_file(
        self,
        relative_name: str,
        root_directory: int,
        desired_access: int,
        share_access: int,
        create_disposition: int,
        create_options: int,
        security_descriptor: int = 0,
    ) -> tuple[int, int, int]:
        self._ensure_init()

        # Build UNICODE_STRING + OBJECT_ATTRIBUTES — keep ctypes buffer alive
        _keep: list = []
        oa, us = _build_object_attributes(
            relative_name, root_directory, security_descriptor, _keep_bufs=_keep,
        )

        # Sentinel-initialize outputs with identifiable constants (Fix #7)
        _SENTINEL_HANDLE = _ct.c_void_p(-1).value  # INVALID_HANDLE_VALUE
        _SENTINEL_STATUS = 0x0BADF00D
        _SENTINEL_INFO = 0xDEADBEEFDEADBEEF if _ct.sizeof(_ct.c_void_p) == 8 else 0xDEADBEEF

        file_handle = _wt.HANDLE(_SENTINEL_HANDLE)
        iosb = _IO_STATUS_BLOCK()
        iosb.Status = _SENTINEL_STATUS
        iosb.set_info(_SENTINEL_INFO)

        # Use injectable native callable seam (Fix #1 + Fix #7)
        if self._native_callable is not None:
            ntstatus_raw = self._native_callable(
                _ct.byref(file_handle), desired_access, _ct.byref(oa),
                _ct.byref(iosb), None, 0, share_access, create_disposition,
                create_options, None, 0,
            )
        else:
            ntstatus_raw = self._n.NtCreateFile(
                _ct.byref(file_handle),
                desired_access,
                _ct.byref(oa),
                _ct.byref(iosb),
                None,  # AllocationSize
                0,     # FileAttributes
                share_access,
                create_disposition,
                create_options,
                None,  # EaBuffer
                0,     # EaLength
            )

        # Normalize outputs (Fix #7): only expose after NT_SUCCESS
        ntstatus_val = _ct.c_int32(ntstatus_raw).value
        if _NT_SUCCESS(ntstatus_val):
            handle_val = file_handle.value
            # Reject NULL, INVALID_HANDLE_VALUE, still-sentinel handle
            if (handle_val is None or handle_val == 0
                    or handle_val == _SENTINEL_HANDLE or handle_val == _ct.c_void_p(-1).value):
                raise SecureStorePermissionError(
                    f"NtCreateFile succeeded but returned invalid handle "
                    f"(0x{_ct.c_uint32(ntstatus_raw).value:08X})"
                )
            # Verify Information was written (no longer sentinel) — Fix #7
            info_val = iosb.get_info()
            _SENTINEL_INFO = 0xDEADBEEFDEADBEEF if _ct.sizeof(_ct.c_void_p) == 8 else 0xDEADBEEF
            if info_val == _SENTINEL_INFO:
                # Defect 1: valid HANDLE + unusable IOSB must close once
                # before propagating; check BOOL, GetLastError; close
                # failure appended to exact primary.
                primary = SecureStorePermissionError(
                    f"NtCreateFile succeeded but IOSB.Information not written (still sentinel)"
                )
                # One close attempt — use existing close_handle for consistency
                try:
                    self.close_handle(handle_val)
                except Exception as ce:
                    _attach_cleanup_errors(primary, (ce,))
                raise primary
            return (handle_val, ntstatus_val, info_val)
        else:
            # Failure: discard polluted outputs, return zeroed (Fix #7)
            return (0, ntstatus_val, 0)

    def ntstatus_to_winerror(self, ntstatus: int) -> int:
        self._ensure_init()
        return self._n.RtlNtStatusToDosError(_ct.c_int32(ntstatus))

    def get_file_info(self, handle: int) -> _BY_HANDLE_FILE_INFO:
        self._ensure_init()
        info = _BY_HANDLE_FILE_INFO()
        if not self._k.GetFileInformationByHandle(handle, _ct.byref(info)):
            raise OSError(
                f"GetFileInformationByHandle failed: {self._k.GetLastError()}"
            )
        return info

    def get_file_type(self, handle: int) -> int:
        self._ensure_init()
        return self._k.GetFileType(handle)

    def get_handle_identity(self, handle: int) -> tuple[int, int, int]:
        info = self.get_file_info(handle)
        return (
            info.dwVolumeSerialNumber,
            info.nFileIndexHigh,
            info.nFileIndexLow,
        )

    def read_dacl_snapshot(self, handle: int) -> DaclSnapshot:
        """Acquire→inspect/copy→release exactly once."""
        self._ensure_init()

        primary: BaseException | None = None
        sd_ptr = _ct.c_void_p()
        dacl_ptr = _ct.c_void_p()

        ret = self._a.GetSecurityInfo(
            handle, _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, _ct.byref(dacl_ptr), None, _ct.byref(sd_ptr),
        )
        if ret != 0:
            # Defect 2: failed GetSecurityInfo with non-null partial SD
            # must LocalFree once; preserve exact primary whether
            # LocalFree returns non-NULL OR raises.
            primary = SecureStorePermissionError(f"GetSecurityInfo failed: {ret}")
            if sd_ptr:
                try:
                    freed = self._k.LocalFree(sd_ptr)
                except Exception as lf_exc:
                    _attach_cleanup_errors(
                        primary,
                        (SecureStorePermissionError(
                            f"LocalFree(SD) on failed GetSecurityInfo raised: {lf_exc}"
                        ),),
                    )
                else:
                    if freed:
                        _attach_cleanup_errors(
                            primary,
                            (SecureStorePermissionError(
                                f"LocalFree(SD) on failed GetSecurityInfo returned non-NULL: {freed}"
                            ),),
                        )
            raise primary

        try:
            result = _parse_dacl_snapshot_from_sd(
                sd_ptr=sd_ptr.value,
                dacl_ptr=dacl_ptr.value,
                get_sd_control=lambda: self._get_sd_control(sd_ptr),
                get_acl_info=lambda: self._get_acl_info(dacl_ptr),
                get_ace=lambda i: self._get_ace_ptr(dacl_ptr, i),
                is_valid_sid=lambda p: self._a.IsValidSid(p),
                get_sid_length=lambda p: self._a.GetLengthSid(p),
            )
        except BaseException as _primary_exc:
            primary = _primary_exc
            raise
        finally:
            cleanup_errors: "list[BaseException]" = []
            if sd_ptr:
                try:
                    freed = self._k.LocalFree(sd_ptr)
                except Exception as lf_exc:
                    cleanup_errors.append(
                        SecureStorePermissionError(
                            f"LocalFree(SD) raised: {lf_exc}"
                        )
                    )
                else:
                    if freed:
                        cleanup_errors.append(
                            SecureStorePermissionError(
                                f"LocalFree(SD) returned non-NULL: {freed}"
                            )
                        )
            if primary is not None:
                _attach_cleanup_errors(primary, tuple(cleanup_errors))
            elif cleanup_errors:
                _raise_no_primary_cleanup(tuple(cleanup_errors), "read_dacl_snapshot")

        return result

    def _get_sd_control(self, sd_ptr) -> "tuple[int, int]":
        ctrl = _wt.WORD()
        rev = _wt.DWORD()
        if not self._a.GetSecurityDescriptorControl(
            sd_ptr, _ct.byref(ctrl), _ct.byref(rev)
        ):
            raise SecureStorePermissionError(
                f"GetSecurityDescriptorControl failed: {self._k.GetLastError()}"
            )
        return (ctrl.value, rev.value)

    def _get_acl_info(self, dacl_ptr) -> "tuple[int, int]":
        size_info = _ACL_SIZE_INFORMATION()
        if not self._a.GetAclInformation(
            dacl_ptr, _ct.byref(size_info),
            _ct.sizeof(_ACL_SIZE_INFORMATION), _ACL_SIZE_INFORMATION_CLASS,
        ):
            raise SecureStorePermissionError(
                f"GetAclInformation failed: {self._k.GetLastError()}"
            )
        return (int(size_info.AceCount), int(size_info.AclBytesInUse))

    def _get_ace_ptr(self, dacl_ptr, i: int) -> int:
        ace_ptr = _ct.c_void_p()
        if not self._a.GetAce(dacl_ptr, i, _ct.byref(ace_ptr)):
            raise SecureStorePermissionError(
                f"GetAce[{i}] failed: {self._k.GetLastError()}"
            )
        if not ace_ptr:
            raise SecureStorePermissionError(f"GetAce[{i}] returned NULL ACE pointer")
        return ace_ptr.value

    def set_delete_disposition(self, handle: int) -> None:
        self._ensure_init()
        disp = _FILE_DISPOSITION_INFO()
        disp.DeleteFile = 1
        if not self._k.SetFileInformationByHandle(
            handle, _FileDispositionInfo,
            _ct.byref(disp), _ct.sizeof(_FILE_DISPOSITION_INFO),
        ):
            raise SecureStorePermissionError(
                f"SetFileInformationByHandle(FileDispositionInfo) failed: "
                f"{self._k.GetLastError()}"
            )

    def close_handle(self, handle: int) -> None:
        self._ensure_init()
        if handle and handle != self._invalid_handle:
            if not self._k.CloseHandle(handle):
                raise OSError(f"CloseHandle failed: {self._k.GetLastError()}")

    def open_osfhandle(self, handle: int) -> int:
        if _msvcrt is None:
            raise SecureStorePermissionError("msvcrt not available")
        fd_flags = _os.O_WRONLY
        if hasattr(_os, "O_BINARY"):
            fd_flags |= _os.O_BINARY
        return _msvcrt.open_osfhandle(handle, fd_flags)

    # ------------------------------------------------------------------
    # Security context (Blocker #1)
    # ------------------------------------------------------------------

    def acquire_security_context(self) -> int:
        """Acquire current-user and LocalSystem SID bytes.

        Returns an opaque context handle.  The caller MUST release via
        ``release_security_context``.

        State machine (frozen contract):
          S1  OpenProcessToken → token HANDLE.
          S2  GetTokenInformation size probe → validate >0.
          S3  GetTokenInformation data query.
          S4  GetLengthSid user → validate >0.
          S5  LocalAlloc + CopySid user.  Slot user_sid_buf set.
          S6  AllocateAndInitializeSid SYSTEM.  Slot system_sid_ptr_val set.
          S7  GetLengthSid SYSTEM → validate >0; string_at.
          S8  Compute candidate context; publish, zero local slots to
              transfer ownership; return ctx_id.
          S9  Token CloseHandle (exactly once in finally).

        Construction failure (any step S1-S8 before publish):
          - Local owned slots stay set.
          - Common finally unwinds user→SYSTEM→token, one attempt each.
          - Cleanup errors appended chronologically; construction primary
            preserved exactly.

        Token-close-only failure (S8 complete, S9 fails):
          - Local slots already zeroed (ownership transferred to context).
          - Pop published context; free user LocalFree + SYSTEM FreeSid
            exactly once; no double-release.
          - All failures surfaced via _raise_no_primary_cleanup.
        """
        self._ensure_init()
        k = self._k
        a = self._a

        # -- S1: open process token --
        token = _wt.HANDLE()
        if not a.OpenProcessToken(
            k.GetCurrentProcess(), _TOKEN_QUERY, _ct.byref(token),
        ):
            raise SecureStorePermissionError(
                f"OpenProcessToken failed: {k.GetLastError()}"
            )

        # Owned resource slots — 0 = not allocated / transferred
        user_sid_buf: int = 0
        system_sid_ptr_val: int = 0
        construction_primary: BaseException | None = None
        cleanup_ordered: "list[BaseException]" = []
        ctx_id: int = 0

        try:
            # -- S2: size probe --
            needed = _wt.DWORD()
            a.GetTokenInformation(
                token, _TOKEN_USER_INFO, None, 0, _ct.byref(needed),
            )
            buf_size = needed.value
            if buf_size == 0:
                raise SecureStorePermissionError(
                    "GetTokenInformation returned zero required size for user SID"
                )

            # -- S3: data query --
            buf = _ct.create_string_buffer(buf_size)
            if not a.GetTokenInformation(
                token, _TOKEN_USER_INFO, buf, buf_size, _ct.byref(needed),
            ):
                raise SecureStorePermissionError(
                    f"GetTokenInformation(TokenUser) failed: {k.GetLastError()}"
                )

            # -- S4: user SID length --
            tu = _TOKEN_USER.from_buffer(buf)
            user_sid_len = a.GetLengthSid(tu.User.Sid)
            if user_sid_len == 0:
                raise SecureStorePermissionError(
                    "GetLengthSid returned 0 for user SID"
                )

            # -- S5: LocalAlloc + CopySid user --
            user_sid_buf = k.LocalAlloc(_LMEM_FIXED, user_sid_len)
            if not user_sid_buf:
                raise SecureStorePermissionError(
                    f"LocalAlloc(user SID) failed: {k.GetLastError()}"
                )
            if not a.CopySid(user_sid_len, user_sid_buf, tu.User.Sid):
                # Blocker 3: do NOT directly LocalFree here — raise with
                # slot still set; common finally handles user→SYSTEM→token.
                raise SecureStorePermissionError(
                    f"CopySid failed: {k.GetLastError()}"
                )

            user_sid_bytes = _ct.string_at(user_sid_buf, user_sid_len)

            # -- S6: AllocateAndInitializeSid SYSTEM --
            system_sid_ptr = _ct.c_void_p()
            auth = _SID_IDENTIFIER_AUTHORITY()
            _ct.memmove(auth.Value, _SECURITY_NT_AUTHORITY_VAL, 6)
            if not a.AllocateAndInitializeSid(
                _ct.byref(auth), 1, _SECURITY_LOCAL_SYSTEM_RID,
                0, 0, 0, 0, 0, 0, 0, _ct.byref(system_sid_ptr),
            ):
                # Blocker 3: do NOT directly LocalFree user here — raise
                # with both slots still set; common finally unwinds both.
                raise SecureStorePermissionError(
                    f"AllocateAndInitializeSid(SYSTEM) failed: {k.GetLastError()}"
                )
            system_sid_ptr_val = system_sid_ptr.value

            # -- S7: GetLengthSid SYSTEM --
            system_sid_len = a.GetLengthSid(system_sid_ptr)
            if system_sid_len == 0:
                raise SecureStorePermissionError(
                    "GetLengthSid returned 0 for SYSTEM SID"
                )
            system_sid_bytes = _ct.string_at(system_sid_ptr, system_sid_len)

            # -- S8: publish context; transfer ownership by zeroing locals --
            ctx_id = id(user_sid_buf)
            if not hasattr(self, "_security_contexts"):
                self._security_contexts: dict = {}
            self._security_contexts[ctx_id] = {
                "user_sid_buf": user_sid_buf,
                "user_sid_len": user_sid_len,
                "user_sid_bytes": user_sid_bytes,
                "system_sid_ptr": system_sid_ptr_val,
                "system_sid_bytes": system_sid_bytes,
            }
            # Transfer: locals → context.  Zero so finally does NOT free them.
            user_sid_buf = 0
            system_sid_ptr_val = 0
            # ctx_id is non-zero; returned after finally (S9) succeeds.
            # return is at end of try — falls through to finally.

        except BaseException as _primary:
            construction_primary = _primary
            raise
        finally:
            # ── S9: ordered unwind ──────────────────────────────────
            # user LocalFree → SYSTEM FreeSid → token CloseHandle.
            # Each exactly once; no retry.  Slots that are zero
            # indicate ownership already transferred (success path).
            #
            # On construction failure: slots hold allocated resources;
            # the common finally frees them in order.
            #
            # On success: slots are zero → no double-free.  Token close
            # is the only remaining action; if it fails, the published
            # context is popped and its SIDs freed here exactly once
            # (not in a separate branch).

            # 1. user LocalFree  (only if slot not transferred)
            if user_sid_buf:
                try:
                    freed = k.LocalFree(user_sid_buf)
                except Exception as lf_exc:
                    cleanup_ordered.append(
                        SecureStorePermissionError(
                            f"LocalFree(user SID) raised in acquire unwind: {lf_exc}"
                        )
                    )
                else:
                    if freed:
                        cleanup_ordered.append(
                            SecureStorePermissionError(
                                f"LocalFree(user SID) returned non-NULL in acquire unwind: {freed}"
                            )
                        )
                user_sid_buf = 0

            # 2. SYSTEM FreeSid  (only if slot not transferred)
            if system_sid_ptr_val:
                try:
                    ret = a.FreeSid(system_sid_ptr_val)
                except Exception as fs_exc:
                    cleanup_ordered.append(
                        SecureStorePermissionError(
                            f"FreeSid(SYSTEM) raised in acquire unwind: {fs_exc}"
                        )
                    )
                else:
                    if ret:
                        cleanup_ordered.append(
                            SecureStorePermissionError(
                                f"FreeSid(SYSTEM) returned non-NULL in acquire unwind"
                            )
                        )
                system_sid_ptr_val = 0

            # 3. token CloseHandle — exactly once
            token_close_ok = True
            try:
                if not k.CloseHandle(token):
                    tc_err = SecureStorePermissionError(
                        f"CloseHandle(token) failed in acquire unwind: {k.GetLastError()}"
                    )
                    cleanup_ordered.append(tc_err)
                    token_close_ok = False
            except Exception as tc_exc:
                cleanup_ordered.append(
                    SecureStorePermissionError(
                        f"CloseHandle(token) raised in acquire unwind: {tc_exc}"
                    )
                )
                token_close_ok = False

            # ── surface results ────────────────────────────────────
            if construction_primary is not None:
                if cleanup_ordered:
                    _attach_cleanup_errors(
                        construction_primary, tuple(cleanup_ordered)
                    )
                # Do NOT return context
            elif ctx_id and token_close_ok:
                # Everything clean → context is valid, caller owns it.
                # ctx_id was already published; return it.
                pass
            elif ctx_id:
                # S8 published context, but S9 failed.
                # Pop the context and free its owned SIDs exactly once.
                # Each release attempted exactly once; both raised
                # exceptions and non-NULL returns surfaced chronologically.
                popped = getattr(self, "_security_contexts", {}).pop(ctx_id, None)
                if popped:
                    # Free SIDs from popped context (they were transferred,
                    # so our local slots are already zero).
                    if popped.get("user_sid_buf"):
                        try:
                            uf = k.LocalFree(popped["user_sid_buf"])
                        except Exception as uf_exc:
                            cleanup_ordered.append(
                                SecureStorePermissionError(
                                    f"LocalFree(user SID) raised in context-discard: {uf_exc}"
                                )
                            )
                        else:
                            if uf:
                                cleanup_ordered.append(
                                    SecureStorePermissionError(
                                        f"LocalFree(user SID) in context-discard returned non-NULL: {uf}"
                                    )
                                )
                    if popped.get("system_sid_ptr"):
                        try:
                            sf = a.FreeSid(popped["system_sid_ptr"])
                        except Exception as sf_exc:
                            cleanup_ordered.append(
                                SecureStorePermissionError(
                                    f"FreeSid(SYSTEM) raised in context-discard: {sf_exc}"
                                )
                            )
                        else:
                            if sf:
                                cleanup_ordered.append(
                                    SecureStorePermissionError(
                                        f"FreeSid(SYSTEM) in context-discard returned non-NULL: {sf}"
                                    )
                                )
                _raise_no_primary_cleanup(
                    tuple(cleanup_ordered), "acquire_security_context token close"
                )
            elif cleanup_ordered:
                # No ctx_id (construction never completed), no primary →
                # cleanup-only failure.
                _raise_no_primary_cleanup(
                    tuple(cleanup_ordered), "acquire_security_context cleanup"
                )

        # Unreachable except through success path (ctx_id > 0, token_close_ok)
        return ctx_id

    def get_context_user_sid(self, ctx: int) -> bytes:
        self._ensure_init()
        entry = self._security_contexts.get(ctx)
        if entry is None:
            raise SecureStorePermissionError(
                f"Security context {ctx} is not valid"
            )
        return entry["user_sid_bytes"]

    def get_context_system_sid(self, ctx: int) -> bytes:
        self._ensure_init()
        entry = self._security_contexts.get(ctx)
        if entry is None:
            raise SecureStorePermissionError(
                f"Security context {ctx} is not valid"
            )
        return entry["system_sid_bytes"]

    def release_security_context(self, ctx: int) -> None:
        """Release all resources owned by *ctx* (no‑op if zero).

        Consume logical record before release; independently attempt
        user LocalFree then SYSTEM FreeSid exactly once even if first
        fails/raises; check return codes; aggregate ordered errors;
        no retry; second release no native calls.
        """
        if ctx == 0:
            return
        self._ensure_init()
        # Consume entry BEFORE any release attempt — one shot, no retry
        entry = getattr(self, "_security_contexts", {}).pop(ctx, None)
        if entry is None:
            return  # idempotent: already released or unknown
        cleanup_errors: "list[BaseException]" = []

        # 1. user LocalFree — check return and exceptions
        if entry.get("user_sid_buf"):
            try:
                freed = self._k.LocalFree(entry["user_sid_buf"])
            except Exception as lf_exc:
                cleanup_errors.append(
                    SecureStorePermissionError(
                        f"LocalFree(user SID) raised in release: {lf_exc}"
                    )
                )
            else:
                if freed:
                    cleanup_errors.append(
                        SecureStorePermissionError(
                            f"LocalFree(user SID) returned non-NULL in release: {freed}"
                        )
                    )

        # 2. SYSTEM FreeSid — check return (c_void_p; NULL=success,
        #    non-NULL=failure pointer)
        if entry.get("system_sid_ptr"):
            try:
                ret = self._a.FreeSid(entry["system_sid_ptr"])
            except Exception as fs_exc:
                cleanup_errors.append(
                    SecureStorePermissionError(
                        f"FreeSid(SYSTEM) raised in release: {fs_exc}"
                    )
                )
            else:
                if ret:
                    cleanup_errors.append(
                        SecureStorePermissionError(
                            f"FreeSid(SYSTEM) returned non-NULL in release"
                        )
                    )

        if cleanup_errors:
            _raise_no_primary_cleanup(
                tuple(cleanup_errors), "release_security_context"
            )

    # ------------------------------------------------------------------
    # Security descriptor construction (Blocker #2)
    # ------------------------------------------------------------------

    def build_file_security_descriptor(self, security_context: int) -> int:
        """Build a protected two-ACE SD for a private file.

        Uses SIDs from *security_context* to construct an ACL with two
        ALLOW ACEs (user + SYSTEM), flags=0, FILE_ALL_ACCESS mask, and
        an absolute SECURITY_DESCRIPTOR with SE_DACL_PROTECTED.

        Returns an opaque handle; caller must release via
        ``free_security_descriptor``.

        Validates SYSTEM SID length > 0 before ACL allocation.
        For every post-ACL failure, preserves exact primary and
        attempts LocalFree once (both non-NULL return and raised
        exception).  No ``_sd_store`` publication on failure.
        """
        self._ensure_init()
        k = self._k
        a = self._a

        entry = self._security_contexts.get(security_context)
        if entry is None:
            raise SecureStorePermissionError(
                f"Security context {security_context} is not valid for SD build"
            )

        user_sid_buf = entry["user_sid_buf"]
        user_sid_len = entry["user_sid_len"]
        system_sid_ptr = entry["system_sid_ptr"]

        user_sid_ptr = _ct.c_void_p(user_sid_buf)
        sys_sid_len = a.GetLengthSid(system_sid_ptr)
        # Defect 6: validate SYSTEM SID length > 0 before ACL allocation
        if sys_sid_len == 0:
            raise SecureStorePermissionError(
                "GetLengthSid returned 0 for SYSTEM SID in SD build"
            )

        # ACE size formula
        _ace_base = _ct.sizeof(_ACCESS_ALLOWED_ACE) - _ct.sizeof(_ct.c_uint32)
        user_ace_sz = _ace_base + user_sid_len
        sys_ace_sz = _ace_base + sys_sid_len
        acl_size = _ct.sizeof(_ACL) + user_ace_sz + sys_ace_sz

        acl_mem = k.LocalAlloc(_LMEM_FIXED, acl_size)
        if not acl_mem:
            raise SecureStorePermissionError(
                f"LocalAlloc(ACL) failed: {k.GetLastError()}"
            )

        sd_handle = 0
        try:
            acl_ptr = _ct.c_void_p(acl_mem)
            if not a.InitializeAcl(acl_ptr, acl_size, _ACL_REVISION_DS):
                raise SecureStorePermissionError(
                    f"InitializeAcl failed: {k.GetLastError()}"
                )

            # Add user ACE (flags=0 for file)
            if not a.AddAccessAllowedAceEx(
                acl_ptr, _ACL_REVISION_DS, 0, _FILE_ALL_ACCESS, user_sid_ptr,
            ):
                raise SecureStorePermissionError(
                    f"AddAccessAllowedAceEx(user) failed: {k.GetLastError()}"
                )
            # Add SYSTEM ACE (flags=0 for file)
            if not a.AddAccessAllowedAceEx(
                acl_ptr, _ACL_REVISION_DS, 0, _FILE_ALL_ACCESS,
                _ct.c_void_p(system_sid_ptr),
            ):
                raise SecureStorePermissionError(
                    f"AddAccessAllowedAceEx(SYSTEM) failed: {k.GetLastError()}"
                )

            # Build absolute SECURITY_DESCRIPTOR (ctypes struct, stack)
            sd = _SECURITY_DESCRIPTOR()
            if not a.InitializeSecurityDescriptor(
                _ct.byref(sd), _SECURITY_DESCRIPTOR_REVISION,
            ):
                raise SecureStorePermissionError(
                    f"InitializeSecurityDescriptor failed: {k.GetLastError()}"
                )
            if not a.SetSecurityDescriptorDacl(
                _ct.byref(sd), True, acl_ptr, False,
            ):
                raise SecureStorePermissionError(
                    f"SetSecurityDescriptorDacl failed: {k.GetLastError()}"
                )
            if not a.SetSecurityDescriptorControl(
                _ct.byref(sd), _SE_DACL_PROTECTED, _SE_DACL_PROTECTED,
            ):
                raise SecureStorePermissionError(
                    f"SetSecurityDescriptorControl failed: {k.GetLastError()}"
                )

            # Success: publish to store
            sd_handle = _ct.addressof(sd)
            if not hasattr(self, "_sd_store"):
                self._sd_store: dict = {}
            self._sd_store[sd_handle] = {
                "sd": sd,
                "acl_mem": acl_mem,
            }
            return sd_handle
        except BaseException:
            # Defect 6: every post-ACL failure frees ACL once.
            # Preserve exact primary; handle LocalFree non-NULL and raised
            # exception without replacing primary.
            import sys as _sys
            primary = _sys.exc_info()[1]
            if primary is not None:
                try:
                    freed = k.LocalFree(acl_mem)
                except Exception as lf_exc:
                    _attach_cleanup_errors(
                        primary,
                        (SecureStorePermissionError(
                            f"LocalFree(ACL) raised in build_file_security_descriptor: {lf_exc}"
                        ),),
                    )
                else:
                    if freed:
                        _attach_cleanup_errors(
                            primary,
                            (SecureStorePermissionError(
                                f"LocalFree(ACL) returned non-NULL in build_file_security_descriptor: {freed}"
                            ),),
                        )
            raise

    def free_security_descriptor(self, sd_handle: int) -> None:
        """Release a security descriptor handle returned by
        ``build_file_security_descriptor``.

        Must be idempotent: releasing a zero or already-released handle
        is a no-op.

        Consume store first; LocalFree non-NULL or raised exception
        surfaced once; second free has no native call.
        """
        if sd_handle == 0:
            return
        self._ensure_init()
        # Consume entry BEFORE LocalFree — one attempt, no retry
        entry = getattr(self, "_sd_store", {}).pop(sd_handle, None)
        if entry is None:
            return  # idempotent: already released or unknown
        acl_mem = entry.get("acl_mem")
        if acl_mem:
            try:
                freed = self._k.LocalFree(acl_mem)
            except Exception as lf_exc:
                raise SecureStorePermissionError(
                    f"LocalFree(ACL) raised in free_security_descriptor: {lf_exc}"
                )
            else:
                if freed:
                    raise SecureStorePermissionError(
                        f"LocalFree(ACL) returned non-NULL in free_security_descriptor: {freed}"
                    )
        # SD struct is stack (ctypes), freed automatically
        # SIDs are owned by the security context, not us


# ---------------------------------------------------------------------------
# Win32 error mapping
# ---------------------------------------------------------------------------


def _win_raise_error(code: int, operation: str, path: str = "") -> None:
    if code in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
        raise FileNotFoundError(f"{operation} failed{f' ({path})' if path else ''}")
    if code in (_ERROR_ACCESS_DENIED, _ERROR_PRIVILEGE_NOT_HELD):
        raise SecureStorePermissionError(
            f"{operation} denied{f' ({path})' if path else ''}"
        )
    if code in (_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS):
        raise FileExistsError(f"{operation} exists{f' ({path})' if path else ''}")
    raise OSError(f"{operation} failed (code {code}){f' ({path})' if path else ''}")


# ---------------------------------------------------------------------------
# Windows secret backend  (injectable for tests)
# ---------------------------------------------------------------------------


class _WinSecretBackend:
    """Injectable backend for Windows secret-store operations."""

    def ensure_secure_directory(self, path: str) -> None:
        raise NotImplementedError

    def create_private_file(self, directory: str, leaf_name: str) -> int:
        raise NotImplementedError


class _RealWinSecretBackend(_WinSecretBackend):
    """Production backend — real ctypes calls to kernel32 + advapi32."""

    def __init__(self) -> None:
        self._initialized = False
        self._k = None
        self._a = None
        self._invalid_handle = _ct.c_void_p(-1).value

    # ------------------------------------------------------------------
    # Initialization — _initialized=True only after full success
    # ------------------------------------------------------------------

    def _init(self) -> None:
        if self._initialized:
            return

        k = _ct.WinDLL("kernel32", use_last_error=True)
        a = _ct.WinDLL("advapi32", use_last_error=True)

        # kernel32 prototypes
        k.CreateDirectoryW.restype = _wt.BOOL
        k.CreateDirectoryW.argtypes = [_wt.LPCWSTR, _ct.c_void_p]

        k.CreateFileW.restype = _wt.HANDLE
        k.CreateFileW.argtypes = [
            _wt.LPCWSTR, _wt.DWORD, _wt.DWORD,
            _ct.c_void_p, _wt.DWORD, _wt.DWORD, _wt.HANDLE,
        ]

        k.CloseHandle.restype = _wt.BOOL
        k.CloseHandle.argtypes = [_wt.HANDLE]

        k.GetLastError.restype = _wt.DWORD
        k.GetLastError.argtypes = []

        k.GetCurrentProcess.restype = _wt.HANDLE
        k.GetCurrentProcess.argtypes = []

        k.GetFileInformationByHandle.restype = _wt.BOOL
        k.GetFileInformationByHandle.argtypes = [
            _wt.HANDLE, _ct.POINTER(_BY_HANDLE_FILE_INFO),
        ]

        k.GetFileType.restype = _wt.DWORD
        k.GetFileType.argtypes = [_wt.HANDLE]

        k.LocalFree.restype = _wt.HLOCAL
        k.LocalFree.argtypes = [_wt.HLOCAL]

        k.LocalAlloc.restype = _wt.HLOCAL
        k.LocalAlloc.argtypes = [_wt.UINT, _ct.c_size_t]

        # advapi32 prototypes
        a.OpenProcessToken.restype = _wt.BOOL
        a.OpenProcessToken.argtypes = [
            _wt.HANDLE, _wt.DWORD, _ct.POINTER(_wt.HANDLE),
        ]

        a.GetTokenInformation.restype = _wt.BOOL
        a.GetTokenInformation.argtypes = [
            _wt.HANDLE, _ct.c_int, _ct.c_void_p, _wt.DWORD,
            _ct.POINTER(_wt.DWORD),
        ]

        a.AllocateAndInitializeSid.restype = _wt.BOOL
        a.AllocateAndInitializeSid.argtypes = [
            _ct.POINTER(_SID_IDENTIFIER_AUTHORITY), _ct.c_byte,
            _wt.DWORD, _wt.DWORD, _wt.DWORD, _wt.DWORD,
            _wt.DWORD, _wt.DWORD, _wt.DWORD, _wt.DWORD,
            _ct.POINTER(_ct.c_void_p),
        ]

        a.FreeSid.restype = _ct.c_void_p
        a.FreeSid.argtypes = [_ct.c_void_p]

        a.InitializeAcl.restype = _wt.BOOL
        a.InitializeAcl.argtypes = [_ct.c_void_p, _wt.DWORD, _wt.DWORD]

        a.AddAccessAllowedAceEx.restype = _wt.BOOL
        a.AddAccessAllowedAceEx.argtypes = [
            _ct.c_void_p, _wt.DWORD, _wt.DWORD, _wt.DWORD, _ct.c_void_p,
        ]

        a.InitializeSecurityDescriptor.restype = _wt.BOOL
        a.InitializeSecurityDescriptor.argtypes = [_ct.c_void_p, _wt.DWORD]

        a.SetSecurityDescriptorDacl.restype = _wt.BOOL
        a.SetSecurityDescriptorDacl.argtypes = [
            _ct.c_void_p, _wt.BOOL, _ct.c_void_p, _wt.BOOL,
        ]

        a.SetSecurityDescriptorControl.restype = _wt.BOOL
        a.SetSecurityDescriptorControl.argtypes = [
            _ct.c_void_p, _wt.DWORD, _wt.DWORD,
        ]

        a.GetSecurityDescriptorControl.restype = _wt.BOOL
        a.GetSecurityDescriptorControl.argtypes = [
            _ct.c_void_p, _ct.POINTER(_wt.WORD), _ct.POINTER(_wt.WORD),
        ]

        a.GetSecurityInfo.restype = _wt.DWORD
        a.GetSecurityInfo.argtypes = [
            _wt.HANDLE, _ct.c_int, _wt.DWORD,
            _ct.POINTER(_ct.c_void_p), _ct.POINTER(_ct.c_void_p),
            _ct.POINTER(_ct.c_void_p), _ct.POINTER(_ct.c_void_p),
            _ct.POINTER(_ct.c_void_p),
        ]

        a.GetAclInformation.restype = _wt.BOOL
        a.GetAclInformation.argtypes = [
            _ct.c_void_p, _ct.c_void_p, _wt.DWORD, _ct.c_int,
        ]

        a.GetAce.restype = _wt.BOOL
        a.GetAce.argtypes = [
            _ct.c_void_p, _wt.DWORD, _ct.POINTER(_ct.c_void_p),
        ]

        a.EqualSid.restype = _wt.BOOL
        a.EqualSid.argtypes = [_ct.c_void_p, _ct.c_void_p]

        a.GetLengthSid.restype = _wt.DWORD
        a.GetLengthSid.argtypes = [_ct.c_void_p]

        a.CopySid.restype = _wt.BOOL
        a.CopySid.argtypes = [_wt.DWORD, _ct.c_void_p, _ct.c_void_p]

        a.ConvertSidToStringSidW.restype = _wt.BOOL
        a.ConvertSidToStringSidW.argtypes = [
            _ct.c_void_p, _ct.POINTER(_wt.LPWSTR),
        ]

        # Only set members after all prototypes succeed
        self._k = k
        self._a = a
        self._initialized = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_secure_directory(self, path: str) -> None:
        self._init()
        self._ensure_secure_directory(path)

    def create_private_file(self, directory: str, leaf_name: str) -> int:
        self._init()
        return self._create_private_file(directory, leaf_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_last_error(self) -> int:
        return self._k.GetLastError()

    def _close_handle(self, h: int, op: str, path: str, primary) -> None:
        if h is None or h == self._invalid_handle:
            return
        ok = self._k.CloseHandle(h)
        if not ok and primary is None:
            code = self._get_last_error()
            _win_raise_error(code, f"CloseHandle ({op})", path)

    # ------------------------------------------------------------------
    # ensure_secure_directory
    # ------------------------------------------------------------------

    def _ensure_secure_directory(self, path: str) -> None:
        """Create or validate a secure directory.

        Parent traversal only validates parent components; the leaf may
        be created.  Existing directories are opened and fully verified
        (including DACL) via the same handle.
        """
        # Walk parent components (NOT the final)
        parts = _split_path_components(path)
        if len(parts) > 1:
            parents = parts[:-1]
        else:
            parents = []

        for comp_path in parents:
            self._open_component_checked(comp_path)

        # Try creating the final component
        leaf_path = path  # the full path IS the final component
        h = self._try_open_existing(leaf_path)
        if h is not None:
            # Exists — validate through the same handle
            primary = None
            try:
                self._validate_existing_directory(h, leaf_path)
                # Also verify DACL
                user_sid_buf, system_sid = self._build_expected_sids()
                try:
                    self._verify_dacl(h, user_sid_buf, system_sid, is_directory=True)
                finally:
                    _win_free_sid(system_sid, self._a)
                    # user_sid_buf is a LocalAlloc copy — free it
                    if user_sid_buf:
                        self._k.LocalFree(user_sid_buf)
            except Exception as exc:
                primary = exc
                raise
            finally:
                self._close_handle(h, "validate existing dir", leaf_path, primary)
            return

        # Does not exist — create it
        user_sid_buf, system_sid = self._build_expected_sids()
        sd, sa, acl_mem = self._build_security_descriptor(
            user_sid_buf, system_sid, is_directory=True
        )
        try:
            if not self._k.CreateDirectoryW(leaf_path, _ct.byref(sa)):
                code = self._get_last_error()
                _win_raise_error(code, "CreateDirectoryW", leaf_path)
        finally:
            if acl_mem:
                self._k.LocalFree(acl_mem)

        # Open the created directory and verify
        h = self._try_open_existing(leaf_path)
        if h is None:
            self._k.LocalFree(user_sid_buf)
            _win_free_sid(system_sid, self._a)
            raise SecureStorePermissionError(
                f"Directory not found after creation: {leaf_path!r}"
            )

        primary = None
        try:
            self._validate_existing_directory(h, leaf_path)
            self._verify_dacl(h, user_sid_buf, system_sid, is_directory=True)
        except Exception as exc:
            primary = exc
            raise
        finally:
            self._close_handle(h, "verify created dir", leaf_path, primary)
            _win_free_sid(system_sid, self._a)
            if user_sid_buf:
                self._k.LocalFree(user_sid_buf)

    # ------------------------------------------------------------------
    # create_private_file (Windows)
    # ------------------------------------------------------------------

    def _create_private_file(self, directory: str, leaf_name: str) -> int:
        """Create a private file via CreateFileW with DACL, verify, return fd."""
        # Walk parent traversal for the directory (validated already)
        parts = _split_path_components(directory)
        for comp_path in parts:
            self._open_component_checked(comp_path)

        # Open directory handle to validate it
        dir_h = self._try_open_existing(directory)
        if dir_h is None:
            raise FileNotFoundError(f"Directory does not exist: {directory!r}")

        primary = None
        try:
            self._validate_existing_directory(dir_h, directory)
        except Exception as exc:
            primary = exc
            raise
        finally:
            self._close_handle(dir_h, "validate dir", directory, primary)

        # Build file path
        filepath = _os.path.join(directory, leaf_name)

        # Build security for file (no inheritance flags)
        user_sid_buf, system_sid = self._build_expected_sids()
        acl_mem = None
        handle = None
        fd = -1
        sid_freed = False

        try:
            acl_mem = self._build_acl_mem(
                user_sid_buf, system_sid, is_directory=False
            )
            sd, sa = self._build_sd_from_acl(
                acl_mem, is_directory=False
            )

            # Create the file with SECURITY_ATTRIBUTES
            handle = self._k.CreateFileW(
                filepath,
                _GENERIC_READ | _GENERIC_WRITE,
                0,
                _ct.byref(sa),
                _CREATE_NEW,
                _FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if handle == self._invalid_handle:
                code = self._get_last_error()
                _win_raise_error(code, "CreateFileW", filepath)

            # Verify file type/reparse BEFORE DACL verification
            self._verify_file_type_and_reparse(handle, filepath)

            # Verify DACL
            self._verify_dacl(handle, user_sid_buf, system_sid, is_directory=False)

            # Convert HANDLE to CRT fd — ownership transfers
            fd_flags = _os.O_WRONLY
            if hasattr(_os, "O_BINARY"):
                fd_flags |= _os.O_BINARY
            try:
                if _msvcrt is None:
                    raise SecureStorePermissionError("msvcrt not available")
                fd = _msvcrt.open_osfhandle(handle, fd_flags)
            except Exception:
                # Conversion failed — CloseHandle
                self._k.CloseHandle(handle)
                handle = None
                raise

            if fd < 0:
                self._k.CloseHandle(handle)
                handle = None
                raise SecureStorePermissionError(
                    f"open_osfhandle failed for {filepath!r}"
                )

            # Ownership transferred — don't CloseHandle
            handle = None

        except Exception:
            if handle is not None:
                self._k.CloseHandle(handle)
            raise
        finally:
            # Free resources (SIDs not owned by CRT fd)
            _win_free_sid(system_sid, self._a)
            sid_freed = True
            if user_sid_buf:
                self._k.LocalFree(user_sid_buf)
                user_sid_buf = None
            if acl_mem:
                self._k.LocalFree(acl_mem)
                acl_mem = None

        return fd

    # ------------------------------------------------------------------
    # File type / reparse verification (on handle)
    # ------------------------------------------------------------------

    def _verify_file_type_and_reparse(self, handle: int, path: str) -> None:
        """Verify the handle is a disk file, not a reparse point or directory."""
        info = _BY_HANDLE_FILE_INFO()
        if not self._k.GetFileInformationByHandle(handle, _ct.byref(info)):
            code = self._get_last_error()
            _win_raise_error(code, "GetFileInformationByHandle", path)

        if info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise SecureStorePermissionError(
                f"File is a reparse point: {path!r}"
            )
        if info.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise SecureStorePermissionError(
                f"File is a directory: {path!r}"
            )

        ftype = self._k.GetFileType(handle)
        if ftype == _FILE_TYPE_UNKNOWN:
            if self._get_last_error() != 0:
                code = self._get_last_error()
                _win_raise_error(code, "GetFileType", path)
            raise SecureStorePermissionError(
                f"File type is unknown: {path!r}"
            )
        if ftype != _FILE_TYPE_DISK:
            raise SecureStorePermissionError(
                f"File is not a disk file (type={ftype}): {path!r}"
            )

    # ------------------------------------------------------------------
    # Parent traversal
    # ------------------------------------------------------------------

    def _open_component_checked(self, comp_path: str) -> None:
        """Open a path component as directory, reject reparse/non-directory."""
        h = self._k.CreateFileW(
            comp_path,
            _GENERIC_READ,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if h == self._invalid_handle:
            code = self._get_last_error()
            _win_raise_error(code, "CreateFileW (component)", comp_path)

        primary = None
        try:
            info = _BY_HANDLE_FILE_INFO()
            if not self._k.GetFileInformationByHandle(h, _ct.byref(info)):
                code = self._get_last_error()
                _win_raise_error(code, "GetFileInformationByHandle", comp_path)
            if info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise SecureStorePermissionError(
                    f"Path component is a reparse point: {comp_path!r}"
                )
            if not (info.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY):
                raise SecureStorePermissionError(
                    f"Path component is not a directory: {comp_path!r}"
                )
        except Exception as exc:
            primary = exc
            raise
        finally:
            self._close_handle(h, "component", comp_path, primary)

    # ------------------------------------------------------------------
    # Directory open/validate
    # ------------------------------------------------------------------

    def _try_open_existing(self, path: str) -> int | None:
        """Try to open *path* as an existing directory.  Returns handle or None."""
        h = self._k.CreateFileW(
            path,
            _GENERIC_READ,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if h == self._invalid_handle:
            code = self._get_last_error()
            if code in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
                return None
            _win_raise_error(code, "CreateFileW (open existing)", path)
        return h

    def _validate_existing_directory(self, handle: int, path: str) -> None:
        """Validate an already-open existing directory handle."""
        info = _BY_HANDLE_FILE_INFO()
        if not self._k.GetFileInformationByHandle(handle, _ct.byref(info)):
            code = self._get_last_error()
            _win_raise_error(code, "GetFileInformationByHandle", path)
        if info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise SecureStorePermissionError(
                f"Directory is a reparse point: {path!r}"
            )
        if not (info.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY):
            raise SecureStorePermissionError(
                f"Not a directory: {path!r}"
            )

    # ------------------------------------------------------------------
    # SID management
    # ------------------------------------------------------------------

    def _build_expected_sids(self) -> tuple[int, int]:
        """Build expected user and system SIDs.

        Returns ``(user_sid_buf, system_sid)`` where:

        - *user_sid_buf* is a ``LocalAlloc``'d copy of the current-user
          SID.  Caller must ``LocalFree`` it.
        - *system_sid* was created by ``AllocateAndInitializeSid``.
          Caller must ``FreeSid`` it.
        """
        token = _wt.HANDLE()
        if not self._a.OpenProcessToken(
            self._k.GetCurrentProcess(), _TOKEN_QUERY, _ct.byref(token)
        ):
            code = self._get_last_error()
            _win_raise_error(code, "OpenProcessToken")

        try:
            # Get token user SID — copy via LocalAlloc+CopySid
            user_sid_buf = self._copy_token_user_sid(token)

            # Create LocalSystem SID — allocated by AllocateAndInitializeSid
            system_sid = self._make_well_known_sid(_SECURITY_LOCAL_SYSTEM_RID)
        finally:
            self._k.CloseHandle(token)

        return user_sid_buf, system_sid

    def _copy_token_user_sid(self, token: int) -> int:
        """Return a LocalAlloc copy of the token's user SID. Caller LocalFree's."""
        needed = _wt.DWORD()
        self._a.GetTokenInformation(
            token, _TOKEN_USER_INFO, None, 0, _ct.byref(needed)
        )
        bufsize = needed.value
        buf = _ct.create_string_buffer(bufsize)
        if not self._a.GetTokenInformation(
            token, _TOKEN_USER_INFO, buf, bufsize, _ct.byref(needed)
        ):
            code = self._get_last_error()
            _win_raise_error(code, "GetTokenInformation")

        tu = _TOKEN_USER.from_buffer(buf)
        sid_len = self._a.GetLengthSid(tu.User.Sid)
        if sid_len == 0:
            raise SecureStorePermissionError("GetLengthSid returned 0 for user SID")

        # Copy into LocalAlloc buffer (caller frees with LocalFree)
        sid_copy = self._k.LocalAlloc(_LMEM_FIXED, sid_len)
        if not sid_copy:
            code = self._get_last_error()
            _win_raise_error(code, "LocalAlloc (user SID copy)")

        if not self._a.CopySid(sid_len, sid_copy, tu.User.Sid):
            self._k.LocalFree(sid_copy)
            code = self._get_last_error()
            _win_raise_error(code, "CopySid")
        return sid_copy

    def _make_well_known_sid(self, rid: int, *sub_auths: int) -> int:
        """Create a well-known SID with NT AUTHORITY.  Caller FreeSid's."""
        auth = _SID_IDENTIFIER_AUTHORITY()
        _ct.memmove(auth.Value, _SECURITY_NT_AUTHORITY_VAL, 6)
        sid_ptr = _ct.c_void_p()
        sub_count = 1 + len(sub_auths)
        args = [
            _ct.byref(auth),
            _ct.c_byte(sub_count),
            _wt.DWORD(rid),
        ] + [
            _wt.DWORD(s) for s in sub_auths
        ]
        # Pad to 8 sub-authorities
        while len(args) < 10:
            args.append(_wt.DWORD(0))
        args.append(_ct.byref(sid_ptr))
        if not self._a.AllocateAndInitializeSid(*args):
            code = self._get_last_error()
            _win_raise_error(code, "AllocateAndInitializeSid")
        return sid_ptr.value

    # ------------------------------------------------------------------
    # ACL construction
    # ------------------------------------------------------------------

    def _build_acl_mem(
        self, user_sid: int, system_sid: int, is_directory: bool
    ) -> int:
        """Build an ACL with 2 ALLOW ACEs (FILE_ALL_ACCESS). Returns LocalAlloc ptr.

        Caller must LocalFree the returned memory.
        """
        user_sid_len = self._a.GetLengthSid(user_sid)
        sys_sid_len = self._a.GetLengthSid(system_sid)

        # ACE size formula: sizeof(ACCESS_ALLOWED_ACE) - sizeof(DWORD) + GetLengthSid
        ace_base = _ct.sizeof(_ACCESS_ALLOWED_ACE) - _ct.sizeof(_ct.c_uint32)
        user_ace_size = ace_base + user_sid_len
        sys_ace_size = ace_base + sys_sid_len

        acl_size = _ct.sizeof(_ACL) + user_ace_size + sys_ace_size
        acl_mem = self._k.LocalAlloc(_LMEM_FIXED, acl_size)
        if not acl_mem:
            code = self._get_last_error()
            _win_raise_error(code, "LocalAlloc (ACL)")

        acl_ptr = _ct.cast(acl_mem, _ct.c_void_p)
        if not self._a.InitializeAcl(acl_ptr, acl_size, _ACL_REVISION_DS):
            self._k.LocalFree(acl_mem)
            code = self._get_last_error()
            _win_raise_error(code, "InitializeAcl")

        ace_flags = (
            (_CONTAINER_INHERIT_ACE | _OBJECT_INHERIT_ACE)
            if is_directory else 0
        )

        if not self._a.AddAccessAllowedAceEx(
            acl_ptr, _ACL_REVISION_DS, ace_flags, _FILE_ALL_ACCESS, user_sid
        ):
            self._k.LocalFree(acl_mem)
            code = self._get_last_error()
            _win_raise_error(code, "AddAccessAllowedAceEx (user)")

        if not self._a.AddAccessAllowedAceEx(
            acl_ptr, _ACL_REVISION_DS, ace_flags, _FILE_ALL_ACCESS, system_sid
        ):
            self._k.LocalFree(acl_mem)
            code = self._get_last_error()
            _win_raise_error(code, "AddAccessAllowedAceEx (system)")

        return acl_mem

    def _build_sd_from_acl(
        self, acl_mem: int, is_directory: bool
    ) -> tuple[_SECURITY_DESCRIPTOR, _SECURITY_ATTRIBUTES]:
        """Build an absolute SECURITY_DESCRIPTOR + SECURITY_ATTRIBUTES.

        Returns (sd, sa).  The sd is stack-allocated (ctypes struct).
        Caller must keep it alive while sa is used.
        """
        sd = _SECURITY_DESCRIPTOR()
        if not self._a.InitializeSecurityDescriptor(
            _ct.byref(sd), _SECURITY_DESCRIPTOR_REVISION
        ):
            code = self._get_last_error()
            _win_raise_error(code, "InitializeSecurityDescriptor")

        acl_ptr = _ct.cast(acl_mem, _ct.c_void_p)
        if not self._a.SetSecurityDescriptorDacl(
            _ct.byref(sd), True, acl_ptr, False
        ):
            code = self._get_last_error()
            _win_raise_error(code, "SetSecurityDescriptorDacl")

        # Mark DACL as protected
        if not self._a.SetSecurityDescriptorControl(
            _ct.byref(sd), _SE_DACL_PROTECTED, _SE_DACL_PROTECTED
        ):
            code = self._get_last_error()
            _win_raise_error(code, "SetSecurityDescriptorControl")

        sa = _SECURITY_ATTRIBUTES()
        sa.nLength = _ct.sizeof(_SECURITY_ATTRIBUTES)
        sa.lpSecurityDescriptor = _ct.addressof(sd)
        sa.bInheritHandle = False

        return sd, sa

    def _build_security_descriptor(
        self, user_sid: int, system_sid: int, is_directory: bool
    ) -> tuple[_SECURITY_DESCRIPTOR, _SECURITY_ATTRIBUTES, int]:
        """Build full security descriptor + SA + ACL memory.

        Returns (sd, sa, acl_mem).  Caller must keep sd/sa alive while
        in use and LocalFree acl_mem when done.
        """
        acl_mem = self._build_acl_mem(user_sid, system_sid, is_directory)
        sd, sa = self._build_sd_from_acl(acl_mem, is_directory)
        return sd, sa, acl_mem

    # ------------------------------------------------------------------
    # DACL verification
    # ------------------------------------------------------------------

    def _verify_dacl(
        self,
        handle: int,
        user_sid: int,
        system_sid: int,
        is_directory: bool,
    ) -> None:
        """Verify the DACL on *handle* meets all requirements.

        Strict gates:
        - DACL present and non-null.
        - SE_DACL_PROTECTED set.
        - Only ACCESS_ALLOWED_ACE_TYPE ACEs accepted.
        - Exactly 2 ACEs (user + SYSTEM).
        - Mask == FILE_ALL_ACCESS for both.
        - Directory: OI+CI flags, no INHERIT_ONLY/NO_PROPAGATE/INHERITED_ACE.
        - File: no inheritance flags.
        - No forbidden SIDs.
        - BytesInUse <= ACL size.
        """
        sd_ptr = _ct.c_void_p()
        dacl_ptr = _ct.c_void_p()

        ret = self._a.GetSecurityInfo(
            handle,
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
            None, None,
            _ct.byref(dacl_ptr), None,
            _ct.byref(sd_ptr),
        )
        if ret != 0:
            raise SecureStorePermissionError(f"GetSecurityInfo failed: {ret}")

        try:
            # 1. DACL present
            if not dacl_ptr:
                raise SecureStorePermissionError("No DACL present on object")

            # 2. SE_DACL_PROTECTED
            ctrl = _wt.WORD()
            dummy = _wt.WORD()
            if not self._a.GetSecurityDescriptorControl(
                sd_ptr, _ct.byref(ctrl), _ct.byref(dummy)
            ):
                code = self._get_last_error()
                _win_raise_error(code, "GetSecurityDescriptorControl")
            if not (ctrl.value & _SE_DACL_PROTECTED):
                raise SecureStorePermissionError("DACL is not protected")

            # 3. ACL size check
            acl = _ACL.from_address(dacl_ptr.value)
            size_info = _ACL_SIZE_INFORMATION()
            if not self._a.GetAclInformation(
                dacl_ptr, _ct.byref(size_info),
                _ct.sizeof(_ACL_SIZE_INFORMATION), _ACL_SIZE_INFORMATION_CLASS,
            ):
                code = self._get_last_error()
                _win_raise_error(code, "GetAclInformation")

            if size_info.AclBytesInUse > acl.AclSize:
                raise SecureStorePermissionError(
                    f"ACL bytes in use ({size_info.AclBytesInUse}) > size ({acl.AclSize})"
                )

            # 4. Exactly 2 ACEs
            if size_info.AceCount != 2:
                raise SecureStorePermissionError(
                    f"Expected exactly 2 ACEs, got {size_info.AceCount}"
                )

            found_user = False
            found_system = False

            for i in range(size_info.AceCount):
                ace_ptr = _ct.c_void_p()
                if not self._a.GetAce(dacl_ptr, i, _ct.byref(ace_ptr)):
                    code = self._get_last_error()
                    _win_raise_error(code, "GetAce")

                header = _ACE_HEADER.from_address(ace_ptr.value)

                # 5. Only ALLOW ACEs accepted
                if header.AceType != _ACCESS_ALLOWED_ACE_TYPE:
                    raise SecureStorePermissionError(
                        f"Unexpected ACE type {header.AceType} at index {i}"
                    )

                # 6. No inherited ACEs
                if header.AceFlags & _INHERITED_ACE:
                    raise SecureStorePermissionError(
                        f"Inherited ACE at index {i}"
                    )

                ace = _ACCESS_ALLOWED_ACE.from_address(ace_ptr.value)

                # 7. Mask must be FILE_ALL_ACCESS
                if ace.Mask != _FILE_ALL_ACCESS:
                    raise SecureStorePermissionError(
                        f"ACE mask 0x{ace.Mask:08X} != FILE_ALL_ACCESS at index {i}"
                    )

                # 8. Get SID from ACE
                sid_offset = _ct.sizeof(_ACE_HEADER) + _ct.sizeof(_ct.c_uint32)
                ace_sid = _ct.c_void_p(ace_ptr.value + sid_offset)

                # 9. Forbidden SID check — must fail closed
                try:
                    if self._is_forbidden_sid(ace_sid.value):
                        raise SecureStorePermissionError(
                            f"Forbidden SID in ALLOW ACE at index {i}"
                        )
                except Exception:
                    raise SecureStorePermissionError(
                        f"Forbidden SID check failed at index {i}"
                    )

                # 10. Inheritance flags
                if is_directory:
                    expected = _CONTAINER_INHERIT_ACE | _OBJECT_INHERIT_ACE
                    if (header.AceFlags & expected) != expected:
                        raise SecureStorePermissionError(
                            f"Directory ACE missing OI|CI at index {i}"
                        )
                    if header.AceFlags & _INHERIT_ONLY_ACE:
                        raise SecureStorePermissionError(
                            f"INHERIT_ONLY_ACE set at index {i}"
                        )
                    if header.AceFlags & _NO_PROPAGATE_INHERIT_ACE:
                        raise SecureStorePermissionError(
                            f"NO_PROPAGATE_INHERIT_ACE set at index {i}"
                        )
                    # No unexpected flags beyond OI|CI
                    allowed_flags = _CONTAINER_INHERIT_ACE | _OBJECT_INHERIT_ACE
                    if header.AceFlags & ~allowed_flags:
                        raise SecureStorePermissionError(
                            f"Unexpected ACE flags 0x{header.AceFlags:02X} at index {i}"
                        )
                else:
                    if header.AceFlags != 0:
                        raise SecureStorePermissionError(
                            f"File ACE has inheritance flags 0x{header.AceFlags:02X} at index {i}"
                        )

                # 11. Match expected SIDs
                if self._a.EqualSid(ace_sid, user_sid):
                    found_user = True
                elif self._a.EqualSid(ace_sid, system_sid):
                    found_system = True
                else:
                    raise SecureStorePermissionError(
                        f"Unexpected SID in ALLOW ACE at index {i}"
                    )

            if not found_user:
                raise SecureStorePermissionError("User SID not in DACL")
            if not found_system:
                raise SecureStorePermissionError("LocalSystem SID not in DACL")

        finally:
            if sd_ptr:
                self._k.LocalFree(sd_ptr)

    def _is_forbidden_sid(self, sid_ptr: int) -> bool:
        """Return True if *sid_ptr* is Everyone, BUILTIN\\Users, or Auth Users.

        Failures in constructing forbidden SIDs are propagated — we fail
        closed rather than silently accepting.
        """
        a = self._a

        # Everyone: S-1-1-0
        auth_world = _SID_IDENTIFIER_AUTHORITY()
        _ct.memmove(auth_world.Value, bytes([0, 0, 0, 0, 0, 1]), 6)
        everyone = _ct.c_void_p()
        if not a.AllocateAndInitializeSid(
            _ct.byref(auth_world), 1, _SECURITY_WORLD_RID,
            0, 0, 0, 0, 0, 0, 0, _ct.byref(everyone),
        ):
            raise SecureStorePermissionError("Cannot create Everyone SID for check")
        try:
            if a.EqualSid(sid_ptr, everyone.value):
                return True
        finally:
            a.FreeSid(everyone.value)

        # Authenticated Users: S-1-5-11
        auth_nt = _SID_IDENTIFIER_AUTHORITY()
        _ct.memmove(auth_nt.Value, _SECURITY_NT_AUTHORITY_VAL, 6)
        auth_users = _ct.c_void_p()
        if not a.AllocateAndInitializeSid(
            _ct.byref(auth_nt), 1, _SECURITY_AUTHENTICATED_USER_RID,
            0, 0, 0, 0, 0, 0, 0, _ct.byref(auth_users),
        ):
            raise SecureStorePermissionError(
                "Cannot create Authenticated Users SID for check"
            )
        try:
            if a.EqualSid(sid_ptr, auth_users.value):
                return True
        finally:
            a.FreeSid(auth_users.value)

        # BUILTIN\Users: S-1-5-32-545
        auth_nt2 = _SID_IDENTIFIER_AUTHORITY()
        _ct.memmove(auth_nt2.Value, _SECURITY_NT_AUTHORITY_VAL, 6)
        builtin = _ct.c_void_p()
        if not a.AllocateAndInitializeSid(
            _ct.byref(auth_nt2), 2, _SECURITY_BUILTIN_DOMAIN_RID,
            545, 0, 0, 0, 0, 0, 0, _ct.byref(builtin),
        ):
            raise SecureStorePermissionError(
                "Cannot create BUILTIN\\Users SID for check"
            )
        try:
            if a.EqualSid(sid_ptr, builtin.value):
                return True
        finally:
            a.FreeSid(builtin.value)

        return False


# ---------------------------------------------------------------------------
# Backend injection
# ---------------------------------------------------------------------------


_win_backend: _WinSecretBackend | None = None


def _get_win_backend() -> _WinSecretBackend:
    global _win_backend
    if _win_backend is None:
        _win_backend = _RealWinSecretBackend()
    return _win_backend


def _set_win_backend(b: _WinSecretBackend | None) -> None:
    global _win_backend
    _win_backend = b


# ---------------------------------------------------------------------------
# P2-B: retained-handle traversal (Windows)
# ---------------------------------------------------------------------------


def _parse_fixed_drive_components(path: str) -> "tuple[str, list[str]]":
    """Split a strict local-drive absolute path into ``(root, components)``.

    Returns ``("C:\\", ["Users", "u", "aisc"])`` for ``C:\\Users\\u\\aisc``.

    Strict grammar (Fix #1):
    - Drive: exactly ``[A-Za-z]:\\``
    - Rejects ``/`` (forward slash), mixed separators, repeated separators
    - Rejects trailing separator on descendants
    - Rejects empty components
    - Every component passes ``_validate_leaf_name(platform="windows")``
      (which also rejects ``< > \" | ? *``, NUL, control, reserved names)
    - All failures raise ``ValueError`` before any API call
    """
    if not path:
        raise ValueError("path must not be empty")
    if not _is_windows_local_drive_absolute(path):
        raise ValueError(
            f"path must be a strict local drive absolute path: {path!r}"
        )
    # Reject forward-slashes and mixed separators (Fix #1)
    if "/" in path:
        raise ValueError(
            f"path must use only backslashes, not forward slashes: {path!r}"
        )
    # Validate drive letter: explicit ASCII [A-Za-z] (Blocker #1)
    if not (path[0].isascii() and path[0].isalpha() and path[1] == ":" and path[2] == "\\"):
        raise ValueError(f"invalid drive format: {path!r}")

    root = path[:3]  # "C:\\"
    rest = path[3:] if len(path) > 3 else ""

    # Reject root-boundary repeated separator (Blocker #1)
    if rest.startswith("\\"):
        raise ValueError(f"path has repeated separator after drive root: {path!r}")
    # Reject repeated separators (empty components) and trailing separator
    if "\\\\" in rest:
        raise ValueError(f"path contains repeated separators: {path!r}")
    if rest.endswith("\\"):
        raise ValueError(f"path has trailing backslash: {path!r}")

    parts = rest.split("\\") if rest else []
    if not parts and len(path) > 3:
        raise ValueError(f"path must not end with separator: {path!r}")
    # Reject any empty component from split (Blocker #1)
    for comp in parts:
        if not comp:
            raise ValueError(f"path contains empty component: {path!r}")

    # Validate each component through Win32 leaf grammar
    for comp in parts:
        _validate_leaf_name(comp, platform="windows")
    return root, parts


def _traverse_retained_handle(
    path: str,
    api: "_WinLowLevelAPI",
    final_access_extra: int = 0,
) -> int:
    """Open a Windows directory path using retained-handle traversal (P2‑B).

    Algorithm:
    1. Parse into drive root + component names.
    2. Verify ``drive_type`` returns ``DRIVE_FIXED``.
    3. ``open_root`` (full path only here).
    4. Validate root.
    5. For each component: relative open (FILE_OPEN), validate child while
       parent is live, close parent, child becomes new parent.
       Intermediate components use least‑privilege access.
       The **final** component adds *final_access_extra* to desired access
       (e.g. ``_READ_CONTROL`` for DACL inspection on the target directory).
    6. Return final validated HANDLE.

    Ownership contract:
    - Every acquired HANDLE closed at most once (exactly once on failure,
      transferred-to-caller on success).
    - Close failures: no-primary → ``_raise_no_primary_cleanup()``;
      with-primary → appended to primary via ``_attach_cleanup_errors``.
    - Intermediate parent close failure → do NOT continue traversal;
      child enters unwind.
    """
    root, components = _parse_fixed_drive_components(path)

    # 1. Drive-type check
    dt = api.drive_type(root)
    if dt != _DRIVE_FIXED:
        raise SecureStorePermissionError(
            f"Drive {root!r} type={dt}, expected DRIVE_FIXED ({_DRIVE_FIXED})"
        )

    handles: list[int] = []       # acquired, not yet transferred/closed
    primary: BaseException | None = None

    _base_access = _FILE_READ_ATTRIBUTES | _FILE_TRAVERSE | _SYNCHRONIZE
    _base_options = (
        _FILE_DIRECTORY_FILE
        | _FILE_OPEN_REPARSE_POINT
        | _FILE_OPEN_FOR_BACKUP_INTENT
        | _FILE_SYNCHRONOUS_IO_NONALERT
    )

    try:
        # 2. Open root — only full-path boundary
        root_handle = api.open_root(root)
        handles.append(root_handle)

        # 3. Validate root
        _validate_traversal_directory(root_handle, root, api)

        # 4. Root-only → return directly
        if not components:
            handles.clear()  # transferred to caller — no cleanup
            return root_handle

        current_parent = root_handle

        # 5. Retained-handle traversal
        for idx, comp in enumerate(components):
            is_final = (idx == len(components) - 1)
            access = _base_access | (final_access_extra if is_final else 0)

            child_handle, ntstatus, info = api.nt_create_file(
                relative_name=comp,
                root_directory=current_parent,
                desired_access=access,
                share_access=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
                create_disposition=_FILE_OPEN,
                create_options=_base_options,
            )
            if child_handle == 0:
                _convert_and_raise_ntstatus(
                    ntstatus, api.ntstatus_to_winerror,
                )

            handles.append(child_handle)

            # 6. Validate child while parent still live (Fix #2)
            _validate_traversal_directory(child_handle, comp, api)

            # 7. Close parent — on failure, child enters unwind (Blocker #2)
            handles.remove(current_parent)
            try:
                api.close_handle(current_parent)
            except Exception as e:
                # Parent close failed — no-operation-primary cleanup failure.
                # Do NOT continue traversal.  Raise cleanup error directly.
                _raise_no_primary_cleanup((e,), f"close parent {comp!r}")

            current_parent = child_handle

        # 8. Success — final handle transferred to caller
        handles.remove(current_parent)
        return current_parent

    except BaseException as exc:
        primary = exc
        raise
    finally:
        # Cleanup: close every handle still in handles list
        cleanup_errs: list[BaseException] = []
        for h in reversed(handles):
            try:
                api.close_handle(h)
            except Exception as e:
                cleanup_errs.append(e)
        if primary is not None:
            if cleanup_errs:
                _attach_cleanup_errors(primary, tuple(cleanup_errs))
        elif cleanup_errs:
            _raise_no_primary_cleanup(tuple(cleanup_errs), "traversal cleanup")


def _validate_traversal_directory(handle: int, name: str, api: "_WinLowLevelAPI") -> None:
    """Validate *handle* is a disk directory, not a reparse point."""
    info = api.get_file_info(handle)
    if info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise SecureStorePermissionError(
            f"Component {name!r} is a reparse point"
        )
    if not (info.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY):
        raise SecureStorePermissionError(
            f"Component {name!r} is not a directory"
        )
    ftype = api.get_file_type(handle)
    if ftype != _FILE_TYPE_DISK:
        raise SecureStorePermissionError(
            f"Component {name!r} file type={ftype}, expected DISK ({_FILE_TYPE_DISK})"
        )


# ---------------------------------------------------------------------------
# P2-C: traverse-or-create directory leaf  (FILE_OPEN_IF)
# ---------------------------------------------------------------------------


def _traverse_or_create_directory(
    path: str,
    api: "_WinLowLevelAPI",
) -> "tuple[int, bool]":
    """Open or create the final directory leaf via retained-handle traversal (P2‑C).

    Traverses parent components via P2‑B retained‑handle pattern, then opens
    or creates the final leaf using NtCreateFile ``FILE_OPEN_IF``.

    Classification (created vs opened) is determined **solely** from IOSB
    Information (``FILE_CREATED_INFO`` / ``FILE_OPENED_INFO``).

    The root is the sole full‑path boundary.  Every descendant ObjectName is
    one validated component relative to the retained live parent.

    Returns ``(handle, created)`` where *handle* is a live, caller‑owned
    HANDLE and *created* is ``True`` when the leaf was newly created.

    Ownership contract:
    - Parent HANDLE closed **only after** child validation succeeds.
    - On failure all acquired HANDLEs enter cleanup in reverse order.
    - Close failures follow ``cleanup_errors`` contract.

    P3‑B: Rollback for created directories.
    - Identities captured immediately after FILE_CREATED_INFO classification,
      before validation.  Only known‑created usable HANDLEs are eligible for
      rollback (FILE_OPENED / collision / invalid-IOBS / failed-create /
      pre-existing: close only, never delete).
    - On rollback: re‑read identity from same live HANDLE just before
      disposition, compare complete tuple, never dispose on identity read
      failure or mismatch.
    - Post‑create failures (validation, parent close, other pre‑return errors)
      all go through identity‑checked rollback.
    - Disposition failure or identity mismatch raises
      ``SecureStoreResidualError(primary=primary)`` from primary;
      cleanup_errors ordered: identity/disposition error, leaf close, parent close.
    - Successful disposition → close leaf; close failures appended to primary.
    """
    root, components = _parse_fixed_drive_components(path)

    # P2‑C requires at least one descendant component
    if not components:
        raise SecureStorePermissionError(
            f"P2‑C traverse-or-create requires at least one component beyond root"
        )

    # Drive-type gate
    dt = api.drive_type(root)
    if dt != _DRIVE_FIXED:
        raise SecureStorePermissionError(
            f"Drive {root!r} type={dt}, expected DRIVE_FIXED ({_DRIVE_FIXED})"
        )

    # Split: parent path (all but last) + leaf
    parent_components = components[:-1]
    leaf = components[-1]

    # Build parent path string (for P2‑B reuse)
    if parent_components:
        parent_path = root + "\\".join(parent_components)
    else:
        parent_path = root

    primary: BaseException | None = None
    parent_handle: int = 0
    leaf_handle: int = 0
    created = False
    identity: "tuple[int, int, int] | None" = None

    try:
        # Traverse to parent via P2‑B retained‑handle pattern
        parent_handle = _traverse_retained_handle(parent_path, api)

        # P2‑C + P3‑B: FILE_OPEN_IF on final leaf, relative to live parent
        # Include DELETE so the created directory can be rolled back.
        desired = (
            _FILE_READ_ATTRIBUTES | _FILE_TRAVERSE | _SYNCHRONIZE | _DELETE
        )
        create_opts = (
            _FILE_DIRECTORY_FILE
            | _FILE_OPEN_REPARSE_POINT
            | _FILE_OPEN_FOR_BACKUP_INTENT
            | _FILE_SYNCHRONOUS_IO_NONALERT
        )

        leaf_handle, ntstatus, info = api.nt_create_file(
            relative_name=leaf,
            root_directory=parent_handle,
            desired_access=desired,
            share_access=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            create_disposition=_FILE_OPEN_IF,
            create_options=create_opts,
        )

        if leaf_handle == 0:
            _convert_and_raise_ntstatus(
                ntstatus, api.ntstatus_to_winerror,
            )
            # unreachable — _convert_and_raise_ntstatus always raises

        # Classify created vs opened **solely** from IOSB Information
        if info == _FILE_CREATED_INFO:
            created = True
        elif info == _FILE_OPENED_INFO:
            created = False
        else:
            # Unexpected/invalid IOSB — ordinary classification failure,
            # close once only, no validation/disposition/deletion.
            raise SecureStorePermissionError(
                f"Unexpected IOSB Information={info} for FILE_OPEN_IF on {leaf!r}"
            )

        # P3‑B: Capture identity immediately after created classification,
        # before validation — only for created directories.
        if created:
            try:
                identity = api.get_handle_identity(leaf_handle)
            except Exception as e:
                # Identity capture failure — cannot safely roll back.
                # .primary and .__cause__ = exact native identity exception.
                # cleanup_errors[0] = distinct rollback-prohibition error
                # (never the primary), then close error if any.
                identity = None
                prohibition = SecureStorePermissionError(
                    f"Rollback prohibited: identity capture failed for "
                    f"created directory {leaf!r}"
                )
                cleanup: list[BaseException] = [prohibition]
                try:
                    api.close_handle(leaf_handle)
                except Exception as ce:
                    cleanup.append(ce)
                leaf_handle = 0
                raise SecureStoreResidualError(
                    f"Rollback identity ambiguous for {leaf!r}",
                    primary=e,
                    cleanup_errors=tuple(cleanup),
                ) from e

        # Validate leaf (directory, non‑reparse, disk) while parent is live
        _validate_traversal_directory(leaf_handle, leaf, api)

        # Close parent only after child validation succeeds.
        # Consume ownership before the first close attempt so a failed
        # close cannot be retried by outer finally.
        _parent_to_close = parent_handle
        parent_handle = 0
        try:
            api.close_handle(_parent_to_close)
        except Exception as e:
            # Parent close failed — if created, rollback leaf before raising.
            # Consume leaf ownership before rollback so identity-read/
            # mismatch/disposition failures cannot retry via outer except/finally.
            if created and identity is not None:
                _leaf_to_rb_parent_close = leaf_handle
                leaf_handle = 0
                _rollback_created_dir(_leaf_to_rb_parent_close, parent_handle,
                                      leaf, identity, api, e)
            # Child leaked, unwind both
            _raise_no_primary_cleanup((e,), f"close parent after FILE_OPEN_IF {leaf!r}")

        # Success — parent is closed, leaf transferred to caller
        result_handle = leaf_handle
        leaf_handle = 0
        return result_handle, created

    except BaseException as exc:
        primary = exc
        # P3‑B: Rollback created directory on any post-creation failure.
        # Consume caller leaf HANDLE ownership before rollback so all
        # residual branches (identity re-read failure, mismatch,
        # disposition failure) close that HANDLE exactly once and
        # outer finally cannot retry.
        if created and identity is not None and leaf_handle > 0:
            _leaf_to_rb = leaf_handle
            leaf_handle = 0
            try:
                _rollback_created_dir(_leaf_to_rb, parent_handle, leaf,
                                      identity, api, primary)
            except SecureStoreResidualError as residual:
                # Failed/ambiguous rollback — residual already carries
                # identity/disposition + close errors with primary set.
                # Attach remaining handles' close errors that this scope owns.
                if parent_handle > 0:
                    try:
                        api.close_handle(parent_handle)
                    except Exception as ce:
                        residual.cleanup_errors = residual.cleanup_errors + (ce,)
                    parent_handle = 0
                # Re-raise residual from primary (not from itself)
                raise residual from primary
        raise
    finally:
        # Cleanup: close any remaining handles (leaf_handle, then parent_handle)
        cleanup_errs: list[BaseException] = []
        for h in (leaf_handle, parent_handle):
            if h == 0:
                continue
            try:
                api.close_handle(h)
            except Exception as e:
                cleanup_errs.append(e)
        if primary is not None:
            if cleanup_errs:
                _attach_cleanup_errors(primary, tuple(cleanup_errs))
        elif cleanup_errs:
            _raise_no_primary_cleanup(
                tuple(cleanup_errs), "traverse_or_create_directory cleanup"
            )


def _rollback_created_dir(
    leaf_handle: int,
    parent_handle: int,
    leaf: str,
    identity: "tuple[int, int, int]",
    api: "_WinLowLevelAPI",
    primary: BaseException,
) -> None:
    """P3‑B: Rollback a created directory leaf.

    Receives the exact original *primary* so that identity/disposition
    failures raise ``SecureStoreResidualError(primary=primary)`` from
    primary.  On disposition success + close failure: appends close error
    to primary, raises primary.  Consumes ownership before one close
    attempt; no retry.

    1. Re‑read identity from same live HANDLE via ``get_handle_identity``.
    2. Compare complete tuple against *identity*.
    3. On match: ``set_delete_disposition(leaf_handle)`` (one‑shot).
    4. Close leaf_handle (disposition takes effect on final close).
    5. All failure paths raise from *primary* with
       ``cleanup_errors`` ordered: identity/disposition error, leaf close.
    """
    # 1. Re-read identity from live HANDLE
    try:
        current_identity = api.get_handle_identity(leaf_handle)
    except Exception as e:
        rb_err = SecureStorePermissionError(
            f"Rollback: cannot re-read identity for directory {leaf!r}: {e}"
        )
        errs = [rb_err]
        try:
            api.close_handle(leaf_handle)
        except Exception as ce:
            errs.append(ce)
        raise SecureStoreResidualError(
            f"Rollback identity read failed for {leaf!r}",
            primary=primary,
            cleanup_errors=tuple(errs),
        ) from primary

    # 2. Compare identities
    if current_identity != identity:
        rb_err = SecureStorePermissionError(
            f"Rollback: directory identity mismatch for {leaf!r}; "
            f"expected {identity}, got {current_identity}"
        )
        errs = [rb_err]
        try:
            api.close_handle(leaf_handle)
        except Exception as ce:
            errs.append(ce)
        raise SecureStoreResidualError(
            f"Rollback identity mismatch for {leaf!r}",
            primary=primary,
            cleanup_errors=tuple(errs),
        ) from primary

    # 3. Set delete disposition (at most once)
    try:
        api.set_delete_disposition(leaf_handle)
    except Exception as e:
        rb_err = SecureStorePermissionError(
            f"Rollback: set_delete_disposition failed for {leaf!r}: {e}"
        )
        errs = [rb_err]
        try:
            api.close_handle(leaf_handle)
        except Exception as ce:
            errs.append(ce)
        raise SecureStoreResidualError(
            f"Rollback disposition failed for {leaf!r}",
            primary=primary,
            cleanup_errors=tuple(errs),
        ) from primary

    # 4. Close leaf_handle — disposition takes effect on final close.
    # Ownership consumed before one close attempt; no retry.
    # Close failure appends to primary; leaf_handle is consumed regardless.
    try:
        api.close_handle(leaf_handle)
    except Exception as ce:
        _attach_cleanup_errors(primary, (ce,))


# ---------------------------------------------------------------------------
# Windows helpers
# ---------------------------------------------------------------------------


def _split_path_components(path: str) -> list[str]:
    """Legacy splitter for old full-path backend — NOT used by P2‑B traversal."""
    norm = path.replace("/", "\\")
    if norm.startswith("\\\\"):
        parts = norm.split("\\")
        if len(parts) < 5:
            raise ValueError(f"Invalid UNC path: {path!r}")
        root = f"\\\\{parts[2]}\\{parts[3]}"
        rest = parts[4:]
    elif len(norm) >= 3 and norm[1] == ":" and norm[2] == "\\":
        root = norm[:3]
        rest = norm[3:].split("\\") if len(norm) > 3 else []
    else:
        raise ValueError(f"Unsupported path format: {path!r}")

    result = [root]
    accum = root
    for comp in rest:
        if not comp:
            continue
        accum = accum + comp if accum.endswith("\\") else accum + "\\" + comp
        result.append(accum)
    return result


# ---------------------------------------------------------------------------
# P2-D: private-file creation via retained-handle + DACL precondition
# ---------------------------------------------------------------------------


def _validate_dir_dacl_snapshot(
    snap: DaclSnapshot,
    *,
    expected_user_sid: bytes,
    expected_system_sid: bytes,
) -> None:
    """Validate a directory DACL snapshot meets the expected security policy.

    Required gates:
    - DACL present and non-null.
    - SE_DACL_PROTECTED set.
    - Exactly 2 ACEs (one user, one SYSTEM).
    - Both ACEs are ACCESS_ALLOWED type.
    - No inherited, INHERIT_ONLY, NO_PROPAGATE flags.
    - CI|OI flags present on both (directory ACEs).
    - No unexpected extra flags.
    - Mask == FILE_ALL_ACCESS for both.
    - Exactly one ACE matches *expected_user_sid* and exactly one matches
      *expected_system_sid* (order-independent, no duplicates, no arbitrary SIDs).
    """
    if not snap.dacl_present:
        raise SecureStorePermissionError("Directory DACL is not present")
    if not snap.protected:
        raise SecureStorePermissionError("Directory DACL is not protected")
    if len(snap.aces) != 2:
        raise SecureStorePermissionError(
            f"Expected exactly 2 ACEs on directory, got {len(snap.aces)}"
        )
    _expected_flags = _CONTAINER_INHERIT_ACE | _OBJECT_INHERIT_ACE
    _user_count = 0
    _system_count = 0

    for i, ace in enumerate(snap.aces):
        if ace.ace_type != _ACCESS_ALLOWED_ACE_TYPE:
            raise SecureStorePermissionError(
                f"Directory ACE[{i}] is not ALLOW type (type=0x{ace.ace_type:02X})"
            )
        if ace.ace_flags & _INHERITED_ACE:
            raise SecureStorePermissionError(
                f"Directory ACE[{i}] is inherited"
            )
        if ace.ace_flags & _INHERIT_ONLY_ACE:
            raise SecureStorePermissionError(
                f"Directory ACE[{i}] has INHERIT_ONLY_ACE"
            )
        if ace.ace_flags & _NO_PROPAGATE_INHERIT_ACE:
            raise SecureStorePermissionError(
                f"Directory ACE[{i}] has NO_PROPAGATE_INHERIT_ACE"
            )
        if (ace.ace_flags & _expected_flags) != _expected_flags:
            raise SecureStorePermissionError(
                f"Directory ACE[{i}] missing CI|OI flags (flags=0x{ace.ace_flags:02X})"
            )
        if ace.ace_flags & ~_expected_flags:
            raise SecureStorePermissionError(
                f"Directory ACE[{i}] has unexpected flags 0x{ace.ace_flags:02X}"
            )
        if ace.mask != _FILE_ALL_ACCESS:
            raise SecureStorePermissionError(
                f"Directory ACE[{i}] mask 0x{ace.mask:08X} != FILE_ALL_ACCESS"
            )
        # SID identity (Blocker #1): exactly one user + one SYSTEM
        if ace.sid_bytes == expected_user_sid:
            _user_count += 1
        elif ace.sid_bytes == expected_system_sid:
            _system_count += 1
        else:
            raise SecureStorePermissionError(
                f"Directory ACE[{i}] has unexpected SID (not user nor SYSTEM)"
            )

    if _user_count != 1:
        raise SecureStorePermissionError(
            f"Expected exactly 1 user ACE, found {_user_count}"
        )
    if _system_count != 1:
        raise SecureStorePermissionError(
            f"Expected exactly 1 SYSTEM ACE, found {_system_count}"
        )


def _validate_file_dacl_snapshot(
    snap: DaclSnapshot,
    *,
    expected_user_sid: bytes,
    expected_system_sid: bytes,
) -> None:
    """Validate a private file DACL snapshot meets the expected policy.

    Same structure as directory DACL but requires ACE inheritance flags == 0
    (no CI|OI — file ACEs must not inherit).
    """
    if not snap.dacl_present:
        raise SecureStorePermissionError("File DACL is not present")
    if not snap.protected:
        raise SecureStorePermissionError("File DACL is not protected")
    if len(snap.aces) != 2:
        raise SecureStorePermissionError(
            f"Expected exactly 2 ACEs on file, got {len(snap.aces)}"
        )
    _user_count = 0
    _system_count = 0

    for i, ace in enumerate(snap.aces):
        if ace.ace_type != _ACCESS_ALLOWED_ACE_TYPE:
            raise SecureStorePermissionError(
                f"File ACE[{i}] is not ALLOW type (type=0x{ace.ace_type:02X})"
            )
        if ace.ace_flags & _INHERITED_ACE:
            raise SecureStorePermissionError(
                f"File ACE[{i}] is inherited"
            )
        # File ACEs must have zero inheritance flags
        if ace.ace_flags != 0:
            raise SecureStorePermissionError(
                f"File ACE[{i}] has non-zero flags 0x{ace.ace_flags:02X} (expected 0)"
            )
        if ace.mask != _FILE_ALL_ACCESS:
            raise SecureStorePermissionError(
                f"File ACE[{i}] mask 0x{ace.mask:08X} != FILE_ALL_ACCESS"
            )
        # SID identity
        if ace.sid_bytes == expected_user_sid:
            _user_count += 1
        elif ace.sid_bytes == expected_system_sid:
            _system_count += 1
        else:
            raise SecureStorePermissionError(
                f"File ACE[{i}] has unexpected SID (not user nor SYSTEM)"
            )

    if _user_count != 1:
        raise SecureStorePermissionError(
            f"Expected exactly 1 user ACE on file, found {_user_count}"
        )
    if _system_count != 1:
        raise SecureStorePermissionError(
            f"Expected exactly 1 SYSTEM ACE on file, found {_system_count}"
        )


def _validate_private_file_handle(
    handle: int, name: str, api: "_WinLowLevelAPI",
) -> None:
    """Validate *handle* is a regular disk file, not a reparse point or directory."""
    info = api.get_file_info(handle)
    if info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise SecureStorePermissionError(
            f"Private file {name!r} is a reparse point"
        )
    if info.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
        raise SecureStorePermissionError(
            f"Private file {name!r} is a directory"
        )
    ftype = api.get_file_type(handle)
    if ftype != _FILE_TYPE_DISK:
        raise SecureStorePermissionError(
            f"Private file {name!r} file type={ftype}, expected DISK ({_FILE_TYPE_DISK})"
        )


# Sentinel SID bytes for P2‑D tests (Linux‑only; real‑Windows gets real SIDs)
_USER_SID_BYTES = b"USER_SID"
_SYSTEM_SID_BYTES = b"SYSTEM_SID"


def _create_private_file_relative(
    directory: str,
    leaf_name: str,
    api: "_WinLowLevelAPI",
) -> int:
    """Create a private file via retained-handle relative operations (P2‑D).

    Algorithm:
    1. Parse + validate leaf grammar; reject drive-root target.
    2. Acquire security context (user + SYSTEM SID bytes).
    3. Traverse to *directory* via P2‑B retained‑handle pattern.
    4. Read/validate directory DACL against acquired SID identities.
    5. Build atomic SD (user + SYSTEM, file‑ACE flags zero) using context.
    6. Create file via ``FILE_CREATE`` relative to directory handle.
    7. Validate returned file handle (type, reparse, file DACL against context SIDs).
    8. Release SD resources.
    9. Release security context.
    10. Close directory handle (zeroed before attempt).
    11. Transfer HANDLE to CRT fd via ``open_osfhandle`` (final fallible action).

    Ownership contract:
    - Security context released before transfer; failure appends to primary.
    - Directory HANDLE zeroed before close — no retry on ambiguous failure.
    - File HANDLE transferred on success (no double‑close).
    - No full‑path descendant operation.

    P3‑B: Rollback for created files.
    - Identity captured immediately after FILE_CREATE success, before any
      validation.  Only created-file HANDLEs are eligible for rollback.
    - On rollback: re‑read identity from same live HANDLE just before
      disposition, compare complete tuple, never dispose on identity
      read failure or mismatch.
    - Post‑create failures (validation, DACL/SD/context acquisition/
      inspection/release, directory close, open_osfhandle failure)
      all go through identity‑checked rollback.
    - open_osfhandle failure must rollback before leaf close.
    - Successful transfer atomically removes native ownership —
      no rollback, no CloseHandle, no later fallible action.
    - Disposition failure or identity mismatch raises
      ``SecureStoreResidualError(primary=primary)`` from primary;
      cleanup_errors ordered: identity/disposition error, leaf close,
      dir close, SD free, context release.
    """
    _validate_leaf_name(leaf_name, platform="windows")

    root, components = _parse_fixed_drive_components(directory)

    # Blocker #3: reject drive-root target before any I/O
    if not components:
        raise SecureStorePermissionError(
            f"Drive root is not a valid private-file directory: {directory!r}"
        )

    # Drive-type gate
    dt = api.drive_type(root)
    if dt != _DRIVE_FIXED:
        raise SecureStorePermissionError(
            f"Drive {root!r} type={dt}, expected DRIVE_FIXED ({_DRIVE_FIXED})"
        )

    primary: BaseException | None = None
    dir_handle: int = 0
    file_handle: int = 0
    sd_handle: int = 0
    ctx: int = 0
    identity: "tuple[int, int, int] | None" = None
    file_created = False

    try:
        # 1. Acquire security context (Blocker #1)
        ctx = api.acquire_security_context()
        user_sid = api.get_context_user_sid(ctx)
        system_sid = api.get_context_system_sid(ctx)

        # 2. Traverse to directory with +READ_CONTROL on final component
        dir_handle = _traverse_retained_handle(
            directory, api, final_access_extra=_READ_CONTROL,
        )

        # 3. DACL precondition: validate directory DACL with acquired SIDs
        dacl_snap = api.read_dacl_snapshot(dir_handle)
        _validate_dir_dacl_snapshot(
            dacl_snap,
            expected_user_sid=user_sid,
            expected_system_sid=system_sid,
        )

        # 4. Build atomic security descriptor (Blocker #2)
        sd_handle = api.build_file_security_descriptor(ctx)

        # 5. Create file relative to directory handle with SD
        desired = (
            _GENERIC_READ | _GENERIC_WRITE | _READ_CONTROL | _DELETE | _SYNCHRONIZE
        )
        create_opts = (
            _FILE_NON_DIRECTORY_FILE
            | _FILE_OPEN_REPARSE_POINT
            | _FILE_SYNCHRONOUS_IO_NONALERT
        )

        file_handle, ntstatus, info = api.nt_create_file(
            relative_name=leaf_name,
            root_directory=dir_handle,
            desired_access=desired,
            share_access=0,
            create_disposition=_FILE_CREATE,
            create_options=create_opts,
            security_descriptor=sd_handle,
        )

        if file_handle == 0:
            _convert_and_raise_ntstatus(ntstatus, api.ntstatus_to_winerror)

        file_created = True

        # P3‑B: Capture identity immediately after FILE_CREATE success,
        # before any validation.
        try:
            identity = api.get_handle_identity(file_handle)
        except Exception as e:
            # Identity capture failure — cannot safely roll back.
            # .primary and .__cause__ = exact native identity exception.
            # cleanup_errors[0] = distinct rollback-prohibition error
            # (never the primary), then close error if any.
            identity = None
            prohibition = SecureStorePermissionError(
                f"Rollback prohibited: identity capture failed for "
                f"created file {leaf_name!r}"
            )
            cleanup: list[BaseException] = [prohibition]
            try:
                api.close_handle(file_handle)
            except Exception as ce:
                cleanup.append(ce)
            file_handle = 0
            raise SecureStoreResidualError(
                f"Rollback identity ambiguous for file {leaf_name!r}",
                primary=e,
                cleanup_errors=tuple(cleanup),
            ) from e

        # 6. Validate returned file handle
        _validate_private_file_handle(file_handle, leaf_name, api)

        # Validate file DACL against acquired SID identities
        file_snap = api.read_dacl_snapshot(file_handle)
        _validate_file_dacl_snapshot(
            file_snap,
            expected_user_sid=user_sid,
            expected_system_sid=system_sid,
        )

        # 7. Release SD resources
        # Defect 7: consume sd_handle BEFORE release call so a release
        # fault is never retried by outer finally.
        _sd_to_free = sd_handle
        sd_handle = 0
        api.free_security_descriptor(_sd_to_free)

        # 8. Release security context
        # Defect 7: consume ctx BEFORE release call so a release
        # fault is never retried by outer finally.
        _ctx_to_release = ctx
        ctx = 0
        api.release_security_context(_ctx_to_release)

        # 9. Close directory handle (zeroed before attempt — Blocker #5)
        _dir_to_close = dir_handle
        dir_handle = 0
        try:
            api.close_handle(_dir_to_close)
        except Exception as e:
            # Directory close failed — if file was created,
            # rollback file before raising.
            # Consume file ownership before rollback.
            if file_created and identity is not None and file_handle > 0:
                _file_to_rb_close = file_handle
                file_handle = 0
                _rollback_created_file(_file_to_rb_close, leaf_name,
                                       identity, api, e)
            raise SecureStorePermissionError(
                f"Directory close failure after file create: {e}"
            ) from e

        # 10. Transfer HANDLE → fd — final fallible action.
        # P3‑B: open_osfhandle failure must rollback before leaf close.
        # Defect 8: open_osfhandle success only for non-negative integer
        # fd; exception/invalid return retains HANDLE for rollback;
        # valid return transfers atomically and no later native fallible
        # action.
        fd = -1
        try:
            fd = api.open_osfhandle(file_handle)
        except Exception as osf_exc:
            # open_osfhandle raised — rollback file before closing.
            # Consume file ownership before rollback.
            if file_created and identity is not None and file_handle > 0:
                _file_to_rb_osf = file_handle
                file_handle = 0
                try:
                    _rollback_created_file(_file_to_rb_osf, leaf_name,
                                           identity, api, osf_exc)
                except SecureStoreResidualError as residual:
                    if dir_handle > 0:
                        try:
                            api.close_handle(dir_handle)
                        except Exception as ce:
                            residual.cleanup_errors = \
                                residual.cleanup_errors + (ce,)
                        dir_handle = 0
                    raise
            raise

        # Defect 8: validate fd is int (not bool, since bool is int subclass)
        # and fd >= 0; invalid return retains HANDLE for rollback, not transfer.
        if not (type(fd) is int and fd >= 0):
            invalid_err = SecureStorePermissionError(
                f"open_osfhandle returned invalid fd {fd!r} "
                f"for file {leaf_name!r}"
            )
            # Retain HANDLE for rollback — do NOT transfer ownership
            if file_created and identity is not None and file_handle > 0:
                _file_to_rb_invalid = file_handle
                file_handle = 0
                try:
                    _rollback_created_file(_file_to_rb_invalid, leaf_name,
                                           identity, api, invalid_err)
                except SecureStoreResidualError as residual:
                    if dir_handle > 0:
                        try:
                            api.close_handle(dir_handle)
                        except Exception as ce:
                            residual.cleanup_errors = \
                                residual.cleanup_errors + (ce,)
                        dir_handle = 0
                    raise residual
            raise invalid_err

        # Ownership transferred to CRT — atomically remove native ownership
        file_handle = 0

        return fd

    except BaseException as exc:
        primary = exc
        # P3‑B: Rollback created file on any post-creation failure.
        # Consume caller file HANDLE ownership before rollback so all
        # residual branches close that HANDLE exactly once and outer
        # finally cannot retry.
        if file_created and identity is not None and file_handle > 0:
            _file_to_rb = file_handle
            file_handle = 0
            try:
                _rollback_created_file(_file_to_rb, leaf_name, identity,
                                       api, primary)
            except SecureStoreResidualError as residual:
                # Failed/ambiguous rollback — residual already carries
                # identity/disposition + close errors with primary set.
                # Attach remaining cleanup errors from this scope
                # (dir close, SD free, context release).
                if dir_handle > 0:
                    try:
                        api.close_handle(dir_handle)
                    except Exception as ce:
                        residual.cleanup_errors = \
                            residual.cleanup_errors + (ce,)
                    dir_handle = 0
                if sd_handle != 0:
                    try:
                        api.free_security_descriptor(sd_handle)
                    except Exception as ce:
                        residual.cleanup_errors = \
                            residual.cleanup_errors + (ce,)
                    sd_handle = 0
                if ctx != 0:
                    try:
                        api.release_security_context(ctx)
                    except Exception as ce:
                        residual.cleanup_errors = \
                            residual.cleanup_errors + (ce,)
                    ctx = 0
                raise residual from primary
        raise
    finally:
        cleanup_errs: list[BaseException] = []
        for h in (file_handle, dir_handle):
            if h == 0:
                continue
            try:
                api.close_handle(h)
            except Exception as e:
                cleanup_errs.append(e)
        if sd_handle != 0:
            try:
                api.free_security_descriptor(sd_handle)
            except Exception as e:
                cleanup_errs.append(e)
        if ctx != 0:
            try:
                api.release_security_context(ctx)
            except Exception as e:
                cleanup_errs.append(e)
        if primary is not None:
            if cleanup_errs:
                _attach_cleanup_errors(primary, tuple(cleanup_errs))
        elif cleanup_errs:
            _raise_no_primary_cleanup(
                tuple(cleanup_errs), "create_private_file cleanup"
            )


def _rollback_created_file(
    file_handle: int,
    leaf_name: str,
    identity: "tuple[int, int, int]",
    api: "_WinLowLevelAPI",
    primary: BaseException,
) -> None:
    """P3‑B: Rollback a created private file.

    Receives the exact original *primary* so that identity/disposition
    failures raise ``SecureStoreResidualError(primary=primary)`` from
    primary.  On disposition success + close failure: appends close error
    to primary, raises primary.  Consumes ownership before one close
    attempt; no retry.

    1. Re‑read identity from same live HANDLE via ``get_handle_identity``.
    2. Compare complete tuple against *identity*.
    3. On match: ``set_delete_disposition(file_handle)`` (one‑shot).
    4. Close file_handle (disposition takes effect on final close).
    5. All failure paths raise from *primary* with
       ``cleanup_errors`` ordered: identity/disposition error, file close.
    """
    # 1. Re-read identity from live HANDLE
    try:
        current_identity = api.get_handle_identity(file_handle)
    except Exception as e:
        rb_err = SecureStorePermissionError(
            f"Rollback: cannot re-read identity for file {leaf_name!r}: {e}"
        )
        errs = [rb_err]
        try:
            api.close_handle(file_handle)
        except Exception as ce:
            errs.append(ce)
        raise SecureStoreResidualError(
            f"Rollback identity read failed for file {leaf_name!r}",
            primary=primary,
            cleanup_errors=tuple(errs),
        ) from primary

    # 2. Compare identities
    if current_identity != identity:
        rb_err = SecureStorePermissionError(
            f"Rollback: file identity mismatch for {leaf_name!r}; "
            f"expected {identity}, got {current_identity}"
        )
        errs = [rb_err]
        try:
            api.close_handle(file_handle)
        except Exception as ce:
            errs.append(ce)
        raise SecureStoreResidualError(
            f"Rollback identity mismatch for file {leaf_name!r}",
            primary=primary,
            cleanup_errors=tuple(errs),
        ) from primary

    # 3. Set delete disposition (at most once)
    try:
        api.set_delete_disposition(file_handle)
    except Exception as e:
        rb_err = SecureStorePermissionError(
            f"Rollback: set_delete_disposition failed for file "
            f"{leaf_name!r}: {e}"
        )
        errs = [rb_err]
        try:
            api.close_handle(file_handle)
        except Exception as ce:
            errs.append(ce)
        raise SecureStoreResidualError(
            f"Rollback disposition failed for file {leaf_name!r}",
            primary=primary,
            cleanup_errors=tuple(errs),
        ) from primary

    # 4. Close file_handle — disposition takes effect on final close.
    # Ownership consumed before one close attempt; no retry.
    # Close failure appends to primary; file_handle is consumed regardless.
    try:
        api.close_handle(file_handle)
    except Exception as ce:
        _attach_cleanup_errors(primary, (ce,))


def _win_free_sid(sid_ptr: int, a) -> None:
    """Free a SID allocated with AllocateAndInitializeSid."""
    if sid_ptr:
        a.FreeSid(sid_ptr)
