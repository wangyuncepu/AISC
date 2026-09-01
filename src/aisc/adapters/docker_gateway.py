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

import json
import os
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol, runtime_checkable

from aisc.adapters.docker_ import _poll_resize_step
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

    def open_interactive(
        self,
        container: str,
        argv: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> InteractiveResult:
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
    """2.1.9 hotfix r3 (#61): docker.from_env() with DOCKER_HOST unset reads
    the docker CLI context meta.json WITHOUT an encoding — on zh-CN Windows
    that GBK-decodes Docker Desktop's UTF-8 context file and raises a plain
    Exception ("corrupted meta file"), not a DockerException. Fall back to
    the platform DEFAULT endpoint (explicit base_url never reads meta.json).
    Mirror of RealDockerExecutor._client_from_env_safe."""
    import docker

    try:
        return docker.from_env()
    except Exception:  # noqa: BLE001 — context meta unreadable
        import os as _os

        if _os.name == "nt":
            return docker.DockerClient(base_url="npipe:////./pipe/docker_engine")
        return docker.DockerClient(base_url="unix:///var/run/docker.sock")


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
    # 2.1.9 hotfix r3: the default_factory CALLS _default_client() at
    # construction — eager docker.from_env() (a zh-CN GBK landmine) and a
    # client instance where _client() expects a callable. A plain function
    # default keeps the field lazy AND callable.
    _client_factory: Callable[[], object] = _default_client

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
                    # Full sha256 image ID ships with the list attrs — no
                    # extra API round-trip (A0: structured image ID).
                    image_id=(c.attrs.get("Image") or ""),
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
                # `.Image` in inspect attrs = content-addressed ID, distinct
                # from the Config.Image REF above (A0: structured image ID).
                image_id=(attrs.get("Image") or ""),
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
            try:
                c.wait(timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                # docker-py surfaces wait timeout as requests.ReadTimeout (not a
                # DockerException); classify by class name so the deadline path
                # returns a stable TIMEOUT result instead of escaping.
                if "ReadTimeout" in type(exc).__name__ or "Timeout" in type(exc).__name__:
                    return LifecycleResult(
                        operation=_new_operation(
                            "sdk", exit_code=1, duration_ms=_elapsed(start),
                            error_code=DockerErrorCode.TIMEOUT,
                            error_message=f"wait timed out after {timeout}s",
                            timed_out=True,
                        ),
                        target=container,
                    )
                if isinstance(exc, docker.errors.DockerException):
                    raise
                return LifecycleResult(
                    operation=_new_operation(
                        "sdk", exit_code=3, duration_ms=_elapsed(start),
                        error_code=DockerErrorCode.UNKNOWN,
                        error_message=str(exc),
                    ),
                    target=container,
                )
            try:
                c.reload()
            except docker.errors.NotFound:
                # Container removed between wait and reload: report exited.
                return LifecycleResult(
                    operation=_new_operation("sdk", exit_code=0, duration_ms=_elapsed(start)),
                    target=container,
                    observed_state="exited",
                )
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

    # -- interactive (SDK-first; D4-03 owns create/start/resize/stream/reap) --

    def open_interactive(
        self,
        container: str,
        argv: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> InteractiveResult:
        """Interactive TTY session via the Docker SDK, using the injected client.

        Lifecycle (D4-03/A-DG04-1): ``exec_create`` → ``exec_start`` (socket) →
        terminal-size watcher forwards ``exec_resize`` → raw stdout/stdin stream →
        ``exec_inspect`` poll for exit → join/reap all threads. No resource is
        left behind on error: the stop event is always set and threads joined.

        v2.1.7 S6: *env* rides the exec environment only (never the image or a
        profile) — the bash tutorial ``help`` function enters sessions this way.
        """
        import docker
        import requests  # 2.1.9 hotfix (#61): transport failures are not DockerExceptions

        start = time.monotonic()
        try:
            client = self._client()
            exec_kwargs: Dict[str, Any] = {"tty": True, "stdin": True}
            if env:
                exec_kwargs["environment"] = dict(env)
            exec_id = client.api.exec_create(container, list(argv), **exec_kwargs)["Id"]
        except docker.errors.NotFound:
            return InteractiveResult(
                operation=_new_operation(
                    "sdk", exit_code=1, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.NOT_FOUND,
                    error_message=f"container {container} not found",
                ),
                session_id="",
            )
        except docker.errors.DockerException as exc:
            return InteractiveResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.DAEMON_UNREACHABLE,
                    error_message=str(exc),
                ),
                session_id="",
            )
        except (requests.RequestException, OSError) as exc:
            return InteractiveResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.DAEMON_UNREACHABLE,
                    error_message=f"exec create transport failure: {exc}",
                ),
                session_id="",
            )

        try:
            sock = client.api.exec_start(exec_id, socket=True, tty=True)
        except (docker.errors.DockerException, requests.RequestException, OSError) as exc:
            return InteractiveResult(
                operation=_new_operation(
                    "sdk", exit_code=3, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.UNKNOWN,
                    error_message=f"exec start failed: {exc}",
                ),
                session_id=exec_id,
            )

        stop = threading.Event()
        errors: List[Exception] = []

        # Initial resize from the resize file (set by the pty supervisor before
        # spawn; AISC_RESIZE_FILE = "<cols> <rows>\n").
        resize_file = os.environ.get("AISC_RESIZE_FILE")
        last_size: Optional[tuple] = None
        if resize_file:
            try:
                content = open(resize_file).read().strip().split()
                if len(content) == 2:
                    last_size = (int(content[0]), int(content[1]))
                    client.api.exec_resize(exec_id, height=last_size[1], width=last_size[0])
            except Exception:  # noqa: BLE001
                pass

        def read_sock(size: int) -> bytes:
            """Raw read from the docker-py exec socket (recv | read | os.read)."""
            if hasattr(sock, "recv"):
                return sock.recv(size)
            if hasattr(sock, "read"):
                return sock.read(size)
            return os.read(sock.fileno(), size)

        def send_all(data: bytes) -> None:
            """Send every byte (sendall | _sock.sendall | write | os.write)."""
            if hasattr(sock, "sendall"):
                sock.sendall(data)
                return
            raw = getattr(sock, "_sock", None)
            if raw is not None and hasattr(raw, "sendall"):
                raw.sendall(data)
                return
            view = memoryview(data)
            while view:
                if hasattr(sock, "write") and getattr(sock, "writable", lambda: False)():
                    sent = sock.write(view)
                else:
                    sent = os.write(sock.fileno(), view)
                if sent is None:
                    raise OSError("socket write would block")
                if sent <= 0:
                    raise OSError("socket write failed")
                view = view[sent:]

        def shutdown_write() -> None:
            """Half-close the write side on stdin EOF (shutdown | _sock.shutdown)."""
            raw = getattr(sock, "_sock", None)
            targets = [raw, sock] if raw is not None else [sock]
            for target in targets:
                if hasattr(target, "shutdown"):
                    try:
                        target.shutdown(socket.SHUT_WR)
                        return
                    except OSError:
                        pass
            try:
                sock.close()
            except OSError:
                pass

        def drain() -> None:
            """Socket → stdout (raw bytes)."""
            try:
                while True:
                    chunk = read_sock(65536)
                    if not chunk:
                        break
                    os.write(sys.stdout.fileno(), chunk)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def forward() -> None:
            """stdin → socket; on EOF close the write side."""
            try:
                while True:
                    chunk = os.read(sys.stdin.fileno(), 4096)
                    if not chunk:
                        break
                    send_all(chunk)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                shutdown_write()

        def watch_resize() -> None:
            """Poll the resize file; forward changes to exec_resize."""
            if not resize_file:
                return
            # Local copy + module-level step helper: immune to the closure
            # trap that previously dropped every post-initial resize (B-05).
            last = last_size
            while not stop.is_set():
                last = _poll_resize_step(
                    resize_file,
                    last,
                    lambda size: client.api.exec_resize(
                        exec_id, height=size[1], width=size[0]
                    ),
                )
                stop.wait(0.1)

        t_drain = threading.Thread(target=drain, daemon=True)
        t_fwd = threading.Thread(target=forward, daemon=True)
        t_resize = threading.Thread(target=watch_resize, daemon=True)
        t_drain.start()
        t_fwd.start()
        t_resize.start()

        exit_code = -1
        waited = False
        # 2.1.9 hotfix (#61): tolerate transient inspect failures (npipe
        # hiccups) before giving up — mirrors RealDockerExecutor.
        inspect_failures = 0
        try:
            while True:
                try:
                    info = client.api.exec_inspect(exec_id)
                    inspect_failures = 0
                except (docker.errors.APIError, requests.RequestException, OSError) as exc:
                    inspect_failures += 1
                    if inspect_failures >= 3:
                        raise
                    time.sleep(0.5)
                    continue
                if not info.get("Running"):
                    exit_code = int(info.get("ExitCode", 0))
                    waited = True
                    break
                time.sleep(0.2)
        except (docker.errors.APIError, requests.RequestException, OSError) as exc:
            errors.append(exc)
        finally:
            stop.set()
            t_drain.join(timeout=5)
            t_fwd.join(timeout=5)
            t_resize.join(timeout=5)

        if errors:
            return InteractiveResult(
                operation=_new_operation(
                    "sdk", exit_code=-1, duration_ms=_elapsed(start),
                    error_code=DockerErrorCode.UNKNOWN,
                    error_message=f"exec stream error: {errors[0]}",
                ),
                session_id=exec_id,
            )
        return InteractiveResult(
            operation=_new_operation("sdk", exit_code=exit_code, duration_ms=_elapsed(start)),
            session_id=exec_id,
            waited=waited,
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
        result = ContainerListResult(
            operation=self._op(r, duration_ms=_elapsed(start)),
            stdout=r.stdout,
            stderr=r.stderr,
        )
        if r.exit_code != 0:
            return result
        # RealDockerExecutor lists with
        # `--format "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}"` — machine
        # format, stable fields. `docker ps` cannot carry labels or the
        # content-addressed image ID: rows leave labels={} / image_id="" and
        # callers inspect the interesting candidates individually (A0).
        for line in (r.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            result.containers.append(
                ContainerSummary(
                    id=parts[0].strip(),
                    name=parts[1].strip(),
                    image=parts[2].strip(),
                    status=parts[3].strip(),
                )
            )
        return result

    def inspect_container(self, container: str) -> ContainerInspectResult:
        start = time.monotonic()
        r: ProcessResult = self._exec().inspect_container(container)
        if r.exit_code != 0:
            return ContainerInspectResult(
                operation=self._op(r, duration_ms=_elapsed(start)),
                stdout=r.stdout,
                stderr=r.stderr,
            )
        # `docker inspect` emits stable machine JSON (never human text).
        try:
            attrs = json.loads(r.stdout or "[]")
            attrs = attrs[0] if isinstance(attrs, list) and attrs else {}
        except ValueError:
            attrs = {}
        if not isinstance(attrs, dict):
            attrs = {}
        config = attrs.get("Config", {}) or {}
        return ContainerInspectResult(
            operation=self._op(r, duration_ms=_elapsed(start)),
            stdout=r.stdout,
            stderr=r.stderr,
            container_id=attrs.get("Id", "") or "",
            name=(attrs.get("Name", "") or "").lstrip("/"),
            state=(attrs.get("State", {}) or {}).get("Status", "") or "",
            image=config.get("Image", "") or "",
            labels=config.get("Labels", {}) or {},
            config=config,
            image_id=attrs.get("Image", "") or "",
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
