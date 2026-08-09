"""Runtime application logic for Workbench Phase 0."""

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aisc.domain.models import (
    CliError,
    ImageInspectStatus,
    RuntimeErrorCode,
    RuntimeExitCode,
    RuntimeSnapshot,
)


# ---------------------------------------------------------------------------
# UUID v4 validation
# ---------------------------------------------------------------------------

def validate_uuid_v4(runtime_id: str) -> bool:
    """Validate that runtime_id is a strict UUID v4.

    Returns True if valid, False otherwise.
    """
    uuid_v4_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    return bool(uuid_v4_pattern.match(runtime_id))


# ---------------------------------------------------------------------------
# Config fingerprint
# ---------------------------------------------------------------------------

def compute_config_fingerprint(
    image: str,
    network: str,
    scope: str,
    workspace: str,
) -> str:
    """Compute canonical config fingerprint for runtime identity.

    Returns sha256:<hex> format per docs/gui-planning/03-lifecycle-contract.md.
    """
    canonical_workspace = str(Path(workspace).resolve())
    config = {
        "image": image,
        "network": network,
        "scope": scope,
        "workspace": canonical_workspace,
    }
    config_str = json.dumps(config, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(config_str.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

@dataclass
class PreflightCheck:
    """Single preflight check result."""
    id: str
    status: str  # pass, warn, fail
    error_code: Optional[str] = None
    detail: Optional[str] = None


@dataclass
class PreflightResult:
    """Preflight command result per docs/gui-planning/05-cli-gui-contract.md §5.1."""
    spec: Dict[str, Any]
    checks: List[PreflightCheck]
    can_start: bool
    recommended_action: str  # start, reuse, restart, resolve_conflict
    matching_runtime_id: Optional[str]
    conflicts: List[Dict[str, Any]]
    observed_at: str


def preflight_runtime(
    runtime_id: str,
    workspace: str,
    image: str,
    network: str,
    scope: str,
    owner: str,
    executor: Any,
    registry_root: Optional[Path] = None,
) -> PreflightResult:
    """Execute preflight checks for runtime start.

    Read-only, zero side effects per contract §5.1.

    Args:
        runtime_id: UUID v4 provided by Workbench
        workspace: Target workspace path
        image: Docker image name
        network: Network mode (direct|proxy)
        scope: Runtime scope (project|temporary)
        owner: Owner identifier (workbench)
        executor: Docker executor for checks
        registry_root: Registry directory (defaults to workspace/.aisc)

    Returns:
        PreflightResult with all checks and recommendation
    """
    import time
    from aisc.adapters.container_registry import list_containers

    # Build spec
    try:
        canonical_workspace = str(Path(workspace).resolve())
    except Exception:
        canonical_workspace = workspace

    spec = {
        "runtime_id": runtime_id,
        "workspace": canonical_workspace,
        "image": image,
        "network": network,
        "scope": scope,
    }

    checks: List[PreflightCheck] = []

    # Check 1: docker
    docker_available = _check_docker(executor)
    if not docker_available:
        checks.append(PreflightCheck(
            id="docker",
            status="fail",
            error_code=RuntimeErrorCode.DOCKER_UNAVAILABLE,
            detail="Docker daemon is not running or CLI is not available"
        ))
    else:
        checks.append(PreflightCheck(id="docker", status="pass"))

    # Check 2: workspace
    workspace_valid = _check_workspace(workspace)
    if not workspace_valid:
        checks.append(PreflightCheck(
            id="workspace",
            status="fail",
            error_code=RuntimeErrorCode.WORKSPACE_INVALID,
            detail=f"Workspace does not exist or is not accessible: {workspace}"
        ))
    else:
        checks.append(PreflightCheck(id="workspace", status="pass"))

    # Check 3: image
    image_error = None
    if docker_available:
        image_error = _check_image(image, executor)
    else:
        image_error = RuntimeErrorCode.DOCKER_UNAVAILABLE

    if image_error:
        checks.append(PreflightCheck(
            id="image",
            status="fail",
            error_code=image_error,
            detail=f"Image not found: {image}" if image_error == RuntimeErrorCode.IMAGE_NOT_FOUND
            else "Cannot check image availability (Docker unreachable)"
        ))
    else:
        checks.append(PreflightCheck(id="image", status="pass"))

    # Check 4: network
    network_valid = network in ("direct", "proxy")
    if not network_valid:
        checks.append(PreflightCheck(
            id="network",
            status="fail",
            error_code=RuntimeErrorCode.NETWORK_INVALID,
            detail=f"Invalid network mode: {network}"
        ))
    else:
        checks.append(PreflightCheck(id="network", status="pass"))

    # Check 5: runtime_conflict
    if registry_root is None and workspace_valid:
        registry_root = Path(canonical_workspace) / ".aisc"

    conflict_check, matching_runtime_id, conflicts, matching_state = _check_runtime_conflict(
        runtime_id=runtime_id,
        workspace=canonical_workspace,
        image=image,
        network=network,
        scope=scope,
        registry_root=registry_root,
        docker_available=docker_available,
        executor=executor,
    )

    checks.append(conflict_check)

    # Compute can_start and recommended_action. "resolve_conflict" is reserved
    # for actual runtime conflicts (runtime_conflict check failed). Other
    # failed gates (docker down, image missing, bad workspace) keep
    # action="start" - the UI's per-gate messages/buttons drive recovery, and
    # a fresh install with a missing image must not be mislabeled as a
    # runtime conflict (S4.1.b regression).
    all_pass = all(c.status == "pass" for c in checks)
    can_start = all_pass and matching_runtime_id is None

    if conflict_check.status == "fail":
        recommended_action = "resolve_conflict"
    elif matching_runtime_id:
        # Config fingerprint matches existing runtime
        # Recommend reuse if running, restart if stopped
        if matching_state == "running":
            recommended_action = "reuse"
        elif matching_state == "stopped":
            recommended_action = "restart"
        else:
            # Unknown state, default to reuse
            recommended_action = "reuse"
    else:
        recommended_action = "start"

    observed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    return PreflightResult(
        spec=spec,
        checks=checks,
        can_start=can_start,
        recommended_action=recommended_action,
        matching_runtime_id=matching_runtime_id,
        conflicts=conflicts,
        observed_at=observed_at,
    )


def _check_docker(executor: Any) -> bool:
    """Check if Docker is available."""
    try:
        result = executor.preflight()
        return result.available
    except Exception:
        return False


def _check_workspace(workspace: str) -> bool:
    """Check if workspace exists and is a directory."""
    try:
        p = Path(workspace)
        return p.exists() and p.is_dir()
    except Exception:
        return False


def _check_image(image: str, executor: Any) -> Optional[str]:
    """Check if Docker image exists locally.

    Returns None if image exists, error code string otherwise.
    Distinguishes "image not found" from "cannot observe".
    """
    try:
        result = executor.inspect_image(image)
        from aisc.domain.models import ImageInspectStatus
        if result.status == ImageInspectStatus.EXISTS:
            return None
        if result.status == ImageInspectStatus.MISSING:
            return RuntimeErrorCode.IMAGE_NOT_FOUND
        # DOCKER_UNAVAILABLE, PERMISSION_DENIED, TIMEOUT, ERROR
        return RuntimeErrorCode.DOCKER_UNAVAILABLE
    except Exception:
        return RuntimeErrorCode.DOCKER_UNAVAILABLE


def _query_docker_labels(
    runtime_id: str,
    executor: Any,
) -> List[Dict[str, str]]:
    """Query Docker for containers with matching io.aisc.runtime-id label.

    Returns list of {container_name, container_id, state, labels...} dicts.
    Empty list if Docker unavailable or no matches.
    """
    try:
        filter_label = f"label=io.aisc.runtime-id={runtime_id}"
        result = executor.run_captured(
            ["ps", "-a", "--filter", filter_label, "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}"],
            timeout=10.0,
        )
    except AttributeError:
        # If executor doesn't have run_captured (e.g., protocol mock), skip
        return []
    except Exception:
        return []

    if result.exit_code != 0:
        return []

    containers = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            containers.append({
                "container_id": parts[0].strip(),
                "container_name": parts[1].strip(),
                "status": parts[2].strip(),
            })

    return containers


def _check_runtime_conflict(
    runtime_id: str,
    workspace: str,
    image: str,
    network: str,
    scope: str,
    registry_root: Optional[Path],
    docker_available: bool,
    executor: Any,
) -> tuple[PreflightCheck, Optional[str], List[Dict[str, Any]], Optional[str]]:
    """Check for runtime conflicts.

    Returns (check, matching_runtime_id, conflicts, matching_state).
    matching_state is "running", "stopped", or None.
    Fail-closed: if registry cannot be read, returns conflict fail.
    Also checks Docker labels to reconcile registry with actual container state.
    """
    from aisc.adapters.container_registry import list_containers_readonly

    if not docker_available or registry_root is None:
        # Cannot verify conflicts without Docker or registry
        return (
            PreflightCheck(id="runtime_conflict", status="pass"),
            None,
            [],
            None
        )

    # Read registry without lock (read-only snapshot)
    # Returns empty dict if registry doesn't exist (fresh workspace)
    # Raises exception if registry exists but is corrupted
    try:
        registry_containers = list_containers_readonly(registry_root)
    except Exception as e:
        # Fail-closed: registry exists but cannot be read
        return (
            PreflightCheck(
                id="runtime_conflict",
                status="fail",
                error_code=RuntimeErrorCode.RUNTIME_CONFLICT,
                detail=f"Cannot read registry: {e}"
            ),
            None,
            [],
            None
        )

    # Compute config fingerprint for this request
    fingerprint = compute_config_fingerprint(image, network, scope, workspace)

    # Query Docker for containers with matching runtime-id label
    docker_containers = _query_docker_labels(runtime_id, executor)
    registry_names = set(registry_containers.keys())

    # Track which Docker container names are NOT in registry
    docker_only_names = set()
    for dc in docker_containers:
        if dc["container_name"] not in registry_names:
            docker_only_names.add(dc["container_name"])

    matching_runtime_id = None
    matching_state = None  # "running" or "stopped"
    conflicts: List[Dict[str, Any]] = []

    # Process registry entries
    for container_name, meta in registry_containers.items():
        meta_runtime_id = meta.get("runtime_id", "")
        meta_workspace = meta.get("workspace", "")
        meta_scope = meta.get("scope", "")
        meta_fingerprint = meta.get("config_fingerprint", "")
        meta_owner = meta.get("owner", "")

        # Check actual Docker container state
        docker_state = _get_container_state(container_name, executor)

        # Legacy record detection: if scope or owner cannot be confirmed,
        # report as conflict per contract §5.1 line 140
        if not meta_scope or not meta_owner or not meta_runtime_id:
            conflicts.append({
                "runtime_id": meta_runtime_id or "(missing)",
                "container_name": container_name,
                "reason": (
                    "Legacy container record: missing "
                    + ", ".join(
                        [f for f, v in [
                            ("runtime_id", meta_runtime_id),
                            ("scope", meta_scope),
                            ("owner", meta_owner),
                        ] if not v]
                    )
                )
            })
            continue

        # Same runtime ID, same fingerprint -> can reuse or restart
        if meta_runtime_id == runtime_id and meta_fingerprint == fingerprint:
            matching_runtime_id = meta_runtime_id
            matching_state = docker_state
            continue

        # Same runtime ID, different fingerprint -> conflict
        if meta_runtime_id == runtime_id and meta_fingerprint != fingerprint:
            conflicts.append({
                "runtime_id": meta_runtime_id,
                "container_name": container_name,
                "reason": "Runtime ID already in use with different config"
            })
            continue

        # Project scope: same workspace -> conflict
        if scope == "project" and meta_scope == "project":
            try:
                canonical_meta_workspace = str(Path(meta_workspace).resolve())
                canonical_request_workspace = str(Path(workspace).resolve())
                if canonical_meta_workspace == canonical_request_workspace:
                    conflicts.append({
                        "runtime_id": meta_runtime_id,
                        "container_name": container_name,
                        "reason": "Project runtime already exists for this workspace"
                    })
            except Exception:
                pass

    # Report Docker-only containers as conflicts (label reconciliation)
    for dc in docker_containers:
        name = dc["container_name"]
        if name in docker_only_names and name not in registry_names:
            conflicts.append({
                "runtime_id": runtime_id,
                "container_name": name,
                "reason": "Container exists in Docker but not in registry (labels only)"
            })

    if conflicts:
        return (
            PreflightCheck(
                id="runtime_conflict",
                status="fail",
                error_code=RuntimeErrorCode.RUNTIME_CONFLICT,
                detail=f"Found {len(conflicts)} conflicting runtime(s)"
            ),
            matching_runtime_id,
            conflicts,
            matching_state
        )

    return (
        PreflightCheck(id="runtime_conflict", status="pass"),
        matching_runtime_id,
        [],
        matching_state
    )


def _get_container_state(container_name: str, executor: Any) -> Optional[str]:
    """Get container state from Docker.

    Returns "running", "stopped", or None if container doesn't exist or error.
    """
    try:
        result = executor.inspect_container(container_name)
        if result.exit_code != 0:
            return None

        # Parse JSON output to get State.Running
        import json
        data = json.loads(result.stdout)
        if isinstance(data, list) and len(data) > 0:
            state = data[0].get("State", {})
            running = state.get("Running", False)
            return "running" if running else "stopped"
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Runtime lifecycle: start / list / inspect / stop / restart / remove
# (docs/gui-planning/05-cli-gui-contract.md §5.2-5.5)
# ---------------------------------------------------------------------------

_RUNTIME_CONTEXT_PATH = "/run/aisc/runtime-context.json"
_RUNTIME_CONTEXT_SCHEMA = "aisc.runtime-context/v1"
_READY_POLL_INTERVAL = 0.5
_READY_DEFAULT_TIMEOUT = 60.0


def container_name_for(runtime_id: str) -> str:
    """Deterministic container name: ``aisc-wb-<first 8 hex of runtime_id>``.

    Matches contract §5.2 example ``aisc-wb-0e7b7e3b``. Deterministic name
    enables idempotent retry and targeted ``docker rm``.

    Note: the 8-hex prefix carries 32 bits of entropy. Docker container names
    are global, and the conflict check is keyed on ``runtime_id`` (128 bits),
    not on the name. At ~65k runtimes per Docker daemon the birthday bound
    makes a name collision plausible; a colliding ``docker run --name`` then
    fails with RUNTIME_OPERATION_FAILED rather than a conflict. Acceptable for
    a single workstation; revisit if multi-tenant.
    """
    return f"aisc-wb-{runtime_id.split('-', 1)[0]}"


def workspace_key_for(workspace: str) -> str:
    """Return ``sha256`` hex of the canonical workspace path.

    Used as ``io.aisc.workspace-key`` label and the workspace-lock filename.
    Never the raw host path.
    """
    canonical = str(Path(workspace).resolve())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _docker_status_to_state(status: str) -> str:
    """Map a ``docker ps`` status string to a runtime state."""
    if not status:
        return "unknown"
    if status.startswith("Up"):
        return "running"
    return "stopped"


def _find_docker_container_by_runtime_id(
    runtime_id: str, executor: Any
) -> Optional[Dict[str, str]]:
    """Find a Docker container carrying ``io.aisc.runtime-id=<runtime_id>``.

    Returns ``{container_name, container_id, state}`` or ``None``. Uses the
    same label query as preflight reconciliation.
    """
    containers = _query_docker_labels(runtime_id, executor)
    if not containers:
        return None
    c = containers[0]
    return {
        "container_name": c.get("container_name", ""),
        "container_id": c.get("container_id", ""),
        "state": _docker_status_to_state(c.get("status", "")),
    }


def resolve_running_container(
    runtime_id: str,
    executor: Any,
    registry_root: Any,
) -> str:
    """Resolve *runtime_id* to a running container's name.

    Used by data-plane commands (session, provider) that need to ``docker exec``
    into the runtime. Raises ``CliError`` with a stable code if Docker is
    unavailable, the runtime is not found, or it is not running.
    """
    from aisc.adapters.container_registry import find_by_runtime_id

    if not _check_docker(executor):
        raise CliError(
            message="Docker daemon is not running or CLI is not available",
            exit_code=RuntimeExitCode.DOCKER_UNAVAILABLE,
            error_code=RuntimeErrorCode.DOCKER_UNAVAILABLE,
        )

    container_name = ""
    found = find_by_runtime_id(registry_root, runtime_id)
    if found is not None:
        container_name = found[0]
    else:
        dc = _find_docker_container_by_runtime_id(runtime_id, executor)
        if dc is not None:
            container_name = dc["container_name"]

    if not container_name:
        raise CliError(
            message=f"Runtime not found: {runtime_id}",
            exit_code=RuntimeExitCode.GENERAL_ERROR,
            error_code=RuntimeErrorCode.RUNTIME_NOT_FOUND,
        )

    state = _get_container_state(container_name, executor)
    if state != "running":
        raise CliError(
            message=f"Runtime is not running (state: {state or 'not_found'}). "
                    f"Start it first: aisc runtime start --runtime-id {runtime_id}",
            exit_code=RuntimeExitCode.RUNTIME_NOT_RUNNING,
            error_code=RuntimeErrorCode.RUNTIME_NOT_RUNNING,
        )

    return container_name


def _list_docker_runtime_containers(
    executor: Any, workspace_key: Optional[str] = None
) -> List[Dict[str, str]]:
    """List Docker containers labeled ``io.aisc.managed=true kind=runtime``.

    Optionally filtered by ``io.aisc.workspace-key``. Returns dicts with
    ``container_name``, ``container_id``, ``state``, ``runtime_id``,
    ``workspace_key``, ``owner``, ``image``.
    """
    fmt = (
        "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t"
        "{{.Label \"io.aisc.runtime-id\"}}\t"
        "{{.Label \"io.aisc.workspace-key\"}}\t"
        "{{.Label \"io.aisc.owner\"}}"
    )
    argv = [
        "ps", "-a",
        "--filter", "label=io.aisc.managed=true",
        "--filter", "label=io.aisc.kind=runtime",
        "--format", fmt,
    ]
    try:
        result = executor.run_captured(argv, timeout=10.0)
    except AttributeError:
        return []
    except Exception:
        # Transient docker ps failure (e.g. a momentary timeout): Docker-only
        # containers become invisible this round and any registry entry for
        # them is reported as state="not_found". A false negative, not an
        # error - _require_docker already passed; the next refresh recovers.
        return []
    if result.exit_code != 0:
        return []

    out: List[Dict[str, str]] = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        cid, name, image, status, rid, wskey, owner = parts[:7]
        if workspace_key is not None and wskey != workspace_key:
            continue
        out.append({
            "container_id": cid.strip(),
            "container_name": name.strip(),
            "image": image.strip(),
            "state": _docker_status_to_state(status.strip()),
            "runtime_id": rid.strip(),
            "workspace_key": wskey.strip(),
            "owner": owner.strip(),
        })
    return out


def _wait_ready(
    executor: Any,
    container_name: str,
    runtime_id: str,
    timeout: float = _READY_DEFAULT_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    """Poll the container's runtime-context.json until ready or timeout.

    Returns the validated context dict, or ``None`` on timeout/validation
    failure. Ready means: file exists, parses, ``schema_version`` present and
    ``runtime_id`` matches. Transient ``docker exec`` errors (e.g. the
    container briefly in a "restarting" state) keep polling until the deadline
    rather than aborting cleanup of a healthy container.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = executor.run_captured(
                ["exec", container_name, "cat", _RUNTIME_CONTEXT_PATH],
                timeout=5.0,
            )
        except Exception:
            # Transient exec error; retry until deadline.
            time.sleep(_READY_POLL_INTERVAL)
            continue
        if result.exit_code == 0 and result.stdout.strip():
            try:
                ctx = json.loads(result.stdout)
            except (ValueError, TypeError):
                ctx = None
            if isinstance(ctx, dict) and ctx.get("runtime_id") == runtime_id \
                    and ctx.get("schema_version"):
                return ctx
        time.sleep(_READY_POLL_INTERVAL)
    return None


def _resolve_registry_root(
    workspace: str, registry_root: Optional[Path]
) -> Path:
    """Return the ``.aisc`` registry dir for *workspace*."""
    if registry_root is not None:
        return registry_root
    return Path(workspace).resolve() / ".aisc"


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _require_docker(executor: Any) -> None:
    """Raise CliError(3) if Docker is unavailable."""
    if not _check_docker(executor):
        raise CliError(
            message="Docker daemon is not running or CLI is not available",
            exit_code=RuntimeExitCode.DOCKER_UNAVAILABLE,
            error_code=RuntimeErrorCode.DOCKER_UNAVAILABLE,
        )


def _require_image(image: str, executor: Any) -> None:
    """Raise CliError if *image* is not locally available."""
    err = _check_image(image, executor)
    if err is None:
        return
    if err == RuntimeErrorCode.IMAGE_NOT_FOUND:
        raise CliError(
            message=f"Image '{image}' not found. Build it first: aisc build --tag {image}",
            exit_code=RuntimeExitCode.IMAGE_NOT_FOUND,
            error_code=RuntimeErrorCode.IMAGE_NOT_FOUND,
        )
    # DOCKER_UNAVAILABLE / others
    raise CliError(
        message=f"Cannot verify image '{image}': Docker unreachable",
        exit_code=RuntimeExitCode.DOCKER_UNAVAILABLE,
        error_code=RuntimeErrorCode.DOCKER_UNAVAILABLE,
    )


@dataclass
class RuntimeStartResult:
    """Result of ``aisc runtime start`` per contract §5.2."""
    runtime_id: str
    container_name: str
    container_id: str
    state: str
    ready: bool
    reused: bool
    config: Dict[str, Any]
    config_fingerprint: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtime_id": self.runtime_id,
            "container_name": self.container_name,
            "container_id": self.container_id,
            "state": self.state,
            "ready": self.ready,
            "reused": self.reused,
            "config": self.config,
            "config_fingerprint": self.config_fingerprint,
            "created_at": self.created_at,
        }


def _build_start_payload(
    runtime_id: str,
    workspace: str,
    image: str,
    network: str,
    scope: str,
    container_name: str,
    container_id: str,
    state: str,
    ready: bool,
    reused: bool,
    fingerprint: str,
) -> RuntimeStartResult:
    return RuntimeStartResult(
        runtime_id=runtime_id,
        container_name=container_name,
        container_id=container_id,
        state=state,
        ready=ready,
        reused=reused,
        config={
            "workspace": workspace,
            "image": image,
            "network": network,
            "scope": scope,
        },
        config_fingerprint=fingerprint,
        created_at=iso_now(),
    )


def start_runtime(
    runtime_id: str,
    workspace: str,
    image: str,
    network: str,
    scope: str,
    owner: str,
    executor: Any,
    registry_root: Optional[Path] = None,
    ready_timeout: float = _READY_DEFAULT_TIMEOUT,
    proxy_config: Optional[str] = None,
) -> RuntimeStartResult:
    """Start a Workbench runtime per contract §5.2.

    Acquires the workspace lock, re-validates conflicts (idempotent reuse /
    conflict), creates a detached idle container, waits for readiness, then
    commits the registry entry. On registry-commit failure the new container
    is removed. Returns the §5.2 payload.
    """
    from aisc.adapters.container_registry import (
        list_containers_readonly,
        register,
        workspace_lock,
    )

    # --- validate inputs ---
    if not validate_uuid_v4(runtime_id):
        raise CliError(
            message=f"Invalid runtime ID (must be UUID v4): {runtime_id}",
            exit_code=RuntimeExitCode.INVALID_RUNTIME_ID,
            error_code=RuntimeErrorCode.INVALID_RUNTIME_ID,
        )
    if scope not in ("project", "temporary"):
        raise CliError(
            message=f"Invalid scope (must be project|temporary): {scope}",
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code=RuntimeErrorCode.SCOPE_INVALID,
        )
    if network not in ("direct", "proxy"):
        raise CliError(
            message=f"Invalid network (must be direct|proxy): {network}",
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code=RuntimeErrorCode.NETWORK_INVALID,
        )

    ws_path = Path(workspace).resolve()
    if not (ws_path.exists() and ws_path.is_dir()):
        raise CliError(
            message=f"Workspace does not exist or is not a directory: {ws_path}",
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code=RuntimeErrorCode.WORKSPACE_INVALID,
        )

    canonical_workspace = str(ws_path)
    fingerprint = compute_config_fingerprint(image, network, scope, canonical_workspace)
    ws_key = workspace_key_for(canonical_workspace)
    container_name = container_name_for(runtime_id)
    reg_root = _resolve_registry_root(canonical_workspace, registry_root)

    _require_docker(executor)
    _require_image(image, executor)

    # --- workspace lock covers conflict check -> create -> ready -> commit ---
    # Timeout must exceed ready_timeout so a concurrent project start on the same
    # workspace waits for the winner (then sees its registry entry -> conflict)
    # rather than spuriously failing with STATE_LOCK_TIMEOUT.
    with workspace_lock(reg_root, ws_key, timeout=ready_timeout + 30.0):
        # Re-validate inside the lock; do not trust client preflight.
        # conflict_check (PreflightCheck) is advisory only and unused here;
        # start decides from matching_runtime_id / conflicts / matching_state.
        _conflict_check, matching_runtime_id, conflicts, matching_state = (
            _check_runtime_conflict(
                runtime_id=runtime_id,
                workspace=canonical_workspace,
                image=image,
                network=network,
                scope=scope,
                registry_root=reg_root,
                docker_available=True,
                executor=executor,
            )
        )

        # Idempotent reuse: same runtime_id + same fingerprint already registered.
        if matching_runtime_id == runtime_id:
            reg_entries = list_containers_readonly(reg_root)
            reuse_name = ""
            reuse_meta: Dict[str, Any] = {}
            for nm, meta in reg_entries.items():
                if isinstance(meta, dict) and meta.get("runtime_id") == runtime_id \
                        and meta.get("config_fingerprint") == fingerprint:
                    reuse_name = nm
                    reuse_meta = meta
                    break
            state = matching_state or "unknown"
            ready = state == "running"
            # A stopped matching runtime cannot satisfy `start`'s running
            # contract; restart it so the caller gets a ready runtime rather
            # than a reused-but-stopped limbo. `reused` stays True (the
            # container itself is reused, not freshly created).
            if state == "stopped":
                start_proc = executor.run_captured(["start", reuse_name], timeout=30.0)
                if start_proc.exit_code != 0:
                    raise CliError(
                        message=f"Failed to restart reused runtime: {(start_proc.stderr or '').strip()}",
                        exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
                        error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
                        data={"container_name": reuse_name, "reused": True},
                    )
                ctx = _wait_ready(executor, reuse_name, runtime_id, ready_timeout)
                if ctx is None:
                    raise CliError(
                        message=f"Reused runtime did not become ready within {ready_timeout}s",
                        exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
                        error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
                        data={"container_name": reuse_name, "reused": True},
                    )
                state = "running"
                ready = True
            return _build_start_payload(
                runtime_id, canonical_workspace, image, network, scope,
                reuse_name, reuse_meta.get("container_id", ""),
                state, ready, reused=True, fingerprint=fingerprint,
            )

        # Any conflict blocks creation.
        if conflicts:
            detail = "; ".join(
                f"{c.get('container_name', c.get('runtime_id', '?'))}: {c.get('reason', '')}"
                for c in conflicts
            )
            raise CliError(
                message=f"Runtime conflict prevents start: {detail}",
                exit_code=RuntimeExitCode.RUNTIME_CONFLICT,
                error_code=RuntimeErrorCode.RUNTIME_CONFLICT,
                data={"conflicts": conflicts, "config_fingerprint": fingerprint},
            )

        # --- create detached idle container ---
        argv = [
            "run", "-d",
            "--name", container_name,
            "--label", "io.aisc.managed=true",
            "--label", "io.aisc.kind=runtime",
            "--label", f"io.aisc.runtime-id={runtime_id}",
            "--label", f"io.aisc.owner={owner}",
            "--label", f"io.aisc.workspace-key={ws_key}",
            "-e", f"CLI_SCOPE={scope}",
            "-e", "AISC_RUNTIME_MODE=idle",
            "-e", f"AISC_RUNTIME_ID={runtime_id}",
            "-e", "TERM=xterm-256color",
            "-v", f"{canonical_workspace}:/root/app",
        ]
        if network == "proxy":
            argv.extend(["--cap-add=NET_ADMIN", "--device", "/dev/net/tun"])
            if proxy_config:
                argv.extend(["-v", f"{proxy_config}:/etc/mihomo/config.yaml:ro"])
        argv.append(image)

        proc = executor.run_captured(argv, timeout=60.0)
        if proc.exit_code != 0 or not (proc.stdout or "").strip():
            raise CliError(
                message=f"Failed to create runtime container: {(proc.stderr or '').strip()}",
                exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
                error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
                data={"container_name": container_name, "config_fingerprint": fingerprint},
            )
        container_id = proc.stdout.strip()

        # --- ready check ---
        ctx = _wait_ready(executor, container_name, runtime_id, ready_timeout)
        if ctx is None:
            # Best-effort cleanup; report partial identity.
            _safe_remove(executor, container_name)
            raise CliError(
                message=f"Runtime container did not become ready within {ready_timeout}s",
                exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
                error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
                data={
                    "container_name": container_name,
                    "container_id": container_id,
                    "config_fingerprint": fingerprint,
                },
            )

        # --- commit registry entry (registry lock acquired inside register) ---
        try:
            register(reg_root, container_name, {
                "image": image,
                "workspace": canonical_workspace,
                "network": network,
                "label": "",
                "runtime_id": runtime_id,
                "owner": owner,
                "scope": scope,
                "config_fingerprint": fingerprint,
                "container_id": container_id,
                "workspace_key": ws_key,
            })
        except CliError:
            # register raises CliError(STATE_LOCK_TIMEOUT) if the registry lock
            # times out. Cleanup the just-created container but preserve the
            # original error code (do not remap to RUNTIME_OPERATION_FAILED).
            _safe_remove(executor, container_name)
            raise
        except (ValueError, OSError) as exc:
            # Registry commit failed: remove the new container, report partial.
            cleanup_ok = _safe_remove(executor, container_name)
            raise CliError(
                message=(
                    f"Failed to commit registry: {exc}. "
                    f"Container cleanup {'succeeded' if cleanup_ok else 'FAILED - orphaned'}."
                ),
                exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
                error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
                data={
                    "container_name": container_name,
                    "container_id": container_id,
                    "config_fingerprint": fingerprint,
                    "cleanup_ok": cleanup_ok,
                },
            ) from exc

        return _build_start_payload(
            runtime_id, canonical_workspace, image, network, scope,
            container_name, container_id,
            state="running", ready=True, reused=False, fingerprint=fingerprint,
        )


def _safe_remove(executor: Any, container_name: str) -> bool:
    """Best-effort ``docker rm -f``; returns True if it succeeded."""
    try:
        result = executor.remove_container(container_name, force=True)
        return result.exit_code == 0
    except Exception:
        return False


def _snapshot_from_registry(
    name: str,
    meta: Dict[str, Any],
    docker_state: Optional[str],
    observed_at: str,
    registry_state: str = "registered",
) -> RuntimeSnapshot:
    """Build a RuntimeSnapshot from a registry entry + observed Docker state.

    ``registry_state`` is "registered" when the meta came from the registry,
    or "missing" when the container was discovered via Docker labels only.
    """
    state = docker_state or "not_found"
    return RuntimeSnapshot(
        runtime_id=meta.get("runtime_id", ""),
        state=state,
        workspace=meta.get("workspace", ""),
        image=meta.get("image", ""),
        network=meta.get("network", "direct"),
        scope=meta.get("scope", "project"),
        owner=meta.get("owner", ""),
        config_fingerprint=meta.get("config_fingerprint", ""),
        container_name=name,
        container_id=meta.get("container_id", ""),
        registry_state=registry_state,
        observed_at=observed_at,
    )


def list_runtimes(
    executor: Any,
    registry_root: Path,
    owner: Optional[str] = None,
    workspace: Optional[str] = None,
) -> List[RuntimeSnapshot]:
    """List runtimes with registry/Docker reconciliation per contract §5.3.

    Docker unavailable -> CliError(3); never disguises cached state as live.
    Containers present in Docker but absent from registry are marked
    ``registry_state: "missing"`` and never auto-deleted.
    """
    from aisc.adapters.container_registry import list_containers

    _require_docker(executor)

    canonical_workspace = str(Path(workspace).resolve()) if workspace else None
    ws_key = workspace_key_for(canonical_workspace) if canonical_workspace else None
    observed_at = iso_now()

    reg_entries = list_containers(registry_root)

    # Docker-managed runtime containers for this workspace (or all if no ws).
    docker_containers = _list_docker_runtime_containers(executor, workspace_key=ws_key)
    docker_by_name = {dc["container_name"]: dc for dc in docker_containers}

    snapshots: List[RuntimeSnapshot] = []
    seen_names: set = set()

    for name, meta in reg_entries.items():
        if not isinstance(meta, dict):
            continue
        if owner is not None and meta.get("owner", "") != owner:
            continue
        if canonical_workspace is not None:
            try:
                if str(Path(meta.get("workspace", "")).resolve()) != canonical_workspace:
                    continue
            except Exception:
                continue
        dc = docker_by_name.get(name)
        docker_state = dc["state"] if dc else None
        snapshots.append(_snapshot_from_registry(name, meta, docker_state, observed_at))
        seen_names.add(name)

    # Docker-only (registry missing) containers for this workspace.
    for dc in docker_containers:
        name = dc["container_name"]
        if name in seen_names:
            continue
        if owner is not None and dc.get("owner", "") != owner:
            continue
        snapshots.append(RuntimeSnapshot(
            runtime_id=dc.get("runtime_id", ""),
            state=dc.get("state", "unknown"),
            workspace=canonical_workspace or "",
            image=dc.get("image", ""),
            network="",
            scope="",
            owner=dc.get("owner", ""),
            config_fingerprint="",
            container_name=name,
            container_id=dc.get("container_id", ""),
            registry_state="missing",
            observed_at=observed_at,
        ))

    return snapshots


def inspect_runtime(
    runtime_id: str,
    executor: Any,
    registry_root: Path,
) -> RuntimeSnapshot:
    """Return a single runtime snapshot per contract §5.4.

    Distinguishes ``not_found`` (Docker & registry both absent), ``stopped``
    (container exists, not running) and ``unknown`` (Docker daemon/permission
    unavailable).
    """
    from aisc.adapters.container_registry import find_by_runtime_id

    if not validate_uuid_v4(runtime_id):
        raise CliError(
            message=f"Invalid runtime ID (must be UUID v4): {runtime_id}",
            exit_code=RuntimeExitCode.INVALID_RUNTIME_ID,
            error_code=RuntimeErrorCode.INVALID_RUNTIME_ID,
        )

    observed_at = iso_now()

    # Docker unavailable -> cannot confirm actual state.
    if not _check_docker(executor):
        return RuntimeSnapshot(
            runtime_id=runtime_id,
            state="unknown",
            registry_state="unknown",
            observed_at=observed_at,
            stale=True,
        )

    found = find_by_runtime_id(registry_root, runtime_id)
    reg_name, reg_meta = (found if found else (None, None))
    dc = _find_docker_container_by_runtime_id(runtime_id, executor)

    if reg_name is None and dc is None:
        return RuntimeSnapshot(
            runtime_id=runtime_id,
            state="not_found",
            registry_state="not_found",
            observed_at=observed_at,
        )

    if reg_name is not None and reg_meta is not None:
        docker_state = dc["state"] if dc else "not_found"
        return _snapshot_from_registry(reg_name, reg_meta, docker_state, observed_at)

    # Docker-only (registry missing).
    return RuntimeSnapshot(
        runtime_id=runtime_id,
        state=dc["state"] if dc else "not_found",
        container_name=dc["container_name"] if dc else "",
        container_id=dc["container_id"] if dc else "",
        registry_state="missing",
        observed_at=observed_at,
    )


def _resolve_container_for_lifecycle(
    runtime_id: str,
    executor: Any,
    registry_root: Path,
) -> Tuple[str, str, Dict[str, Any], str]:
    """Resolve (container_name, container_id, meta, registry_state) for
    stop/restart/remove.

    Prefers the registry entry (registry_state="registered"); falls back to
    Docker label discovery (registry_state="missing"). Raises
    CliError(RUNTIME_NOT_FOUND) if absent from both.
    """
    from aisc.adapters.container_registry import find_by_runtime_id

    if not validate_uuid_v4(runtime_id):
        raise CliError(
            message=f"Invalid runtime ID (must be UUID v4): {runtime_id}",
            exit_code=RuntimeExitCode.INVALID_RUNTIME_ID,
            error_code=RuntimeErrorCode.INVALID_RUNTIME_ID,
        )
    _require_docker(executor)

    found = find_by_runtime_id(registry_root, runtime_id)
    if found is not None:
        name, meta = found
        return name, meta.get("container_id", ""), meta, "registered"

    dc = _find_docker_container_by_runtime_id(runtime_id, executor)
    if dc is not None:
        return dc["container_name"], dc["container_id"], {
            "runtime_id": runtime_id,
            "container_id": dc["container_id"],
            "workspace": "",
            "image": "",
            "network": "",
            "scope": "",
            "owner": "",
            "config_fingerprint": "",
        }, "missing"

    raise CliError(
        message=f"Runtime not found: {runtime_id}",
        exit_code=RuntimeExitCode.GENERAL_ERROR,
        error_code=RuntimeErrorCode.RUNTIME_NOT_FOUND,
    )


def stop_runtime(
    runtime_id: str,
    executor: Any,
    registry_root: Path,
    grace_seconds: int = 10,
) -> RuntimeSnapshot:
    """Stop a runtime but keep container + registry metadata per §5.5.

    Idempotent for a stopped-but-present container: ``docker stop`` on an
    already-stopped container is a no-op success. A runtime whose container
    is gone raises RUNTIME_NOT_FOUND. ``grace_seconds`` is passed through to
    ``docker stop -t`` (CLI default 10; Workbench fast path 3).
    """
    name, container_id, meta, registry_state = _resolve_container_for_lifecycle(
        runtime_id, executor, registry_root
    )
    result = executor.stop_container(name, timeout=grace_seconds)
    if result.exit_code != 0:
        stderr = (result.stderr or "").lower()
        if any(kw in stderr for kw in ("no such", "not found")):
            raise CliError(
                message=f"Runtime container not found: {name}",
                exit_code=RuntimeExitCode.GENERAL_ERROR,
                error_code=RuntimeErrorCode.RUNTIME_NOT_FOUND,
            )
        raise CliError(
            message=f"Failed to stop runtime: {(result.stderr or '').strip()}",
            exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
            error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
        )
    return _snapshot_from_registry(
        name, meta, "stopped", iso_now(), registry_state=registry_state
    )


def restart_runtime(
    runtime_id: str,
    executor: Any,
    registry_root: Path,
    ready_timeout: float = _READY_DEFAULT_TIMEOUT,
) -> RuntimeSnapshot:
    """Restart the same container with its original config per §5.5.

    Waits for readiness before returning.
    """
    name, container_id, meta, registry_state = _resolve_container_for_lifecycle(
        runtime_id, executor, registry_root
    )
    result = executor.run_captured(["start", name], timeout=30.0)
    if result.exit_code != 0:
        raise CliError(
            message=f"Failed to restart runtime: {(result.stderr or '').strip()}",
            exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
            error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
        )
    ctx = _wait_ready(executor, name, runtime_id, ready_timeout)
    if ctx is None:
        raise CliError(
            message=f"Restarted runtime did not become ready within {ready_timeout}s",
            exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
            error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
        )
    return _snapshot_from_registry(
        name, meta, "running", iso_now(), registry_state=registry_state
    )


def remove_runtime(
    runtime_id: str,
    executor: Any,
    registry_root: Path,
    force: bool = False,
) -> RuntimeSnapshot:
    """Delete the container and unregister the runtime per §5.5.

    A running runtime is rejected unless ``force`` is set. Idempotent: removing
    an already-removed runtime returns a not_found snapshot (rc 0) per §十二.
    """
    from aisc.adapters.container_registry import unregister_by_runtime_id

    try:
        name, container_id, meta, _registry_state = _resolve_container_for_lifecycle(
            runtime_id, executor, registry_root
        )
    except CliError as exc:
        if exc.error_code == RuntimeErrorCode.RUNTIME_NOT_FOUND:
            # Idempotent: already removed -> not_found success (contract §十二).
            return RuntimeSnapshot(
                runtime_id=runtime_id,
                state="not_found",
                workspace="",
                image="",
                network="",
                scope="",
                owner="",
                config_fingerprint="",
                container_name="",
                container_id="",
                registry_state="not_found",
                observed_at=iso_now(),
            )
        raise

    # Refuse to remove a running runtime without --force.
    state = _get_container_state(name, executor)
    if state == "running" and not force:
        raise CliError(
            message=(
                f"Runtime {runtime_id} is running. "
                "Stop it first or pass --force to remove a running runtime."
            ),
            exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
            error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
            data={"runtime_id": runtime_id, "state": "running"},
        )

    result = executor.remove_container(name, force=force)
    if result.exit_code != 0:
        stderr = (result.stderr or "").lower()
        if not any(kw in stderr for kw in ("no such", "not found")):
            raise CliError(
                message=f"Failed to remove runtime: {(result.stderr or '').strip()}",
                exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
                error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
            )

    unregister_by_runtime_id(registry_root, runtime_id)

    return RuntimeSnapshot(
        runtime_id=runtime_id,
        state="not_found",
        workspace=meta.get("workspace", ""),
        image=meta.get("image", ""),
        network=meta.get("network", ""),
        scope=meta.get("scope", ""),
        owner=meta.get("owner", ""),
        config_fingerprint=meta.get("config_fingerprint", ""),
        container_name=name,
        container_id=container_id,
        registry_state="not_found",
        observed_at=iso_now(),
    )


