"""DockerGateway domain models (Stage 4, DG-02).

Every gateway operation returns a structured result carrying the cross-cutting
facts the contract requires: ``operation_id``, ``backend``, observed state,
exit code, duration, stable error/cleanup status. ``stdout``/``stderr`` are
only populated when the caller explicitly requests capture and are bounded.

These are pure data models — no I/O, no docker-py import.  The adapter
(``aisc.adapters.docker_gateway``) maps Engine/SDK/CLI results onto them so
application code never sees backend-specific shapes (D4-06).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Operation envelope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GatewayOperation:
    """Cross-cutting envelope for one gateway operation.

    ``backend`` is ``sdk`` | ``cli`` | ``auto`` (what actually ran); the
    application must not branch on it — it exists for diagnostics and the
    recording/fault-injection matrix (D4-07).
    """

    operation_id: str = ""
    backend: str = "auto"
    exit_code: int = -1
    duration_ms: int = 0
    error_code: str = ""           # stable: AISC_* or DockerErrorCode
    error_message: str = ""
    cleanup_status: str = "none"   # none | ok | partial | failed
    timed_out: bool = False


@dataclass(frozen=True)
class GatewayResult:
    """Base result: operation envelope + optional captured output."""

    operation: GatewayOperation = field(default_factory=GatewayOperation)
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.operation.exit_code == 0 and not self.operation.error_code

    @property
    def timed_out(self) -> bool:
        return self.operation.timed_out

    @property
    def exit_code(self) -> int:
        """Convenience alias for ``operation.exit_code``."""
        return self.operation.exit_code


# ---------------------------------------------------------------------------
# Query results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PreflightResult(GatewayResult):
    """Gateway preflight: daemon reachability + docker availability."""

    available: bool = False
    reason: str = ""  # "ok" | "cli_not_found" | "daemon_unreachable" | "permission_denied"
    docker_path: str = ""
    docker_version: str = ""
    engine_ok: bool = False


@dataclass(frozen=True)
class ImageInspectGatewayResult(GatewayResult):
    """Structured image inspection.

    ``status`` reuses :class:`aisc.domain.models.ImageInspectStatus` values
    (exists | missing | docker_unavailable | permission_denied | timeout | error).
    """

    status: str = "error"
    image: str = ""
    message: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContainerSummary:
    """One container row from ``list_containers``."""

    id: str = ""
    name: str = ""
    image: str = ""
    state: str = ""       # running | exited | created | restarting | paused | dead
    status: str = ""      # human string e.g. "Up 2 hours" / "Exited (0) 1 minute ago"
    labels: Dict[str, str] = field(default_factory=dict)
    # Content-addressed image ID (sha256:...) — A0 docker-ownership-
    # foundation. Empty when the backend cannot provide it cheaply
    # (CLI `docker ps` only knows the image REF); callers needing the ID
    # inspect the specific container instead of guessing from the ref.
    image_id: str = ""


@dataclass(frozen=True)
class ContainerListResult(GatewayResult):
    """Container listing with stable per-row summary."""

    containers: List[ContainerSummary] = field(default_factory=list)


@dataclass(frozen=True)
class ContainerInspectResult(GatewayResult):
    """Container inspection: id, name, state, image, labels, config."""

    container_id: str = ""
    name: str = ""
    state: str = ""
    image: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    # Content-addressed image ID (``.Image`` in docker inspect JSON) —
    # distinct from ``image`` (the REF the container was created with).
    image_id: str = ""


# ---------------------------------------------------------------------------
# Lifecycle results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LifecycleResult(GatewayResult):
    """One lifecycle operation (start/stop/remove/wait/create)."""

    target: str = ""          # container name or id
    observed_state: str = ""  # e.g. running | stopped | removed | created | exited
    container_id: str = ""


# ---------------------------------------------------------------------------
# Interactive / build results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InteractiveResult(GatewayResult):
    """Interactive exec session result.

    ``exit_code`` is the agent process exit code from ``exec_inspect``;
    ``session_id`` is the exec id for resize/cancel/wait.
    """

    session_id: str = ""
    resized: bool = False
    waited: bool = False


@dataclass(frozen=True)
class BuildResult(GatewayResult):
    """Image build result. Events are streamed via the caller's callback;
    this carries the terminal exit code + image ref + duration."""

    image_ref: str = ""
    events_received: int = 0
