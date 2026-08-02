"""Container registry — multi-container index at ``.aisc/containers.json``.

Replaces the single-container ``CONTAINER_NAME`` pointer in ``state.env``.
Each ``aisc run`` registers a container; ``status``/``stop``/``restart``/
``shell``/``switch`` discover the target via :func:`resolve_target`.

The registry is a JSON file with a ``default`` pointer and a ``containers``
map keyed by container name. Writes are atomic (temp-file + rename) and
serialized with ``fcntl.flock`` to make concurrent ``run`` from multiple
terminals safe.

``resolve_target`` runs a lazy GC (``docker inspect`` each entry) before
addressing; entries whose container no longer exists are pruned so stale
records from deleted/crashed containers do not accumulate.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from aisc.domain.models import CliError


_REGISTRY_FILE = "containers.json"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _registry_path(root: Path) -> Path:
    return root / ".aisc" / _REGISTRY_FILE


def _resolve_root(root: Optional[Path], explicit_root: Optional[str] = None) -> Optional[Path]:
    """Resolve the aisc root, accepting either a ready Path or explicit_root str."""
    if root is not None:
        return root
    if explicit_root is not None:
        p = Path(explicit_root).resolve()
        if p.is_dir():
            return p
    # Fall back to locate_aisc_root for auto-discovery
    try:
        from aisc.application.resources import locate_aisc_root
        return locate_aisc_root(explicit_root=explicit_root)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def _read_registry(root: Path) -> Dict[str, Any]:
    """Load the registry. Returns empty structure if file absent or corrupt."""
    path = _registry_path(root)
    if not path.is_file():
        return {"default": "", "containers": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"default": "", "containers": {}}
    if not isinstance(data, dict):
        return {"default": "", "containers": {}}
    data.setdefault("default", "")
    data.setdefault("containers", {})
    if not isinstance(data["containers"], dict):
        data["containers"] = {}
    return data


@contextmanager
def _registry_lock(root: Path) -> Iterator[None]:
    """Hold the registry lock across a complete read-modify-write cycle."""
    state_dir = root / ".aisc"
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / ".containers.lock"
    lock_fd = None
    locked = False
    try:
        try:
            import fcntl
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            locked = True
        except ImportError:
            pass
        yield
    finally:
        if locked and lock_fd is not None:
            try:
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass


def _write_registry_unlocked(root: Path, data: Dict[str, Any]) -> None:
    """Atomically replace the registry; caller is responsible for locking.

    Atomicity still prevents readers from observing a partially written JSON
    document while the separate lock serializes writers.
    """
    state_dir = root / ".aisc"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _registry_path(root)

    fd, tmp_path = tempfile.mkstemp(prefix=".containers_", dir=str(state_dir), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _write_registry(root: Path, data: Dict[str, Any]) -> None:
    """Atomically write a complete registry under the registry lock."""
    with _registry_lock(root):
        _write_registry_unlocked(root, data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register(root: Path, name: str, meta: Dict[str, Any]) -> None:
    """Register a container and mark it as the default target.

    Args:
        root: AISC root directory.
        name: Container name (unique per run).
        meta: Metadata dict with keys image/workspace/network/label.
    """
    entry = {
        "image": meta.get("image", ""),
        "workspace": meta.get("workspace", ""),
        "network": meta.get("network", ""),
        "label": meta.get("label", ""),
        "created_at": meta.get("created_at") or time.time(),
    }
    with _registry_lock(root):
        data = _read_registry(root)
        data["containers"][name] = entry
        data["default"] = name
        _write_registry_unlocked(root, data)


def unregister(root: Path, name: str) -> None:
    """Remove a container from the registry.

    If the removed name was the default, repoint default to the most recently
    created remaining entry (max created_at). Clears default when empty.
    """
    with _registry_lock(root):
        data = _read_registry(root)
        data["containers"].pop(name, None)
        if data["default"] == name:
            data["default"] = _pick_newest(data["containers"])
        _write_registry_unlocked(root, data)


def list_containers(root: Path) -> Dict[str, Dict[str, Any]]:
    """Return all registered container entries (name → meta)."""
    return _read_registry(root)["containers"]


def _pick_newest(containers: Dict[str, Any]) -> str:
    """Return the name of the entry with the greatest created_at, or ''."""
    if not containers:
        return ""
    best_name = ""
    best_ts = -1.0
    for nm, meta in containers.items():
        ts = meta.get("created_at", 0) if isinstance(meta, dict) else 0
        if ts >= best_ts:
            best_ts = ts
            best_name = nm
    return best_name


# ---------------------------------------------------------------------------
# GC — prune entries whose docker container no longer exists
# ---------------------------------------------------------------------------

def _container_exists(executor, name: str) -> Optional[bool]:
    """Return True/False for container existence, or None if docker is
    unreachable (GC skipped, do not block addressing)."""
    fmt = '{{.State.Running}}'
    proc = executor.run_captured(["inspect", "--format", fmt, name], timeout=10.0)
    if proc.command_not_found or proc.timed_out:
        return None
    stderr_lower = (proc.stderr or "").lower()
    if proc.exit_code != 0:
        if any(kw in stderr_lower for kw in (
            "no such object", "no such container", "not found",
        )):
            return False
        # Daemon down / permission — skip GC
        if any(kw in stderr_lower for kw in (
            "cannot connect", "is the docker daemon running",
            "connection refused", "error during connect", "permission denied",
        )):
            return None
        return None
    return True


def gc(root: Path, executor) -> List[str]:
    """Prune registry entries whose container is gone. Returns pruned names.

    Best-effort: if docker is unreachable, prunes nothing and returns [].
    """
    snapshot = _read_registry(root)
    containers = snapshot.get("containers", {})
    if not containers:
        return []
    missing: List[str] = []
    for nm in list(containers):
        exists = _container_exists(executor, nm)
        if exists is False:
            missing.append(nm)
    if not missing:
        return []

    pruned: List[str] = []
    with _registry_lock(root):
        data = _read_registry(root)
        current = data.get("containers", {})
        for nm in missing:
            # Do not delete a same-name container re-registered while Docker
            # checks were running.
            if current.get(nm) == containers.get(nm):
                current.pop(nm, None)
                pruned.append(nm)
        if pruned:
            if data["default"] in pruned:
                data["default"] = _pick_newest(current)
            _write_registry_unlocked(root, data)
    return pruned


# ---------------------------------------------------------------------------
# Target resolution — replaces discover_container
# ---------------------------------------------------------------------------

def _format_candidates(containers: Dict[str, Dict[str, Any]]) -> str:
    lines = []
    for nm, meta in containers.items():
        label = meta.get("label", "") or "-"
        img = meta.get("image", "")
        ws = meta.get("workspace", "")
        lines.append(f"  {nm}  [{label}]  {img}  {ws}")
    return "\n".join(lines)


def resolve_target(
    root: Optional[Path] = None,
    *,
    name_override: Optional[str] = None,
    label_override: Optional[str] = None,
    executor=None,
    explicit_root: Optional[str] = None,
) -> str:
    """Resolve which container to operate on.

    Priority:
    1. ``name_override``  — validate existence via GC, return (or error+list)
    2. ``label_override`` — match by label; unique → return
    3. ``default`` pointer (after GC) — return if still present
    4. single registered container — return it
    5. multiple + no override — ``CliError`` listing candidates

    Raises:
        CliError: when no target can be resolved.
    """
    resolved_root = _resolve_root(root, explicit_root)
    if resolved_root is None:
        raise CliError(
            message=(
                "No AISC root found and no container name/label given.\n"
                "  Pass --name NAME or --label LABEL, or run inside an AISC workspace."
            ),
            exit_code=1, error_code="AISC_ERR_CONTAINER_NOT_FOUND",
        )

    # Lazy GC before addressing (best-effort, executor may be None in dry paths)
    if executor is not None:
        try:
            gc(resolved_root, executor)
        except Exception:
            pass

    data = _read_registry(resolved_root)
    containers: Dict[str, Dict[str, Any]] = data.get("containers", {})

    # 1. explicit name
    if name_override:
        if name_override in containers:
            return name_override
        # Not in registry — may still exist in docker (e.g. --name passed to a
        # container run outside aisc, or registry was wiped). Accept it; caller's
        # cmd_status will verify real existence via docker inspect.
        return name_override

    # 2. explicit label
    if label_override:
        matches = [nm for nm, m in containers.items()
                   if m.get("label", "") == label_override]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise CliError(
                message=(
                    f"No container with label '{label_override}'. Registered:\n"
                    f"{_format_candidates(containers) or '  (none)'}"
                ),
                exit_code=1, error_code="AISC_ERR_CONTAINER_NOT_FOUND",
            )
        raise CliError(
            message=(
                f"Multiple containers share label '{label_override}':\n"
                + _format_candidates({nm: containers[nm] for nm in matches})
                + "\nSpecify --name NAME to disambiguate."
            ),
            exit_code=1, error_code="AISC_ERR_MULTIPLE_CONTAINERS",
        )

    # 3. default pointer
    default = data.get("default", "")
    if default and default in containers:
        return default

    # 4. single container
    if len(containers) == 1:
        return next(iter(containers))

    # 5. none / multiple
    if not containers:
        raise CliError(
            message=(
                "No container registered. Run 'aisc run' first, or pass "
                "--name NAME / --label LABEL."
            ),
            exit_code=1, error_code="AISC_ERR_CONTAINER_NOT_FOUND",
        )
    raise CliError(
        message=(
            f"Multiple containers registered ({len(containers)}). "
            "Specify --name NAME or --label LABEL:\n"
            + _format_candidates(containers)
        ),
        exit_code=1, error_code="AISC_ERR_MULTIPLE_CONTAINERS",
    )
