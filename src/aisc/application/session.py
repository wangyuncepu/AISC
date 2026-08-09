"""Session application logic for Workbench Phase 0 S0.3.

Implements the business logic behind ``aisc session open/list/terminate``.
Per docs/gui-planning/05-cli-gui-contract.md §6.

Key design:
- ``open_session`` is interactive (``docker exec -it``), returns a
  ``ProcessResult`` whose ``exit_code`` is the agent's exit code.
- ``list_sessions`` reads in-container session metadata via ``docker exec``
  (non-interactive, captured stdout).
- ``terminate_session`` runs the wrapper's ``--terminate`` mode via
  ``docker exec`` (non-interactive, captured stdout).

The container-side logic (env rebuild, process group management, PID
identity check, session record) lives in ``container/aisc-session-wrapper``.
"""

from __future__ import annotations

import math

import json
import re
from typing import Any, Dict, List, Optional

from aisc.application.runtime import resolve_running_container, validate_uuid_v4
from aisc.domain.models import (
    CliError,
    RuntimeErrorCode,
    RuntimeExitCode,
    SessionAgent,
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_SESSION_WRAPPER_PATH = "/usr/local/bin/aisc-session-wrapper"
_SESSIONS_DIR = "/run/aisc/sessions"

# Reuse the same UUID v4 pattern as runtime_id.
_UUID_V4_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def validate_session_id(session_id: str) -> bool:
    """Validate that *session_id* is a strict UUID v4."""
    return bool(_UUID_V4_RE.match(session_id))


def validate_agent(agent: str) -> bool:
    """Validate that *agent* is one of the four controlled values."""
    return agent in SessionAgent.ALL


# ---------------------------------------------------------------------------
# Container resolution (shared with provider; implementation in application.runtime)
# ---------------------------------------------------------------------------

# Kept as a private alias so this module's callers and tests are unaffected by
# the extraction of ``resolve_running_container`` to application.runtime.
_resolve_running_container = resolve_running_container


# ---------------------------------------------------------------------------
# Session open (interactive)
# ---------------------------------------------------------------------------

def open_session(
    runtime_id: str,
    session_id: str,
    agent: str,
    executor: Any,
    registry_root: Any,
) -> Any:
    """Open an interactive agent session via ``docker exec -it``.

    Per contract §6.1:
    - Validates runtime_id, session_id (UUID v4) and agent (controlled enum).
    - Checks runtime exists and is running.
    - Constructs a controlled argv (no shell=True) to execute the
      in-container ``aisc-session-wrapper``.
    - Runs with inherited stdio (interactive TTY); the agent's exit code
      becomes the process exit code.

    Returns a ``ProcessResult`` from ``executor.run_streaming``.
    """
    if not validate_uuid_v4(runtime_id):
        raise CliError(
            message=f"Invalid runtime ID (must be UUID v4): {runtime_id}",
            exit_code=RuntimeExitCode.INVALID_RUNTIME_ID,
            error_code=RuntimeErrorCode.INVALID_RUNTIME_ID,
        )

    if not validate_session_id(session_id):
        raise CliError(
            message=f"Invalid session ID (must be UUID v4): {session_id}",
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code=RuntimeErrorCode.INVALID_SESSION_ID,
        )

    if not validate_agent(agent):
        raise CliError(
            message=f"Invalid agent (must be one of {', '.join(SessionAgent.ALL)}): {agent}",
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code=RuntimeErrorCode.INVALID_AGENT,
        )

    container_name = _resolve_running_container(runtime_id, executor, registry_root)

    # Controlled argv: docker exec -it <container> <wrapper> <session_id> <runtime_id> <agent>
    # The wrapper reads /run/aisc/runtime-context.json to rebuild scope env,
    # starts the agent in its own process group, records session metadata,
    # and propagates the agent's exit code.
    docker_argv = [
        "exec", "-it", container_name,
        _SESSION_WRAPPER_PATH,
        "open",
        "--session-id", session_id,
        "--runtime-id", runtime_id,
        "--agent", agent,
    ]

    return executor.run_streaming(docker_argv, timeout=None)


# ---------------------------------------------------------------------------
# Session list (non-interactive, captured)
# ---------------------------------------------------------------------------

def list_sessions(
    runtime_id: str,
    executor: Any,
    registry_root: Any,
) -> List[Dict[str, Any]]:
    """List sessions for a runtime by reading in-container metadata.

    Per contract §6.2: reads ``/run/aisc/sessions/*.json`` inside the
    container via ``docker exec`` (non-interactive, captured stdout).
    Only used for diagnostics and crash cleanup; never claims PTY
    recoverability.
    """
    container_name = _resolve_running_container(runtime_id, executor, registry_root)

    docker_argv = [
        "exec", container_name,
        _SESSION_WRAPPER_PATH,
        "list",
    ]

    result = executor.run_captured(docker_argv, timeout=15.0)

    if result.exit_code != 0:
        raise CliError(
            message=f"Failed to list sessions: {(result.stderr or '').strip()[:200]}",
            exit_code=RuntimeExitCode.SESSION_FAILED,
            error_code=RuntimeErrorCode.SESSION_FAILED,
        )

    stdout = result.stdout.strip()
    if not stdout:
        return []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CliError(
            message=f"Invalid session list output: {exc}",
            exit_code=RuntimeExitCode.SESSION_FAILED,
            error_code=RuntimeErrorCode.SESSION_FAILED,
        )

    if not isinstance(data, list):
        raise CliError(
            message="Session list output is not a JSON array",
            exit_code=RuntimeExitCode.SESSION_FAILED,
            error_code=RuntimeErrorCode.SESSION_FAILED,
        )

    return data


# ---------------------------------------------------------------------------
# Session terminate (non-interactive, captured)
# ---------------------------------------------------------------------------

def terminate_session(
    runtime_id: str,
    session_id: str,
    executor: Any,
    registry_root: Any,
    *,
    grace_seconds: float = 5.0,
) -> Dict[str, Any]:
    """Terminate a session by running the wrapper's ``--terminate`` mode.

    Per contract §6.2:
    - Sends TERM to the session process group, waits a bounded grace period,
      then KILL if still alive.
    - Uses PID/PGID/start-ticks identity check to avoid killing a reused PID.
    - Idempotent: terminating an already-exited session succeeds.
    - Returns the terminal session record.
    """
    if not validate_uuid_v4(runtime_id):
        raise CliError(
            message=f"Invalid runtime ID (must be UUID v4): {runtime_id}",
            exit_code=RuntimeExitCode.INVALID_RUNTIME_ID,
            error_code=RuntimeErrorCode.INVALID_RUNTIME_ID,
        )

    if not validate_session_id(session_id):
        raise CliError(
            message=f"Invalid session ID (must be UUID v4): {session_id}",
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code=RuntimeErrorCode.INVALID_SESSION_ID,
        )

    # --grace must be finite and in 0..600; reject NaN/Infinity/out-of-range
    # before any Docker call (05 §4.2).
    if not isinstance(grace_seconds, (int, float)) or not math.isfinite(grace_seconds) or not 0 <= grace_seconds <= 600:
        raise CliError(
            message=f"Invalid --grace {grace_seconds!r}: must be a finite number in 0..600",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        )

    container_name = _resolve_running_container(runtime_id, executor, registry_root)

    docker_argv = [
        "exec", container_name,
        _SESSION_WRAPPER_PATH,
        "terminate",
        "--session-id", session_id,
        "--runtime-id", runtime_id,
        "--grace", str(grace_seconds),
    ]

    # Outer transport budget is grace + 1s (05 §4.2): keeps the Workbench
    # --grace 3 path inside its 5s command budget while leaving TERM->KILL
    # grace untouched.
    result = executor.run_captured(docker_argv, timeout=grace_seconds + 1.0)

    if result.exit_code != 0:
        raise CliError(
            message=f"Failed to terminate session: {(result.stderr or '').strip()[:200]}",
            exit_code=RuntimeExitCode.SESSION_FAILED,
            error_code=RuntimeErrorCode.SESSION_FAILED,
        )

    stdout = result.stdout.strip()
    if not stdout:
        # Wrapper may return empty on success (already exited, record cleaned).
        return {"session_id": session_id, "state": "exited", "exit_code": None}

    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    return {"session_id": session_id, "state": "exited", "exit_code": None}
