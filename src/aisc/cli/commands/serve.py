"""``aisc serve`` — the long-lived remote channel (2.1.10 R1/R2, D-7/D-8).

The Workbench (or any client) reaches a remote machine's aisc CLI over SSH
by spawning ``ssh <alias> aisc serve --stdio``: the serve process then speaks
newline-delimited JSON frames on stdio — the same "authenticated transport
is the SSH session" model as VS Code Remote-SSH. There is deliberately NO
token and NO listening socket in stdio mode (D-7); a future TCP mode must
re-open that decision.

Frame protocol v1.1 (docs/plans/2.1.10-dev-plans/r2-remote-sessions.md §2):

    serve -> client   {"type":"ready","serve_protocol":1,"cli_version":...}
    client -> serve   {"id":"u1","op":"version","args":[...]}
    serve -> client   {"id":"u1","type":"result","ok":true,"envelope":{...}}
    serve -> client   {"type":"log","level":"info","line":"..."}

    R2 PTY stream frames (D-8):
    client -> serve   {"id":"u2","op":"session.open","args":{...}}
    serve -> client   result frame, then stream frames for that sid:
    client -> serve   {"type":"pty.input","sid":...,"data":"<b64>"}
    client -> serve   {"type":"pty.resize","sid":...,"cols":80,"rows":24}
    client -> serve   {"type":"pty.kill","sid":...}
    serve -> client   {"type":"pty.output","sid":...,"data":"<b64>"}
    serve -> client   {"type":"pty.exit","sid":...,"exit_code":0}

Lifecycle: stdin EOF, SIGINT or SIGTERM ends the loop (in-flight request is
allowed up to 3s to finish, every live PTY is killed). Malformed lines and
unknown ops answer with an error result frame — the process never dies from
bad input.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import os
import signal
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from aisc.cli.output import build_envelope
from aisc.domain.models import CliError

#: Wire protocol version. Human labels v1.1 (PTY) / v1.2 (fs.*) were additive
#: while the field stayed 1; v1.3 (D-10: generic `cli` op + ready `home`)
#: BUMPS the field to 3 and drops cross-version compatibility by ruling —
#: both ends ship from one repo, a mismatch is a hard client-side error
#: ("upgrade the remote aisc"), never a silent per-op-ssh fallback.
SERVE_PROTOCOL = 3

#: Grace period for an in-flight op when the loop is asked to stop (s).
SHUTDOWN_GRACE_SECONDS = 3.0

#: Initial pty size for session.open when the client did not send one.
DEFAULT_COLS = 80
DEFAULT_ROWS = 24


def _frame(line: str) -> str:
    return json.dumps(line, ensure_ascii=False, separators=(",", ":"))


# -- PTY registry (R2, D-8) -----------------------------------------------------


class PtyEntry:
    """One live exec TTY owned by this serve process."""

    def __init__(self, sid: str, handle: Any, runtime: "ServeRuntime") -> None:
        self.sid = sid
        self.handle = handle
        self.runtime = runtime
        self.waiter = threading.Thread(target=self._wait, daemon=True)

    def start(self) -> None:
        self.waiter.start()

    def _wait(self) -> None:
        try:
            code = self.handle.wait_exit()
        except Exception as exc:  # noqa: BLE001 — exit frame carries the failure
            self.runtime._emit({"type": "pty.exit", "sid": self.sid,
                                "error": f"{type(exc).__name__}: {exc}"})
            return
        self.runtime._emit({"type": "pty.exit", "sid": self.sid,
                            "exit_code": code})
        self.runtime._forget_pty(self.sid)


class ServeRuntime:
    """Everything the loop + pump threads share: the serialized stdout
    writer (frames from the main loop AND from every PTY pump thread ride
    one lock) and the live-PTY registry."""

    def __init__(self, stdout: Any) -> None:
        self._stdout = stdout
        self._write_lock = threading.Lock()
        self._ptys: Dict[str, PtyEntry] = {}
        self._pty_lock = threading.Lock()
        # R3 (D-9): lazy-created watchdog registry; fs.watch fails cleanly
        # where watchdog is unavailable.
        from aisc.cli.commands.serve_fs import WatchRegistry

        self.fs_watches = WatchRegistry(self._emit)

    def _emit(self, frame: Dict[str, Any]) -> None:
        line = _frame(frame) + "\n"
        with self._write_lock:
            self._stdout.write(line)
            self._stdout.flush()

    def _on_output(self, sid: str) -> Callable[[bytes], None]:
        def push(chunk: bytes) -> None:
            self._emit({
                "type": "pty.output",
                "sid": sid,
                "data": base64.b64encode(chunk).decode("ascii"),
            })
        return push

    def register_pty(self, sid: str, handle: Any) -> None:
        entry = PtyEntry(sid, handle, self)
        with self._pty_lock:
            self._ptys[sid] = entry
        entry.start()

    def _forget_pty(self, sid: str) -> None:
        with self._pty_lock:
            self._ptys.pop(sid, None)

    def pty(self, sid: str) -> Optional[Any]:
        with self._pty_lock:
            return self._ptys.get(sid)

    def pty_input(self, sid: str, data_b64: str) -> Optional[str]:
        entry = self.pty(sid)
        if entry is None:
            return f"unknown sid {sid!r}"
        try:
            entry.handle.write(base64.b64decode(data_b64))
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {exc}"
        return None

    def pty_resize(self, sid: str, cols: int, rows: int) -> Optional[str]:
        entry = self.pty(sid)
        if entry is None:
            return f"unknown sid {sid!r}"
        try:
            entry.handle.resize((int(cols), int(rows)))
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {exc}"
        return None

    def pty_kill(self, sid: str) -> None:
        entry = self.pty(sid)
        if entry is not None:
            entry.handle.kill()
            self._forget_pty(sid)

    def kill_all(self) -> None:
        with self._pty_lock:
            entries = list(self._ptys.values())
            self._ptys.clear()
        for entry in entries:
            try:
                entry.handle.kill()
            except Exception:  # noqa: BLE001
                pass


# -- op dispatch ----------------------------------------------------------------
#
# Ops map straight onto the same application-layer code paths the one-shot
# CLI commands use (never argparse); each returns (data, exit_code, errors).
# serve ALWAYS answers with an envelope — stdout carries nothing else.


def _op_version(args: argparse.Namespace, payload: Dict[str, Any],
                runtime: ServeRuntime) -> Tuple[Any, int, List[Dict[str, Any]]]:
    from aisc.cli.main import _cmd_version

    return _cmd_version(args).to_dict(), 0, []


def _op_doctor(args: argparse.Namespace, payload: Dict[str, Any],
               runtime: ServeRuntime) -> Tuple[Any, int, List[Dict[str, Any]]]:
    from aisc.cli.main import _cmd_doctor

    data, report = _cmd_doctor(args, effective_format="json")
    # doctor's own exit code (0 ok / 3 docker-unavailable) rides the envelope
    # exactly as the one-shot CLI reports it.
    return data, report.exit_code, []


def _op_ps(args: argparse.Namespace, payload: Dict[str, Any],
           runtime: ServeRuntime) -> Tuple[Any, int, List[Dict[str, Any]]]:
    from aisc.cli.main import _cmd_ps

    return _cmd_ps(args, effective_format="json")


#: Commands that must never run inside serve's `cli` op (D-10): interactive /
#: TUI / streaming / self-referential — they would block the serial op loop
#: or capture the transport itself. PTY entry rides its own session.open op;
#: build stays on its per-op ssh event stream.
_SERVE_CLI_DENY = frozenset({
    "serve",             # recursion
    "run",               # interactive exec
    "shell",             # docker exec -it
    "switch", "cc-switch",  # TUIs
    "build",             # long streaming op (own channel)
    "wizard",            # interactive
    "session",           # streams ride session.open / pty.* frames
})


def _op_cli(args: argparse.Namespace, payload: Dict[str, Any],
            runtime: ServeRuntime) -> Tuple[Any, int, List[Dict[str, Any]]]:
    """D-10 generic control-plane op: run one non-interactive CLI argv
    in-process and return its envelope's (data, exit_code, errors).

    Reuses the one-shot CLI's own dispatch (``main``) under captured
    stdio — one op covers every envelope command, zero per-command
    registration. Frame transport is unaffected by the capture: the loop
    and PTY drains write through the ``ServeRuntime``'s cached stdout
    handle, not the rebound ``sys.stdout``.
    """
    from aisc.cli.main import main as _cli_main, _detect_json_format

    argv = [str(a) for a in (payload.get("argv") or [])]
    if not argv:
        raise CliError(message="cli op requires a non-empty argv",
                       exit_code=2, error_code="AISC_ERR_USAGE")
    if argv[0] in _SERVE_CLI_DENY:
        raise CliError(
            message=f"'{argv[0]}' cannot run over serve (interactive, "
                    f"streaming or self-referential)",
            exit_code=2, error_code="AISC_ERR_USAGE",
            hint="PTY sessions ride session.open; build keeps its ssh stream")
    if "--events" in argv or "-h" in argv or "--help" in argv:
        raise CliError(message="cli op rejects --events/-h/--help argv",
                       exit_code=2, error_code="AISC_ERR_USAGE")
    # The op contract is the JSON envelope — force it for callers that
    # omitted --format (same detector the one-shot CLI uses pre-parse).
    if not _detect_json_format(argv):
        argv = [*argv, "--format", "json"]

    stdin_text = payload.get("stdin")
    run_id = payload.get("run_id")
    prev_run_id = os.environ.get("AISC_RUN_ID")
    if isinstance(run_id, str) and run_id:
        os.environ["AISC_RUN_ID"] = run_id

    buf = io.StringIO()
    code = 0
    prev_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_text if isinstance(stdin_text, str) else "")
    try:
        with contextlib.redirect_stdout(buf):
            try:
                _cli_main(argv)
            except SystemExit as exc:  # argparse errors print + exit
                code = exc.code if isinstance(exc.code, int) else (0 if not exc.code else 2)
    finally:
        sys.stdin = prev_stdin
        if prev_run_id is None:
            os.environ.pop("AISC_RUN_ID", None)
        else:
            os.environ["AISC_RUN_ID"] = prev_run_id

    text = buf.getvalue().strip()
    if text:
        try:
            env = json.loads(text)
            meta = env.get("meta") or {}
            errors = list(env.get("errors") or [])
            return (env.get("data"), int(meta.get("exit_code", code)), errors)
        except ValueError:
            pass
    raise CliError(
        message=f"cli op got non-envelope output: {text[:200]!r}",
        exit_code=code or 2, error_code="AISC_ERR_SERVE_CLI_OUTPUT")


def _op_session_open(args: argparse.Namespace, payload: Dict[str, Any],
                     runtime: ServeRuntime) -> Tuple[Any, int, List[Dict[str, Any]]]:
    """R2 (D-8): open one exec TTY as a stream; result frame reports the
    exec establishment, then pty.output/exit stream frames follow."""
    from aisc.adapters.docker_ import RealDockerExecutor
    from aisc.adapters.docker_gateway import create_docker_gateway
    from aisc.application.session import build_session_exec
    from aisc.cli.commands.session import _resolve_workspace_and_registry

    runtime_id = str(payload.get("runtime_id") or "")
    session_id = str(payload.get("session_id") or "")
    agent = str(payload.get("agent") or "")
    workspace = payload.get("workspace")
    resume = payload.get("resume_conversation_id")

    # Resolution/validation speaks the DockerExecutor interface (run_captured
    # etc. — RealDockerExecutor, docker CLI); the PTY stream is SDK-only
    # (exec_resize, G-02). Two objects, two contracts.
    executor = RealDockerExecutor()
    gateway = create_docker_gateway("auto")
    registry_root = _resolve_workspace_and_registry(
        workspace if isinstance(workspace, str) and workspace else None
    )[1]

    container, docker_argv, env = build_session_exec(
        runtime_id=runtime_id,
        session_id=session_id,
        agent=agent,
        executor=executor,
        registry_root=registry_root,
        resume_conversation_id=resume if isinstance(resume, str) else None,
    )

    cols = int(payload.get("cols") or DEFAULT_COLS)
    rows = int(payload.get("rows") or DEFAULT_ROWS)
    handle = gateway.open_pty_stream(
        container, docker_argv, env=env,
        on_output=runtime._on_output(session_id), initial_size=(cols, rows),
    )
    runtime.register_pty(session_id, handle)
    return {"session_id": session_id, "agent": agent, "container": container}, 0, []


OPS: Dict[str, Callable[..., Tuple[Any, int, List[Dict[str, Any]]]]] = {
    "version": _op_version,
    "doctor": _op_doctor,
    "ps": _op_ps,
    "session.open": _op_session_open,
    "cli": _op_cli,
}

# R3 (D-9): the remote-authoritative file plane rides the same serve session.
from aisc.cli.commands.serve_fs import OPS as _FS_OPS  # noqa: E402

OPS.update(_FS_OPS)

#: Ops that may not run while another op is executing — R1 is strictly
#: serial; the ``id`` field already exists so a concurrent executor can be
#: introduced later without a protocol change.


def _run_op(op: str, payload: Dict[str, Any], runtime: ServeRuntime) -> Dict[str, Any]:
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
        # Uniform handler signature (ns, payload, runtime) — R2's stream ops
        # need the payload dict and the PTY registry; plain ops ignore them.
        data, exit_code, errors = handler(ns, payload, runtime)
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
    except NotImplementedError as exc:
        # PTY transport on a CLI-only backend: an honest refusal, not a crash.
        return {
            "id": None,
            "type": "result",
            "ok": False,
            "error": str(exc),
        }
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
    """Entry point. Only ``--stdio`` is supported — the TCP transport needs
    its own security ruling (D-7) and does not exist."""
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
    runtime = ServeRuntime(stdout)

    def _stop(_sig: int, _frm: Any = None) -> None:
        stop["flag"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except ValueError:
            pass  # non-main thread (tests): signals unavailable, EOF still ends us

    # Ready banner — the client's version-pairing handshake (VS Code's
    # commit-match equivalent): it can refuse the connection before any op.
    # `home` (v1.3) anchors the remote-side directory browser (F2-B).
    runtime._emit({
        "type": "ready",
        "serve_protocol": SERVE_PROTOCOL,
        "cli_version": __version__,
        "home": os.path.expanduser("~"),
    })

    while not stop["flag"]:
        line = stdin.readline()
        if not line:  # EOF — the ssh session went away
            break
        line = line.strip()
        if not line:
            continue
        frame_in: Dict[str, Any]
        try:
            frame_in = json.loads(line)
            if not isinstance(frame_in, dict):
                raise ValueError("frame must be a JSON object")
        except ValueError as exc:
            runtime._emit({"id": None, "type": "result", "ok": False,
                           "error": f"bad frame: {exc}"})
            continue

        ftype = frame_in.get("type")

        # Stream-control frames (R2): fast, no result frame.
        if ftype == "pty.input":
            err = runtime.pty_input(str(frame_in.get("sid") or ""),
                                    str(frame_in.get("data") or ""))
            if err:
                runtime._emit({"type": "log", "level": "error", "line": err})
            continue
        if ftype == "pty.resize":
            err = runtime.pty_resize(str(frame_in.get("sid") or ""),
                                     frame_in.get("cols") or DEFAULT_COLS,
                                     frame_in.get("rows") or DEFAULT_ROWS)
            if err:
                runtime._emit({"type": "log", "level": "error", "line": err})
            continue
        if ftype == "pty.kill":
            runtime.pty_kill(str(frame_in.get("sid") or ""))
            continue

        # Request frame: {"id", "op", "args"} — args is the payload dict.
        op = frame_in.get("op")
        if not isinstance(op, str):
            runtime._emit({"id": frame_in.get("id"), "type": "result", "ok": False,
                           "error": "frame requires a string 'op'"})
            continue
        payload = frame_in.get("args")
        if not isinstance(payload, dict):
            payload = {}
        response = _run_op(op, payload, runtime)
        response["id"] = frame_in.get("id")
        runtime._emit(response)

    runtime.kill_all()
    runtime.fs_watches.shutdown()
    return 0


def print_serve_text(subcommand: str, data: Any, errors: list) -> None:  # pragma: no cover
    """Text rendering for serve is intentionally minimal: serve is a machine
    protocol (RFC-adjacent); the interactive CLI should not reach here."""
    print(json.dumps({"data": data, "errors": errors}, ensure_ascii=False))
