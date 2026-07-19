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


# ---------------------------------------------------------------------------
# Version info
# ---------------------------------------------------------------------------

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
        """Return RFC-compliant dict with 6 fixed keys in order."""
        return {
            "cli_version": self.cli_version,
            "bundle_version": self.bundle_version,
            "contract_version": self.contract_version,
            "image_version": self.image_version,
            "claude_version": self.declared_claude_version,
            "python_version": self.python_version,
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
    """

    status: str = ImageInspectStatus.ERROR  # one of ImageInspectStatus
    image: str = ""
    message: str = ""


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

    @property
    def docker_argv(self) -> list:
        """Return the ``docker run`` argv list (without ``docker``).

        - interactive=True  → includes ``-it``
        - interactive=False → omits ``-it``
        - non_interactive=True → also omits ``-it``, adds AISC_NON_INTERACTIVE + CLAUDE_SCOPE
        - network=proxy     → adds NET_ADMIN, TUN device, mihomo config mount
        """
        argv = ["run", "--rm"]
        if self.interactive and not self.non_interactive:
            argv.append("-it")
        argv.extend([
            "-e", "TERM=xterm-256color",
            "--name", self.name,
            "-v", f"{self.workspace}:/home/AISC/app",
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
