"""DockerGateway adapter (Stage 4, DG-01..DG-08).

Evolves the CLI-only ``RealDockerExecutor`` into a backend-selecting gateway
while keeping ``DockerExecutor`` as a compatibility alias for at least one
release (D4-02).  Backend choice (``auto|sdk|cli``) lives entirely inside this
module — application/domain never branches on it (D4-06).

Layer diagram (per ``stage-4-docker-gateway/02-domain-contract.md``):

    application/domain
           ↓ DockerGateway (Protocol)
    AutoGateway → SdkGateway | CliGateway
           ↓
    Docker Engine

Backends
--------
- ``SdkGateway``: docker-py for query (preflight/inspect/list) and lifecycle
  (start/stop/remove/wait). Interactive exec stays SDK-first (D4-03, reuses the
  transport helpers from ``docker_.RealDockerExecutor.open_interactive``).
- ``CliGateway``: wraps ``RealDockerExecutor`` (argv-only, no ``shell=True``);
  kept as the fallback until the equivalence matrix is complete (D4-08).
- ``AutoGateway``: selects by capability/feature flag; never leaks the choice.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Protocol, runtime_checkable

from aisc.domain.gateway import (
    BuildResult,
    ContainerInspectResult,
    ContainerListResult,
    ContainerSummary,
    GatewayOperation,
    GatewayResult,
    ImageInspectGatewayResult,
    InteractiveResult,
    LifecycleResult,
    PreflightResult,
)
from aisc.domain.models import (
    BuildPlan,
    DockerPreflightResult,
    ImageInspectResult,
    ImageInspectStatus,
    ProcessResult,
    RunPlan,
)


# ---------------------------------------------------------------------------
# Backend identity (adapter-internal; never leaks to application code)
# ---------------------------------------------------------------------------

BackendName = str  # "auto" | "sdk" | "cli"

# Stable Docker error codes (D4-07). Prefixed to avoid colliding with AISC_*.
class DockerErrorCode:
    DAEMON_UNREACHABLE = "DOCKER_ERR_DAEMON_UNREACHABLE"
    CLI_NOT_FOUND = "DOCKER_ERR_CLI_NOT_FOUND"
    PERMISSION_DENIED = "DOCKER_ERR_PERMISSION_DENIED"
    NOT_FOUND = "DOCKER_ERR_NOT_FOUND"
    TIMEOUT = "DOCKER_ERR_TIMEOUT"
    CONFLICT = "DOCKER_ERR_CONFLICT"
    UNKNOWN = "DOCKER_ERR_UNKNOWN"


# ---------------------------------------------------------------------------
# Gateway protocol — the single injectable abstraction (DG-01)
# ---------------------------------------------------------------------------

@runtime_checkable
class DockerGateway(Protocol):
    """Structured gateway over the Docker Engine.

    Every method returns a :class:`GatewayResult` subclass carrying
    ``operation_id``, ``backend``, exit code, duration, stable error and
    cleanup status.  stdout/stderr are only populated on explicit capture
    request and are bounded.
    """

    @property
    def backend(self) -> str:
        """Which backend actually runs (sdk | cli | auto)."""
        ...

    def preflight(self) -> PreflightResult:
        """Daemon reachability + docker availability."""
        ...

    def inspect_image(self, image_name: str) -> ImageInspectGatewayResult:
        """Structured local-image inspection."""
        ...

    def list_containers(self, all: bool = False) -> ContainerListResult:
        """List containers with stable per-row summaries."""
        ...

    def inspect_container(self, container: str) -> ContainerInspectResult:
        """Inspect one container."""
        ...

    def start_container(self, container: str) -> LifecycleResult:
        """Start a container."""
        ...

    def stop_container(self, container: str, timeout: int = 10) -> LifecycleResult:
        """Stop a container with a grace timeout."""
        ...

    def remove_container(self, container: str, force: bool = False) -> LifecycleResult:
        """Remove a container."""
        ...

    def wait_container(self, container: str, timeout: Optional[float] = None) -> LifecycleResult:
        """Wait for a container to exit; returns its final state."""
        ...

    def open_interactive(self, container: str, argv: List[str]) -> InteractiveResult:
        """Open an interactive exec session (SDK-first, resizable)."""
        ...

    def build_image(
        self,
        plan: BuildPlan,
        on_event: Optional[Callable[[str, str], None]] = None,
    ) -> BuildResult:
        """Build an image; events stream to *on_event* when provided."""
        ...


# ---------------------------------------------------------------------------
# Operation envelope helper
# ---------------------------------------------------------------------------

def _new_operation(backend: str, **kw) -> GatewayOperation:
    # Allow callers to override duration_ms without a duplicate-kwarg clash.
    return GatewayOperation(
        operation_id=uuid.uuid4().hex[:16],
        backend=backend,
        **kw,
    )


def _elapsed(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _default_client():
    import docker
    return docker.from_env()


# ---------------------------------------------------------------------------
# SDK backend — docker-py (query + lifecycle)
# ---------------------------------------------------------------------------

@dataclass
class SdkGateway:
    """docker-py backed gateway (D4-03/D4-04, query+lifecycle first).

    ``client`` may be injected for tests (Fake/recording); when ``None`` the
    gateway lazily creates ``docker.from_env()``.
    """

    client: object = None  # docker.DockerClient (duck-typed to keep SDK optional)
    timeout: float = 10.0
    _client_factory: Callable[[], object] = field(default_factory=lambda: _default_client())

    @property
    def backend(self) -> str:
        return "sdk"

    def _client(self):
        if self.client is None:
            self.client = self._client_factory()
        return self.client

    # -- helpers ----------------------------------------------------------

    def _op(self, **kw) -> GatewayOperation:
        return _new_operation("sdk", **kw)

    # -- query ------------------------------------------------------------

    def preflight(self) -> PreflightResult:
        import docker  # lazy: keep the module importable without the SDK
        start = time.monotonic()
        try:
            client = self._client()
            version = client.version()  # raises if daemon unreachable
            return PreflightResult(
                operation=_new_operation(
                    "sdk", exit_code=0, duration_ms=_elapsed(start), cleanup_status="ok",
                ),
                available=True,
                reason="ok",
                docker_version=str(version.get("Version", "")),
                engine_ok=True,
            )
        except docker.errors.DockerException as exc:
            return PreflightResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.DAEMON_UNREACHABLE,
                    error_message=str(exc), cleanup_status="ok",
                ),
                available=False,
                reason="daemon_unreachable",
            )
        except Exception as exc:  # noqa: BLE001
            return PreflightResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.UNKNOWN,
                    error_message=str(exc), cleanup_status="ok",
                ),
                available=False,
                reason="daemon_unreachable",
            )

    def inspect_image(self, image_name: str) -> ImageInspectGatewayResult:
        import docker
        start = time.monotonic()
        try:
            client = self._client()
            client.images.get(image_name)
            return ImageInspectGatewayResult(
                operation=_new_operation("sdk", exit_code=0, duration_ms=_elapsed(start)),
                status=ImageInspectStatus.EXISTS,
                image=image_name,
                message="",
            )
        except docker.errors.ImageNotFound:
            return ImageInspectGatewayResult(
                operation=_new_operation("sdk", exit_code=5, duration_ms=_elapsed(start)),
                status=ImageInspectStatus.MISSING,
                image=image_name,
                message="image not found locally",
            )
        except docker.errors.DockerException as exc:
            return ImageInspectGatewayResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.DAEMON_UNREACHABLE,
                    error_message=str(exc),
                ),
                status=ImageInspectStatus.DOCKER_UNAVAILABLE,
                image=image_name,
                message=str(exc),
            )

    def list_containers(self, all: bool = False) -> ContainerListResult:
        import docker
        start = time.monotonic()
        try:
            client = self._client()
            rows = client.containers.list(all=all)
            summaries = [
                ContainerSummary(
                    id=c.id[:12],
                    name=(c.name or ""),
                    image=(c.image.tags[0] if getattr(c, "image", None) and getattr(c.image, "tags", None) else ""),
                    state=(c.status or ""),
                    status=(c.attrs.get("State", {}).get("Status", "") or (c.status or "")),
                    labels=(c.attrs.get("Config", {}).get("Labels", {}) or {}),
                )
                for c in rows
            ]
            return ContainerListResult(
                operation=_new_operation("sdk", exit_code=0, duration_ms=_elapsed(start)),
                containers=summaries,
            )
        except docker.errors.DockerException as exc:
            return ContainerListResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.DAEMON_UNREACHABLE,
                    error_message=str(exc),
                ),
            )

    def inspect_container(self, container: str) -> ContainerInspectResult:
        import docker
        start = time.monotonic()
        try:
            client = self._client()
            c = client.containers.get(container)
            attrs = c.attrs
            state = attrs.get("State", {}) or {}
            config = attrs.get("Config", {}) or {}
            return ContainerInspectResult(
                operation=_new_operation("sdk", exit_code=0, duration_ms=_elapsed(start)),
                container_id=c.id,
                name=(c.name or ""),
                state=state.get("Status", ""),
                image=attrs.get("Config", {}).get("Image", "") or "",
                labels=config.get("Labels", {}) or {},
                config=config,
            )
        except docker.errors.NotFound:
            return ContainerInspectResult(
                operation=_new_operation(
                    "sdk", exit_code=1, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.NOT_FOUND,
                    error_message=f"container {container} not found",
                ),
            )
        except docker.errors.DockerException as exc:
            return ContainerInspectResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.DAEMON_UNREACHABLE,
                    error_message=str(exc),
                ),
            )

    # -- lifecycle --------------------------------------------------------

    def start_container(self, container: str) -> LifecycleResult:
        import docker
        start = time.monotonic()
        try:
            client = self._client()
            c = client.containers.get(container)
            c.start()
            return LifecycleResult(
                operation=_new_operation("sdk", exit_code=0, duration_ms=_elapsed(start)),
                target=container,
                observed_state="running",
                container_id=c.id,
            )
        except docker.errors.NotFound:
            return LifecycleResult(
                operation=_new_operation(
                    "sdk", exit_code=1, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.NOT_FOUND,
                    error_message=f"container {container} not found",
                ),
                target=container,
            )
        except docker.errors.DockerException as exc:
            return LifecycleResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.DAEMON_UNREACHABLE,
                    error_message=str(exc),
                ),
                target=container,
            )

    def stop_container(self, container: str, timeout: int = 10) -> LifecycleResult:
        import docker
        start = time.monotonic()
        try:
            client = self._client()
            c = client.containers.get(container)
            c.stop(timeout=timeout)
            return LifecycleResult(
                operation=_new_operation("sdk", exit_code=0, duration_ms=_elapsed(start)),
                target=container,
                observed_state="stopped",
                container_id=c.id,
            )
        except docker.errors.NotFound:
            return LifecycleResult(
                operation=_new_operation(
                    "sdk", exit_code=1, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.NOT_FOUND,
                    error_message=f"container {container} not found",
                ),
                target=container,
            )
        except docker.errors.DockerException as exc:
            return LifecycleResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.DAEMON_UNREACHABLE,
                    error_message=str(exc),
                ),
                target=container,
            )

    def remove_container(self, container: str, force: bool = False) -> LifecycleResult:
        import docker
        start = time.monotonic()
        try:
            client = self._client()
            c = client.containers.get(container)
            c.remove(force=force)
            return LifecycleResult(
                operation=_new_operation("sdk", exit_code=0, duration_ms=_elapsed(start)),
                target=container,
                observed_state="removed",
                container_id=c.id,
            )
        except docker.errors.NotFound:
            # Already absent is a successful remove (idempotent).
            return LifecycleResult(
                operation=_new_operation("sdk", exit_code=0, duration_ms=_elapsed(start)),
                target=container,
                observed_state="removed",
            )
        except docker.errors.DockerException as exc:
            return LifecycleResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.DAEMON_UNREACHABLE,
                    error_message=str(exc),
                ),
                target=container,
            )

    def wait_container(self, container: str, timeout: Optional[float] = None) -> LifecycleResult:
        import docker
        start = time.monotonic()
        try:
            client = self._client()
            c = client.containers.get(container)
            c.wait(timeout=timeout)
            c.reload()
            return LifecycleResult(
                operation=_new_operation("sdk", exit_code=0, duration_ms=_elapsed(start)),
                target=container,
                observed_state=((c.attrs.get("State", {}) or {}).get("Status", "exited")),
                container_id=c.id,
            )
        except docker.errors.NotFound:
            return LifecycleResult(
                operation=_new_operation(
                    "sdk", exit_code=1, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.NOT_FOUND,
                    error_message=f"container {container} not found",
                ),
                target=container,
            )
        except docker.errors.DockerException as exc:
            return LifecycleResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.DAEMON_UNREACHABLE,
                    error_message=str(exc),
                ),
                target=container,
            )

    # -- interactive / build (SDK-first; 4d wires the full lifecycle) -------

    def open_interactive(self, container: str, argv: List[str]) -> InteractiveResult:
        # 4d: unify exec socket/resize/cancel/reap here. For now, delegate to the
        # CLI executor's SDK exec path so interactive behavior is unchanged, then
        # surface as an InteractiveResult.
        from aisc.adapters.docker_ import RealDockerExecutor
        exec_result: ProcessResult = RealDockerExecutor().open_interactive(container, argv)
        return InteractiveResult(
            operation=_new_operation("sdk", exit_code=exec_result.exit_code, duration_ms=0),
            exit_code=exec_result.exit_code,
            session_id="",
        )

    def build_image(
        self,
        plan: BuildPlan,
        on_event: Optional[Callable[[str, str], None]] = None,
    ) -> BuildResult:
        from aisc.adapters.docker_ import RealDockerExecutor
        executor = RealDockerExecutor()
        if on_event is not None:
            result = executor.run_streaming_captured(
                plan.docker_argv,
                on_chunk=on_event,
            )
        else:
            result = executor.run_captured(plan.docker_argv)
        return BuildResult(
            operation=_new_operation("sdk", exit_code=result.exit_code, duration_ms=0),
            image_ref=plan.tag,
            stdout=result.stdout,
            stderr=result.stderr,
        )


# ---------------------------------------------------------------------------
# CLI backend — wraps RealDockerExecutor (argv-only fallback, D4-04/D4-08)
# ---------------------------------------------------------------------------

@dataclass
class CliGateway:
    """CLI-backed gateway: delegates to the existing ``RealDockerExecutor``.

    Kept for the equivalence/regression window; never removed until the SDK/CLI
    matrix and cross-platform evidence are complete (D4-08).
    """

    executor: object = None  # RealDockerExecutor (duck-typed)

    def _exec(self):
        if self.executor is None:
            from aisc.adapters.docker_ import RealDockerExecutor
            self.executor = RealDockerExecutor()
        return self.executor

    @property
    def backend(self) -> str:
        return "cli"

    def _op(self, result: ProcessResult, **kw) -> GatewayOperation:
        return _new_operation(
            "cli",
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            **kw,
        )

    def preflight(self) -> PreflightResult:
        start = time.monotonic()
        r: DockerPreflightResult = self._exec().preflight()
        return PreflightResult(
            operation=_new_operation(
                "cli", exit_code=r.exit_code, duration_ms=_elapsed(start),
                error_code=r.error_code or "",
            ),
            available=r.available,
            reason=r.reason,
            docker_path=r.docker_path,
        )

    def inspect_image(self, image_name: str) -> ImageInspectGatewayResult:
        start = time.monotonic()
        r: ImageInspectResult = self._exec().inspect_image(image_name)
        return ImageInspectGatewayResult(
            operation=_new_operation("cli", exit_code=_map_inspect_exit(r.status), duration_ms=_elapsed(start)),
            status=r.status,
            image=r.image,
            message=r.message,
        )

    def list_containers(self, all: bool = False) -> ContainerListResult:
        start = time.monotonic()
        r: ProcessResult = self._exec().list_containers(all=all)
        return ContainerListResult(
            operation=self._op(r, duration_ms=_elapsed(start)),
            stdout=r.stdout,
            stderr=r.stderr,
        )

    def inspect_container(self, container: str) -> ContainerInspectResult:
        start = time.monotonic()
        r: ProcessResult = self._exec().inspect_container(container)
        return ContainerInspectResult(
            operation=self._op(r, duration_ms=_elapsed(start)),
            stdout=r.stdout,
            stderr=r.stderr,
        )

    def start_container(self, container: str) -> LifecycleResult:
        # CLI executor exposes run_captured; start = `docker start <name>`.
        return self._lifecycle_via_argv(["start", container], target=container, state="running")

    def stop_container(self, container: str, timeout: int = 10) -> LifecycleResult:
        return self._lifecycle_via_argv(
            ["stop", "-t", str(timeout), container], target=container, state="stopped",
        )

    def remove_container(self, container: str, force: bool = False) -> LifecycleResult:
        argv = ["rm"] + (["-f"] if force else []) + [container]
        return self._lifecycle_via_argv(argv, target=container, state="removed")

    def wait_container(self, container: str, timeout: Optional[float] = None) -> LifecycleResult:
        return self._lifecycle_via_argv(["wait", container], target=container, state="exited")

    def _lifecycle_via_argv(
        self, argv: List[str], *, target: str, state: str,
    ) -> LifecycleResult:
        start = time.monotonic()
        r: ProcessResult = self._exec().run_captured(argv)
        return LifecycleResult(
            operation=_new_operation(
                "cli", exit_code=r.exit_code, duration_ms=_elapsed(start),
                timed_out=r.timed_out,
            ),
            target=target,
            observed_state=state if r.exit_code == 0 else "",
        )

    def open_interactive(self, container: str, argv: List[str]) -> InteractiveResult:
        start = time.monotonic()
        r: ProcessResult = self._exec().open_interactive(container, argv)
        return InteractiveResult(
            operation=_new_operation("cli", exit_code=r.exit_code, duration_ms=_elapsed(start)),
            exit_code=r.exit_code,
        )

    def build_image(
        self,
        plan: BuildPlan,
        on_event: Optional[Callable[[str, str], None]] = None,
    ) -> BuildResult:
        start = time.monotonic()
        executor = self._exec()
        if on_event is not None:
            r: ProcessResult = executor.run_streaming_captured(plan.docker_argv, on_chunk=on_event)
        else:
            r: ProcessResult = executor.run_captured(plan.docker_argv)
        return BuildResult(
            operation=_new_operation("cli", exit_code=r.exit_code, duration_ms=_elapsed(start)),
            image_ref=plan.tag,
            stdout=r.stdout,
            stderr=r.stderr,
        )


def _map_inspect_exit(status: str) -> int:
    if status == ImageInspectStatus.EXISTS:
        return 0
    if status == ImageInspectStatus.MISSING:
        return 5
    if status == ImageInspectStatus.PERMISSION_DENIED:
        return 9
    if status == ImageInspectStatus.TIMEOUT:
        return 1
    return 3  # docker_unavailable / error


# ---------------------------------------------------------------------------
# Auto backend — capability-based selection (D4-06)
# ---------------------------------------------------------------------------

@dataclass
class AutoGateway:
    """Selects sdk vs cli by capability.

    The choice is a pure function of environment capability (SDK importable,
    daemon reachable); it never reflects a caller-supplied preference.  The
    resolved backend is exposed on every operation result for diagnostics.
    """

    _sdk: Optional[SdkGateway] = None
    _cli: Optional[CliGateway] = None
    prefer_sdk: bool = True  # SDK is the default when available (D4-03/D4-04)

    @property
    def backend(self) -> str:
        return "auto"

    def _resolve(self) -> DockerGateway:
        if self.prefer_sdk:
            try:
                import docker  # noqa: F401
                if self._sdk is None:
                    self._sdk = SdkGateway()
                return self._sdk
            except ImportError:
                pass
        if self._cli is None:
            self._cli = CliGateway()
        return self._cli

    def preflight(self) -> PreflightResult:
        return self._resolve().preflight()

    def inspect_image(self, image_name: str) -> ImageInspectGatewayResult:
        return self._resolve().inspect_image(image_name)

    def list_containers(self, all: bool = False) -> ContainerListResult:
        return self._resolve().list_containers(all=all)

    def inspect_container(self, container: str) -> ContainerInspectResult:
        return self._resolve().inspect_container(container)

    def start_container(self, container: str) -> LifecycleResult:
        return self._resolve().start_container(container)

    def stop_container(self, container: str, timeout: int = 10) -> LifecycleResult:
        return self._resolve().stop_container(container, timeout=timeout)

    def remove_container(self, container: str, force: bool = False) -> LifecycleResult:
        return self._resolve().remove_container(container, force=force)

    def wait_container(self, container: str, timeout: Optional[float] = None) -> LifecycleResult:
        return self._resolve().wait_container(container, timeout=timeout)

    def open_interactive(self, container: str, argv: List[str]) -> InteractiveResult:
        return self._resolve().open_interactive(container, argv)

    def build_image(
        self,
        plan: BuildPlan,
        on_event: Optional[Callable[[str, str], None]] = None,
    ) -> BuildResult:
        return self._resolve().build_image(plan, on_event=on_event)


# ---------------------------------------------------------------------------
# Factory + compatibility alias
# ---------------------------------------------------------------------------

def create_docker_gateway(
    backend: BackendName = "auto",
    client: object = None,
) -> DockerGateway:
    """Return a gateway for *backend* (auto | sdk | cli).

    ``client`` injects a docker-py client (tests/recording); CLI backend accepts
    an executor for the same purpose.  The backend string is never interpreted
    outside this module.
    """
    if backend == "sdk":
        return SdkGateway(client=client)
    if backend == "cli":
        return CliGateway(executor=client)
    return AutoGateway(_sdk=(SdkGateway(client=client) if client is not None else None))


# D4-02: compatibility alias — existing callers of `DockerExecutor` keep working.
DockerExecutor = DockerGateway
