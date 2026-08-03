"""Runtime commands implementation.

Implements aisc runtime subcommands: preflight, start, stop, list, inspect, etc.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from aisc.adapters.docker_ import DockerExecutor, RealDockerExecutor
from aisc.domain.models import RuntimeErrorCode, RuntimeSnapshot
from aisc.application.runtime import compute_config_fingerprint, generate_runtime_id


def cmd_runtime_preflight(
    workspace: Optional[str] = None,
    image: str = "super-claude:latest",
    network: str = "direct",
    scope: str = "project",
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Perform read-only preflight checks for runtime startup.

    Checks:
    - Docker availability
    - Workspace validity
    - Image existence
    - Network configuration
    - Runtime conflicts (project scope only)

    Args:
        workspace: Workspace path (defaults to cwd)
        image: Docker image name
        network: Network mode (direct/proxy)
        scope: Scope mode (project/temporary)
        executor: Docker executor (for testing)

    Returns:
        Dict with structure:
        {
            "checks": {
                "docker": {"status": "pass/fail", "message": "..."},
                "workspace": {"status": "pass/fail", "message": "..."},
                "image": {"status": "pass/fail", "message": "..."},
                "network": {"status": "pass/fail", "message": "..."},
                "runtime_conflict": {"status": "pass/warn", "message": "..."}
            },
            "overall_status": "ready/warning/error",
            "config_fingerprint": "<hash>"
        }
    """
    exec_ = executor or RealDockerExecutor()
    checks: Dict[str, Dict[str, str]] = {}

    # Resolve workspace
    ws_path = Path(workspace).resolve() if workspace else Path.cwd()

    # Check 1: Docker availability
    try:
        # Try to run docker ps to check if Docker is available
        result = exec_.run_captured(["ps", "-q"], timeout=5.0)

        if result.command_not_found:
            checks["docker"] = {
                "status": "fail",
                "message": "Docker CLI not found",
                "error_code": RuntimeErrorCode.DOCKER_UNAVAIL,
            }
        elif result.exit_code != 0:
            checks["docker"] = {
                "status": "fail",
                "message": f"Docker daemon unreachable: {result.stderr.strip()}",
                "error_code": RuntimeErrorCode.DOCKER_UNAVAIL,
            }
        else:
            checks["docker"] = {"status": "pass", "message": "Docker is available"}
    except Exception as e:
        checks["docker"] = {
            "status": "fail",
            "message": f"Docker check failed: {str(e)}",
            "error_code": RuntimeErrorCode.DOCKER_UNAVAIL,
        }

    # Check 2: Workspace validity
    if not ws_path.exists():
        checks["workspace"] = {
            "status": "fail",
            "message": f"Workspace does not exist: {ws_path}",
            "error_code": RuntimeErrorCode.WORKSPACE_INVALID,
        }
    elif not ws_path.is_dir():
        checks["workspace"] = {
            "status": "fail",
            "message": f"Workspace is not a directory: {ws_path}",
            "error_code": RuntimeErrorCode.WORKSPACE_INVALID,
        }
    else:
        checks["workspace"] = {
            "status": "pass",
            "message": f"Workspace is valid: {ws_path}",
        }

    # Check 3: Image existence (only if Docker is available)
    if checks["docker"]["status"] == "pass":
        try:
            # Use docker image inspect to check if image exists
            result = exec_.run_captured(["image", "inspect", image], timeout=5.0)

            if result.exit_code == 0:
                checks["image"] = {"status": "pass", "message": f"Image exists: {image}"}
            else:
                checks["image"] = {
                    "status": "fail",
                    "message": f"Image not found: {image}",
                    "error_code": RuntimeErrorCode.IMAGE_NOT_FOUND,
                }
        except Exception as e:
            checks["image"] = {
                "status": "fail",
                "message": f"Image check failed: {str(e)}",
            }
    else:
        checks["image"] = {"status": "skip", "message": "Skipped (Docker unavailable)"}

    # Check 4: Network configuration
    if network == "direct":
        checks["network"] = {"status": "pass", "message": "Direct network mode"}
    elif network == "proxy":
        # TODO: Validate proxy config file exists
        checks["network"] = {"status": "pass", "message": "Proxy network mode"}
    else:
        checks["network"] = {
            "status": "fail",
            "message": f"Invalid network mode: {network}",
            "error_code": RuntimeErrorCode.NETWORK_INVALID,
        }

    # Check 5: Runtime conflict (project scope only)
    if scope == "project":
        # Check if a project runtime already exists for this workspace
        try:
            from aisc.adapters.container_registry import list_containers
            from aisc.application.resources import locate_aisc_root

            root = locate_aisc_root(explicit_root=str(ws_path))
            containers = list_containers(root)

            # Find project runtimes for this workspace
            project_runtimes = [
                (name, meta)
                for name, meta in containers.items()
                if meta.get("scope") == "project"
                and Path(meta.get("workspace", "")).resolve() == ws_path
            ]

            if project_runtimes:
                runtime_ids = [meta.get("runtime_id", name) for name, meta in project_runtimes]
                checks["runtime_conflict"] = {
                    "status": "warn",
                    "message": f"Project runtime(s) already exist: {', '.join(runtime_ids)}",
                }
            else:
                checks["runtime_conflict"] = {
                    "status": "pass",
                    "message": "No conflicting project runtime",
                }
        except Exception:
            checks["runtime_conflict"] = {
                "status": "pass",
                "message": "No conflicting project runtime (registry check skipped)",
            }
    else:
        checks["runtime_conflict"] = {
            "status": "pass",
            "message": "Temporary scope (no conflict check)",
        }

    # Compute config fingerprint
    fingerprint = compute_config_fingerprint(
        image=image,
        network=network,
        scope=scope,
        workspace=str(ws_path),
    )

    # Determine overall status
    failed = any(c["status"] == "fail" for c in checks.values())
    warned = any(c["status"] == "warn" for c in checks.values())

    if failed:
        overall_status = "error"
    elif warned:
        overall_status = "warning"
    else:
        overall_status = "ready"

    return {
        "checks": checks,
        "overall_status": overall_status,
        "config_fingerprint": fingerprint,
        "workspace": str(ws_path),
    }
