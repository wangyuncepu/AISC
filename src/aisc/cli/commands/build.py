"""``aisc build`` — Docker image build command.

Plans a ``docker build`` invocation based on user args + config/versions.env,
then optionally executes it.  Supports ``--events`` JSONL output.

**All** docker operations go through an injected ``DockerExecutor``;
this module never calls ``subprocess.run`` directly.
"""

from __future__ import annotations

import sys as _sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.domain.models import BuildPlan, CliError
from aisc.adapters.docker_ import (
    DockerExecutor,
    RealDockerExecutor,
    validate_build_resources,
)
from aisc.application.version import _parse_versions_env
from aisc.cli.output import JsonlEmitter


# ---------------------------------------------------------------------------
# Build service: plan the build
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _BuildEnv:
    """Parsed values from config/versions.env used during build."""
    use_cn_mirror: str = "1"
    node_image: str = ""


def _parse_build_env(root: Path) -> _BuildEnv:
    """Parse build-relevant values from config/versions.env."""
    env = _parse_versions_env(root)
    use_cn = env.get("USE_CN_MIRROR", "1")
    node_image = env.get("NODE_IMAGE", "")
    return _BuildEnv(use_cn_mirror=use_cn, node_image=node_image)


def plan_build(
    root: Path,
    tag: str = "super-claude:latest",
    no_cache: bool = False,
    pull: bool = False,
    dry_run: bool = False,
) -> BuildPlan:
    """Create an immutable ``BuildPlan`` from user args.

    Returns a ``BuildPlan`` with the computed ``docker argv``.

    Raises:
        CliError (exit 1, AISC_ERR_GENERAL): if Dockerfile, versions.env,
            or NODE_IMAGE are missing.  These are planning errors,
            NOT build failures (exit 4).
    """
    # Validate resources — planning phase, exit 1 on missing
    try:
        validate_build_resources(root)
    except FileNotFoundError as exc:
        raise CliError(message=str(exc), exit_code=1,
                       error_code="AISC_ERR_GENERAL") from exc

    dockerfile = str(root / "container" / "Dockerfile")
    build_env = _parse_build_env(root)

    if not build_env.node_image:
        raise CliError(
            message="NODE_IMAGE is missing from config/versions.env. "
                    "Please add NODE_IMAGE=<base-image> to config/versions.env.",
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
        )

    # If tag is just a name without tag (no ':'), append ':latest'
    if ":" not in tag:
        tag = f"{tag}:latest"

    return BuildPlan(
        tag=tag,
        root=str(root),
        dockerfile=dockerfile,
        no_cache=no_cache,
        pull=pull,
        build_arg_use_cn_mirror=build_env.use_cn_mirror,
        build_arg_node_image=build_env.node_image,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Build result (structured outcome)
# ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    """Result of a build execution — all fields populated even on failure."""
    image_tag: str = ""
    docker_argv: List[str] = field(default_factory=list)
    docker_exit_code: Optional[int] = None
    dry_run: bool = False
    executed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image_tag": self.image_tag,
            "dry_run": self.dry_run,
            "executed": self.executed,
            "docker_argv": list(self.docker_argv),
            "docker_exit_code": self.docker_exit_code,
        }


# ---------------------------------------------------------------------------
# Run the build (orchestration)
# ---------------------------------------------------------------------------

def run_build(
    plan: BuildPlan,
    *,
    emitter: Optional[JsonlEmitter] = None,
    executor: Optional[DockerExecutor] = None,
    streaming: bool = False,
) -> BuildResult:
    """Execute or simulate a build, emitting events as needed.

    All docker operations go through *executor* (RealDockerExecutor by default).

    Args:
        plan: The immutable build plan.
        emitter: JsonlEmitter for --events mode, or None.
        executor: DockerExecutor for injection (testing).
        streaming:
            ``True`` (text mode) — use ``run_streaming`` with inherited
            stdout/stderr.
            ``False`` (JSON/events mode) — use ``run_captured`` and forward
            docker stdout/stderr to stderr so stdout stays pure envelope/JSONL.

    Returns:
        BuildResult with outcome data.

    Raises:
        CliError: with ``data`` field carrying full BuildResult.to_dict().
    """
    exec_ = executor or RealDockerExecutor()

    result = BuildResult(
        image_tag=plan.tag,
        docker_argv=list(plan.docker_argv),
        dry_run=plan.dry_run,
        executed=False,
    )

    # --- emit start event ---
    if emitter is not None:
        emitter.emit("build.start", data={"image_tag": plan.tag})

    # --- dry-run: zero docker calls ---
    if plan.dry_run:
        if emitter is not None:
            emitter.emit("build.plan", data={
                "docker_argv": result.docker_argv,
                "dry_run": True,
            })
        return result

    # --- preflight ---
    pf = exec_.preflight()
    if not pf.available:
        raise CliError(
            message=f"Docker unavailable: {pf.reason}",
            exit_code=pf.exit_code,
            error_code=pf.error_code,
            data=result.to_dict(),
        )

    # --- check if image already exists ---
    from aisc.domain.models import ImageInspectStatus
    inspect_result = exec_.inspect_image(plan.tag)
    if inspect_result.status == ImageInspectStatus.EXISTS:
        if streaming and emitter is None:
            # Text mode: warn user about existing image
            _sys.stderr.write(f"\n⚠️  Image already exists: {plan.tag}\n")
            _sys.stderr.write("   Building will replace it (may create dangling <none> images).\n")
            _sys.stderr.write("   Tip: Use 'docker rmi {tag}' before build, or use a different tag.\n\n")
            _sys.stderr.flush()
        elif emitter is not None:
            # Events mode: emit warning event
            emitter.emit("build.warning", data={
                "message": f"Image already exists: {plan.tag}",
                "hint": "Building will replace it (may create dangling <none> images).",
            })

    # --- plan event (non-dry-run) ---
    if emitter is not None:
        emitter.emit("build.plan", data={
            "docker_argv": result.docker_argv,
        })

    # --- execute docker build ---
    argv = list(plan.docker_argv)

    if streaming:
        # Text mode: inherit streams for real-time build log
        proc = exec_.run_streaming(argv)
        result.docker_exit_code = proc.exit_code if proc.exit_code >= 0 else proc.exit_code
        result.executed = True

        if proc.command_not_found:
            raise CliError(
                message="Docker CLI not found",
                exit_code=3, error_code="AISC_ERR_DOCKER_UNAVAILABLE",
                data=result.to_dict(),
            )
        if proc.timed_out:
            raise CliError(
                message="Docker build timed out",
                exit_code=1, error_code="AISC_ERR_GENERAL",
                data=result.to_dict(),
            )
        if proc.exit_code != 0:
            raise CliError(
                message=f"Docker build failed (exit {proc.exit_code})",
                exit_code=4, error_code="AISC_ERR_BUILD_FAILED",
                data=result.to_dict(),
            )
    else:
        # JSON / events mode: capture, forward to stderr
        proc = exec_.run_captured(argv)
        result.docker_exit_code = proc.exit_code
        result.executed = True

        # Forward docker stdout/stderr to stderr — keep stdout pure
        if proc.stdout:
            _sys.stderr.write(proc.stdout)
        if proc.stderr:
            _sys.stderr.write(proc.stderr)

        if proc.exit_code != 0:
            raise CliError(
                message=f"Docker build failed (exit {proc.exit_code})",
                exit_code=4, error_code="AISC_ERR_BUILD_FAILED",
                data=result.to_dict(),
            )

    # --- success ---
    if emitter is not None:
        emitter.emit("build.step.complete", data={
            "step": "build_context", "status": "ok",
        })

    return result
