"""System / process adapter — narrow interface for command execution."""

from __future__ import annotations

import subprocess
from typing import Protocol, List, Optional, runtime_checkable

from aisc.domain.models import ProcessResult


@runtime_checkable
class ProcessRunner(Protocol):
    """Protocol for running subprocess commands (testable via injection)."""

    def run(
        self,
        argv: List[str],
        timeout: Optional[float] = None,
    ) -> ProcessResult:
        """Execute *argv* and return a ``ProcessResult``."""
        ...


class RealProcessRunner:
    """Real subprocess runner — shell=False, text capture, timeout support.

    Uses ``encoding='utf-8'``, ``errors='replace'``.
    Catches ``FileNotFoundError`` → ``command_not_found``.
    Catches generic ``OSError`` → ``command_not_found`` (e.g. permission,
    broken symlink).
    ``subprocess.TimeoutExpired`` → ``timed_out``.
    """

    def run(
        self,
        argv: List[str],
        timeout: Optional[float] = None,
    ) -> ProcessResult:
        """Execute *argv* in a subprocess."""
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            return ProcessResult(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=proc.returncode,
            )
        except FileNotFoundError:
            return ProcessResult(
                stdout="",
                stderr=f"command not found: {argv[0] if argv else ''}",
                exit_code=-1,
                command_not_found=True,
            )
        except subprocess.TimeoutExpired:
            return ProcessResult(
                stdout="",
                stderr="command timed out",
                exit_code=-1,
                timed_out=True,
            )
        except OSError as exc:
            return ProcessResult(
                stdout="",
                stderr=f"command error: {exc}",
                exit_code=-1,
                command_not_found=True,
            )
