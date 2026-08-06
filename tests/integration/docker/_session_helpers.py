"""Shared helpers for session integration tests (real Docker + image).

These tests require the Docker daemon and the ``super-claude:latest`` image
(which includes ``/usr/local/bin/aisc-session-wrapper``). They skip cleanly
otherwise so PRs touching only Python never break on a Docker-less CI.
"""

import os
import pty
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

IMAGE = "super-claude:latest"


def get_aisc_executable():
    venv_bin = Path(sys.executable).parent
    aisc_path = venv_bin / "aisc"
    if not aisc_path.exists():
        raise unittest.SkipTest("aisc executable not found in venv")
    return str(aisc_path)


def docker_available():
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False


def image_present(image):
    try:
        r = subprocess.run(["docker", "image", "inspect", image],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def script_present(name):
    """True if the image ships an executable /usr/local/bin/<name>.

    Used to skip integration tests when the local image predates the wrapper
    (S0.3) or inspector (S0.4) the test needs.
    """
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "sh", IMAGE,
             "-c", f"test -x /usr/local/bin/{name}"],
            capture_output=True, text=True, timeout=20,
        )
        return r.returncode == 0
    except Exception:
        return False


def docker_ready():
    return docker_available() and image_present(IMAGE)


def integration_ready():
    """Image has the S0.3 session wrapper (required by session integration tests)."""
    return docker_ready() and script_present("aisc-session-wrapper")


def open_bash_session(aisc, workspace, runtime_id, session_id, *,
                      send="exit\n", settle=1.0, timeout=30.0):
    """Drive ``aisc session open --agent bash`` through a PTY to completion.

    Writes *send* once bash has started, then reads until the CLI exits or
    *timeout* elapses. Returns ``(returncode, output_text)``.
    """
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [aisc, "session", "open", "--runtime-id", runtime_id,
         "--session-id", session_id, "--agent", "bash",
         "--workspace", workspace],
        stdin=slave, stdout=slave, stderr=slave, close_fds=True,
    )
    os.close(slave)
    time.sleep(settle)
    try:
        if send:
            os.write(master, send.encode())
    except OSError:
        pass
    out = bytearray()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if chunk:
            out += chunk
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    try:
        os.close(master)
    except OSError:
        pass
    return proc.returncode, out.decode("utf-8", "replace")


def start_session_bg(aisc, workspace, runtime_id, session_id, *,
                     agent="bash", send="", settle=1.5):
    """Start ``aisc session open`` in the background, return ``(proc, master)``.

    The caller owns ``proc`` and ``master`` and must terminate/clean both.
    """
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [aisc, "session", "open", "--runtime-id", runtime_id,
         "--session-id", session_id, "--agent", agent,
         "--workspace", workspace],
        stdin=slave, stdout=slave, stderr=slave, close_fds=True,
    )
    os.close(slave)
    time.sleep(settle)
    if send:
        try:
            os.write(master, send.encode())
        except OSError:
            pass
    return proc, master


class BaseSessionIntegration(unittest.TestCase):
    """Start a runtime, exercise session commands, clean up container + workspace."""

    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="aisc-sess-it-")
        self.aisc = get_aisc_executable()
        self.runtime_id = str(uuid.uuid4())
        self.container_name = f"aisc-wb-{self.runtime_id.split('-', 1)[0]}"

    def tearDown(self):
        subprocess.run(["docker", "rm", "-f", self.container_name],
                       capture_output=True, text=True, timeout=15)
        # Runtime container is root and writes into the bind-mounted workspace;
        # clear root-owned files via a throwaway container so the host can rmdir.
        subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "sh",
             "-v", f"{self.workspace}:/w", IMAGE,
             "-c", "rm -rf /w/* /w/.[!.]* /w/..?* 2>/dev/null; exit 0"],
            capture_output=True, text=True, timeout=30,
        )
        shutil.rmtree(self.workspace, ignore_errors=True)

    def start_runtime(self, scope="project"):
        r = subprocess.run(
            [self.aisc, "runtime", "start", "--runtime-id", self.runtime_id,
             "--workspace", self.workspace, "--network", "direct",
             "--scope", scope, "--format", "json"],
            capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, f"runtime start failed: {r.stderr}"
        return r

    def session_list(self):
        return subprocess.run(
            [self.aisc, "session", "list", "--runtime-id", self.runtime_id,
             "--workspace", self.workspace, "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )

    def session_terminate(self, session_id, grace=5.0):
        return subprocess.run(
            [self.aisc, "session", "terminate", "--runtime-id", self.runtime_id,
             "--session-id", session_id, "--workspace", self.workspace,
             "--grace", str(grace), "--format", "json"],
            capture_output=True, text=True, timeout=60,
        )

    def container_procs(self, name):
        """Return PIDs of processes whose comm == *name* in the container.

        The runtime image ships no ``pgrep``/``ps``, so scan ``/proc`` via the
        container's python3 (comm is truncated to 15 chars, which is enough for
        ``sleep``/``bash``).
        """
        script = (
            "import os,sys;"
            "print('\\n'.join(p for p in os.listdir('/proc') if p.isdigit() "
            "and open('/proc/'+p+'/comm').read().strip()==sys.argv[1]))"
        )
        r = subprocess.run(
            ["docker", "exec", self.container_name, "python3", "-c", script, name],
            capture_output=True, text=True, timeout=15,
        )
        return [ln for ln in r.stdout.splitlines() if ln.strip()]
