"""``aisc serve`` — the long-lived remote channel (2.1.10 R1, D-7).

The Workbench (or any client) reaches a remote machine's aisc CLI over SSH
by spawning ``ssh <alias> aisc serve --stdio``: the serve process then speaks
newline-delimited JSON frames on stdio — the same "authenticated transport
is the SSH session" model as VS Code Remote-SSH. There is deliberately NO
token and NO listening socket in stdio mode (D-7); a future TCP mode must
re-open that decision.

Frame protocol v1 (see docs/plans/2.1.10-dev-plans/r1-serve-transport.md §2):

    serve -> client   {"type":"ready","serve_protocol":1,"cli_version":...}
    client -> serve   {"id":"u1","op":"version","args":[]}
    serve -> client   {"id":"u1","type":"result","ok":true,"envelope":{...}}
    serve -> client   {"type":"log","level":"info","line":"..."}   (diagnostics)

Lifecycle: stdin EOF, SIGINT or SIGTERM ends the loop (in-flight request is
allowed up to 3s to finish). Malformed lines and unknown ops answer with an
error result frame — the process never dies from bad input.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from aisc.cli.output import build_envelope
from aisc.domain.models import CliError

SERVE_PROTOCOL = 1

#: Grace period for an in-flight op when the loop is asked to stop (s).
SHUTDOWN_GRACE_SECONDS = 3.0


def _frame(line: str) -> Dict[str, Any]:
    return json.dumps(line, ensure_ascii=False, separators=(",", ":"))


def _log_frame(level: str, line: str) -> Dict[str, Any]:
    return {"type": "log", "level": level, "line": line}


# -- op dispatch ----------------------------------------------------------------
#
# Ops map straight onto the same application-layer code paths the one-shot
# CLI commands use (never argparse); each returns (data, exit_code, errors).
# serve ALWAYS answers with an envelope — stdout carries nothing else.


def _op_version(args: argparse.Namespace) -> Tuple[Any, int, List[Dict[str, Any]]]:
    from aisc.cli.main import _cmd_version

    return _cmd_version(args).to_dict(), 0, []


def _op_doctor(args: argparse.Namespace) -> Tuple[Any, int, List[Dict[str, Any]]]:
    from aisc.cli.main import _cmd_doctor

    data, report = _cmd_doctor(args, effective_format="json")
    # doctor's own exit code (0 ok / 3 docker-unavailable) rides the envelope
    # exactly as the one-shot CLI reports it.
    return data, report.exit_code, []


def _op_ps(args: argparse.Namespace) -> Tuple[Any, int, List[Dict[str, Any]]]:
    from aisc.cli.main import _cmd_ps

    return _cmd_ps(args, effective_format="json")


OPS: Dict[str, Callable[[argparse.Namespace], Tuple[Any, int, List[Dict[str, Any]]]]] = {
    "version": _op_version,
    "doctor": _op_doctor,
    "ps": _op_ps,
}

#: Ops that may not run while another op is executing — R1 is strictly
#: serial; the ``id`` field already exists so a concurrent executor can be
#: introduced later without a protocol change.


def _run_op(op: str, args: List[str]) -> Dict[str, Any]:
    """Execute one op and wrap it in a result frame (never raises)."""
    ns = argparse.Namespace(aisc_root=None)
    handler = OPS.get(op)
    if handler is None:
        return {
            "id": None,
            "type": "result",
            "ok": False,
            "error": f"unknown op {op!r} (known: {', '.join(sorted(OPS))})",
        }
    try:
        data, exit_code, errors = handler(ns)
        envelope = build_envelope(command=op, exit_code=exit_code, version=_cli_version(),
                                  data=data, errors=errors)
        return {"id": None, "type": "result", "ok": True, "envelope": envelope}
    except CliError as exc:
        envelope = build_envelope(
            command=op,
            exit_code=exc.exit_code,
            version=_cli_version(),
            errors=[{
                "code": exc.error_code,
                "message": exc.message,
                **({"hint": exc.hint} if exc.hint else {}),
            }],
        )
        return {"id": None, "type": "result", "ok": True, "envelope": envelope}
    except Exception as exc:  # noqa: BLE001 — serve must survive bad ops
        return {
            "id": None,
            "type": "result",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _cli_version() -> str:
    from aisc import __version__

    return __version__


def cmd_serve(args: argparse.Namespace) -> int:
    """Entry point. Only ``--stdio`` is supported in R1 — the TCP transport
    needs its own security ruling (D-7) and does not exist yet."""
    if not getattr(args, "stdio", False):
        from aisc.domain.models import CliError as _CE

        raise _CE(
            message="serve requires --stdio (the only transport in this version)",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
            hint="Remote callers spawn: ssh <host> aisc serve --stdio",
        )
    return _serve_loop(sys.stdin, sys.stdout)


def _serve_loop(stdin: Any, stdout: Any) -> int:
    from aisc import __version__

    stop = {"flag": False}

    def _stop(_sig: int, _frm: Any = None) -> None:
        stop["flag"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except ValueError:
            pass  # non-main thread (tests): signals unavailable, EOF still ends us

    # Ready banner — the client's version-pairing handshake (VS Code's
    # commit-match equivalent): it can refuse the connection before any op.
    stdout.write(_frame({
        "type": "ready",
        "serve_protocol": SERVE_PROTOCOL,
        "cli_version": __version__,
    }) + "\n")
    stdout.flush()

    while not stop["flag"]:
        line = stdin.readline()
        if not line:  # EOF — the ssh session went away
            break
        line = line.strip()
        if not line:
            continue
        request: Dict[str, Any]
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("frame must be a JSON object")
        except ValueError as exc:
            response: Dict[str, Any] = {
                "id": None, "type": "result", "ok": False,
                "error": f"bad frame: {exc}",
            }
        else:
            op = request.get("op")
            if not isinstance(op, str):
                response = {
                    "id": request.get("id"), "type": "result", "ok": False,
                    "error": "frame requires a string 'op'",
                }
            else:
                response = _run_op(op, request.get("args") or [])
                response["id"] = request.get("id")
        stdout.write(_frame(response) + "\n")
        stdout.flush()
    return 0


def print_serve_text(subcommand: str, data: Any, errors: list) -> None:  # pragma: no cover
    """Text rendering for serve is intentionally minimal: serve is a machine
    protocol (RFC-adjacent); the interactive CLI should not reach here."""
    print(json.dumps({"data": data, "errors": errors}, ensure_ascii=False))
