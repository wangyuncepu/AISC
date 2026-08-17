"""Host-side application layer for the cc-switch Provider data plane (8d).

Mirrors ``aisc.application.provider``: resolves the running container for a
runtime, then ``docker exec -i``s the in-container adapter
(``aisc-cc-provider``) with ONE JSON request document on stdin. The adapter
speaks ``aisc.cc-switch-provider/v1``; this layer validates the envelope and
maps adapter failures onto CliError with the adapter's stable codes.

Secrets travel ONLY via the stdin document (D8-09) — the docker exec argv
never carries one.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from aisc.application.runtime import resolve_running_container, validate_uuid_v4
from aisc.domain.models import CliError, RuntimeExitCode

PROTOCOL = "aisc.cc-switch-provider/v1"
_ADAPTER_PATH = "/usr/local/bin/aisc-cc-provider"
_AGENTS = ("claude", "codex")
_OPS = ("list", "add", "edit", "delete")


def _validate(runtime_id: str, agent: str, op: str) -> None:
    if not validate_uuid_v4(runtime_id):
        raise CliError(
            message=f"Invalid runtime ID (must be UUID v4): {runtime_id}",
            exit_code=RuntimeExitCode.INVALID_RUNTIME_ID,
            error_code=RuntimeExitCode.INVALID_RUNTIME_ID,
        )
    if agent not in _AGENTS:
        raise CliError(
            message=f"Invalid agent (must be claude|codex): {agent}",
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code="AISC_ERR_INVALID_AGENT",
        )
    if op not in _OPS:
        raise CliError(
            message=f"Invalid cc-switch op: {op}",
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code="AISC_ERR_USAGE",
        )


def _exec_adapter(
    runtime_id: str,
    registry_root: Any,
    executor: Any,
    op: str,
    agent: str,
    provider_id: Optional[str],
    request: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Run the in-container adapter and return the validated envelope."""
    from aisc.adapters.docker_ import RealDockerExecutor

    executor = executor or RealDockerExecutor()
    argv = ["exec", "-i"]
    container = resolve_running_container(runtime_id, executor, registry_root)
    argv.append(container)
    argv.extend(
        [
            "bash", "-c",
            # Same scope wrapper as the TUI switch surface: the adapter needs
            # the container's CC_SWITCH_CONFIG_DIR from PID 1's environ.
            _SCOPE_WRAPPER,
            "aisc-scope", "/proc/1/environ", "--",
            _ADAPTER_PATH, op, "--agent", agent,
        ]
    )
    if provider_id:
        argv.extend(["--id", provider_id])

    stdin_text = ""
    if request is not None:
        stdin_text = json.dumps(request, ensure_ascii=False)

    # Docker `-i` + run_captured(input_text=…): the request (with any secret)
    # reaches the adapter via stdin only — never argv, never disk (D8-09).
    result = executor.run_captured(argv, timeout=60.0, input_text=stdin_text)
    if result.returncode != 0 and not (result.stdout or "").strip():
        raise CliError(
            message=f"cc-switch provider {op} failed: {(result.stderr or '').strip()[:200]}",
            exit_code=RuntimeExitCode.PROVIDER_STATUS_FAILED,
            error_code="AISC_ERR_CC_SWITCH_PROVIDER_EXEC_FAILED",
        )
    try:
        envelope = json.loads((result.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise CliError(
            message=f"invalid adapter output for {op}: {exc}",
            exit_code=RuntimeExitCode.PROVIDER_STATUS_FAILED,
            error_code="AISC_ERR_CC_SWITCH_PROVIDER_EXEC_FAILED",
        ) from exc
    if not isinstance(envelope, dict) or envelope.get("schema") != PROTOCOL:
        raise CliError(
            message=f"adapter envelope schema mismatch for {op}",
            exit_code=RuntimeExitCode.PROVIDER_STATUS_FAILED,
            error_code="AISC_ERR_CC_SWITCH_PROVIDER_EXEC_FAILED",
        )
    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        raise CliError(
            message=str(error.get("message") or f"cc-switch provider {op} failed"),
            exit_code=1,
            error_code=str(error.get("code") or "AISC_ERR_CC_SWITCH_PROVIDER_EXEC_FAILED"),
            data={"providers": envelope.get("providers") or []},
        )
    return envelope


# The scope wrapper mirrors aisc.cli.commands.container._SCOPE_WRAPPER (kept
# in sync deliberately — importing the CLI layer from application would invert
# the dependency direction).
_SCOPE_WRAPPER = "\n".join([
    'if [ ! -r "$1" ]; then',
    "  echo 'Error: Cannot read scope environment from PID 1' >&2",
    '  exit 101',
    'fi',
    'unset CLAUDE_CONFIG_DIR CC_SWITCH_CONFIG_DIR CODEX_CONFIG_DIR CODEX_HOME',
    "while IFS= read -r -d '' entry; do",
    '  case "$entry" in',
    '    CLAUDE_CONFIG_DIR=*) CLAUDE_CONFIG_DIR=${entry#*=} ;;',
    '    CC_SWITCH_CONFIG_DIR=*) CC_SWITCH_CONFIG_DIR=${entry#*=} ;;',
    '    CODEX_CONFIG_DIR=*)     CODEX_CONFIG_DIR=${entry#*=}     ;;',
    '    CODEX_HOME=*)           CODEX_HOME=${entry#*=}           ;;',
    '  esac',
    'done < "$1"',
    'shift',
    'shift',
    'if [ -z "${CLAUDE_CONFIG_DIR:-}" ] || [ -z "${CC_SWITCH_CONFIG_DIR:-}" ]; then',
    "  echo 'Error: Cannot read scope environment from PID 1' >&2",
    '  exit 101',
    'fi',
    'export CLAUDE_CONFIG_DIR CC_SWITCH_CONFIG_DIR CODEX_CONFIG_DIR CODEX_HOME',
    'exec "$@"',
    '',
])


def list_providers(runtime_id: str, agent: str, workspace: Optional[str], executor: Any) -> Dict[str, Any]:
    from aisc.application.data_root import workspace_state_dir
    from pathlib import Path

    ws_path = Path(workspace).resolve() if workspace else Path.cwd()
    _validate(runtime_id, agent, "list")
    envelope = _exec_adapter(
        runtime_id, workspace_state_dir(ws_path), executor, "list", agent, None, None
    )
    return {"agent": agent, "providers": envelope.get("providers") or [],
            "operation_id": envelope.get("operation_id")}


def add_provider(runtime_id: str, agent: str, request: Dict[str, Any],
                 workspace: Optional[str], executor: Any) -> Dict[str, Any]:
    from aisc.application.data_root import workspace_state_dir
    from pathlib import Path

    ws_path = Path(workspace).resolve() if workspace else Path.cwd()
    _validate(runtime_id, agent, "add")
    envelope = _exec_adapter(
        runtime_id, workspace_state_dir(ws_path), executor, "add", agent,
        request.get("id"), request,
    )
    return {"agent": agent, "providers": envelope.get("providers") or [],
            "operation_id": envelope.get("operation_id")}


def edit_provider(runtime_id: str, agent: str, provider_id: str,
                  request: Dict[str, Any], workspace: Optional[str], executor: Any) -> Dict[str, Any]:
    from aisc.application.data_root import workspace_state_dir
    from pathlib import Path

    ws_path = Path(workspace).resolve() if workspace else Path.cwd()
    _validate(runtime_id, agent, "edit")
    envelope = _exec_adapter(
        runtime_id, workspace_state_dir(ws_path), executor, "edit", agent,
        provider_id, request,
    )
    return {"agent": agent, "providers": envelope.get("providers") or [],
            "operation_id": envelope.get("operation_id")}


def delete_provider(runtime_id: str, agent: str, provider_id: str,
                    workspace: Optional[str], executor: Any) -> Dict[str, Any]:
    from aisc.application.data_root import workspace_state_dir
    from pathlib import Path

    ws_path = Path(workspace).resolve() if workspace else Path.cwd()
    _validate(runtime_id, agent, "delete")
    envelope = _exec_adapter(
        runtime_id, workspace_state_dir(ws_path), executor, "delete", agent,
        provider_id, None,
    )
    return {"agent": agent, "providers": envelope.get("providers") or [],
            "operation_id": envelope.get("operation_id")}
