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

from aisc.domain.models import CliError, RuntimeErrorCode, RuntimeExitCode


_REGISTRY_FILE = "containers.json"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _registry_path(root: Path) -> Path:
    """Return path to containers.json inside the STATE DIRECTORY *root*.

    Stage 7 wiring: *root* is the registry's state directory itself (the
    data-root ``workspaces/<hash>/runtime`` dir, or the legacy
    ``<workspace>/.aisc`` during transition) — callers resolve it via
    ``application.data_root.workspace_state_dir``; this module never
    concatenates workspace paths (01-cross-stage-contracts §1).
    """
    return root / _REGISTRY_FILE


def _state_dir(root: Path) -> Path:
    """Return the state directory for locks/temp files (= *root* itself)."""
    return root


def _resolve_root(root: Optional[Path], explicit_root: Optional[str] = None) -> Optional[Path]:
    """Resolve the registry STATE DIR for the active workspace (Stage 7).

    *root*/*explicit_root* may be a workspace path, a pre-resolved state
    dir (legacy ``.aisc`` or data-root ``runtime``), or None (→ current
    directory). State is per-workspace under the data root — the old
    install-root fallback (repo/.aisc split-brain with run's workspace
    registry) is gone; legacy state is adopted on first use.
    Resolver failures propagate (fail closed, never write the workspace).
    """
    if root is not None:
        base = Path(root)
    elif explicit_root is not None:
        base = Path(explicit_root).resolve()
        if not base.is_dir():
            return None
    else:
        base = Path.cwd()
    if base.name == ".aisc" or (base / _REGISTRY_FILE).is_file():
        return base  # already a state dir
    from aisc.application.data_root import workspace_state_dir

    return workspace_state_dir(base)


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
def _registry_lock(root: Path, timeout: float = 10.0) -> Iterator[None]:
    """Hold the registry lock across a complete read-modify-write cycle.

    Uses fcntl.flock (POSIX) or msvcrt.locking (Windows).
    Fail-closed: raises on lock acquisition failure.

    Args:
        root: AISC root directory
        timeout: Lock timeout in seconds (default 10.0)

    Raises:
        CliError (STATE_LOCK_TIMEOUT): If lock cannot be acquired within timeout
        OSError: On other lock-related errors

    Yields:
        None while lock is held
    """
    import sys
    import time as time_module

    state_dir = _state_dir(root)
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / ".containers.lock"
    lock_fd = None
    locked = False

    try:
        # Open lock file
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)

        # Platform-specific locking with timeout
        if sys.platform == "win32":
            # Windows: msvcrt.locking with bounded retry
            import msvcrt

            start_time = time_module.time()
            while True:
                try:
                    # Try to lock 1 byte at offset 0
                    msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError as e:
                    elapsed = time_module.time() - start_time
                    if elapsed >= timeout:
                        raise CliError(
                            message=f"Failed to acquire registry lock within {timeout}s",
                            exit_code=RuntimeExitCode.STATE_LOCK_TIMEOUT,
                            error_code=RuntimeErrorCode.STATE_LOCK_TIMEOUT,
                        ) from e
                    # Retry after short sleep
                    time_module.sleep(0.1)
        else:
            # POSIX: fcntl.flock with alarm-based timeout
            import fcntl
            import signal

            def timeout_handler(signum, frame):
                raise CliError(
                    message=f"Failed to acquire registry lock within {timeout}s",
                    exit_code=RuntimeExitCode.STATE_LOCK_TIMEOUT,
                    error_code=RuntimeErrorCode.STATE_LOCK_TIMEOUT,
                )

            # Only set alarm if we're in the main thread
            # (signal.alarm only works in main thread)
            try:
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                # Use ceil to ensure timeout >= 1 second works
                signal.alarm(int(timeout) + 1)
                alarm_set = True
            except ValueError:
                # Not in main thread, fall back to blocking lock
                alarm_set = False

            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                locked = True
            finally:
                if alarm_set:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)

        yield

    finally:
        # Release lock
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

        # Close file descriptor
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
    state_dir = _state_dir(root)
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

def register(root: Path, name: str, meta: Dict[str, Any],
             *, set_default: bool = True) -> None:
    """Register a container and mark it as the default target.

    Args:
        root: AISC root directory.
        name: Container name (unique per run).
        meta: Metadata dict with keys:
            - image: Docker image name
            - workspace: Workspace path
            - network: Network mode (direct/proxy)
            - label: Optional user label
            - runtime_id: Runtime ID (UUID v4 for Workbench runtimes)
            - owner: Username who created this runtime
            - scope: Scope mode (project/temporary)
            - config_fingerprint: Config hash for idempotent retry
            - container_id: Docker container ID (Workbench runtimes)
            - workspace_key: sha256 of canonical workspace (Workbench runtimes)
            - image_id: Content-addressed image ID at create time
              (容器随镜像同步更新, KI-4 挂账 — empty on legacy records)
            - lifecycle/retention/dependency_policy (runtime-lifecycle-ux
              02 §1): "" on legacy records — absent lifecycle is the legacy
              marker reconcile treats as recyclable-after-verification;
              never part of the config fingerprint.
            - workbench_instance_id: creating Workbench instance (Stage 2+
              callers); "" for CLI-created runtimes.
        set_default: also mark the container as the default target. The
            image_id heal path (start_runtime reusing a legacy record)
            re-registers with False so an in-place metadata fix never
            steals the default from another container.

    Backward compatible: if old fields are missing, stores empty strings.
    """
    entry = {
        "image": meta.get("image", ""),
        "workspace": meta.get("workspace", ""),
        "network": meta.get("network", ""),
        "label": meta.get("label", ""),
        "created_at": meta.get("created_at") or time.time(),
        # New fields (v2.2.0+) - backward compatible
        "runtime_id": meta.get("runtime_id", ""),
        "owner": meta.get("owner", ""),
        "scope": meta.get("scope", ""),
        "config_fingerprint": meta.get("config_fingerprint", ""),
        "container_id": meta.get("container_id", ""),
        "workspace_key": meta.get("workspace_key", ""),
        "image_id": meta.get("image_id", ""),
        # svc-2 (web gateway): loopback host port of this runtime's gateway
        # publish; 0/absent on legacy records (web access reports
        # legacy_runtime). Runtime metadata only — never in the fingerprint.
        "web_gateway_host_port": meta.get("web_gateway_host_port", 0),
        # runtime-lifecycle-ux Stage 1 (02 §1): lifecycle metadata. Epoch
        # float to match created_at (contract shows RFC3339; the registry's
        # existing timestamp convention wins for on-disk consistency).
        "lifecycle": meta.get("lifecycle", ""),
        "retention": meta.get("retention", ""),
        "dependency_policy": meta.get("dependency_policy", ""),
        "workbench_instance_id": meta.get("workbench_instance_id", ""),
        "last_state_change_at": meta.get("last_state_change_at") or time.time(),
    }
    with _registry_lock(root):
        data = _read_registry(root)
        data["containers"][name] = entry
        if set_default:
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


@contextmanager
def workspace_lock(root: Path, workspace_key: str, timeout: float = 10.0) -> Iterator[None]:
    """Hold a per-workspace lock for project Runtime start.

    Serializes ``registry/labels conflict check -> Docker create/ready ->
    registry commit`` for one canonical workspace so two concurrent
    ``project`` starts on the same workspace cannot both succeed.

    Lock file: ``<state_dir>/workspace-locks/<workspace_key>.lock``.
    Cross-platform and fail-closed, identical semantics to
    :func:`_registry_lock`. Lock order is ``workspace lock -> registry lock``;
    callers must not acquire the registry lock first.

    Args:
        root: Registry root (workspace root or ``.aisc`` dir).
        workspace_key: ``sha256`` hex of the canonical workspace path.
        timeout: Lock acquisition timeout in seconds.

    Raises:
        CliError (STATE_LOCK_TIMEOUT): if the lock cannot be acquired within *timeout*.
    """
    import sys
    import time as time_module

    state_dir = _state_dir(root)
    locks_dir = state_dir / "workspace-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = locks_dir / f"{workspace_key}.lock"
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
                except OSError as e:
                    if time_module.time() - start_time >= timeout:
                        raise CliError(
                            message=f"Failed to acquire workspace lock within {timeout}s",
                            exit_code=RuntimeExitCode.STATE_LOCK_TIMEOUT,
                            error_code=RuntimeErrorCode.STATE_LOCK_TIMEOUT,
                        ) from e
                    time_module.sleep(0.1)
        else:
            import fcntl
            import signal

            def timeout_handler(signum, frame):
                raise CliError(
                    message=f"Failed to acquire workspace lock within {timeout}s",
                    exit_code=RuntimeExitCode.STATE_LOCK_TIMEOUT,
                    error_code=RuntimeErrorCode.STATE_LOCK_TIMEOUT,
                )

            # SIGALRM-based timeout only works in the main thread; a non-main
            # caller (signal.signal raises ValueError) falls back to an
            # unbounded blocking flock. Fine for the single-threaded aisc CLI;
            # a future threaded caller would need a different timeout strategy.
            alarm_set = False
            try:
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(int(timeout) + 1)
                alarm_set = True
            except ValueError:
                alarm_set = False

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


def find_by_runtime_id(root: Path, runtime_id: str) -> Optional[tuple]:
    """Return ``(container_name, meta)`` for the registry entry matching
    *runtime_id*, or ``None`` if not found. Reads under the registry lock.
    """
    with _registry_lock(root):
        data = _read_registry(root)
        for name, meta in data["containers"].items():
            if isinstance(meta, dict) and meta.get("runtime_id", "") == runtime_id:
                import copy
                return name, copy.deepcopy(meta)
    return None


def unregister_by_runtime_id(root: Path, runtime_id: str) -> Optional[str]:
    """Remove the registry entry matching *runtime_id*.

    Returns the removed container name, or ``None`` if no entry matched.
    Repoints ``default`` when the removed entry was the default.
    """
    with _registry_lock(root):
        data = _read_registry(root)
        removed: Optional[str] = None
        for name, meta in data["containers"].items():
            if isinstance(meta, dict) and meta.get("runtime_id", "") == runtime_id:
                removed = name
                break
        if removed is None:
            return None
        data["containers"].pop(removed, None)
        if data["default"] == removed:
            data["default"] = _pick_newest(data["containers"])
        _write_registry_unlocked(root, data)
        return removed


def list_containers(root: Path) -> Dict[str, Dict[str, Any]]:
    """Return all registered container entries (name → meta).

    Reads registry snapshot under lock to ensure consistency.
    Returns a copy to prevent external mutation.
    """
    with _registry_lock(root):
        data = _read_registry(root)
        # Return a deep copy to prevent external mutation
        import copy
        return copy.deepcopy(data["containers"])


def list_containers_readonly(root: Path) -> Dict[str, Dict[str, Any]]:
    """Return all registered container entries (name → meta) without side effects.

    Read-only: does not acquire lock or create directories/files.
    For preflight and other observational operations.
    Returns empty dict if registry file doesn't exist.
    Raises exception if registry exists but is corrupted/unreadable.
    """
    import copy
    import json

    registry_file = _registry_path(root)
    if not registry_file.exists():
        return {}

    # File exists, so corruption/read errors must be raised
    with open(registry_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Registry root is not a dict")
    containers = data.get("containers", {})
    if not isinstance(containers, dict):
        raise ValueError("Registry containers field is not a dict")
    return copy.deepcopy(containers)


def get_default(root: Path) -> str:
    """Return the default container name, or empty string if none."""
    with _registry_lock(root):
        data = _read_registry(root)
        return data.get("default", "")


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

    Pattern: lock→snapshot→unlock→inspect→relock→compare→prune per contract.
    """
    # Phase 1: lock → snapshot → unlock
    with _registry_lock(root):
        snapshot = _read_registry(root)
        containers = snapshot.get("containers", {})
        if not containers:
            return []

    # Phase 2: Docker inspect outside lock
    missing: List[str] = []
    for nm in list(containers):
        exists = _container_exists(executor, nm)
        if exists is False:
            missing.append(nm)

    if not missing:
        return []

    # Phase 3: relock → compare current entry → conditional prune
    with _registry_lock(root):
        current_data = _read_registry(root)
        current_containers = current_data.get("containers", {})

        pruned: List[str] = []
        for nm in missing:
            # Do not delete a same-name container re-registered while Docker
            # checks were running.
            if current_containers.get(nm) == containers.get(nm):
                current_containers.pop(nm, None)
                pruned.append(nm)

        if pruned:
            if current_data["default"] in pruned:
                current_data["default"] = _pick_newest(current_containers)
            _write_registry_unlocked(root, current_data)
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

    containers = list_containers(resolved_root)

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
    default = get_default(resolved_root)
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
