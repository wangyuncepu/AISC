"""Docker adapter — unified ``DockerExecutor`` protocol with preflight,
image inspection, and build/run execution.

**All** docker operations go through the executor.  Application / command
code never calls ``subprocess.run`` directly.

Protocol methods
----------------
- ``preflight()``      → ``DockerPreflightResult``
- ``inspect_image()``  → ``ImageInspectResult``  (structured, never swallows)
- ``run_captured()``   → ``ProcessResult``        (capture stdout/stderr)
- ``run_streaming()``  → ``int``                  (inherit streams, return exit code)

``shell=True`` is **never** used.
"""

from __future__ import annotations

import os
import queue
import select
import socket
import time
import shlex
import signal
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Protocol, runtime_checkable

from aisc.domain.models import (
    BuildPlan,
    DockerPreflightResult,
    ImageInspectResult,
    ImageInspectStatus,
    ProcessResult,
    RunPlan,
)


# ---------------------------------------------------------------------------
# Executor protocol — single injectable abstraction
# ---------------------------------------------------------------------------

@runtime_checkable
class DockerExecutor(Protocol):
    """Narrow interface for all Docker operations.

    Every method maps to one or more ``docker`` CLI invocations.
    """

    def preflight(self) -> DockerPreflightResult:
        """Check Docker CLI availability + daemon reachability via
        ``docker info`` (8 s timeout)."""

    def inspect_image(self, image_name: str) -> ImageInspectResult:
        """Check whether *image_name* exists locally via
        ``docker image inspect`` (10 s timeout).  Structured result —
        never returns bare ``bool``."""

    def run_captured(self, docker_argv: List[str],
                     *, timeout: Optional[float] = None) -> ProcessResult:
        """Execute ``docker <argv>`` with captured stdout / stderr."""

    def run_streaming(self, docker_argv: List[str],
                      *, timeout: Optional[float] = None) -> ProcessResult:
        """Execute ``docker <argv>`` with inherited stdin / stdout / stderr.
        Returns a ``ProcessResult`` with exit code captured, stderr empty."""

    def open_interactive(self, container: str, argv: List[str]) -> ProcessResult:
        """Open an interactive TTY session via the Docker SDK so the exec pty
        can be resized with ``exec_resize`` (G-02: the docker CLI's exec pty is
        frozen at the spawn size). Raw tty stream: stdout forwarded to fd 1,
        stdin forwarded to the socket, terminal-size watcher forwards changes.
        Returns the agent's exit code from exec_inspect."""

    def run_non_interactive(self, docker_argv: List[str],
                            *, timeout: Optional[float] = None) -> ProcessResult:
        """Execute ``docker <argv>`` with DEVNULL stdin, inherited stdout / stderr.
        For ``--non-interactive`` mode."""

    def run_streaming_captured(self, docker_argv: List[str],
                               on_chunk: "Callable[[str, str], None]",
                               *, timeout: Optional[float] = None) -> ProcessResult:
        """Execute ``docker <argv>`` streaming stdout/stderr chunks to
        *on_chunk(stream, chunk)*. Used by ``build --events`` for real-time
        ``build.output`` events (not end-of-build replay). The child runs in its
        own process group so a cancel can kill it without signaling the CLI."""

    # Container operations
    def list_containers(self, all: bool = False) -> ProcessResult:
        """List containers via ``docker ps`` (or ``docker ps -a`` if all=True)."""

    def stop_container(self, container_name: str, timeout: int = 10) -> ProcessResult:
        """Stop a container via ``docker stop``."""

    def remove_container(self, container_name: str, force: bool = False) -> ProcessResult:
        """Remove a container via ``docker rm`` (with -f if force=True)."""

    def inspect_container(self, container_name: str) -> ProcessResult:
        """Inspect a container via ``docker inspect``."""

    # Image operations
    def list_images(self) -> ProcessResult:
        """List images via ``docker images``."""

    def remove_image(self, image_name: str, force: bool = False) -> ProcessResult:
        """Remove an image via ``docker rmi`` (with -f if force=True)."""

    def pull_image(self, image_name: str) -> ProcessResult:
        """Pull an image via ``docker pull``."""

    def tag_image(self, source: str, target: str) -> ProcessResult:
        """Tag an image via ``docker tag``."""


# Factory functions are below; Protocol methods don't have bodies.

# ---------------------------------------------------------------------------
# Process-tree kill helper (cross-platform)
# ---------------------------------------------------------------------------

def _kill_child(proc: subprocess.Popen) -> None:
    """Kill *proc* and its whole child tree, never raising.

    POSIX: SIGKILL the child's process group (docker build subprocesses must
    not outlive the CLI).  Windows: ``taskkill /T /F`` tree kill with
    ``proc.kill()`` as fallback.  Safe to call from exception handlers —
    neither ``os.killpg`` nor ``signal.SIGKILL`` exist on Windows, so the
    fallbacks keep the cleanup path from crashing and masking the original
    exception.
    """
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            return
        except OSError:
            pass
    else:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Real Docker executor (production)
# ---------------------------------------------------------------------------

class RealDockerExecutor:
    """Real ``docker`` subprocess executor — all methods use ``subprocess``."""

    _PREFLIGHT_TIMEOUT = 8.0
    _INSPECT_TIMEOUT = 10.0

    # Windows install locations to try when the CLI is not on PATH. A fresh
    # winget install only lands in the user PATH after Explorer re-reads the
    # environment, so a Workbench launched straight from the installer inherits
    # a stale PATH and ``shutil.which`` misses it (TODO 20260806 line 76).
    _WINDOWS_FALLBACK_PATHS = (
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
        r"%LOCALAPPDATA%\Docker\Docker\resources\bin\docker.exe",
    )

    def __init__(self, docker_path: Optional[str] = None):
        self._docker_path: Optional[str] = docker_path

    def _resolve_path(self) -> Optional[str]:
        if self._docker_path is not None:
            return self._docker_path
        self._docker_path = shutil.which("docker")
        if self._docker_path is None and os.name == "nt":
            for candidate in self._WINDOWS_FALLBACK_PATHS:
                expanded = os.path.expandvars(candidate)
                if os.path.isfile(expanded):
                    self._docker_path = expanded
                    break
        return self._docker_path

    def _subprocess_env(self) -> dict:
        """Env for docker subprocesses: the resolved docker dir prepended to
        PATH so credential helpers next to the docker CLI (e.g.
        ``docker-credential-desktop.exe``) resolve even when the parent
        process inherited a stale PATH (Workbench launched straight from the
        installer; S4.1.b)."""
        env = os.environ.copy()
        dp = self._resolve_path()
        if dp:
            env["PATH"] = os.path.dirname(dp) + os.pathsep + env.get("PATH", "")
        return env

    # ------------------------------------------------------------------
    # preflight
    # ------------------------------------------------------------------

    def preflight(self) -> DockerPreflightResult:
        docker_path = self._resolve_path()
        if docker_path is None:
            return DockerPreflightResult(
                docker_path="", available=False, reason="cli_not_found",
            )

        try:
            proc = subprocess.run(
                [docker_path, "info"],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=self._PREFLIGHT_TIMEOUT,
                env=self._subprocess_env(),
            )
        except FileNotFoundError:
            return DockerPreflightResult(
                docker_path=docker_path, available=False, reason="cli_not_found",
            )
        except subprocess.TimeoutExpired:
            return DockerPreflightResult(
                docker_path=docker_path, available=False, reason="daemon_unreachable",
            )
        except PermissionError:
            return DockerPreflightResult(
                docker_path=docker_path, available=False, reason="permission_denied",
            )
        except OSError as exc:
            return DockerPreflightResult(
                docker_path=docker_path, available=False,
                reason="daemon_unreachable",
            )

        if proc.returncode != 0:
            stderr_lower = (proc.stderr or "").lower()
            if "permission denied" in stderr_lower:
                return DockerPreflightResult(
                    docker_path=docker_path, available=False,
                    reason="permission_denied",
                )
            return DockerPreflightResult(
                docker_path=docker_path, available=False,
                reason="daemon_unreachable",
            )

        return DockerPreflightResult(
            docker_path=docker_path, available=True, reason="ok",
        )

    # ------------------------------------------------------------------
    # inspect_image
    # ------------------------------------------------------------------

    def inspect_image(self, image_name: str) -> ImageInspectResult:
        docker_path = self._resolve_path()
        if docker_path is None:
            return ImageInspectResult(
                status=ImageInspectStatus.DOCKER_UNAVAILABLE,
                image=image_name,
                message="Docker CLI not found",
            )

        try:
            proc = subprocess.run(
                [docker_path, "image", "inspect", image_name],
                capture_output=True, text=True,
                timeout=self._INSPECT_TIMEOUT,
                encoding="utf-8", errors="replace",
                env=self._subprocess_env(),
            )
        except FileNotFoundError:
            return ImageInspectResult(
                status=ImageInspectStatus.DOCKER_UNAVAILABLE,
                image=image_name, message="Docker CLI not found",
            )
        except subprocess.TimeoutExpired:
            return ImageInspectResult(
                status=ImageInspectStatus.TIMEOUT,
                image=image_name, message="docker image inspect timed out",
            )
        except PermissionError:
            return ImageInspectResult(
                status=ImageInspectStatus.PERMISSION_DENIED,
                image=image_name, message="Permission denied accessing Docker daemon",
            )
        except OSError as exc:
            return ImageInspectResult(
                status=ImageInspectStatus.ERROR,
                image=image_name, message=f"Command error: {exc}",
            )

        if proc.returncode == 0:
            return ImageInspectResult(
                status=ImageInspectStatus.EXISTS,
                image=image_name, message="",
            )

        stderr_text = proc.stderr or ""
        stderr_lower = stderr_text.lower()

        # Permission denied patterns
        if "permission denied" in stderr_lower:
            return ImageInspectResult(
                status=ImageInspectStatus.PERMISSION_DENIED,
                image=image_name, message="Permission denied accessing Docker daemon",
            )

        # Explicit "not found" — Docker standard messages
        # Must check BEFORE daemon keyword because Docker error response
        # format "Error response from daemon: No such image: ..." contains
        # the word "daemon" even for missing images
        if any(kw in stderr_lower for kw in (
            "no such image", "no such object",
            "image not found", "not found",
        )):
            return ImageInspectResult(
                status=ImageInspectStatus.MISSING,
                image=image_name, message=f"Image '{image_name}' not found",
            )

        # Docker daemon / connection errors (AFTER not-found check)
        if any(kw in stderr_lower for kw in (
            "cannot connect", "is the docker daemon running",
            "connection refused", "error during connect",
        )):
            return ImageInspectResult(
                status=ImageInspectStatus.DOCKER_UNAVAILABLE,
                image=image_name, message=f"Docker daemon unreachable: {stderr_text.strip()[:200]}",
            )

        # Fallback: unknown error
        return ImageInspectResult(
            status=ImageInspectStatus.ERROR,
            image=image_name,
            message=f"Image inspect failed (exit {proc.returncode}): {stderr_text.strip()[:200]}",
        )

    # ------------------------------------------------------------------
    # run_captured
    # ------------------------------------------------------------------

    def run_captured(self, docker_argv: List[str],
                     *, timeout: Optional[float] = None) -> ProcessResult:
        dp = self._resolve_path() or "docker"
        try:
            proc = subprocess.run(
                [dp] + list(docker_argv),
                capture_output=True, text=True,
                timeout=timeout,
                encoding="utf-8", errors="replace",
                env=self._subprocess_env(),
            )
            return ProcessResult(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=proc.returncode,
            )
        except FileNotFoundError:
            return ProcessResult(
                stdout="", stderr="command not found: docker",
                exit_code=-1, command_not_found=True,
            )
        except subprocess.TimeoutExpired:
            return ProcessResult(
                stdout="", stderr="command timed out",
                exit_code=-1, timed_out=True,
            )
        except OSError as exc:
            return ProcessResult(
                stdout="", stderr=f"command error: {exc}",
                exit_code=-1, command_not_found=True,
            )

    # ------------------------------------------------------------------
    # run_streaming
    # ------------------------------------------------------------------

    def run_streaming(self, docker_argv: List[str],
                      *, timeout: Optional[float] = None) -> ProcessResult:
        dp = self._resolve_path() or "docker"
        try:
            proc = subprocess.run(
                [dp] + list(docker_argv), timeout=timeout, env=self._subprocess_env(),
            )
            return ProcessResult(
                stdout="", stderr="", exit_code=proc.returncode,
            )
        except FileNotFoundError:
            return ProcessResult(
                stdout="", stderr="command not found: docker",
                exit_code=-1, command_not_found=True,
            )
        except subprocess.TimeoutExpired:
            return ProcessResult(
                stdout="", stderr="command timed out",
                exit_code=-1, timed_out=True,
            )
        except OSError as exc:
            return ProcessResult(
                stdout="", stderr=f"command error: {exc}",
                exit_code=-1, command_not_found=True,
            )

    # ------------------------------------------------------------------
    # open_interactive (G-02 resize chain)
    # ------------------------------------------------------------------

    def open_interactive(self, container: str, argv: List[str]) -> ProcessResult:
        """Interactive TTY session via the Docker SDK (see protocol doc).

        G-02 root cause (2026-08-10): ``docker exec -it``'s exec pty is sized
        once at creation; the docker CLI has no resize command, so the local
        ConPTY resize never reached the container. The SDK's ``exec_resize``
        is the in-band fix: a watcher thread polls the local terminal size
        (ConPTY on Windows, winsize ioctl on POSIX) and forwards changes.
        """
        import docker  # lazy: every other path stays dependency-free

        # The container's Linux pty emits UTF-8. The ConPTY output codepage
        # is fixed at the system default (GBK/CP936 on zh-CN) and cannot be
        # changed at runtime (SetConsoleOutputCP is ignored by ConPTY).
        # The drain thread transcodes: decode UTF-8 -> re-encode to the
        # console's actual codepage -> os.write. WriteConsoleW was rejected:
        # it uses Unicode width tables that treat box-drawing as 2 columns
        # on zh-CN, causing TUI misalignment. (G-02, 2026-08-10.)

        try:
            client = docker.from_env()
        except docker.errors.DockerException as exc:
            return ProcessResult(
                stdout="", stderr=f"docker daemon unreachable: {exc}",
                exit_code=-1, command_not_found=True,
            )
        try:
            exec_id = client.api.exec_create(container, list(argv), tty=True, stdin=True)["Id"]
        except docker.errors.NotFound:
            return ProcessResult(
                stdout="", stderr="container not found",
                exit_code=-1, command_not_found=True,
            )
        except docker.errors.APIError as exc:
            return ProcessResult(
                stdout="", stderr=f"exec create failed: {exc}",
                exit_code=-1, command_not_found=True,
            )
        try:
            sock = client.api.exec_start(exec_id, socket=True, tty=True)
        except docker.errors.APIError as exc:
            return ProcessResult(
                stdout="", stderr=f"exec start failed: {exc}",
                exit_code=-1, command_not_found=True,
            )

        stop = threading.Event()
        errors: List[Exception] = []

        def drain() -> None:
            """Socket -> stdout (transcoded to the console's codepage).

            Windows: The ConPTY output codepage is fixed (GBK/CP936 on
            zh-CN) and SetConsoleOutputCP is ignored. Rather than writing
            raw UTF-8 bytes (garbled) or WriteConsoleW (Unicode width
            tables -> box-drawing = 2 cols -> misaligned), we **transcode**:
            decode the container's UTF-8 to Unicode, re-encode to the
            console's actual codepage (queried via GetConsoleOutputCP),
            and write via os.write. The console decodes the transcoded
            bytes correctly, and the codepage width tables (with
            ENABLE_LVB_GRID_WORLDWIDE) treat box-drawing as 1 column.

            Bare ``\\n`` is replaced with ``ESC D`` (IND) at the byte level
            to prevent ENABLE_PROCESSED_OUTPUT from translating it to
            ``\\r\\n``. Safe because 0x0A never appears inside multi-byte
            sequences of any East-Asian codepage.

            POSIX: raw os.write (no codepage on pty).
            """
            try:
                if os.name == "nt":
                    import ctypes
                    import codecs
                    from ctypes import wintypes
                    k32 = ctypes.windll.kernel32
                    k32.GetConsoleOutputCP.restype = ctypes.c_uint32
                    console_cp = k32.GetConsoleOutputCP()
                    # Python codec name for the console's codepage.
                    out_encoding = "cp%d" % console_cp if console_cp else "gbk"
                    # Set ENABLE_LVB_GRID_WORLDWIDE on the output handle so
                    # the codepage width tables treat box-drawing as 1 col.
                    k32.GetStdHandle.restype = wintypes.HANDLE
                    k32.GetStdHandle.argtypes = [wintypes.DWORD]
                    oh = k32.GetStdHandle(-11)
                    omode = wintypes.DWORD()
                    if oh and k32.GetConsoleMode(
                        wintypes.HANDLE(oh), ctypes.byref(omode)
                    ):
                        k32.SetConsoleMode.argtypes = [
                            wintypes.HANDLE, wintypes.DWORD,
                        ]
                        k32.SetConsoleMode.restype = wintypes.BOOL
                        k32.SetConsoleMode(
                            wintypes.HANDLE(oh),
                            wintypes.DWORD(omode.value | 0x0010),
                        )
                    decoder = codecs.getincrementaldecoder("utf-8")(
                        errors="replace"
                    )
                    while True:
                        chunk = sock.recv(65536)
                        if not chunk:
                            text = decoder.decode(b"", final=True)
                            if text:
                                data = text.encode(
                                    out_encoding, errors="replace"
                                ).replace(b"\n", b"\x1bD")
                                os.write(sys.stdout.fileno(), data)
                            break
                        text = decoder.decode(chunk)
                        if text:
                            data = text.encode(
                                out_encoding, errors="replace"
                            ).replace(b"\n", b"\x1bD")
                            os.write(sys.stdout.fileno(), data)
                else:
                    while True:
                        chunk = sock.recv(65536)
                        if not chunk:
                            break
                        os.write(sys.stdout.fileno(), chunk)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def forward() -> None:
            """stdin -> socket; on EOF, close the write side so the exec sees it.

            Windows: ENABLE_VIRTUAL_TERMINAL_INPUT (0x0200) directs the ConPTY
            to pass VT input sequences through as raw bytes - no translation to
            KEY_EVENT_RECORDs. This fixes two issues with the previous
            ReadConsoleInputW approach:
            1. Arrow/special keys: ReadConsoleInputW gives uChar=NUL for
               VK_UP/VK_DOWN/etc., which were silently dropped (arrow keys
               did nothing in TUIs). VT passthrough preserves ESC[A etc.
            2. CR/LF loss: os.read on a cooked/raw-mode console handle loses
               CR/LF (cooked eats CR, raw drops terminators). VT input mode
               passes the exact byte stream from xterm.js (incl. \\r for Enter).
            POSIX: plain os.read (no codepage on pty).
            """
            if os.name == "nt":
                try:
                    import ctypes
                    from ctypes import wintypes
                    import msvcrt
                    in_handle = msvcrt.get_osfhandle(sys.stdin.fileno())
                    k32 = ctypes.windll.kernel32
                    in_mode = wintypes.DWORD()
                    if k32.GetConsoleMode(in_handle, ctypes.byref(in_mode)):
                        # Clear PROCESSED/LINE/ECHO input; set VT passthrough.
                        k32.SetConsoleMode(
                            in_handle, (in_mode.value & ~0x0007) | 0x0200
                        )
                except Exception:  # noqa: BLE001
                    pass  # not a console - os.read still works on pipes
            try:
                while True:
                    chunk = os.read(sys.stdin.fileno(), 4096)
                    if not chunk:
                        break
                    sock.sendall(chunk)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                try:
                    sock.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        def terminal_size() -> Optional[tuple]:
            """(cols, rows) of the local terminal. Windows: the ConPTY size via
            GetConsoleScreenBufferInfo on the stdout handle (os.get_terminal_size
            fails on console INPUT handles). POSIX: winsize ioctl."""
            if os.name == "nt":
                try:
                    import ctypes
                    from ctypes import wintypes

                    kernel32 = ctypes.windll.kernel32
                    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE

                    class COORD(ctypes.Structure):
                        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

                    class SMALL_RECT(ctypes.Structure):
                        _fields_ = [
                            ("Left", wintypes.SHORT),
                            ("Top", wintypes.SHORT),
                            ("Right", wintypes.SHORT),
                            ("Bottom", wintypes.SHORT),
                        ]

                    class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
                        _fields_ = [
                            ("dwSize", COORD),
                            ("dwCursorPosition", COORD),
                            ("wAttributes", wintypes.WORD),
                            ("srWindow", SMALL_RECT),
                            ("dwMaximumWindowSize", COORD),
                        ]

                    info = CONSOLE_SCREEN_BUFFER_INFO()
                    if kernel32.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)):
                        cols = info.srWindow.Right - info.srWindow.Left + 1
                        rows = info.srWindow.Bottom - info.srWindow.Top + 1
                        if cols > 0 and rows > 0:
                            return (cols, rows)
                except Exception:  # noqa: BLE001
                    return None
                return None
            try:
                size = os.get_terminal_size(sys.stdin.fileno())
                return (size.columns, size.lines)
            except (OSError, ValueError):
                return None

        def watch_resize() -> None:
            """Poll the local terminal size; forward changes to the exec pty."""
            last: Optional[tuple] = None
            while not stop.is_set():
                cur = terminal_size()
                if cur is None:
                    return  # not a terminal - nothing to resize
                if cur != last:
                    last = cur
                    try:
                        client.api.exec_resize(exec_id, height=cur[1], width=cur[0])
                    except docker.errors.APIError as exc:
                        errors.append(exc)
                        return
                stop.wait(0.2)

        t_drain = threading.Thread(target=drain, daemon=True)
        t_fwd = threading.Thread(target=forward, daemon=True)
        t_resize = threading.Thread(target=watch_resize, daemon=True)
        t_drain.start()
        t_fwd.start()
        t_resize.start()

        exit_code = -1
        try:
            while True:
                info = client.api.exec_inspect(exec_id)
                if not info.get("Running"):
                    exit_code = int(info.get("ExitCode", 0))
                    break
                time.sleep(0.2)
        except docker.errors.APIError as exc:
            errors.append(exc)
        finally:
            stop.set()
            t_drain.join(timeout=5)
            t_fwd.join(timeout=5)

        if errors:
            try:
                os.write(2, ("[open_interactive] thread error: %r\n" % (errors[0],)).encode())
            except OSError:
                pass
            return ProcessResult(
                stdout="", stderr=f"exec stream error: {errors[0]}",
                exit_code=-1,
            )
        return ProcessResult(stdout="", stderr="", exit_code=exit_code)

    # ------------------------------------------------------------------
    # run_non_interactive
    # ------------------------------------------------------------------

    def run_non_interactive(self, docker_argv: List[str],
                            *, timeout: Optional[float] = None) -> ProcessResult:
        """Execute ``docker <argv>`` with DEVNULL stdin, inherited stdout/stderr."""
        dp = self._resolve_path() or "docker"
        try:
            proc = subprocess.run(
                [dp] + list(docker_argv),
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                env=self._subprocess_env(),
            )
            return ProcessResult(
                stdout="", stderr="", exit_code=proc.returncode,
            )
        except FileNotFoundError:
            return ProcessResult(
                stdout="", stderr="command not found: docker",
                exit_code=-1, command_not_found=True,
            )
        except subprocess.TimeoutExpired:
            return ProcessResult(
                stdout="", stderr="command timed out",
                exit_code=-1, timed_out=True,
            )
        except OSError as exc:
            return ProcessResult(
                stdout="", stderr=f"command error: {exc}",
                exit_code=-1, command_not_found=True,
            )

    # ------------------------------------------------------------------
    # run_streaming_captured (build --events: real-time build.output)
    # ------------------------------------------------------------------

    def run_streaming_captured(self, docker_argv: List[str],
                               on_chunk: "Callable[[str, str], None]",
                               *, timeout: Optional[float] = None) -> ProcessResult:
        """Run ``docker <argv>`` in its own process group, streaming each
        stdout/stderr chunk to *on_chunk(stream, chunk)*. On any interruption
        (cancel/error) the child's whole process tree is killed so Docker
        build subprocesses do not outlive the CLI.

        Drain strategy is platform-specific: ``select`` is POSIX-only
        (Windows supports sockets only), so Windows uses reader threads +
        a queue instead.  Chunk ordering and the timeout contract
        (applied at the final ``proc.wait``) are identical on both."""
        dp = self._resolve_path() or "docker"
        try:
            proc = subprocess.Popen(
                [dp] + list(docker_argv),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,  # own process group -> cancel can kill tree
                env=self._subprocess_env(),
            )
        except FileNotFoundError:
            return ProcessResult(
                stdout="", stderr="command not found: docker",
                exit_code=-1, command_not_found=True,
            )
        except OSError as exc:
            return ProcessResult(
                stdout="", stderr=f"command error: {exc}",
                exit_code=-1, command_not_found=True,
            )
        try:
            if os.name == "posix":
                result = self._drain_select(proc, on_chunk, timeout=timeout)
            else:
                result = self._drain_threads(proc, on_chunk, timeout=timeout)
        except BaseException:
            # Cancel or error: kill the Docker child's whole process tree.
            _kill_child(proc)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            raise
        finally:
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except Exception:
                    pass
        return result

    def _drain_select(self, proc: subprocess.Popen,
                      on_chunk: "Callable[[str, str], None]",
                      *, timeout: Optional[float]) -> ProcessResult:
        """POSIX: incremental read of both pipes via ``select`` (original
        implementation, kept byte-for-byte equivalent)."""
        streams = {proc.stdout: "stdout", proc.stderr: "stderr"}
        open_fds = list(streams.keys())
        while open_fds:
            ready, _, _ = select.select(open_fds, [], [], 0.5)
            for f in ready:
                data = f.read1(4096)
                if data:
                    on_chunk(streams[f], data.decode("utf-8", "replace"))
                else:
                    open_fds.remove(f)
        proc.wait(timeout=timeout)
        return ProcessResult(stdout="", stderr="", exit_code=proc.returncode)

    def _drain_threads(self, proc: subprocess.Popen,
                       on_chunk: "Callable[[str, str], None]",
                       *, timeout: Optional[float]) -> ProcessResult:
        """Windows: two daemon reader threads feed a queue; the main thread
        drains it and invokes *on_chunk* so emission stays single-threaded
        (``JsonlEmitter`` is not lock-protected)."""
        q: "queue.Queue[Optional[tuple[str, bytes]]]" = queue.Queue()

        def _reader(stream: "object", name: str) -> None:
            try:
                while True:
                    chunk = stream.read1(4096)
                    if not chunk:
                        break
                    q.put((name, chunk))
            finally:
                q.put(None)  # EOF sentinel for this stream

        threads = [
            threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True),
        ]
        for t in threads:
            t.start()

        remaining = 2
        while remaining:
            try:
                item = q.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                remaining -= 1
                continue
            stream, chunk = item
            on_chunk(stream, chunk.decode("utf-8", "replace"))

        proc.wait(timeout=timeout)
        return ProcessResult(stdout="", stderr="", exit_code=proc.returncode)

    @property
    def docker_path(self) -> str:
        return self._resolve_path() or "docker"

    # ------------------------------------------------------------------
    # Container operations
    # ------------------------------------------------------------------

    def list_containers(self, all: bool = False) -> ProcessResult:
        """List containers via ``docker ps`` (or ``docker ps -a`` if all=True)."""
        argv = ["ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}"]
        if all:
            argv.insert(1, "-a")
        return self.run_captured(argv, timeout=10.0)

    def stop_container(self, container_name: str, timeout: int = 10) -> ProcessResult:
        """Stop a container via ``docker stop``."""
        argv = ["stop", "-t", str(timeout), container_name]
        return self.run_captured(argv, timeout=float(timeout + 5))

    def remove_container(self, container_name: str, force: bool = False) -> ProcessResult:
        """Remove a container via ``docker rm`` (with -f if force=True)."""
        argv = ["rm"]
        if force:
            argv.append("-f")
        argv.append(container_name)
        return self.run_captured(argv, timeout=10.0)

    def inspect_container(self, container_name: str) -> ProcessResult:
        """Inspect a container via ``docker inspect``."""
        argv = ["inspect", container_name]
        return self.run_captured(argv, timeout=10.0)

    # ------------------------------------------------------------------
    # Image operations
    # ------------------------------------------------------------------

    def list_images(self) -> ProcessResult:
        """List images via ``docker images``."""
        argv = ["images", "--format", "{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}"]
        return self.run_captured(argv, timeout=10.0)

    def remove_image(self, image_name: str, force: bool = False) -> ProcessResult:
        """Remove an image via ``docker rmi`` (with -f if force=True)."""
        argv = ["rmi"]
        if force:
            argv.append("-f")
        argv.append(image_name)
        return self.run_captured(argv, timeout=30.0)

    def pull_image(self, image_name: str) -> ProcessResult:
        """Pull an image via ``docker pull``."""
        argv = ["pull", image_name]
        return self.run_captured(argv, timeout=300.0)

    def tag_image(self, source: str, target: str) -> ProcessResult:
        """Tag an image via ``docker tag``."""
        argv = ["tag", source, target]
        return self.run_captured(argv, timeout=10.0)


# ---------------------------------------------------------------------------
# Fake Docker executor (testing — zero process calls)
# ---------------------------------------------------------------------------

class FakeDockerExecutor:
    """Fully controllable fake executor.

    Configure responses via attributes / dicts.  Tracks all calls so tests
    can assert call counts and exact argv.
    """

    def __init__(self):
        self._preflight_result: DockerPreflightResult = DockerPreflightResult(
            docker_path="docker", available=True, reason="ok",
        )
        self._inspect_results: dict = {}  # image_name → ImageInspectResult
        self._default_inspect: ImageInspectResult = ImageInspectResult(
            status=ImageInspectStatus.MISSING, image="",
        )
        self._captured_results: dict = {}  # key substr → ProcessResult
        self._default_captured: ProcessResult = ProcessResult(
            stdout="", stderr="", exit_code=0,
        )
        self._streaming_exit_code: int = 0
        self._streaming_chunks: List = []  # [(stream, chunk), ...] for run_streaming_captured

        # Call tracking
        self.calls: List[List[str]] = []           # run_captured argv
        self.streaming_calls: List[List[str]] = []  # run_streaming argv
        self.interactive_calls: List[tuple] = []    # (container, argv) for open_interactive
        self.preflight_calls: int = 0
        self.inspect_calls: List[str] = []          # image names inspected

    # ------------------------------------------------------------------
    # preflight
    # ------------------------------------------------------------------

    def preflight(self) -> DockerPreflightResult:
        self.preflight_calls += 1
        return self._preflight_result

    def set_preflight(self, result: DockerPreflightResult) -> None:
        self._preflight_result = result

    # ------------------------------------------------------------------
    # inspect_image
    # ------------------------------------------------------------------

    def inspect_image(self, image_name: str) -> ImageInspectResult:
        self.inspect_calls.append(image_name)
        return self._inspect_results.get(image_name, self._default_inspect)

    def set_inspect(self, image_name: str, result: ImageInspectResult) -> None:
        self._inspect_results[image_name] = result

    def set_default_inspect(self, result: ImageInspectResult) -> None:
        self._default_inspect = result

    # ------------------------------------------------------------------
    # run_captured
    # ------------------------------------------------------------------

    def run_captured(self, docker_argv: List[str],
                     *, timeout: Optional[float] = None) -> ProcessResult:
        self.calls.append(list(docker_argv))
        # Match by first subcommand or keyword
        key = docker_argv[0] if docker_argv else ""
        if key in self._captured_results:
            return self._captured_results[key]
        for k, v in self._captured_results.items():
            if k in docker_argv:
                return v
        # fallback: scan all keys against joined arg string
        joined = " ".join(docker_argv)
        for k, v in self._captured_results.items():
            if k in joined:
                return v
        return ProcessResult(
            stdout=self._default_captured.stdout,
            stderr=self._default_captured.stderr,
            exit_code=self._default_captured.exit_code,
        )

    def set_captured(self, key: str, result: ProcessResult) -> None:
        self._captured_results[key] = result

    def set_default_captured(self, result: ProcessResult) -> None:
        self._default_captured = result

    # ------------------------------------------------------------------
    # run_streaming
    # ------------------------------------------------------------------

    def run_streaming(self, docker_argv: List[str],
                      *, timeout: Optional[float] = None) -> ProcessResult:
        self.streaming_calls.append(list(docker_argv))
        return ProcessResult(
            stdout="", stderr="",
            exit_code=self._streaming_exit_code if self._streaming_exit_code >= 0 else -1,
            command_not_found=(self._streaming_exit_code < 0),
        )

    # ------------------------------------------------------------------
    # open_interactive (G-02 resize chain)
    # ------------------------------------------------------------------

    def set_streaming_exit(self, code: int) -> None:
        """Configure the exit code returned by run_streaming / open_interactive."""
        self._streaming_exit_code = code

    def run_streaming_captured(self, docker_argv: List[str],
                               on_chunk: "Callable[[str, str], None]",
                               *, timeout: Optional[float] = None) -> ProcessResult:
        """Replay configured chunks to *on_chunk*, then return the preset exit
        code. Set chunks via :meth:`set_streaming_chunks`."""
        self.streaming_calls.append(list(docker_argv))
        for stream, chunk in self._streaming_chunks:
            on_chunk(stream, chunk)
        return ProcessResult(
            stdout="", stderr="",
            exit_code=self._streaming_exit_code if self._streaming_exit_code >= 0 else -1,
            command_not_found=(self._streaming_exit_code < 0),
        )

    def set_streaming_chunks(self, chunks) -> None:
        """Configure ``[(stream, chunk), ...]`` replayed by run_streaming_captured."""
        self._streaming_chunks = list(chunks)

    def open_interactive(self, container: str, argv: List[str]) -> ProcessResult:
        """Fake interactive session: record (container, argv), return the
        configured streaming exit code."""
        self.interactive_calls.append((container, list(argv)))
        return ProcessResult(
            stdout="", stderr="",
            exit_code=self._streaming_exit_code if self._streaming_exit_code >= 0 else -1,
            command_not_found=(self._streaming_exit_code < 0),
        )

    # ------------------------------------------------------------------
    # Zero-call assertion
    # ------------------------------------------------------------------

    @property
    def total_calls(self) -> int:
        return len(self.calls) + len(self.streaming_calls) + len(self.interactive_calls)

    def assert_zero_docker_calls(self, msg: str = "") -> None:
        """Fail if any docker subprocess call was made."""
        if self.total_calls > 0:
            raise AssertionError(
                f"Expected zero docker calls, got {self.total_calls}. {msg}"
            )

    # ------------------------------------------------------------------
    # Container operations (fake implementations)
    # ------------------------------------------------------------------

    def list_containers(self, all: bool = False) -> ProcessResult:
        """Fake container list."""
        self.calls.append(("list_containers", {"all": all}))
        return self._default_captured or ProcessResult(
            stdout="", stderr="", exit_code=0
        )

    def stop_container(self, container_name: str, timeout: int = 10) -> ProcessResult:
        """Fake container stop."""
        self.calls.append(("stop_container", {"name": container_name, "timeout": timeout}))
        return self._default_captured or ProcessResult(
            stdout="", stderr="", exit_code=0
        )

    def remove_container(self, container_name: str, force: bool = False) -> ProcessResult:
        """Fake container removal."""
        self.calls.append(("remove_container", {"name": container_name, "force": force}))
        return self._default_captured or ProcessResult(
            stdout="", stderr="", exit_code=0
        )

    def inspect_container(self, container_name: str) -> ProcessResult:
        """Fake container inspect."""
        self.calls.append(("inspect_container", {"name": container_name}))
        return self._default_captured or ProcessResult(
            stdout="[]", stderr="", exit_code=0
        )

    # ------------------------------------------------------------------
    # Image operations (fake implementations)
    # ------------------------------------------------------------------

    def list_images(self) -> ProcessResult:
        """Fake image list."""
        self.calls.append(("list_images", {}))
        return self._default_captured or ProcessResult(
            stdout="", stderr="", exit_code=0
        )

    def remove_image(self, image_name: str, force: bool = False) -> ProcessResult:
        """Fake image removal."""
        self.calls.append(("remove_image", {"name": image_name, "force": force}))
        return self._default_captured or ProcessResult(
            stdout="", stderr="", exit_code=0
        )

    def pull_image(self, image_name: str) -> ProcessResult:
        """Fake image pull."""
        self.calls.append(("pull_image", {"name": image_name}))
        return self._default_captured or ProcessResult(
            stdout="", stderr="", exit_code=0
        )

    def tag_image(self, source: str, target: str) -> ProcessResult:
        """Fake image tag."""
        self.calls.append(("tag_image", {"source": source, "target": target}))
        return self._default_captured or ProcessResult(
            stdout="", stderr="", exit_code=0
        )


# ---------------------------------------------------------------------------
# Resource validation helpers (no subprocess)
# ---------------------------------------------------------------------------

def validate_build_resources(root: Path) -> None:
    """Validate that required build resources exist.

    Raises FileNotFoundError with descriptive message.
    """
    dockerfile = root / "container" / "Dockerfile"
    if not dockerfile.is_file():
        raise FileNotFoundError(f"Dockerfile not found: {dockerfile}")
    versions_env = root / "config" / "versions.env"
    if not versions_env.is_file():
        raise FileNotFoundError(f"versions.env not found: {versions_env}")


def validate_run_resources(workspace: Path) -> None:
    """Validate that *workspace* exists and is readable.

    Raises FileNotFoundError, PermissionError, or NotADirectoryError.
    """
    if not workspace.exists():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    if not workspace.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {workspace}")
    if not os.access(str(workspace), os.R_OK):
        raise PermissionError(f"Workspace is not readable: {workspace}")


def validate_proxy_config(proxy_config: Path) -> None:
    """Validate that proxy config exists and is readable."""
    if not proxy_config.is_file():
        raise FileNotFoundError(
            f"Proxy network mode requires {proxy_config}. "
            "Please create the proxy configuration first."
        )
    if not os.access(str(proxy_config), os.R_OK):
        raise PermissionError(f"Proxy config is not readable: {proxy_config}")


# ---------------------------------------------------------------------------
# Cross-platform argv formatter for dry-run display
# ---------------------------------------------------------------------------

def format_argv_display(argv: List[str]) -> str:
    """Format an argv list for human-readable display.

    Uses ``shlex.join`` on POSIX, ``subprocess.list2cmdline`` on Windows.
    """
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)
