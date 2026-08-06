"""Provider command implementation (Workbench Phase 0 S0.4).

Implements ``aisc provider current``. The legacy interactive ``set-key``
subcommand stays in ``aisc.cli.commands.container`` / ``main.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from aisc.adapters.docker_ import DockerExecutor, RealDockerExecutor
from aisc.application.provider import current_provider


def _resolve_workspace_and_registry(workspace: Optional[str]):
    ws_path = Path(workspace).resolve() if workspace else Path.cwd()
    return str(ws_path), ws_path / ".aisc"


def cmd_provider_current(
    runtime_id: str,
    agent: str,
    workspace: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Execute ``aisc provider current`` per contract §七."""
    exec_ = executor or RealDockerExecutor()
    _ws, reg_root = _resolve_workspace_and_registry(workspace)
    status = current_provider(
        runtime_id=runtime_id,
        agent=agent,
        executor=exec_,
        registry_root=reg_root,
    )
    return status.to_dict()


def print_provider_current_text(data: Any) -> None:
    """Minimal human-readable output for ``aisc provider current`` text mode."""
    if not isinstance(data, dict):
        return
    print(f"{data.get('agent', '')}: {data.get('provider_name', '')} "
          f"({data.get('provider_id', '')})")
    print(f"  route_mode : {data.get('route_mode', '')}")
    print(f"  auth_status: {data.get('auth_status', '')}")
