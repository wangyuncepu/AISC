"""Runtime commands implementation.

Implements aisc runtime subcommands: preflight, start, stop, list, inspect, etc.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from aisc.adapters.docker_ import DockerExecutor, RealDockerExecutor
from aisc.domain.models import RuntimeErrorCode, RuntimeSnapshot, RuntimeExitCode
from aisc.application.runtime import (
    compute_config_fingerprint,
    validate_uuid_v4,
    preflight_runtime,
    start_runtime,
    list_runtimes,
    inspect_runtime,
    stop_runtime,
    restart_runtime,
    remove_runtime,
)


def cmd_runtime_preflight(
    runtime_id: str,
    workspace: Optional[str] = None,
    image: str = "super-claude:latest",
    network: str = "direct",
    scope: str = "project",
    owner: str = "workbench",
    format: str = "text",
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Perform read-only preflight checks for runtime startup.

    Per docs/gui-planning/05-cli-gui-contract.md §5.1.

    Args:
        runtime_id: UUID v4 provided by Workbench
        workspace: Workspace path (defaults to cwd)
        image: Docker image name
        network: Network mode (direct/proxy)
        scope: Scope mode (project/temporary)
        owner: Owner identifier
        format: Output format (text/json)
        executor: Docker executor (for testing)

    Returns:
        Dict with preflight result payload
    """

    # Validate runtime_id
    if not validate_uuid_v4(runtime_id):
        return {
            "error": {
                "code": RuntimeErrorCode.INVALID_RUNTIME_ID,
                "message": f"Invalid runtime ID format (must be UUID v4): {runtime_id}",
            },
            "exit_code": RuntimeExitCode.INVALID_RUNTIME_ID,
        }

    # Validate scope
    if scope not in ("project", "temporary"):
        return {
            "error": {
                "code": RuntimeErrorCode.SCOPE_INVALID,
                "message": f"Invalid scope (must be project|temporary): {scope}",
            },
            "exit_code": RuntimeExitCode.USAGE_ERROR,
        }

    # Resolve workspace
    ws_path = Path(workspace).resolve() if workspace else Path.cwd()

    # Use RealDockerExecutor for preflight checks
    from aisc.adapters.docker_ import RealDockerExecutor
    exec_ = executor or RealDockerExecutor()

    # Execute preflight
    registry_root = ws_path / ".aisc"
    result = preflight_runtime(
        runtime_id=runtime_id,
        workspace=str(ws_path),
        image=image,
        network=network,
        scope=scope,
        owner=owner,
        executor=exec_,
        registry_root=registry_root,
    )

    # Convert to dict for JSON output
    return {
        "spec": result.spec,
        "checks": [
            {
                "id": c.id,
                "status": c.status,
                "error_code": c.error_code,
                "detail": c.detail,
            }
            for c in result.checks
        ],
        "can_start": result.can_start,
        "recommended_action": result.recommended_action,
        "matching_runtime_id": result.matching_runtime_id,
        "conflicts": result.conflicts,
        "observed_at": result.observed_at,
    }


# ---------------------------------------------------------------------------
# Runtime lifecycle commands (§5.2-5.5)
# ---------------------------------------------------------------------------

def _resolve_workspace_and_registry(workspace: Optional[str]) -> tuple:
    """Return (canonical_workspace_str, registry_root_path)."""
    ws_path = Path(workspace).resolve() if workspace else Path.cwd()
    return str(ws_path), ws_path / ".aisc"


def cmd_runtime_start(
    runtime_id: str,
    workspace: Optional[str] = None,
    image: str = "super-claude:latest",
    network: str = "direct",
    scope: str = "project",
    owner: str = "workbench",
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Execute ``aisc runtime start`` per contract §5.2."""
    exec_ = executor or RealDockerExecutor()
    ws, reg_root = _resolve_workspace_and_registry(workspace)
    result = start_runtime(
        runtime_id=runtime_id,
        workspace=ws,
        image=image,
        network=network,
        scope=scope,
        owner=owner,
        executor=exec_,
        registry_root=reg_root,
    )
    return result.to_dict()


def cmd_runtime_list(
    workspace: Optional[str] = None,
    owner: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Execute ``aisc runtime list`` per contract §5.3."""
    exec_ = executor or RealDockerExecutor()
    ws, reg_root = _resolve_workspace_and_registry(workspace)
    snapshots = list_runtimes(executor=exec_, registry_root=reg_root, owner=owner, workspace=ws)
    return {"runtimes": [s.to_dict() for s in snapshots], "observed_at": _iso_now()}


def cmd_runtime_inspect(
    runtime_id: str,
    workspace: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Execute ``aisc runtime inspect`` per contract §5.4."""
    exec_ = executor or RealDockerExecutor()
    _ws, reg_root = _resolve_workspace_and_registry(workspace)
    snapshot = inspect_runtime(runtime_id=runtime_id, executor=exec_, registry_root=reg_root)
    return snapshot.to_dict()


def cmd_runtime_stop(
    runtime_id: str,
    workspace: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Execute ``aisc runtime stop`` per contract §5.5."""
    exec_ = executor or RealDockerExecutor()
    _ws, reg_root = _resolve_workspace_and_registry(workspace)
    snapshot = stop_runtime(runtime_id=runtime_id, executor=exec_, registry_root=reg_root)
    return snapshot.to_dict()


def cmd_runtime_restart(
    runtime_id: str,
    workspace: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Execute ``aisc runtime restart`` per contract §5.5."""
    exec_ = executor or RealDockerExecutor()
    _ws, reg_root = _resolve_workspace_and_registry(workspace)
    snapshot = restart_runtime(runtime_id=runtime_id, executor=exec_, registry_root=reg_root)
    return snapshot.to_dict()


def cmd_runtime_remove(
    runtime_id: str,
    workspace: Optional[str] = None,
    force: bool = False,
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Execute ``aisc runtime remove`` per contract §5.5."""
    exec_ = executor or RealDockerExecutor()
    _ws, reg_root = _resolve_workspace_and_registry(workspace)
    snapshot = remove_runtime(
        runtime_id=runtime_id, executor=exec_, registry_root=reg_root, force=force
    )
    return snapshot.to_dict()


def _iso_now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def print_runtime_text(subcommand: str, data: Any, errors: list) -> None:
    """Minimal human-readable output for ``aisc runtime`` text mode."""
    if errors:
        for e in errors:
            print(f"Error: {e.get('message', '')}")
        return
    if not isinstance(data, dict):
        return
    if subcommand == "preflight":
        print(f"can_start: {data.get('can_start')}")
        print(f"recommended_action: {data.get('recommended_action')}")
        for c in data.get("checks", []):
            print(f"  {c.get('id')}: {c.get('status')}")
    elif subcommand == "start":
        cfg = data.get("config", {})
        print(f"runtime {data.get('runtime_id', '')}")
        print(f"  container: {data.get('container_name', '')} ({data.get('container_id', '')})")
        print(f"  state: {data.get('state', '')}  ready: {data.get('ready', '')}  "
              f"reused: {data.get('reused', '')}")
        print(f"  image: {cfg.get('image', '')}  network: {cfg.get('network', '')}  "
              f"scope: {cfg.get('scope', '')}")
    elif subcommand == "list":
        runtimes = data.get("runtimes", [])
        if not runtimes:
            print("(no runtimes)")
        for r in runtimes:
            print(f"{r.get('runtime_id', '')}  {r.get('container_name', '')}  "
                  f"state={r.get('state', '')}  registry={r.get('registry_state', '')}")
    elif subcommand in ("inspect", "stop", "restart", "remove"):
        print(f"runtime {data.get('runtime_id', '')}")
        print(f"  container: {data.get('container_name', '')}")
        print(f"  state: {data.get('state', '')}  registry: {data.get('registry_state', '')}")
