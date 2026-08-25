"""Domain models for AISC CLI."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Core enums / constants
# ---------------------------------------------------------------------------

class CheckStatus:
    """Status values for a single doctor check."""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


class RuntimeErrorCode:
    """Stable error codes for runtime operations.

    Aligned with docs/rfc/aisc-cli-v1.md §4.1.
    """
    DOCKER_UNAVAILABLE = "AISC_ERR_DOCKER_UNAVAILABLE"
    RUNTIME_CONFLICT = "AISC_ERR_RUNTIME_CONFLICT"
    INVALID_RUNTIME_ID = "AISC_ERR_INVALID_RUNTIME_ID"
    RUNTIME_OPERATION_FAILED = "AISC_ERR_RUNTIME_OPERATION_FAILED"
    WORKSPACE_INVALID = "AISC_ERR_WORKSPACE_INVALID"
    IMAGE_NOT_FOUND = "AISC_ERR_IMAGE_NOT_FOUND"
    NETWORK_INVALID = "AISC_ERR_NETWORK_INVALID"
    SCOPE_INVALID = "AISC_ERR_SCOPE_INVALID"
    # Session-specific codes (S0.3)
    SESSION_NOT_FOUND = "AISC_ERR_SESSION_NOT_FOUND"
    SESSION_FAILED = "AISC_ERR_SESSION_FAILED"
    RUNTIME_NOT_RUNNING = "AISC_ERR_RUNTIME_NOT_RUNNING"
    INVALID_SESSION_ID = "AISC_ERR_INVALID_SESSION_ID"
    INVALID_AGENT = "AISC_ERR_INVALID_AGENT"
    # Provider status codes (S0.4)
    PROVIDER_STATUS_FAILED = "AISC_ERR_PROVIDER_STATUS_FAILED"
    # Agent Artifact codes (Stage 3, ART-02)
    ARTIFACT_INVALID = "AISC_ERR_ARTIFACT_INVALID"
    ARTIFACT_NOT_FOUND = "AISC_ERR_ARTIFACT_NOT_FOUND"
    # Extended codes: STATE_LOCK_TIMEOUT is registered in RFC §4.1 (exit 17);
    # the rest are extended codes not in the RFC exit-code table.
    RUNTIME_NOT_FOUND = "AISC_ERR_RUNTIME_NOT_FOUND"
    STATE_LOCK_TIMEOUT = "AISC_ERR_STATE_LOCK_TIMEOUT"
    RUNTIME_UNHEALTHY = "AISC_ERR_RUNTIME_UNHEALTHY"
    CONTAINER_NOT_FOUND = "AISC_ERR_CONTAINER_NOT_FOUND"


class RuntimeExitCode:
    """Exit codes for runtime operations.

    Uses RFC-compliant exit codes. New runtime-specific codes use 14+.
    Aligned with docs/rfc/aisc-cli-v1.md §4.1.
    """
    SUCCESS = 0
    GENERAL_ERROR = 1
    USAGE_ERROR = 2
    DOCKER_UNAVAILABLE = 3  # Reuses existing AISC_EXIT_DOCKER_UNAVAILABLE
    # 4 = AISC_EXIT_BUILD_FAILED (reserved by RFC)
    IMAGE_NOT_FOUND = 5  # AISC_EXIT_IMAGE_NOT_FOUND (reserved by RFC)
    # 6 = AISC_EXIT_CONFIG_INVALID (reserved by RFC)
    PERMISSION_DENIED = 9
    # New runtime-specific exit codes (14+, registered in RFC)
    RUNTIME_CONFLICT = 14           # AISC_EXIT_RUNTIME_CONFLICT
    INVALID_RUNTIME_ID = 15         # AISC_EXIT_INVALID_RUNTIME_ID
    RUNTIME_OPERATION_FAILED = 16   # AISC_EXIT_RUNTIME_OPERATION_FAILED
    STATE_LOCK_TIMEOUT = 17         # AISC_EXIT_STATE_LOCK_TIMEOUT
    # Session-specific exit codes (S0.3, registered in RFC §4.1)
    SESSION_NOT_FOUND = 18          # AISC_EXIT_SESSION_NOT_FOUND
    SESSION_FAILED = 19             # AISC_EXIT_SESSION_FAILED
    RUNTIME_NOT_RUNNING = 20        # AISC_EXIT_RUNTIME_NOT_RUNNING
    # Provider status exit code (S0.4)
    PROVIDER_STATUS_FAILED = 21     # AISC_EXIT_PROVIDER_STATUS_FAILED


# ---------------------------------------------------------------------------
# Version info
# ---------------------------------------------------------------------------

# Workbench capability negotiation (05-cli-gui-contract.md §四).
# Advertised by ``aisc version --format json`` so the Workbench gates UI on
# what this CLI actually implements -- it must not guess from the version
# string. Add a key here as each capability ships.
WORKBENCH_CAPABILITIES = {
    "runtime": "aisc.runtime/v1",               # S0.2
    "session": "aisc.session/v1",               # S0.3
    "providerStatus": "aisc.provider-status/v1",  # S0.4
    "buildEvents": "aisc.build-events/v1",      # S0.5
    "runtimeServices": "aisc.runtime-services/v1",  # svc-2 (web gateway)
}


@dataclass
class VersionInfo:
    """Structured version information gathered from the environment.

    Six fixed keys per RFC; unknown values are ``None``.
    """

    cli_version: str
    python_version: str
    bundle_version: Optional[str] = None
    declared_claude_version: Optional[str] = None
    image_version: Optional[str] = None
    contract_version: Optional[str] = None

    def to_dict(self) -> dict:
        """Return RFC-compliant dict with 6 fixed keys + Workbench capabilities."""
        return {
            "cli_version": self.cli_version,
            "bundle_version": self.bundle_version,
            "contract_version": self.contract_version,
            "image_version": self.image_version,
            "claude_version": self.declared_claude_version,
            "python_version": self.python_version,
            "capabilities": WORKBENCH_CAPABILITIES,
        }

    def to_text(self) -> str:
        lines = [
            f"AISC CLI version  : {self.cli_version}",
            f"Python version     : {self.python_version}",
        ]
        if self.bundle_version is not None:
            lines.append(f"Bundle version     : {self.bundle_version}")
        else:
            lines.append("Bundle version     : (not found)")
        if self.image_version is not None:
            lines.append(f"Image version      : {self.image_version}")
        if self.contract_version is not None:
            lines.append(f"Contract version   : {self.contract_version}")
        if self.declared_claude_version is not None:
            lines.append(f"Claude Code version: {self.declared_claude_version}")
        else:
            lines.append("Claude Code version: (not found)")
        if WORKBENCH_CAPABILITIES:
            lines.append("Capabilities       : " + ", ".join(WORKBENCH_CAPABILITIES.keys()))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Result of a single doctor check."""

    name: str
    status: str  # pass / warn / fail / skip
    message: str = ""
    detail: Optional[str] = None
    hint: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "status": self.status, "message": self.message}
        if self.detail is not None:
            d["detail"] = self.detail
        if self.hint is not None:
            d["hint"] = self.hint
        return d


@dataclass
class DoctorReport:
    """Full doctor report containing all checks and a summary."""

    checks: List[CheckResult] = field(default_factory=list)
    exit_code: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def summary(self) -> dict:
        passed = sum(1 for c in self.checks if c.status == CheckStatus.PASS)
        warnings = sum(1 for c in self.checks if c.status == CheckStatus.WARN)
        failures = sum(1 for c in self.checks if c.status == CheckStatus.FAIL)
        skipped = sum(1 for c in self.checks if c.status == CheckStatus.SKIP)
        return {
            "passed": passed,
            "warnings": warnings,
            "failures": failures,
            "skipped": skipped,
        }

    def to_dict(self) -> dict:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "summary": self.summary,
        }

    def add_check(self, check: CheckResult) -> None:
        self.checks.append(check)


# ---------------------------------------------------------------------------
# CLI error for controlled exits
# ---------------------------------------------------------------------------

@dataclass
class CliError(Exception):
    """Controlled CLI error with exit code, stable error code, and optional
    structured outcome data for JSON envelope / events terminal."""

    message: str
    exit_code: int = 1
    error_code: str = "AISC_ERR_GENERAL"
    hint: Optional[str] = None
    data: Optional[Dict[str, Any]] = None  # structured outcome preserved on failure


# ---------------------------------------------------------------------------
# Process result (for adapter)
# ---------------------------------------------------------------------------

@dataclass
class ProcessResult:
    """Result of a subprocess execution."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    command_not_found: bool = False


# ---------------------------------------------------------------------------
# Docker preflight result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DockerPreflightResult:
    """Result of Docker availability preflight check."""

    docker_path: str = ""
    available: bool = False
    reason: str = ""  # "ok", "cli_not_found", "daemon_unreachable", "permission_denied"

    @property
    def exit_code(self) -> int:
        """Map preflight result to AISC exit code."""
        if self.available:
            return 0
        if self.reason == "permission_denied":
            return 9  # AISC_EXIT_PERMISSION_DENIED
        return 3  # AISC_EXIT_DOCKER_UNAVAILABLE

    @property
    def error_code(self) -> str:
        """Map preflight result to AISC error code."""
        if self.available:
            return ""
        if self.reason == "permission_denied":
            return "AISC_ERR_PERMISSION_DENIED"
        return "AISC_ERR_DOCKER_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Docker image inspect — structured result
# ---------------------------------------------------------------------------

class ImageInspectStatus:
    """Classification of a docker image inspect call."""
    EXISTS = "exists"
    MISSING = "missing"
    DOCKER_UNAVAILABLE = "docker_unavailable"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True)
class ImageInspectResult:
    """Structured result of ``docker image inspect``.

    Only ``status == MISSING`` maps to AISC_EXIT_IMAGE_NOT_FOUND(5);
    other non-ok statuses map to DOCKER_UNAVAILABLE(3), PERMISSION_DENIED(9),
    or GENERAL(1) depending on the underlying cause.

    ``image_id`` (容器随镜像同步更新, KI-4 挂账) carries the content-addressed
    ``.Id`` on the EXISTS path — empty when unparseable or non-ok; existence
    remains the primary question, the ID is opportunistic metadata.
    """

    status: str = ImageInspectStatus.ERROR  # one of ImageInspectStatus
    image: str = ""
    message: str = ""
    image_id: str = ""


# ---------------------------------------------------------------------------
# Docker build / run plans (immutable, no side effects)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BuildPlan:
    """Immutable build specification — argv, tag, flags, root."""

    tag: str = "super-claude:latest"
    root: str = ""
    dockerfile: str = ""
    no_cache: bool = False
    pull: bool = False
    build_arg_use_cn_mirror: str = "1"
    build_arg_node_image: str = "node:20-slim"
    dry_run: bool = False
    # Stage 8 (CS-01/CS-02): the resolver-pinned cc-switch release. Empty
    # strings = manual/legacy `docker build` (Dockerfile ARG fallback path,
    # documented as non-reproducible); `aisc build` always injects these.
    cc_switch_version: str = ""
    cc_switch_commit: str = ""
    cc_switch_asset_url: str = ""
    cc_switch_asset_sha256: str = ""
    cc_switch_asset_name: str = ""
    cc_switch_manifest: str = ""  # compact JSON for the org.aisc.build-manifest label

    @property
    def docker_argv(self) -> list:
        """Return the ``docker build`` argv list (without ``docker``)."""
        argv = ["build"]
        if self.no_cache:
            argv.append("--no-cache")
        if self.pull:
            argv.append("--pull")
        argv.extend([
            "--build-arg", f"USE_CN_MIRROR={self.build_arg_use_cn_mirror}",
            "--build-arg", f"NODE_IMAGE={self.build_arg_node_image}",
        ])
        if self.cc_switch_version:
            argv.extend([
                "--build-arg", f"CC_SWITCH_RESOLVED_VERSION={self.cc_switch_version}",
                "--build-arg", f"CC_SWITCH_RELEASE_COMMIT={self.cc_switch_commit}",
                "--build-arg", f"CC_SWITCH_ASSET_URL={self.cc_switch_asset_url}",
                "--build-arg", f"CC_SWITCH_ASSET_SHA256={self.cc_switch_asset_sha256}",
                "--build-arg", f"CC_SWITCH_ASSET_NAME={self.cc_switch_asset_name}",
                "--build-arg", f"CC_SWITCH_BUILD_MANIFEST={self.cc_switch_manifest}",
            ])
        argv.extend([
            "-f", self.dockerfile,
            "-t", self.tag,
            self.root,
        ])
        return argv


@dataclass(frozen=True)
class RunPlan:
    """Immutable run specification — argv, image, workspace, network, flags."""

    image: str = "super-claude:latest"
    workspace: str = ""
    name: str = ""
    network: str = "direct"
    dry_run: bool = False
    interactive: bool = True  # True for text mode, False for json/events
    non_interactive: bool = False  # --non-interactive: omit -it, add env vars, DEVNULL stdin
    proxy_config: str = ""    # host path to .claude/mihomo/config.yaml (when network=proxy)
    label: str = ""           # optional container label for multi-container addressing
    keep_alive: bool = False  # --keep-alive: omit --rm, keep container after exit
    # Stage 7 (DATA-01): data-root workspaces/<hash>/ dir; when set (and the
    # run is project-scoped) the agent config dirs mount from here instead
    # of being copied into the workspace.
    agent_state_root: str = ""

    @property
    def docker_argv(self) -> list:
        """Return the ``docker run`` argv list (without ``docker``).

        - interactive=True  → includes ``-it``
        - interactive=False → omits ``-it``
        - non_interactive=True → also omits ``-it``, adds AISC_NON_INTERACTIVE + CLAUDE_SCOPE
        - network=proxy     → adds NET_ADMIN, TUN device, mihomo config mount
        - keep_alive=False  → includes ``--rm`` (default: remove on exit)
        - keep_alive=True   → omits ``--rm`` (persist after exit)
        - agent_state_root  → project-scope mounts: claude/codex/cc-switch
                          config + daemon runtime state from the data root
        - Runs as the image default user (root) so bind-mounted WSL2 files remain writable
        """
        argv = ["run"]

        # Only add --rm if keep_alive is False (default behavior)
        if not self.keep_alive:
            argv.append("--rm")

        # For keep_alive mode, use -d (detached) instead of -it to prevent container exit on client disconnect
        if self.keep_alive and self.interactive and not self.non_interactive:
            argv.append("-d")
        elif self.interactive and not self.non_interactive:
            argv.append("-it")
        argv.extend([
            "-e", "TERM=xterm-256color",
            "--name", self.name,
            "-v", f"{self.workspace}:/root/app",
        ])
        if self.agent_state_root:
            base = self.agent_state_root.rstrip("/\\")
            argv.extend([
                "-v", f"{base}/claude:/root/.claude",
                "-v", f"{base}/codex:/root/.codex",
                "-v", f"{base}/cc-switch:/root/.cc-switch",
                "-v", f"{base}/runtime:/root/.local/state/cc-switch",
            ])
        if self.non_interactive:
            argv.extend([
                "-e", "AISC_NON_INTERACTIVE=1",
                "-e", "CLAUDE_SCOPE=project",
            ])
        if self.network == "proxy":
            argv.extend([
                "--cap-add=NET_ADMIN",
                "--device", "/dev/net/tun",
            ])
            if self.proxy_config:
                argv.extend([
                    "-v", f"{self.proxy_config}:/etc/mihomo/config.yaml:ro",
                ])
        argv.append(self.image)
        return argv


# ---------------------------------------------------------------------------
# Runtime snapshot — structured runtime state
# ---------------------------------------------------------------------------

@dataclass
class RuntimeSnapshot:
    """Structured runtime state matching lifecycle contract.

    Combines registry metadata with live Docker state.
    See docs/gui-planning/03-lifecycle-contract.md for state machine.
    """
    runtime_id: str = ""           # UUID v4 (provided by Workbench)
    state: str = "unknown"         # unknown, not_found, starting, running, stopping, stopped, removing
    workspace: str = ""            # canonical absolute path
    image: str = ""                # image:tag
    network: str = "direct"        # direct, proxy
    scope: str = "project"         # project, temporary
    owner: str = ""                # who created this runtime (e.g., "workbench")
    config_fingerprint: str = ""   # sha256:<hash> of canonical config
    container_name: str = ""       # Docker container name (for legacy compat)
    container_id: str = ""         # Docker container ID (from inspect)
    label: str = ""                # optional user label

    # Registry reconciliation
    registry_state: str = "unknown"  # registered, missing, unknown

    # Timestamps
    created_at: str = ""           # ISO timestamp or numeric (backward compat)
    started_at: str = ""           # ISO timestamp from Docker
    observed_at: str = ""          # ISO timestamp when this snapshot was taken

    # Staleness indicator
    stale: bool = False            # True if observation is potentially outdated

    # svc-2 (web gateway): loopback gateway reachability per
    # aisc.runtime-services/v1; None = not observed (list path / old CLI) —
    # consumers treat absent as unavailable, never as a parse failure.
    web_access: Optional[Dict[str, Any]] = None

    # Last operation error (None if last operation succeeded)
    last_operation_error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict matching CLI contract."""
        result = {
            "runtime_id": self.runtime_id,
            "state": self.state,
            "config": {
                "workspace": self.workspace,
                "image": self.image,
                "network": self.network,
                "scope": self.scope,
            },
            "owner": self.owner,
            "config_fingerprint": self.config_fingerprint,
            "container_name": self.container_name,
            "container_id": self.container_id,
            "registry_state": self.registry_state,
            "observed_at": self.observed_at,
            "stale": self.stale,
        }

        # Optional fields
        if self.label:
            result["label"] = self.label
        if self.created_at:
            result["created_at"] = self.created_at
        if self.started_at:
            result["started_at"] = self.started_at
        if self.web_access is not None:
            result["web_access"] = self.web_access
        if self.last_operation_error:
            result["last_operation_error"] = self.last_operation_error

        return result


# ---------------------------------------------------------------------------
# Session constants and models (S0.3)
# ---------------------------------------------------------------------------

class SessionAgent:
    """Controlled agent enum for ``aisc session open``."""
    CLAUDE = "claude"
    CODEX = "codex"
    BASH = "bash"
    CC_SWITCH = "cc-switch"

    ALL = (CLAUDE, CODEX, BASH, CC_SWITCH)


class SessionState:
    """Session lifecycle states per 03-lifecycle-contract.md §5.1."""
    STARTING = "starting"
    RUNNING = "running"
    CLOSING = "closing"
    EXITED = "exited"
    FAILED = "failed"
    DISCONNECTED = "disconnected"


class SessionExitReason:
    """Reasons for session termination per 03-lifecycle-contract.md §5.1."""
    PROCESS_EXIT = "process_exit"
    USER_CLOSE = "user_close"
    RUNTIME_STOP = "runtime_stop"
    TRANSPORT_ERROR = "transport_error"
    WORKBENCH_CRASH_CLEANUP = "workbench_crash_cleanup"


@dataclass
class SessionRecord:
    """Session metadata stored in-container at ``/run/aisc/sessions/<id>.json``.

    Per contract 6.1: 0600, atomic write, no argv/env/output. Used only
    for diagnostics and crash cleanup; never claims PTY recoverability.
    """

    schema_version: str = "aisc.session/v1"
    runtime_id: str = ""
    session_id: str = ""
    agent: str = ""
    state: str = SessionState.STARTING
    pid: Optional[int] = None
    pgid: Optional[int] = None
    start_ticks: Optional[int] = None
    started_at: str = ""
    finished_at: str = ""
    exit_code: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runtime_id": self.runtime_id,
            "session_id": self.session_id,
            "agent": self.agent,
            "state": self.state,
            "pid": self.pid,
            "pgid": self.pgid,
            "start_ticks": self.start_ticks,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Provider status model (S0.4)
# ---------------------------------------------------------------------------

@dataclass
class ProviderStatus:
    """Observable provider status for one agent (05-cli-gui-contract.md §七).

    Secret-free: only routing/auth metadata, never keys/tokens/cookies.
    """

    runtime_id: str
    agent: str
    provider_id: str
    provider_name: str
    route_mode: str
    auth_status: str
    observed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtime_id": self.runtime_id,
            "agent": self.agent,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "route_mode": self.route_mode,
            "auth_status": self.auth_status,
            "observed_at": self.observed_at,
        }
