"""Session commands implementation.

Implements ``aisc session`` subcommands: open, list, terminate.
Per docs/gui-planning/05-cli-gui-contract.md §6.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aisc.adapters.docker_ import DockerExecutor, RealDockerExecutor
from aisc.application.session import (
    list_sessions,
    open_session,
    terminate_session,
    validate_agent,
    validate_session_id,
)
from aisc.domain.models import (
    CliError,
    RuntimeErrorCode,
    RuntimeExitCode,
    SessionAgent,
)


def _resolve_workspace_and_registry(workspace: Optional[str]) -> Tuple[str, Path]:
    """Return (canonical_workspace_str, registry_root_path)."""
    ws_path = Path(workspace).resolve() if workspace else Path.cwd()
    return str(ws_path), ws_path / ".aisc"


# ---------------------------------------------------------------------------
# session open
# ---------------------------------------------------------------------------

def cmd_session_open(
    runtime_id: str,
    session_id: str,
    agent: str,
    workspace: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> Tuple[Dict[str, Any], int]:
    """Execute ``aisc session open`` per contract §6.1.

    This is a text-only interactive command. It validates inputs, resolves
    the running container, then runs ``docker exec -it`` with inherited
    stdio. The agent's exit code becomes the process exit code.

    Returns (data_dict, exit_code). The caller is expected to ``sys.exit()``
    with the exit code; the interactive streams are already inherited.
    """
    exec_ = executor or RealDockerExecutor()
    _ws, reg_root = _resolve_workspace_and_registry(workspace)

    proc = open_session(
        runtime_id=runtime_id,
        session_id=session_id,
        agent=agent,
        executor=exec_,
        registry_root=reg_root,
    )

    exit_code = proc.exit_code if proc.exit_code >= 0 else 1

    data: Dict[str, Any] = {
        "runtime_id": runtime_id,
        "session_id": session_id,
        "agent": agent,
        "exit_code": exit_code,
    }
    if proc.command_not_found:
        data["error"] = "docker command not found"
    elif proc.timed_out:
        data["error"] = "session timed out"

    return data, exit_code


# ---------------------------------------------------------------------------
# session list
# ---------------------------------------------------------------------------

def cmd_session_list(
    runtime_id: str,
    workspace: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Execute ``aisc session list`` per contract §6.2."""
    exec_ = executor or RealDockerExecutor()
    _ws, reg_root = _resolve_workspace_and_registry(workspace)

    sessions = list_sessions(
        runtime_id=runtime_id,
        executor=exec_,
        registry_root=reg_root,
    )
    return {"sessions": sessions, "count": len(sessions)}


# ---------------------------------------------------------------------------
# session terminate
# ---------------------------------------------------------------------------

def cmd_session_terminate(
    runtime_id: str,
    session_id: str,
    workspace: Optional[str] = None,
    executor: Optional[DockerExecutor] = None,
    grace_seconds: float = 5.0,
) -> Dict[str, Any]:
    """Execute ``aisc session terminate`` per contract §6.2."""
    exec_ = executor or RealDockerExecutor()
    _ws, reg_root = _resolve_workspace_and_registry(workspace)

    result = terminate_session(
        runtime_id=runtime_id,
        session_id=session_id,
        executor=exec_,
        registry_root=reg_root,
        grace_seconds=grace_seconds,
    )
    return result


# ---------------------------------------------------------------------------
# Text output
# ---------------------------------------------------------------------------

def print_session_text(subcommand: str, data: Any, errors: list) -> None:
    """Minimal human-readable output for ``aisc session`` text mode."""
    if errors:
        for e in errors:
            print(f"Error: {e.get('message', '')}")
        return
    if not isinstance(data, dict):
        return
    if subcommand == "open":
        print(f"session {data.get('session_id', '')} agent={data.get('agent', '')} "
              f"exit_code={data.get('exit_code', '')}")
    elif subcommand == "list":
        sessions = data.get("sessions", [])
        if not sessions:
            print("(no sessions)")
        for s in sessions:
            print(f"{s.get('session_id', '')}  agent={s.get('agent', '')}  "
                  f"state={s.get('state', '')}  pid={s.get('pid', '')}")
    elif subcommand == "terminate":
        print(f"session {data.get('session_id', '')} state={data.get('state', '')} "
              f"exit_code={data.get('exit_code', '')}")
