"""Provider status application logic for Workbench Phase 0 S0.4.

Implements the business logic behind ``aisc provider current``. Per
docs/gui-planning/05-cli-gui-contract.md §七. Secret-free: the in-container
``aisc-provider-inspect`` emits only metadata; this layer adds runtime_id and
observed_at.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from aisc.application.runtime import resolve_running_container, validate_uuid_v4
from aisc.domain.models import (
    CliError,
    ProviderStatus,
    RuntimeErrorCode,
    RuntimeExitCode,
)

_PROVIDER_INSPECT_PATH = "/usr/local/bin/aisc-provider-inspect"
_AGENTS = ("claude", "codex")


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_provider(
    runtime_id: str,
    agent: str,
    executor: Any,
    registry_root: Any,
) -> ProviderStatus:
    """Return the observable provider status for *agent* in runtime *runtime_id*.

    Requires the runtime to be running; reads config in-container via
    ``docker exec <ct> aisc-provider-inspect <agent>``. Never returns secrets.
    """
    if not validate_uuid_v4(runtime_id):
        raise CliError(
            message=f"Invalid runtime ID (must be UUID v4): {runtime_id}",
            exit_code=RuntimeExitCode.INVALID_RUNTIME_ID,
            error_code=RuntimeErrorCode.INVALID_RUNTIME_ID,
        )
    if agent not in _AGENTS:
        raise CliError(
            message=f"Invalid agent (must be one of {', '.join(_AGENTS)}): {agent}",
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code=RuntimeErrorCode.INVALID_AGENT,
        )

    container_name = resolve_running_container(runtime_id, executor, registry_root)

    result = executor.run_captured(
        ["exec", container_name, _PROVIDER_INSPECT_PATH, agent],
        timeout=15.0,
    )
    if result.exit_code != 0:
        raise CliError(
            message=f"Provider status inspection failed: "
                    f"{(result.stderr or '').strip()[:200]}",
            exit_code=RuntimeExitCode.PROVIDER_STATUS_FAILED,
            error_code=RuntimeErrorCode.PROVIDER_STATUS_FAILED,
        )

    try:
        data = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise CliError(
            message=f"Invalid provider status output: {exc}",
            exit_code=RuntimeExitCode.PROVIDER_STATUS_FAILED,
            error_code=RuntimeErrorCode.PROVIDER_STATUS_FAILED,
        )
    if not isinstance(data, dict):
        raise CliError(
            message="Provider status output is not a JSON object",
            exit_code=RuntimeExitCode.PROVIDER_STATUS_FAILED,
            error_code=RuntimeErrorCode.PROVIDER_STATUS_FAILED,
        )

    return ProviderStatus(
        runtime_id=runtime_id,
        agent=agent,
        provider_id=str(data.get("provider_id", "")),
        provider_name=str(data.get("provider_name", "")),
        route_mode=str(data.get("route_mode", "unknown")) or "unknown",
        auth_status=str(data.get("auth_status", "unknown")) or "unknown",
        observed_at=_iso_now(),
    )
