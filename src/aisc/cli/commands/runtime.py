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
