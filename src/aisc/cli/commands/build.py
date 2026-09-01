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
    node_image_mirrors: tuple = ()


def _parse_build_env(root: Path) -> _BuildEnv:
    """Parse build-relevant values from config/versions.env."""
    env = _parse_versions_env(root)
    use_cn = env.get("USE_CN_MIRROR", "1")
    node_image = env.get("NODE_IMAGE", "")
    node_image_cn = env.get("NODE_IMAGE_CN", "")
    # T8a: comma-separated registry prefixes for the pre-pull chain.
    mirrors = tuple(
        m.strip().rstrip("/")
        for m in env.get("NODE_IMAGE_MIRRORS", "").split(",")
        if m.strip()
    )
    return _BuildEnv(
        use_cn_mirror=use_cn, node_image=node_image,
        node_image_cn=node_image_cn, node_image_mirrors=mirrors,
    )


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
        node_image_mirrors=build_env.node_image_mirrors,
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

# T8a (2.1.9 D-9): host-side base-image pre-pull through a mirror chain.
# Evidence: nairong's first build crawled docker.1ms.run for ~10 minutes and
# was abandoned — buildkit's FROM has no mirror fallback, no retry, no
# guidance. aisc build therefore pre-pulls the base itself: local hit →
# zero docker calls; otherwise walk the chain (selected image first, then
# NODE_IMAGE_MIRRORS entries), `docker tag` the first success to the bare
# local name so buildkit hits the local store, and only fail (with guidance)
# when every mirror failed.
_PULL_TIMEOUT_S = 600.0


def _base_image_candidates(plan: "BuildPlan") -> list:
    """Pull candidates in priority order: the plan's selected image, then
    each mirror prefix joined with the bare image name (deduped)."""
    selected = plan.build_arg_node_image
    bare = selected.rsplit("/", 1)[-1]
    seen = {selected}
    out = [selected]
    for prefix in plan.node_image_mirrors:
        ref = f"{str(prefix).rstrip('/')}/{bare}"
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def _ensure_base_image(exec_, plan, emitter, streaming: bool) -> str:
    """Pre-pull the base image through the mirror chain.

    Returns the node image reference the build argv should use (the bare
    local name once tagged). Raises CliError (exit 4) when every candidate
    fails — with actionable guidance for mainland-network users.
    """
    from aisc.domain.models import ImageInspectStatus

    candidates = _base_image_candidates(plan)
    bare = candidates[0].rsplit("/", 1)[-1]

    def _say(line: str) -> None:
        if emitter is not None:
            emitter.emit("build.output", data={"stream": "stderr", "chunk": line})
        if streaming and emitter is None:
            _sys.stderr.write(line)
            _sys.stderr.flush()

    # Local store hit → buildkit needs no network at all.
    if exec_.inspect_image(bare).status == ImageInspectStatus.EXISTS:
        return bare

    for ref in candidates:
        _say(f"⬇️  基础镜像 try: {ref}\n")
        proc = exec_.run_captured(["pull", ref], timeout=_PULL_TIMEOUT_S)
        if proc.exit_code == 0:
            if ref == bare:
                return bare
            # Retag to the bare local name; if tagging fails, build directly
            # from the pulled (now local) reference instead of failing.
            if exec_.run_captured(["tag", ref, bare], timeout=30.0).exit_code == 0:
                return bare
            return ref

    raise CliError(
        message=(
            "基础镜像预拉失败（所有镜像源均不可达）：" + ", ".join(candidates) +
            "。可依次尝试：① Docker Desktop 设置里配置 registry-mirrors 后重试；"
            "② 手动 docker pull <任一镜像源>/node:20-slim 成功后重新构建；"
            "③ 切换到可直连 Docker Hub 的网络。"
        ),
        exit_code=4, error_code="AISC_ERR_BUILD_FAILED",
        data={"base_image_candidates": candidates},
    )


def _rewrite_node_image(argv: list, new_value: str) -> list:
    """Replace the NODE_IMAGE build-arg value in a docker build argv copy."""
    out = list(argv)
    for i, tok in enumerate(out):
        if tok == "--build-arg" and i + 1 < len(out) and out[i + 1].startswith("NODE_IMAGE="):
            out[i + 1] = f"NODE_IMAGE={new_value}"
            break
    return out


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

    # --- T8a: pre-pull the base image through the mirror chain (CN 网络兜底;
    # local hit is a zero-IPC no-op) and point the build at the local name ---
    effective_node_image = _ensure_base_image(exec_, plan, emitter, streaming)

    # --- execute docker build ---
    argv = _rewrite_node_image(plan.docker_argv, effective_node_image)
    result.docker_argv = argv  # error payloads carry the argv that actually ran

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
