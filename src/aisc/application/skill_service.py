"""Skill service — MVP application API for skill-bundle import.

Operations: add, list, remove, check.
skills-lock.json v2 is sole source of truth. No skills.json, no manifest.

Remediation: bundle-root non-following, strict fail-closed lock, complete atomic write,
destination type checks, two-pass preflight limits, fully non-following check.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat as stat_module
import tempfile
import uuid
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

from aisc.domain.skill_models import (
    CheckResult, FetchedTree, ParsedGitHubURL, ResolvedRef,
    SkillFileEntry, SkillLockEntryV2, SkillLockV2, TransactionError,
    ValidationResult, deserialize_lock_v2, parse_github_url,
)
from aisc.adapters.lock_serializer import serialize_lock_v2
from aisc.adapters.skill_validator import (
    ValidationLimits, normalize_skill_name, scan_dependencies, validate_tree,
)
from aisc.adapters.github_client import (
    GitHubError, GitHubTransport, RealGitHubTransport,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOCK_FILE = "skills-lock.json"
_BUNDLE_SKILLS_DIR = "container/_bundle/skills"
_ALLOWED_BLOB_MODE = "100644"
_ALLOWED_TREE_MODE = "040000"
_REJECTED_MODES_SYMLINK = frozenset({"120000"})
_REJECTED_MODES_SUBMODULE = frozenset({"160000"})

# Preflight limits
_MAX_FILES = 100
_MAX_FILE_BYTES = 1 * 1024 * 1024   # 1 MiB
_MAX_TOTAL_BYTES = 5 * 1024 * 1024  # 5 MiB

# ---------------------------------------------------------------------------
# Non-following bundle tree validation
# ---------------------------------------------------------------------------

def _validate_bundle_tree(root: Path) -> Path:
    """Validate root → container → _bundle → skills is non-following real dirs.

    Returns the validated bundle_dir. Raises ValueError on any anomaly.
    """
    # Validate root itself
    _validate_real_dir(root, "AISC root")
    # container/
    container = root / "container"
    _validate_real_dir(container, "container/")
    # _bundle/
    bundle = container / "_bundle"
    _validate_real_dir(bundle, "container/_bundle/")
    # skills/
    skills = bundle / "skills"
    if skills.exists() or skills.is_symlink():
        _validate_real_dir(skills, "container/_bundle/skills/")
    else:
        skills.mkdir(parents=False, exist_ok=False)
    return skills


def _validate_real_dir(path: Path, label: str) -> None:
    """Assert *path* is a real directory (not symlink, not special, not file)."""
    try:
        st = os.lstat(str(path))
    except FileNotFoundError:
        raise ValueError(f"{label} not found: {path}")
    except OSError as e:
        raise ValueError(f"{label} cannot stat: {path}: {e}")
    if stat_module.S_ISLNK(st.st_mode):
        raise ValueError(f"{label} is a symlink: {path}")
    if not stat_module.S_ISDIR(st.st_mode):
        raise ValueError(f"{label} is not a directory: {path}")


def _validate_lock_file_type(lock_path: Path) -> None:
    """Reject lock that is symlink, directory, FIFO, device, or special."""
    if not lock_path.exists():
        return  # absent = empty lock (handled by caller)
    try:
        st = os.lstat(str(lock_path))
    except OSError:
        return  # let caller try open
    if stat_module.S_ISLNK(st.st_mode):
        raise ValueError(f"skills-lock.json is a symlink — refusing")
    if stat_module.S_ISDIR(st.st_mode):
        raise ValueError(f"skills-lock.json is a directory — refusing")
    if stat_module.S_ISFIFO(st.st_mode) or stat_module.S_ISSOCK(st.st_mode) \
            or stat_module.S_ISBLK(st.st_mode) or stat_module.S_ISCHR(st.st_mode):
        raise ValueError(f"skills-lock.json is a special file — refusing")
    if not stat_module.S_ISREG(st.st_mode):
        raise ValueError(f"skills-lock.json is not a regular file — refusing")


def _read_lock_no_follow(lock_path: Path) -> bytes:
    """Read lock file with O_NOFOLLOW where available."""
    _validate_lock_file_type(lock_path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(str(lock_path), flags)
    except OSError as e:
        raise ValueError(f"Cannot open skills-lock.json: {e}")
    try:
        # Verify no type change between lstat and open
        st_before = os.fstat(fd)
        if not stat_module.S_ISREG(st_before.st_mode):
            raise ValueError(f"skills-lock.json is not regular file on open")
        data = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            data += chunk
        return data
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Atomic write — loop, zero-progress detection
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: bytes) -> None:
    """Write data atomically via temp file + loop-write + fsync + os.replace."""
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            total = len(data)
            offset = 0
            while offset < total:
                try:
                    written = os.write(fd, data[offset:])
                except InterruptedError:
                    continue
                if written == 0:
                    raise OSError("Zero-progress write on temp file")
                if written < 0:
                    raise OSError(f"Negative return from write: {written}")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(path))
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Lock I/O — fail-closed
# ---------------------------------------------------------------------------

class _LockCorruptedError(ValueError):
    """Raised when existing skills-lock.json is invalid v2."""


def _parse_lock(lock_path: Path) -> SkillLockV2:
    """Parse skills-lock.json v2.  Only FileNotFoundError → empty.

    Uses os.lstat as the sole existence/type decision point.
    Broken symlink, symlink, directory, FIFO, special, non-regular,
    and all other OSErrors raise _LockCorruptedError.
    """
    try:
        st = os.lstat(str(lock_path))
    except FileNotFoundError:
        return SkillLockV2()
    except OSError as exc:
        raise _LockCorruptedError(
            f"skills-lock.json cannot be stat'd: {exc}"
        ) from exc

    if stat_module.S_ISLNK(st.st_mode):
        raise _LockCorruptedError(
            "skills-lock.json is a symlink. Fix or remove it manually."
        )
    if not stat_module.S_ISREG(st.st_mode):
        raise _LockCorruptedError(
            "skills-lock.json exists but is not a regular file. "
            "Fix or remove it manually before using aisc skill."
        )
    try:
        data = _read_lock_no_follow(lock_path)
        return deserialize_lock_v2(data)
    except ValueError:
        raise _LockCorruptedError(
            "skills-lock.json exists but is not valid v2. "
            "Fix or remove it manually before using aisc skill."
        )


def _write_lock(lock: SkillLockV2, lock_path: Path) -> None:
    data = serialize_lock_v2(lock)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(lock_path, data)


# ---------------------------------------------------------------------------
# Cross-platform helpers
# ---------------------------------------------------------------------------

_BACKSLASH_RE = re.compile(r"\\")
_UNSAFE_CHARS_RE = re.compile(r"[\\:]")
_WINDOWS_RESERVED = frozenset({
    "CON","PRN","AUX","NUL","COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
    "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9",
})

def _check_safe_name(name: str) -> None:
    if not name or not isinstance(name, str): raise ValueError("Skill name must be non-empty")
    if "/" in name or ".." in name: raise ValueError(f"Name {name!r} contains path separator")
    if _BACKSLASH_RE.search(name): raise ValueError(f"Name {name!r} contains backslash")
    if _UNSAFE_CHARS_RE.search(name): raise ValueError(f"Name {name!r} contains unsafe char")
    if name.startswith("."): raise ValueError(f"Name {name!r} starts with dot")
    if len(name) > 64: raise ValueError(f"Name {name!r} exceeds 64 chars")

def _validate_fetched_path(path: str) -> None:
    if not path: raise ValueError("Empty path")
    if path.startswith("/"): raise ValueError(f"Absolute path: {path!r}")
    if ".." in path.split("/"): raise ValueError(f"Traversal in: {path!r}")
    if _BACKSLASH_RE.search(path): raise ValueError(f"Backslash in: {path!r}")
    if _UNSAFE_CHARS_RE.search(path): raise ValueError(f"Unsafe char in: {path!r}")
    for part in path.split("/"):
        if not part: raise ValueError(f"Empty component in: {path!r}")
        if part != part.rstrip(". "): raise ValueError(f"Trailing dot/space: {part!r}")
        if part.upper() in _WINDOWS_RESERVED: raise ValueError(f"Windows reserved: {part!r}")

def _validate_dest_type(dest: Path) -> None:
    """Destination must be absent or a real non-symlink directory."""
    if dest.is_symlink():
        raise ValueError(f"Destination {dest} is a symlink — refusing")
    if dest.exists():
        try:
            st = os.lstat(str(dest))
        except OSError as e:
            raise ValueError(f"Cannot stat destination {dest}: {e}")
        if stat_module.S_ISLNK(st.st_mode):
            raise ValueError(f"Destination {dest} is a symlink — refusing")
        if not stat_module.S_ISDIR(st.st_mode):
            raise ValueError(f"Destination {dest} exists but is not a directory — refusing")

# ---------------------------------------------------------------------------
# Transaction error builder
# ---------------------------------------------------------------------------

def _build_tx_error(msg: str, primary: BaseException, cleanup: List[str], committed: bool = False) -> TransactionError:
    full = msg
    if cleanup: full += " (cleanup errors: " + "; ".join(cleanup) + ")"
    return TransactionError(full, primary=primary, cleanup_errors=cleanup, committed=committed)


# ---------------------------------------------------------------------------
# Two-pass tree fetch with preflight limits
# ---------------------------------------------------------------------------

def _fetch_tree(parsed: ParsedGitHubURL, resolved: ResolvedRef, transport: GitHubTransport) -> FetchedTree:
    owner, repo, commit = parsed.owner, parsed.repo, resolved.resolved_commit
    directory = parsed.directory
    tree_entries = transport.get_tree(owner, repo, commit, directory)
    dir_prefix = directory.rstrip("/") + "/" if directory else ""

    # --- PASS 1: type/mode/path validation + size/count accounting (NO blobs) ---
    blob_entries: list = []  # (rel_path, entry_sha, declared_size)
    blob_count = 0
    total_declared = 0

    for entry in tree_entries:
        entry_type = entry.get("type","")
        entry_path = entry.get("path","")
        entry_mode = entry.get("mode","")

        if dir_prefix:
            if not entry_path.startswith(dir_prefix): continue
            rel_path = entry_path[len(dir_prefix):]
        else:
            rel_path = entry_path
        if not rel_path:
            if entry_type != "tree":
                raise GitHubError(f"Empty relative path with type {entry_type!r}", error_code="GITHUB_ERR_UNSAFE_OBJECT")
            continue

        if not entry_type or not entry_mode:
            raise GitHubError(f"Missing type/mode at {rel_path!r}", error_code="GITHUB_ERR_UNSAFE_OBJECT")
        if entry_type == "commit" or entry_mode in _REJECTED_MODES_SUBMODULE:
            raise GitHubError(f"Submodule at {rel_path!r}", error_code="GITHUB_ERR_UNSAFE_OBJECT")
        if entry_mode in _REJECTED_MODES_SYMLINK:
            raise GitHubError(f"Symlink at {rel_path!r}", error_code="GITHUB_ERR_UNSAFE_OBJECT")
        if entry_type == "tree":
            if entry_mode != _ALLOWED_TREE_MODE:
                raise GitHubError(f"Tree {rel_path!r} mode {entry_mode!r} != {_ALLOWED_TREE_MODE!r}", error_code="GITHUB_ERR_UNSAFE_OBJECT")
            continue
        if entry_type != "blob":
            raise GitHubError(f"Unknown type {entry_type!r} at {rel_path!r}", error_code="GITHUB_ERR_UNSAFE_OBJECT")
        if entry_mode != _ALLOWED_BLOB_MODE:
            raise GitHubError(f"Blob {rel_path!r} mode {entry_mode!r} != {_ALLOWED_BLOB_MODE!r}", error_code="GITHUB_ERR_UNSAFE_OBJECT")

        sha = entry.get("sha","")
        if not sha:
            raise GitHubError(f"Blob {rel_path!r} missing SHA", error_code="GITHUB_ERR_UNSAFE_OBJECT")
        decl_size = entry.get("size")
        if not isinstance(decl_size, int) or decl_size < 0:
            raise GitHubError(f"Blob {rel_path!r} missing/invalid declared size", error_code="GITHUB_ERR_UNSAFE_OBJECT")
        if decl_size > _MAX_FILE_BYTES:
            raise GitHubError(f"Blob {rel_path!r} declared size {decl_size} > {_MAX_FILE_BYTES}", error_code="GITHUB_ERR_UNSAFE_OBJECT")

        _validate_fetched_path(rel_path)
        blob_count += 1
        total_declared += decl_size
        blob_entries.append((rel_path, sha, decl_size))

    if blob_count > _MAX_FILES:
        raise GitHubError(f"Too many blob files: {blob_count} > {_MAX_FILES}", error_code="GITHUB_ERR_UNSAFE_OBJECT")
    if total_declared > _MAX_TOTAL_BYTES:
        raise GitHubError(f"Declared total {total_declared} > {_MAX_TOTAL_BYTES}", error_code="GITHUB_ERR_UNSAFE_OBJECT")
    if not blob_entries:
        raise GitHubError(f"No files in {directory!r}", error_code="GITHUB_ERR_NOT_FOUND", status=404)

    # --- PASS 2: fetch blobs, verify actual lengths ---
    files: Dict[str, bytes] = {}
    for rel_path, sha, decl_size in blob_entries:
        content = transport.get_blob(owner, repo, sha)
        if len(content) != decl_size:
            raise GitHubError(
                f"Blob {rel_path!r}: actual size {len(content)} != declared {decl_size}",
                error_code="GITHUB_ERR_SIZE_MISMATCH")
        if len(content) > _MAX_FILE_BYTES:
            raise GitHubError(f"Blob {rel_path!r} actual size {len(content)} > {_MAX_FILE_BYTES}", error_code="GITHUB_ERR_UNSAFE_OBJECT")
        files[rel_path] = content

    actual_total = sum(len(v) for v in files.values())
    if actual_total > _MAX_TOTAL_BYTES:
        raise GitHubError(f"Actual total {actual_total} > {_MAX_TOTAL_BYTES}", error_code="GITHUB_ERR_UNSAFE_OBJECT")

    return FetchedTree(commit=commit, files=files)


def _materialize_to_temp(tree: FetchedTree, skill_name: str, parent_dir: Path) -> Path:
    parent_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=str(parent_dir), prefix=f".tmp-{skill_name}-"))
    try:
        for rel_path, content in sorted(tree.files.items()):
            fp = tmp / rel_path
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(content)
        return tmp
    except Exception:
        if tmp.exists(): shutil.rmtree(str(tmp))
        raise


# ---------------------------------------------------------------------------
# ADD
# ---------------------------------------------------------------------------

def skill_add(url: str, root: Path, *, transport: Optional[GitHubTransport] = None,
              ) -> Tuple[SkillLockEntryV2, List[str]]:
    if transport is None: transport = RealGitHubTransport()

    # --- Bundle tree guard ---
    bundle_dir = _validate_bundle_tree(root)

    # 1. Parse URL
    parsed = parse_github_url(url)
    # 2. Resolve ref
    sha = transport.resolve_ref(parsed.owner, parsed.repo, parsed.requested_ref)
    resolved = ResolvedRef(requested_ref=parsed.requested_ref, resolved_commit=sha, owner=parsed.owner, repo=parsed.repo)
    # 3. Two-pass fetch
    fetched = _fetch_tree(parsed, resolved, transport)
    # 4. Validate
    validation = validate_tree(fetched)
    if not validation.valid:
        raise ValueError("Validation failed:\n" + "\n".join(f"  - {e}" for e in validation.errors))
    skill_name = validation.skill_name
    normalized_name = normalize_skill_name(skill_name)
    _check_safe_name(normalized_name)
    for fe in validation.files:
        _validate_fetched_path(fe.path)

    deps = scan_dependencies(fetched)
    warnings: List[str] = [f"Detected dependency: /{d} (not auto-imported)" for d in sorted(deps)]

    entry = SkillLockEntryV2(name=normalized_name, source_url=parsed.full_url,
        requested_ref=parsed.requested_ref, resolved_commit=resolved.resolved_commit,
        directory=parsed.directory, owner=parsed.owner, repo=parsed.repo,
        files=validation.files, detected_references=deps)

    lock_path = root / _LOCK_FILE
    dest = bundle_dir / normalized_name

    # Read lock before touching destination
    try:
        current_lock = _parse_lock(lock_path)
    except _LockCorruptedError:
        raise

    # Unmanaged-name guard
    if (dest.exists() or dest.is_symlink()) and normalized_name not in current_lock.skills:
        raise ValueError(f"Destination {dest} exists but {normalized_name!r} not in lock — refusing overwrite")

    # Destination type guard
    _validate_dest_type(dest)

    # Materialize temp
    tmp_dir = _materialize_to_temp(fetched, normalized_name, bundle_dir)

    # Backup old dest
    backup_dir: Optional[Path] = None
    try:
        if dest.exists():
            suffix = uuid.uuid4().hex[:8]
            backup_dir = dest.parent / f".{dest.name}.backup-{suffix}"
            os.replace(str(dest), str(backup_dir))
        os.replace(str(tmp_dir), str(dest))
        tmp_dir = None
        new_skills = dict(current_lock.skills)
        new_skills[normalized_name] = entry
        new_lock = SkillLockV2(version=2, skills=new_skills)
    except Exception as primary_exc:
        cleanup: List[str] = []
        if tmp_dir is not None and os.path.exists(str(tmp_dir)):
            try: shutil.rmtree(str(tmp_dir))
            except Exception as e: cleanup.append(f"temp cleanup: {e}")
        if backup_dir is not None and os.path.exists(str(backup_dir)):
            try:
                if dest.exists(): shutil.rmtree(str(dest))
                os.replace(str(backup_dir), str(dest))
            except Exception as e: cleanup.append(f"restore backup: {e}")
        raise _build_tx_error("Placement failed", primary_exc, cleanup) from primary_exc

    # Write lock
    committed = False
    try:
        _write_lock(new_lock, lock_path)
        committed = True
    except Exception as primary_exc:
        cleanup: List[str] = []
        if dest.exists():
            try: shutil.rmtree(str(dest))
            except Exception as e: cleanup.append(f"remove new dest: {e}")
        if backup_dir is not None and os.path.exists(str(backup_dir)):
            try: os.replace(str(backup_dir), str(dest))
            except Exception as e: cleanup.append(f"restore backup: {e}")
        raise _build_tx_error("Lock write failed", primary_exc, cleanup) from primary_exc

    # Post-commit: cleanup backup (warnings only on failure)
    if backup_dir is not None and os.path.exists(str(backup_dir)):
        try:
            shutil.rmtree(str(backup_dir))
        except Exception as e:
            warnings.append(f"Post-commit cleanup warning: stale backup at {backup_dir}: {e}")

    return entry, warnings


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------

def skill_list(root: Path) -> List[SkillLockEntryV2]:
    _validate_bundle_tree(root)
    lock = _parse_lock(root / _LOCK_FILE)
    return [lock.skills[n] for n in sorted(lock.skills.keys())]


# ---------------------------------------------------------------------------
# REMOVE
# ---------------------------------------------------------------------------

def skill_remove(name: str, root: Path) -> Tuple[str, Dict[str, object]]:
    """Remove skill. Returns (name, result_info) with directory_missing if applicable."""
    bundle_dir = _validate_bundle_tree(root)
    lock_path = root / _LOCK_FILE
    try:
        current_lock = _parse_lock(lock_path)
    except _LockCorruptedError:
        raise
    if name not in current_lock.skills:
        raise ValueError(f"Skill {name!r} not found in lock")
    _check_safe_name(name)
    dest = bundle_dir / name
    _validate_dest_type(dest)

    result_info: Dict[str, object] = {}
    backup_dir: Optional[Path] = None
    dest_missing = not dest.exists()

    if not dest_missing:
        backup_suffix = uuid.uuid4().hex[:8]
        backup_dir = dest.parent / f".{dest.name}.backup-{backup_suffix}"
        os.replace(str(dest), str(backup_dir))

    new_skills = dict(current_lock.skills)
    del new_skills[name]
    new_lock = SkillLockV2(version=2, skills=new_skills)

    committed = False
    try:
        _write_lock(new_lock, lock_path)
        committed = True
    except Exception as primary_exc:
        cleanup: List[str] = []
        if backup_dir is not None and os.path.exists(str(backup_dir)):
            try:
                if dest.exists(): shutil.rmtree(str(dest))
                os.replace(str(backup_dir), str(dest))
            except Exception as e:
                cleanup.append(f"restore backup: {e}")
        raise _build_tx_error("Lock write failed during remove", primary_exc, cleanup) from primary_exc

    # Post-commit cleanup
    if backup_dir is not None and os.path.exists(str(backup_dir)):
        try:
            shutil.rmtree(str(backup_dir))
        except Exception as e:
            result_info["stale_backup"] = str(backup_dir)
            result_info["cleanup_warning"] = str(e)
    if dest_missing:
        result_info["directory_missing"] = True

    return name, result_info


# ---------------------------------------------------------------------------
# CHECK — fully non-following, O_NOFOLLOW hashing, identity verification
# ---------------------------------------------------------------------------

def skill_check(root: Path) -> CheckResult:
    result = CheckResult()
    bundle_dir: Optional[Path] = None
    try:
        bundle_dir = _validate_bundle_tree(root)
    except ValueError as exc:
        result.in_sync = False
        result.drift_items.append(f"Bundle tree anomaly: {exc}")
        return result

    lock_path = root / _LOCK_FILE
    if not lock_path.is_file():
        result.in_sync = False
        result.drift_items.append("Lock file missing: skills-lock.json")
        return result

    try:
        raw_data = _read_lock_no_follow(lock_path)
    except ValueError as exc:
        result.in_sync = False
        result.drift_items.append(f"Lock read error: {exc}")
        return result

    # Pre-validate raw keys
    try:
        raw_json = json.loads(raw_data.decode("utf-8"))
    except Exception as exc:
        result.in_sync = False
        result.drift_items.append(f"Lock parse error: {exc}")
        return result
    if isinstance(raw_json, dict) and isinstance(raw_json.get("skills"), dict):
        for key_name in raw_json["skills"]:
            try: _check_safe_name(key_name)
            except ValueError as exc:
                result.in_sync = False
                result.drift_items.append(f"Unsafe lock key {key_name!r}: {exc}")

    try:
        lock = deserialize_lock_v2(raw_data)
    except ValueError as exc:
        result.in_sync = False
        result.drift_items.append(f"Lock schema error: {exc}")
        return result

    for name in lock.skills:
        skill_dir = bundle_dir / name
        if not skill_dir.is_dir() or skill_dir.is_symlink():
            result.in_sync = False
            result.drift_items.append(f"Managed dir missing/symlink: {name!r}")
            continue

        entry = lock.skills[name]
        actual_files: Dict[str, Tuple[int, str]] = {}
        walk_errors: List[str] = []
        _walk_non_following(skill_dir, skill_dir, actual_files, walk_errors)

        for err in walk_errors:
            result.in_sync = False
            result.drift_items.append(f"Traversal error in {name!r}: {err}")

        for fe in entry.files:
            if fe.path not in actual_files:
                result.in_sync = False
                result.drift_items.append(f"File missing from {name!r}: {fe.path}")
            else:
                a_size, a_hash = actual_files[fe.path]
                if a_size < 0:  # symlink sentinel
                    result.in_sync = False
                    result.drift_items.append(f"Symlink at {name!r}/{fe.path}")
                elif a_size != fe.size:
                    result.in_sync = False
                    result.drift_items.append(f"Size mismatch {name!r}/{fe.path}: {fe.size} vs {a_size}")
                elif a_hash != fe.sha256:
                    result.in_sync = False
                    result.drift_items.append(f"Hash mismatch {name!r}/{fe.path}")

        expected = {fe.path for fe in entry.files}
        for p in sorted(actual_files.keys() - expected):
            result.in_sync = False
            result.drift_items.append(f"Unexpected file in {name!r}: {p}")

    return result


def _walk_non_following(
    dir_path: Path, base_dir: Path,
    result: Dict[str, Tuple[int, str]],
    errors: List[str],
) -> None:
    """Collect regular files under dir_path using fd-based traversal.

    Uses O_DIRECTORY|O_NOFOLLOW open, os.scandir(dir_fd), relative opens
    with dir_fd. Identity cross-check between lstat and fstat.
    Falls back to explicit unsupported-platform drift on missing features.
    """
    _UNSUPPORTED = not (
        hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW") and
        hasattr(os, "scandir")
    )
    if _UNSUPPORTED:
        errors.append(f"fd-based check traversal not supported on this platform for {dir_path}")
        return

    try:
        root_st_before = os.lstat(str(dir_path))
    except OSError as exc:
        errors.append(f"lstat root {dir_path}: {exc}")
        return
    if stat_module.S_ISLNK(root_st_before.st_mode):
        errors.append(f"Managed root {dir_path} is a symlink")
        return
    if not stat_module.S_ISDIR(root_st_before.st_mode):
        errors.append(f"Managed root {dir_path} is not a directory")
        return

    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        root_fd = os.open(str(dir_path), dir_flags)
    except OSError as exc:
        errors.append(f"open root {dir_path}: {exc}")
        return

    try:
        root_st_fd = os.fstat(root_fd)
        if root_st_fd.st_ino != root_st_before.st_ino or root_st_fd.st_dev != root_st_before.st_dev:
            errors.append(f"Root identity changed between lstat/open at {dir_path}")
            return
        if not stat_module.S_ISDIR(root_st_fd.st_mode):
            errors.append(f"Root type changed at {dir_path}")
            return
        _walk_dir_fd(root_fd, base_dir, "", result, errors)
    finally:
        os.close(root_fd)


def _walk_dir_fd(
    parent_fd: int, base_dir: Path, rel_prefix: str,
    result: Dict[str, Tuple[int, str]], errors: List[str],
) -> None:
    try:
        with os.scandir(parent_fd) as entries:
            for entry in entries:
                name = entry.name
                rel = f"{rel_prefix}{name}" if rel_prefix else name
                if entry.is_symlink():
                    result[rel] = (-1, "")
                    continue
                try:
                    child_st = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    errors.append(f"stat failed {rel}: {exc}")
                    continue
                if stat_module.S_ISLNK(child_st.st_mode):
                    result[rel] = (-1, "")
                    continue
                if stat_module.S_ISFIFO(child_st.st_mode) or stat_module.S_ISSOCK(child_st.st_mode) \
                        or stat_module.S_ISBLK(child_st.st_mode) or stat_module.S_ISCHR(child_st.st_mode):
                    errors.append(f"Special object at {rel}")
                    continue
                if stat_module.S_ISREG(child_st.st_mode):
                    file_flags = os.O_RDONLY | os.O_NOFOLLOW
                    fd = -1
                    try:
                        fd = os.open(name, file_flags, dir_fd=parent_fd)
                    except OSError as exc:
                        errors.append(f"open file {rel}: {exc}")
                        continue
                    try:
                        file_st = os.fstat(fd)
                        if file_st.st_ino != child_st.st_ino or file_st.st_dev != child_st.st_dev:
                            errors.append(f"File identity changed {rel}")
                            result[rel] = (-2, "")
                            continue
                        if not stat_module.S_ISREG(file_st.st_mode):
                            errors.append(f"File type changed {rel}")
                            result[rel] = (-2, "")
                            continue
                        h = hashlib.sha256()
                        total = 0
                        while True:
                            chunk = os.read(fd, 65536)
                            if not chunk:
                                break
                            h.update(chunk)
                            total += len(chunk)
                        result[rel] = (total, h.hexdigest())
                    except OSError as exc:
                        errors.append(f"read/hash {rel}: {exc}")
                    finally:
                        os.close(fd)
                elif stat_module.S_ISDIR(child_st.st_mode):
                    sub_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                    sub_fd = -1
                    try:
                        sub_fd = os.open(name, sub_flags, dir_fd=parent_fd)
                    except OSError as exc:
                        errors.append(f"open dir {rel}: {exc}")
                        continue
                    try:
                        sub_st = os.fstat(sub_fd)
                        if sub_st.st_ino != child_st.st_ino or sub_st.st_dev != child_st.st_dev:
                            errors.append(f"Directory identity changed {rel}")
                            continue
                        if not stat_module.S_ISDIR(sub_st.st_mode):
                            errors.append(f"Directory type changed {rel}")
                            continue
                        _walk_dir_fd(sub_fd, base_dir, f"{rel}/", result, errors)
                    finally:
                        os.close(sub_fd)
                else:
                    errors.append(f"Unknown entry type at {rel}")
    except OSError as exc:
        errors.append(f"scandir failed (fd {parent_fd}): {exc}")
