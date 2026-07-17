"""Domain models for AISC CLI."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import List, Optional


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
    """Controlled CLI error with exit code and stable error code."""

    message: str
    exit_code: int = 1
    error_code: str = "AISC_ERR_GENERAL"
    hint: Optional[str] = None


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
