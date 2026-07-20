"""CLI output formatting — JSON envelope, human-readable text, and JSONL emitter."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# JSON envelope (RFC §2)
# ---------------------------------------------------------------------------

PROTOCOL = "aisc.cli/v1"


def _utc_now() -> str:
    """Return an ISO 8601 UTC timestamp string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_envelope(
    command: str,
    exit_code: int,
    version: str,
    data: Any = None,
    errors: Optional[List[Dict[str, Any]]] = None,
    *,
    run_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a complete JSON envelope per RFC §2.

    Parameters
    ----------
    command:
        Subcommand name (e.g. ``"version"``, ``"doctor"``).
    exit_code:
        Process exit code — must match ``sys.exit()``.
    version:
        CLI product version.
    data:
        Command-specific payload.  ``None`` is treated as ``null`` in JSON.
    errors:
        List of error objects.  ``None`` is treated as ``[]``.
    run_id:
        UUID v4.  Auto-generated when not provided.
    timestamp:
        ISO 8601 UTC string.  Auto-generated when not provided.
    """
    return {
        "meta": {
            "protocol": PROTOCOL,
            "command": command,
            "exit_code": exit_code,
            "timestamp": timestamp or _utc_now(),
            "version": version,
            "run_id": run_id or str(uuid.uuid4()),
        },
        "data": data,
        "errors": errors if errors is not None else [],
    }


def build_error(code: str, message: str, hint: Optional[str] = None) -> Dict[str, Any]:
    """Build a single error object (RFC §2.3)."""
    return {"code": code, "message": message, "hint": hint}


def emit_json(envelope: Dict[str, Any]) -> None:
    """Write *envelope* as JSON to stdout."""
    print(json.dumps(envelope, ensure_ascii=False))


def emit_json_usage_error(
    command: str,
    version: str,
    error_code: str = "AISC_ERR_USAGE",
    message: str = "Invalid command-line arguments",
) -> None:
    """Emit a JSON usage error envelope to stdout and ``sys.exit(2)``."""
    env = build_envelope(
        command=command,
        exit_code=2,
        version=version,
        data=None,
        errors=[build_error(error_code, message)],
    )
    emit_json(env)


# ---------------------------------------------------------------------------
# Human-readable text helpers
# ---------------------------------------------------------------------------

_ANSI_COLORS = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "reset": "\033[0m",
    "bold": "\033[1m",
}


def _maybe_style(text: str, style: str, use_color: bool) -> str:
    if not use_color:
        return text
    code = _ANSI_COLORS.get(style, "")
    reset = _ANSI_COLORS["reset"] if code else ""
    return f"{code}{text}{reset}"


def print_doctor_text(report: Any, use_color: bool = True) -> None:
    """Print a doctor report in human-readable format."""
    from aisc.domain.models import CheckStatus

    status_labels = {
        CheckStatus.PASS: _maybe_style("PASS", "green", use_color),
        CheckStatus.WARN: _maybe_style("WARN", "yellow", use_color),
        CheckStatus.FAIL: _maybe_style("FAIL", "red", use_color),
        CheckStatus.SKIP: "SKIP",
    }

    lines: List[str] = []
    lines.append(_maybe_style("=== AISC Doctor (host) ===", "bold", use_color))
    lines.append("")

    for check in report.checks:
        label = status_labels.get(check.status, check.status.upper())
        lines.append(f"  [{label}] {check.name}")
        if check.message:
            lines.append(f"         {check.message}")
        if check.detail:
            lines.append(f"         {check.detail}")
        if check.hint:
            lines.append(f"         Hint: {check.hint}")
        lines.append("")

    s = report.summary
    lines.append("--- Summary ---")
    lines.append(
        f"  Passed: {s['passed']}  Warnings: {s['warnings']}  "
        f"Failures: {s['failures']}  Skipped: {s['skipped']}"
    )
    if report.error_message:
        lines.append(f"  Error: {report.error_message}")

    for line in lines:
        print(line)


# ---------------------------------------------------------------------------
# JSONL Event Emitter (RFC §3)
# ---------------------------------------------------------------------------

class JsonlEmitter:
    """Emit JSONL event lines to stdout during long commands (build/run).

    Usage::

        emitter = JsonlEmitter(command="build")
        emitter.emit("build.start", data={"image_tag": "..."})
        # ... docker build ...
        emitter.emit("build.complete", data={"exit_code": 0}, terminal=True)

    Each emit() writes one JSON line to stdout, increments seq by 1,
    and enforces that ``terminal=True`` can only be called once as the
    final event.
    """

    def __init__(self, command: str, *, run_id: Optional[str] = None):
        self._command = command
        self._run_id = run_id or str(uuid.uuid4())
        self._seq = 0
        self._terminated = False

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def terminated(self) -> bool:
        """``True`` if a terminal event has already been emitted."""
        return self._terminated

    def emit(self, event_type: str, data: Dict[str, Any],
             *, terminal: bool = False) -> None:
        """Emit a single JSONL event line.

        Args:
            event_type: RFC event type, e.g. ``"build.start"``.
            data: Event-specific payload dict.
            terminal: ``True`` for the final terminating event only.
        """
        if self._terminated:
            raise RuntimeError(
                f"JSONL stream already terminated (last event was seq={self._seq})"
            )
        self._seq += 1
        event = {
            "protocol": PROTOCOL,
            "command": self._command,
            "run_id": self._run_id,
            "seq": self._seq,
            "type": event_type,
            "ts": _utc_now(),
            "data": data,
        }
        if terminal:
            self._terminated = True
        print(json.dumps(event, ensure_ascii=False))

    def emit_terminal(self, terminal_type: str, exit_code: int,
                      extra_data: Optional[Dict[str, Any]] = None) -> None:
        """Emit the terminal event with ``data.exit_code``."""
        data: Dict[str, Any] = dict(extra_data or {})
        data["exit_code"] = exit_code
        self.emit(terminal_type, data, terminal=True)
