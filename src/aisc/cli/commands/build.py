"""``aisc build`` — Docker image build command.

Plans a ``docker build`` invocation based on user args + config/versions.env,
then optionally executes it.  Supports ``--events`` JSONL output.

**All** docker operations go through an injected ``DockerExecutor``;
this module never calls ``subprocess.run`` directly.
"""

from __future__ import annotations

import json
import re
import sys as _sys
import time as _time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.domain.models import BuildPlan, CliError
from aisc.adapters.docker_ import (
    DockerExecutor,
    RealDockerExecutor,
    validate_build_resources,
)
from aisc.application.version import _parse_versions_env
from aisc.cli.build_progress_parser import BuildProgressParser, parse_context_bytes
from aisc.cli.output import JsonlEmitter


# ---------------------------------------------------------------------------
# Build service: plan the build
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _BuildEnv:
    """Parsed values from config/versions.env used during build."""
    use_cn_mirror: str = "1"
    node_image: str = ""
    node_image_cn: str = ""


def _parse_build_env(root: Path) -> _BuildEnv:
    """Parse build-relevant values from config/versions.env."""
    env = _parse_versions_env(root)
    use_cn = env.get("USE_CN_MIRROR", "1")
    node_image = env.get("NODE_IMAGE", "")
    node_image_cn = env.get("NODE_IMAGE_CN", "")
    return _BuildEnv(use_cn_mirror=use_cn, node_image=node_image, node_image_cn=node_image_cn)


def _open_build_log() -> Optional[Path]:
    """Create a timestamped build log under ``<data-root>/logs`` (Gate-S4 §1:
    the UI keeps only a bounded tail; the complete raw output lives here and
    ``build.start`` carries its path). Best-effort — never blocks the build."""
    try:
        from aisc.application.data_root import shared_root
        logs = shared_root() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / f"build-{int(_time.time())}.log"
        path.write_text("", encoding="utf-8")
        return path
    except Exception:
        return None


def _previous_context_total(skip_log: Optional[Path]) -> Optional[float]:
    """The FINAL `transferring context: X done` bytes from the most recent
    PREVIOUS build log — the estimated denominator for the prepare-phase
    progress bar (Gate-S4 §1 amendment). Best-effort; absence = the bar
    simply stays indeterminate."""
    try:
        from aisc.application.data_root import shared_root
        logs = shared_root() / "logs"
        candidates = sorted(
            (p for p in logs.glob("build-*.log") if p != skip_log),
            key=lambda p: p.name,
            reverse=True,
        )
        for path in candidates[:3]:  # newest few; tolerate partial logs
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            last: Optional[float] = None
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.endswith("done") or stripped.endswith("done)"):
                    val = parse_context_bytes(stripped)
                    if val:
                        last = val
            if last:
                return last
    except Exception:
        pass
    return None


# Dockerfile instructions that count as build steps (candidate step_total).
_INSTRUCTION_RE = re.compile(
    r"^\s*(?:FROM|RUN|CMD|LABEL|MAINTAINER|EXPOSE|ENV|ADD|COPY|ENTRYPOINT"
    r"|VOLUME|USER|WORKDIR|ARG|ONBUILD|STOPSIGNAL|HEALTHCHECK|SHELL)\b",
    re.IGNORECASE,
)


def _dockerfile_instruction_count(plan: BuildPlan) -> Optional[int]:
    """Metadata only (Gate-S4): the Dockerfile's instruction count as a
    candidate ``step_total``. build.progress itself only trusts what the
    docker output actually maps; this feeds the plan event for consumers
    that want an early hint."""
    try:
        if not plan.root or not plan.dockerfile:
            return None
        text = (Path(plan.root) / plan.dockerfile).read_text(encoding="utf-8")
    except OSError:
        return None
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _INSTRUCTION_RE.match(stripped):
            count += 1
    return count or None


def plan_build(
    root: Path,
    tag: str = "super-claude:latest",
    no_cache: bool = False,
    pull: bool = False,
    dry_run: bool = False,
    cc_switch: Optional[Any] = None,
) -> BuildPlan:
    """Create an immutable ``BuildPlan`` from user args.

    Args:
        cc_switch: a ``ResolvedRelease`` (aisc.domain.cc_switch_release) from
            the resolver — injected as docker build args + image labels (Stage
            8b, CS-01/CS-02). ``None`` keeps the legacy ARG-fallback path
            (manual docker builds only; never used by ``aisc build``).

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

    # Select node image based on USE_CN_MIRROR
    selected_node_image = build_env.node_image
    if build_env.use_cn_mirror == "1" and build_env.node_image_cn:
        selected_node_image = build_env.node_image_cn

    cc_kwargs: Dict[str, str] = {}
    if cc_switch is not None:
        manifest = cc_switch.to_manifest()
        # Compact label JSON — keep the OCI label small and stable-shaped.
        label_manifest = json.dumps(
            {
                "schema": manifest["schema"],
                "channel": manifest["channel"],
                "version": manifest["version"],
                "commit": manifest["commit"],
                "asset_sha256": manifest["asset_sha256"],
                "asset_name": manifest["asset_name"],
                "source": manifest["source"],
            },
            separators=(",", ":"),
        )
        cc_kwargs = {
            "cc_switch_version": cc_switch.tag,
            "cc_switch_commit": cc_switch.commit,
            "cc_switch_asset_url": cc_switch.asset_url,
            "cc_switch_asset_sha256": cc_switch.asset_sha256,
            "cc_switch_asset_name": cc_switch.asset_name,
            "cc_switch_manifest": label_manifest,
        }

    return BuildPlan(
        tag=tag,
        root=str(root),
        dockerfile=dockerfile,
        no_cache=no_cache,
        pull=pull,
        build_arg_use_cn_mirror=build_env.use_cn_mirror,
        build_arg_node_image=selected_node_image,
        dry_run=dry_run,
        **cc_kwargs,
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
    """Stage 8b: resolved cc-switch summary (version/sha256/source/...) and
    the manifest file path — the reproducibility receipt for the build."""
    cc_switch: Dict[str, Any] = field(default_factory=dict)
    cc_switch_manifest_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image_tag": self.image_tag,
            "dry_run": self.dry_run,
            "executed": self.executed,
            "docker_argv": list(self.docker_argv),
            "docker_exit_code": self.docker_exit_code,
            "cc_switch": dict(self.cc_switch),
            "cc_switch_manifest_path": self.cc_switch_manifest_path,
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
    cc_switch_summary: Optional[Dict[str, Any]] = None,
    cc_switch_manifest_path: str = "",
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
        cc_switch_summary / cc_switch_manifest_path: Stage 8b resolver facts
            surfaced in BuildResult (and thus in error payloads too).

    Returns:
        BuildResult with outcome data.

    Raises:
        CliError: with ``data`` field carrying full BuildResult.to_dict().
    """
    exec_ = executor or RealDockerExecutor()

    if cc_switch_summary is None and plan.cc_switch_version:
        # Derive from the plan's label manifest so error payloads still carry
        # the pin even when the caller passed no explicit summary.
        try:
            cc_switch_summary = json.loads(plan.cc_switch_manifest)
        except json.JSONDecodeError:
            cc_switch_summary = {"version": plan.cc_switch_version}

    result = BuildResult(
        image_tag=plan.tag,
        docker_argv=list(plan.docker_argv),
        dry_run=plan.dry_run,
        executed=False,
        cc_switch=dict(cc_switch_summary or {}),
        cc_switch_manifest_path=cc_switch_manifest_path,
    )

    # --- emit start event ---
    # v2.1.7 S4 (Gate-S4): build.start carries the full-log path — the raw
    # docker output lands there while the UI keeps only a bounded tail.
    build_log_path = _open_build_log() if emitter is not None else None
    if emitter is not None:
        emitter.emit("build.start", data={
            "image_tag": plan.tag,
            "log_path": str(build_log_path) if build_log_path else None,
        })

    # --- dry-run: zero docker calls ---
    if plan.dry_run:
        if emitter is not None:
            emitter.emit("build.plan", data={
                "docker_argv": result.docker_argv,
                "dry_run": True,
                "cc_switch": result.cc_switch,
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
    image_exists = inspect_result.status == ImageInspectStatus.EXISTS
    if image_exists and streaming and emitter is None:
        # Text mode: warn user about existing image
        _sys.stderr.write(f"\n⚠️  Image already exists: {plan.tag}\n")
        _sys.stderr.write("   Building will replace it (may create dangling <none> images).\n")
        _sys.stderr.write("   Tip: Use 'docker rmi {tag}' before build, or use a different tag.\n\n")
        _sys.stderr.flush()

    # --- plan event (non-dry-run) ---
    if emitter is not None:
        emitter.emit("build.plan", data={
            "docker_argv": result.docker_argv,
            "image_exists": image_exists,
            "cc_switch": result.cc_switch,
            # Gate-S4: Dockerfile instruction count as candidate step_total
            # metadata; build.progress only trusts what the output maps.
            "step_total": _dockerfile_instruction_count(plan),
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
    elif emitter is not None:
        # --events: stream docker output as real-time build.output events and
        # (v2.1.7 S4, Gate-S4) derive structured build.progress updates from
        # the SAME bytes — the emitter is the only progress fact source; the
        # UI never parses build.output. Raw chunks also append to the
        # build.start log file.
        progress = BuildProgressParser(
            context_total_bytes=_previous_context_total(build_log_path)
        )

        def _on_chunk(stream: str, chunk: str) -> None:
            if build_log_path is not None:
                try:
                    with open(build_log_path, "a", encoding="utf-8", errors="replace") as _lf:
                        _lf.write(chunk)
                except OSError:
                    pass  # logging must never break the build
            emitter.emit("build.output", data={"stream": stream, "chunk": chunk})
            for upd in progress.feed(chunk):
                emitter.emit("build.progress", data=asdict(upd))

        try:
            proc = exec_.run_streaming_captured(argv, _on_chunk)
        except KeyboardInterrupt:
            # Cancel: the executor already killpg'd the docker child. Emit the
            # terminal build.cancelled with a resource summary and exit 130
            # (bypasses main.py's generic handler so we control the payload).
            emitter.emit_terminal("build.cancelled", 130, extra_data={
                "image_tag": plan.tag,
                "docker_exit_code": None,
                "reason": "cancelled",
            })
            _sys.exit(130)
        result.docker_exit_code = proc.exit_code
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
        # --format json: capture, forward docker output to stderr (stdout pure).
        proc = exec_.run_captured(argv)
        result.docker_exit_code = proc.exit_code
        result.executed = True

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

    # --- success: main.py emits the build.complete terminal event ---
    return result
