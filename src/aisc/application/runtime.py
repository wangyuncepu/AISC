"""Runtime application logic for Workbench Phase 0."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.domain.models import RuntimeErrorCode, RuntimeExitCode


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

    # Compute can_start and recommended_action
    all_pass = all(c.status == "pass" for c in checks)
    can_start = all_pass and matching_runtime_id is None

    if not all_pass:
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
    elif conflicts:
        recommended_action = "resolve_conflict"
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
        containers = list_containers_readonly(registry_root)
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

    matching_runtime_id = None
    matching_state = None  # "running" or "stopped"
    conflicts: List[Dict[str, Any]] = []

    for container_name, meta in containers.items():
        meta_runtime_id = meta.get("runtime_id", "")
        meta_workspace = meta.get("workspace", "")
        meta_scope = meta.get("scope", "")
        meta_fingerprint = meta.get("config_fingerprint", "")

        # Check actual Docker container state
        docker_state = _get_container_state(container_name, executor)

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
        if result.returncode != 0:
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


