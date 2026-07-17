"""Main CLI entry point — argument parsing, command dispatch, output formatting.

``aisc version`` and ``aisc doctor`` commands.
``python -m aisc`` and console_script ``aisc`` are both supported.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from aisc import __version__
from aisc.cli.output import (
    build_envelope,
    build_error,
    emit_json,
    emit_json_usage_error,
    print_doctor_text,
)
from aisc.domain.models import CliError, DoctorReport, VersionInfo


# ---------------------------------------------------------------------------
# Custom argument parser — JSON-aware error handling
# ---------------------------------------------------------------------------

class _AiscArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that respects ``--format json`` when reporting errors."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)
        self._aisc_format: Optional[str] = None
        self._aisc_command: str = "aisc"

    def error(self, message: str) -> None:  # type: ignore[override]
        if self._aisc_format == "json":
            emit_json_usage_error(
                command=self._aisc_command or "aisc",
                version=__version__,
                message=message,
            )
            sys.exit(2)
        else:
            super().error(message)


# ---------------------------------------------------------------------------
# Parser setup
# ---------------------------------------------------------------------------

def _add_global_args(p: argparse.ArgumentParser, *, is_subparser: bool = False) -> None:
    """Add global options."""
    default_val = argparse.SUPPRESS if is_subparser else "text"
    p.add_argument(
        "--format",
        choices=["text", "json"],
        default=default_val,
        help="Output format (default: text)",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS if is_subparser else False,
        help="Disable ANSI color output",
    )
    p.add_argument(
        "--aisc-root",
        type=str,
        default=argparse.SUPPRESS if is_subparser else None,
        help="Path to AISC repository root",
    )
    p.add_argument(
        "--events",
        action="store_true",
        default=argparse.SUPPRESS if is_subparser else False,
        help=argparse.SUPPRESS,
    )


def _build_parser() -> _AiscArgumentParser:
    """Build the top-level argument parser."""
    parser = _AiscArgumentParser(
        prog="aisc",
        description="AISC CLI — Super Claude workstation management",
    )
    _add_global_args(parser)

    sub = parser.add_subparsers(dest="command", title="commands")

    vp = sub.add_parser("version", help="Show version information", allow_abbrev=False)
    _add_global_args(vp, is_subparser=True)

    dp = sub.add_parser("doctor", help="Run environment diagnostics", allow_abbrev=False)
    _add_global_args(dp, is_subparser=True)

    return parser


# ---------------------------------------------------------------------------
# JSON format detection from raw argv
# ---------------------------------------------------------------------------

def _detect_json_format(argv: List[str]) -> bool:
    """Check whether ``--format json`` or ``--format=json`` appears in *argv*."""
    for i, arg in enumerate(argv):
        if arg == "--format" and i + 1 < len(argv) and argv[i + 1] == "json":
            return True
        if arg == "--format=json":
            return True
    return False


def _detect_command(argv: List[str]) -> Optional[str]:
    """Extract the recognised subcommand from raw *argv* for error messages.

    Returns the first positional arg that matches a known command, or None.
    """
    known = {"version", "doctor"}
    for arg in argv:
        if arg in known:
            return arg
    return None


# ---------------------------------------------------------------------------
# Arg post-processing: resolve last-wins --format
# ---------------------------------------------------------------------------

def _resolve_format(args: argparse.Namespace, argv: List[str]) -> str:
    """Resolve effective format value: last explicit --format wins.

    When both parent and subparser define --format with SUPPRESS,
    the namespace can have setattr overwritten multiple times.
    We scan raw *argv* to determine the last explicit setting.
    """
    last = "text"  # default
    for i, arg in enumerate(argv):
        if arg == "--format" and i + 1 < len(argv):
            val = argv[i + 1]
            if val in ("text", "json"):
                last = val
        elif arg.startswith("--format="):
            val = arg.split("=", 1)[1]
            if val in ("text", "json"):
                last = val
    return last


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def _cmd_version(args: argparse.Namespace) -> VersionInfo:
    """Gather version info."""
    from aisc.application.version import gather_version_info
    from aisc.application.resources import _RootSourceError

    try:
        info = gather_version_info(explicit_root=args.aisc_root, cwd=Path.cwd())
    except _RootSourceError as exc:
        raise CliError(
            message=str(exc),
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
        ) from exc
    except Exception as exc:
        raise CliError(
            message=str(exc),
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
        ) from exc
    return info


def _cmd_doctor(args: argparse.Namespace) -> Tuple[Dict[str, Any], DoctorReport]:
    """Run doctor checks and return (data_dict, report)."""
    from aisc.application.doctor import run_doctor
    from aisc.application.resources import locate_aisc_root, _RootSourceError

    root = None
    root_error: Optional[str] = None
    try:
        root = locate_aisc_root(explicit_root=args.aisc_root)
    except _RootSourceError as exc:
        root_error = str(exc)
    except Exception as exc:
        root_error = str(exc)

    report = run_doctor(root=root, root_error=root_error)

    data: Dict[str, Any] = {"host": report.to_dict(), "container": None}
    return data, report


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> None:
    """Main CLI entry point."""
    parser = _build_parser()
    args_list = list(argv) if argv is not None else sys.argv[1:]

    # Pre-detect JSON format and command for error messages
    json_requested = _detect_json_format(args_list)
    cmd_hint = _detect_command(args_list) or "aisc"
    parser._aisc_format = "json" if json_requested else None
    parser._aisc_command = cmd_hint

    try:
        args = parser.parse_args(args_list)
    except SystemExit:
        raise

    # Resolve effective format (last explicit --format wins)
    effective_format = _resolve_format(args, args_list)
    parser._aisc_format = effective_format
    # Keep command hint set; update if we have an actual command now
    if getattr(args, "command", None):
        parser._aisc_command = args.command

    # --events is not implemented
    if getattr(args, "events", False):
        if effective_format == "json":
            emit_json_usage_error(
                command=args.command or cmd_hint,
                version=__version__,
                error_code="AISC_ERR_USAGE",
                message="--events is not implemented in this version",
            )
            sys.exit(2)
        else:
            parser.error("--events is not implemented in this version")

    # Require a command
    if not getattr(args, "command", None):
        if effective_format == "json":
            emit_json_usage_error(
                command=cmd_hint,
                version=__version__,
                message="No command specified",
            )
            sys.exit(2)
        else:
            parser.print_help()
            sys.exit(2)

    use_color = sys.stdout.isatty() and not getattr(args, "no_color", False)
    # use getattr for aisc-root (may be SUPPRESSed)
    aisc_root = getattr(args, "aisc_root", None)
    if aisc_root is argparse.SUPPRESS:
        aisc_root = None

    # Execute command
    data: Any = None
    report: Optional[DoctorReport] = None
    exit_code = 0
    errors: List[Dict[str, Any]] = []
    version_info: Optional[VersionInfo] = None

    try:
        if args.command == "version":
            version_info = _cmd_version(args)
            data = version_info.to_dict()
        elif args.command == "doctor":
            data, report = _cmd_doctor(args)
            exit_code = report.exit_code
            if report.error_code:
                errors.append(
                    build_error(report.error_code, report.error_message or "")
                )
        else:
            if effective_format == "json":
                emit_json_usage_error(
                    command=args.command,
                    version=__version__,
                    message=f"Unknown command: {args.command}",
                )
            else:
                parser.error(f"Unknown command: {args.command}")
            sys.exit(2)
            return

    except CliError as exc:
        if effective_format == "json":
            envelope = build_envelope(
                command=args.command,
                exit_code=exc.exit_code,
                version=__version__,
                data=None,
                errors=[build_error(exc.error_code, exc.message, exc.hint)],
            )
            emit_json(envelope)
        else:
            print(f"Error: {exc.message}", file=sys.stderr)
        sys.exit(exc.exit_code)
        return

    # Output
    if effective_format == "json":
        envelope = build_envelope(
            command=args.command,
            exit_code=exit_code,
            version=__version__,
            data=data,
            errors=errors,
        )
        emit_json(envelope)
    else:
        if args.command == "version":
            assert version_info is not None
            print(version_info.to_text())
        elif args.command == "doctor":
            assert report is not None
            print_doctor_text(report, use_color=use_color)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
