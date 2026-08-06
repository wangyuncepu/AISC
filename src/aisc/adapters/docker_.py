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
import select
import shlex
import signal
import shutil
import subprocess
import sys
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
# Real Docker executor (production)
# ---------------------------------------------------------------------------

class RealDockerExecutor:
    """Real ``docker`` subprocess executor — all methods use ``subprocess``."""

    _PREFLIGHT_TIMEOUT = 8.0
    _INSPECT_TIMEOUT = 10.0

    def __init__(self, docker_path: Optional[str] = None):
        self._docker_path: Optional[str] = docker_path

    def _resolve_path(self) -> Optional[str]:
        if self._docker_path is not None:
            return self._docker_path
        self._docker_path = shutil.which("docker")
        return self._docker_path

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
                timeout=self._PREFLIGHT_TIMEOUT,
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
            proc = subprocess.run([dp] + list(docker_argv), timeout=timeout)
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
        (cancel/error) the child's whole process group is SIGKILLed so Docker
        build subprocesses do not outlive the CLI."""
        dp = self._resolve_path() or "docker"
        try:
            proc = subprocess.Popen(
                [dp] + list(docker_argv),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,  # own process group -> cancel can killpg
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
        streams = {proc.stdout: "stdout", proc.stderr: "stderr"}
        open_fds = list(streams.keys())
        try:
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
        except BaseException:
            # Cancel or error: kill the Docker child's whole process group.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            raise

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
    # run_non_interactive
    # ------------------------------------------------------------------

    def run_non_interactive(self, docker_argv: List[str],
                            *, timeout: Optional[float] = None) -> ProcessResult:
        """Fake non-interactive — tracks call, returns streaming exit code."""
        self.streaming_calls.append(list(docker_argv))
        return ProcessResult(
            stdout="", stderr="",
            exit_code=self._streaming_exit_code if self._streaming_exit_code >= 0 else -1,
            command_not_found=(self._streaming_exit_code < 0),
        )

    def set_streaming_exit(self, code: int) -> None:
        self._streaming_exit_code = code

    # ------------------------------------------------------------------
    # run_streaming_captured (build --events)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Zero-call assertion
    # ------------------------------------------------------------------

    @property
    def total_calls(self) -> int:
        return len(self.calls) + len(self.streaming_calls)

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
