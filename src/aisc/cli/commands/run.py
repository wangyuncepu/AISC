"""``aisc run`` — Docker container run command.

Plans a ``docker run`` invocation based on user args, then optionally
executes it.  Supports ``--events`` JSONL output.

**All** docker operations go through an injected ``DockerExecutor``;
this module never calls ``subprocess.run`` directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.domain.models import (
    CliError,
    ImageInspectStatus,
    RunPlan,
)
from aisc.adapters.docker_ import (
    DockerExecutor,
    RealDockerExecutor,
    format_argv_display,
    validate_run_resources,
    validate_proxy_config,
)
from aisc.cli.output import JsonlEmitter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_container_name(base: str) -> str:
    """Generate a unique container name by appending a short random suffix."""
    short = uuid.uuid4().hex[:8]
    return f"{base}-{short}"


# ---------------------------------------------------------------------------
# Run service: plan the run
# ---------------------------------------------------------------------------

def plan_run(
    image: str = "super-claude:latest",
    workspace: str = "",
    name: str = "super-claude-station",
    network: str = "direct",
    dry_run: bool = False,
    interactive: bool = True,
    non_interactive: bool = False,
    proxy_config: str = "",
    label: str = "",
    keep_alive: bool = False,
    aisc_root: Optional[Path] = None,
) -> RunPlan:
    """Create an immutable ``RunPlan`` from user args.

    Args:
        image: Docker image name (default: super-claude:latest).
        workspace: Host path to bind-mount.
        name: Container name prefix; unique suffix is appended.
        network: ``"direct"`` or ``"proxy"``.
        dry_run: Plan only, don't execute.
        interactive: ``True`` → include ``-it``; ``False`` → omit.
        non_interactive: ``True`` → omit ``-it``, add ``AISC_NON_INTERACTIVE=1``
            and ``CLAUDE_SCOPE=project`` env vars, use DEVNULL for stdin.
        proxy_config: Host path to ``.claude/mihomo/config.yaml``.
            If omitted but ``network=proxy``, use
            ``<aisc_root>/.claude/mihomo/config.yaml``.
        keep_alive: ``True`` → omit ``--rm``, keep container after exit.
        aisc_root: AISC root path for proxy config resolution.

    Returns:
        A ``RunPlan`` with computed docker arguments.

    Raises:
        CliError: on workspace / proxy config validation failure.
    """
    if ":" not in image:
        image = f"{image}:latest"

    ws_path = Path(workspace).resolve() if workspace else Path.cwd()

    # Resolve proxy config (IDEA-2: data-root subscription first — the
    # legacy <aisc_root>/.claude/mihomo/config.yaml is adopted once on first
    # use; an explicit --proxy-config always wins).
    resolved_proxy = proxy_config
    if network == "proxy" and not resolved_proxy:
        from aisc.application.network_subscription import (
            resolve_subscription_config_path,
        )

        resolved_proxy = resolve_subscription_config_path() or ""

    # Stage 7 (DATA-01): agent config mounts from the data root. The dirs
    # are created here (host side) so Windows bind mounts have real targets.
    # Fail closed: an unusable data root stops the run — never fall back to
    # copying agent state into the workspace.
    from aisc.application.data_root import DataRootResolver

    resolved_state = DataRootResolver().resolve(ws_path)
    ws_state_dir = resolved_state.workspace_dir
    for sub in ("claude", "codex", "cc-switch", "runtime"):
        (ws_state_dir / sub).mkdir(parents=True, exist_ok=True)

    # svc-5: one gateway host port per one-shot run (same capability as
    # managed runtimes). Ports reserved by other registered containers are
    # skipped best-effort; dry-run shows the publish plan without Docker.
    from aisc.application.web_gateway import (
        allocate_gateway_host_port,
        registry_host_ports,
    )

    exclude: set = set()
    if aisc_root is not None:
        try:
            from aisc.adapters.container_registry import list_containers

            exclude = registry_host_ports(list_containers(Path(aisc_root)))
        except Exception:
            exclude = set()
    web_gateway_port = allocate_gateway_host_port(exclude=exclude)

    return RunPlan(
        image=image,
        workspace=str(ws_path),
        name=_generate_container_name(name),
        network=network,
        dry_run=dry_run,
        interactive=interactive,
        non_interactive=non_interactive,
        proxy_config=resolved_proxy,
        label=label,
        keep_alive=keep_alive,
        agent_state_root=str(ws_state_dir),
        web_gateway_host_port=web_gateway_port,
    )


# ---------------------------------------------------------------------------
# Run result (structured outcome)
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Result of a run execution — all fields populated even on failure."""
    image: str = ""
    container_id: Optional[str] = None
    docker_argv: List[str] = field(default_factory=list)
    container_exit_code: Optional[int] = None
    dry_run: bool = False
    executed: bool = False
    # svc-5: service-access metadata — the gateway publish that rode this
    # run's docker argv. Empty when no port was allocated.
    web_gateway: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "image": self.image,
            "container_id": self.container_id,
            "dry_run": self.dry_run,
            "executed": self.executed,
            "docker_argv": list(self.docker_argv),
            "container_exit_code": self.container_exit_code,
        }
        if self.web_gateway:
            out["web_gateway"] = dict(self.web_gateway)
        return out


def _run_captured_with_publish_retry(executor, plan: RunPlan, attempts: int = 3):
    """``docker run`` (captured) with bounded gateway bind-conflict retry.

    The argv is regenerated from the (replaced) plan each attempt so the
    publish spec never stacks. Only the captured paths can detect the
    conflict — the interactive streaming path inherits stderr and surfaces
    Docker's own message on the terminal (unchanged behavior).
    """
    import dataclasses

    from aisc.application.web_gateway import allocate_gateway_host_port, is_bind_conflict

    proc = executor.run_captured(list(plan.docker_argv))
    tried = 1
    while proc.exit_code != 0 and is_bind_conflict(proc.stderr or "") \
            and tried < attempts:
        plan = dataclasses.replace(
            plan,
            web_gateway_host_port=allocate_gateway_host_port(
                start_hint=plan.web_gateway_host_port + 1),
        )
        proc = executor.run_captured(list(plan.docker_argv))
        tried += 1
    return proc, plan


# ---------------------------------------------------------------------------
# Execute the run
# ---------------------------------------------------------------------------

def run_container(
    plan: RunPlan,
    *,
    emitter: Optional[JsonlEmitter] = None,
    executor: Optional[DockerExecutor] = None,
    capture: bool = False,
    aisc_root: Optional[Path] = None,
) -> RunResult:
    """Execute or simulate a ``docker run``, emitting events as needed.

    All docker operations go through *executor* (RealDockerExecutor by default).

    Args:
        plan: The immutable run plan.
        emitter: JsonlEmitter for --events mode, or None.
        executor: DockerExecutor for injection (testing).
        capture: Force captured output (stdout/stderr forwarded to stderr).
            When True, container output never reaches stdout.

    Returns:
        RunResult with outcome data.

    Raises:
        CliError: with ``data`` field carrying full RunResult.to_dict().
    """
    exec_ = executor or RealDockerExecutor()

    result = RunResult(
        image=plan.image,
        docker_argv=list(plan.docker_argv),
        dry_run=plan.dry_run,
        executed=False,
    )
    if plan.web_gateway_host_port:
        from aisc.domain.web_services import WEB_GATEWAY_CONTAINER_PORT

        result.web_gateway = {
            "container_port": WEB_GATEWAY_CONTAINER_PORT,
            "host_port": plan.web_gateway_host_port,
        }

    # --- emit start event ---
    if emitter is not None:
        emitter.emit("run.start", data={
            "image": plan.image,
            "workspace": plan.workspace,
            "name": plan.name,
            "network": plan.network,
            "docker_argv": result.docker_argv,
        })

    # --- validate workspace (both dry-run and real) ---
    try:
        validate_run_resources(Path(plan.workspace))
    except (FileNotFoundError, PermissionError, NotADirectoryError) as exc:
        raise CliError(message=str(exc), exit_code=9,
                       error_code="AISC_ERR_PERMISSION_DENIED",
                       data=result.to_dict()) from exc

    # --- validate proxy config (skip file checks in dry-run) ---
    if plan.network == "proxy":
        if not plan.proxy_config:
            raise CliError(
                message="Proxy network mode requires proxy configuration. "
                        "Set --aisc-root or ensure .claude/mihomo/config.yaml exists.",
                exit_code=1, error_code="AISC_ERR_GENERAL",
                data=result.to_dict(),
            )
        if not plan.dry_run:
            try:
                validate_proxy_config(Path(plan.proxy_config))
            except (FileNotFoundError, PermissionError) as exc:
                raise CliError(message=str(exc), exit_code=1,
                               error_code="AISC_ERR_GENERAL",
                               data=result.to_dict()) from exc

    # --- dry-run: zero docker calls, validated locally ---
    if plan.dry_run:
        if emitter is not None:
            emitter.emit("run.plan", data={
                "docker_argv": result.docker_argv,
                "dry_run": True,
            })
        return result

    # --- preflight ---
    pf = exec_.preflight()
    if not pf.available:
        raise CliError(
            message=f"Docker unavailable: {pf.reason}",
            exit_code=pf.exit_code, error_code=pf.error_code,
            data=result.to_dict(),
        )

    # --- image inspect (structured result) ---
    inspect = exec_.inspect_image(plan.image)
    if inspect.status == ImageInspectStatus.MISSING:
        raise CliError(
            message=f"Image '{plan.image}' not found. Please build it first:\n"
                    f"  aisc build --tag {plan.image}\n"
                    f"Or specify an existing image with --image <name>.",
            exit_code=5, error_code="AISC_ERR_IMAGE_NOT_FOUND",
            data=result.to_dict(),
        )
    elif inspect.status == ImageInspectStatus.DOCKER_UNAVAILABLE:
        raise CliError(
            message=inspect.message, exit_code=3,
            error_code="AISC_ERR_DOCKER_UNAVAILABLE",
            data=result.to_dict(),
        )
    elif inspect.status == ImageInspectStatus.PERMISSION_DENIED:
        raise CliError(
            message=inspect.message, exit_code=9,
            error_code="AISC_ERR_PERMISSION_DENIED",
            data=result.to_dict(),
        )
    elif inspect.status in (ImageInspectStatus.TIMEOUT, ImageInspectStatus.ERROR):
        raise CliError(
            message=inspect.message or "Image inspect failed",
            exit_code=1, error_code="AISC_ERR_GENERAL",
            data=result.to_dict(),
        )
    # EXISTS → proceed

    # --- register container in the multi-container index ---
    if aisc_root is not None:
        from aisc.adapters.container_registry import register
        try:
            register(aisc_root, plan.name, {
                "image": plan.image,
                "workspace": plan.workspace,
                "network": plan.network,
                "label": plan.label,
            })
        except (ValueError, OSError) as exc:
            raise CliError(
                message=f"Failed to write container registry: {exc}",
                exit_code=1, error_code="AISC_ERR_STATE_WRITE_FAILED",
                data=result.to_dict(),
            ) from exc

    # --- plan event for non-dry ---
    if emitter is not None:
        emitter.emit("run.plan", data={
            "docker_argv": result.docker_argv,
        })

    # --- execute ---
    argv = list(plan.docker_argv)

    if emitter is not None:
        emitter.emit("run.container.start", data={
            "image": plan.image, "name": plan.name,
            "docker_argv": argv,
        })

    if capture:
        # --- machine mode (json / events): captured output, forwarded to stderr ---
        import sys as _sys
        proc, plan = _run_captured_with_publish_retry(exec_, plan)
        result.docker_argv = list(plan.docker_argv)
        if plan.web_gateway_host_port:
            result.web_gateway = {**result.web_gateway,
                                  "host_port": plan.web_gateway_host_port}
        result.container_exit_code = proc.exit_code
        result.executed = True

        # Forward docker stdout/stderr to stderr
        if proc.stdout:
            _sys.stderr.write(proc.stdout)
        if proc.stderr:
            _sys.stderr.write(proc.stderr)

        if proc.exit_code != 0:
            raise CliError(
                message=f"Container exited with code {proc.exit_code}",
                exit_code=10, error_code="AISC_ERR_CONTAINER_FAILED",
                data=result.to_dict(),
            )
    elif plan.interactive and not plan.non_interactive:
        # Text mode: streaming with inherited streams
        # For keep_alive mode, container runs in background (-d), then we attach
        if plan.keep_alive:
            # Step 1: Start container in detached mode
            proc, plan = _run_captured_with_publish_retry(exec_, plan)
            result.docker_argv = list(plan.docker_argv)
            if plan.web_gateway_host_port:
                result.web_gateway = {**result.web_gateway,
                                      "host_port": plan.web_gateway_host_port}
            if proc.exit_code != 0:
                raise CliError(
                    message=f"Failed to start container: {proc.stderr}",
                    exit_code=10, error_code="AISC_ERR_CONTAINER_FAILED",
                    data=result.to_dict(),
                )

            # Step 2: Attach to the running container
            attach_argv = ["attach", "--sig-proxy=true", plan.name]
            proc = exec_.run_streaming(attach_argv)
            result.container_exit_code = 0  # Container keeps running after detach
            result.executed = True

            if proc.command_not_found:
                raise CliError(
                    message="Docker CLI not found",
                    exit_code=3, error_code="AISC_ERR_DOCKER_UNAVAILABLE",
                    data=result.to_dict(),
                )
        else:
            # Normal interactive mode (container removed on exit)
            proc = exec_.run_streaming(argv)
            result.container_exit_code = proc.exit_code if proc.exit_code >= 0 else proc.exit_code
            result.executed = True

            if proc.command_not_found:
                raise CliError(
                    message="Docker CLI not found",
                    exit_code=3, error_code="AISC_ERR_DOCKER_UNAVAILABLE",
                    data=result.to_dict(),
                )
            if proc.timed_out:
                raise CliError(
                    message="Container run timed out",
                    exit_code=1, error_code="AISC_ERR_GENERAL",
                    data=result.to_dict(),
                )
            if proc.exit_code != 0:
                raise CliError(
                    message=f"Container exited with code {proc.exit_code}",
                    exit_code=10, error_code="AISC_ERR_CONTAINER_FAILED",
                    data=result.to_dict(),
                )
    elif plan.non_interactive and not capture:
        # Non-interactive mode: streaming with DEVNULL stdin
        proc = exec_.run_non_interactive(argv)
        result.container_exit_code = proc.exit_code if proc.exit_code >= 0 else proc.exit_code
        result.executed = True

        if proc.command_not_found:
            raise CliError(
                message="Docker CLI not found",
                exit_code=3, error_code="AISC_ERR_DOCKER_UNAVAILABLE",
                data=result.to_dict(),
            )
        if proc.timed_out:
            raise CliError(
                message="Container run timed out",
                exit_code=1, error_code="AISC_ERR_GENERAL",
                data=result.to_dict(),
            )
        if proc.exit_code != 0:
            raise CliError(
                message=f"Container exited with code {proc.exit_code}",
                exit_code=10, error_code="AISC_ERR_CONTAINER_FAILED",
                data=result.to_dict(),
            )
    else:
        # JSON / events mode (no capture flag, not interactive, not non_interactive): captured
        import sys as _sys
        proc, plan = _run_captured_with_publish_retry(exec_, plan)
        result.docker_argv = list(plan.docker_argv)
        if plan.web_gateway_host_port:
            result.web_gateway = {**result.web_gateway,
                                  "host_port": plan.web_gateway_host_port}
        result.container_exit_code = proc.exit_code
        result.executed = True

        # Forward docker stdout/stderr to stderr
        if proc.stdout:
            _sys.stderr.write(proc.stdout)
        if proc.stderr:
            _sys.stderr.write(proc.stderr)

        if proc.exit_code != 0:
            raise CliError(
                message=f"Container exited with code {proc.exit_code}",
                exit_code=10, error_code="AISC_ERR_CONTAINER_FAILED",
                data=result.to_dict(),
            )

    # --- success ---
    if emitter is not None:
        emitter.emit("run.container.complete", data={
            "exit_code": result.container_exit_code,
        })

    # svc-5: a `--rm` container is gone the moment it exits — prune its
    # registry entry now so nothing lingers (best-effort, never fatal).
    if not plan.keep_alive and aisc_root is not None:
        try:
            from aisc.adapters.container_registry import gc as registry_gc

            registry_gc(Path(aisc_root), exec_)
        except Exception:
            pass

    return result
