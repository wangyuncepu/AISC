"""Cross-platform tests for ``RealDockerExecutor.run_streaming_captured``.

``run_streaming_captured`` (the ``build --events`` path) is POSIX-only in
implementation: ``select`` only supports sockets on Windows and
``os.killpg``/``signal.SIGKILL`` do not exist there.  The Windows branch
uses reader threads + a queue instead.  These tests exercise the real
subprocess path (injecting ``sys.executable`` as the "docker" binary) and
run on **any** OS — Windows CI covers the thread branch, POSIX CI covers
the select branch.

The kill-path tests are covered here with a pidfile + platform-aware
aliveness probe (Windows forbids ``os.kill(pid, 0)``).
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from aisc.adapters.docker_ import RealDockerExecutor

# Child script template: pidfile + two chunks then sleep, keeping both
# pipes open until killed.
_CHILD = (
    "import os, sys, time\n"
    "open({pidfile!r}, 'w').write(str(os.getpid()))\n"
    "sys.stdout.write('chunk-a\\n'); sys.stdout.flush()\n"
    "time.sleep(1)\n"
    "sys.stdout.write('chunk-b\\n'); sys.stdout.flush()\n"
    "time.sleep(60)\n"
)


def _process_alive(pid: int) -> bool:
    """Cross-platform liveness probe (Windows has no ``os.kill(pid, 0)``)."""
    if os.name == "posix":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    r = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True, text=True, timeout=10,
    )
    return str(pid) in r.stdout


class TestRunStreamingCapturedCrossPlatform(unittest.TestCase):
    def setUp(self):
        self.executor = RealDockerExecutor(docker_path=sys.executable)
        self.chunks = []

    def _on_chunk(self, stream, chunk):
        self.chunks.append((stream, chunk))

    def test_streams_both_channels_in_realtime(self):
        result = self.executor.run_streaming_captured(
            ["-u", "-c",
             "import sys; print('out-1'); sys.stderr.write('err-1\\n'); print('out-2')"],
            self._on_chunk, timeout=15,
        )
        assert result.exit_code == 0
        streams = dict((s, "".join(c for st, c in self.chunks if st == s))
                       for s in ("stdout", "stderr"))
        assert "out-1" in streams["stdout"]
        assert "out-2" in streams["stdout"]
        assert "err-1" in streams["stderr"]

    def test_nonzero_exit_code(self):
        result = self.executor.run_streaming_captured(
            ["-u", "-c", "print('boom'); import sys; sys.exit(7)"],
            self._on_chunk, timeout=15,
        )
        assert result.exit_code == 7
        assert not result.command_not_found

    def test_command_not_found(self):
        missing = str(Path(tempfile.gettempdir()) / "aisc-missing-docker-xyz.exe")
        executor = RealDockerExecutor(docker_path=missing)
        result = executor.run_streaming_captured(["info"], self._on_chunk)
        assert result.command_not_found
        assert result.exit_code == -1

    def test_invalid_utf8_decoded_with_replace(self):
        result = self.executor.run_streaming_captured(
            ["-u", "-c",
             "import sys; sys.stdout.buffer.write(b'\\xff\\xfe bad\\n'); "
             "sys.stdout.flush()"],
            self._on_chunk, timeout=15,
        )
        assert result.exit_code == 0
        stdout = "".join(c for s, c in self.chunks if s == "stdout")
        assert "�" in stdout  # replacement character, no crash

    def test_exception_in_on_chunk_kills_child(self):
        with tempfile.TemporaryDirectory() as td:
            pidfile = Path(td) / "child.pid"

            def cancelling_on_chunk(stream, chunk):
                self.chunks.append((stream, chunk))
                if "chunk-b" in chunk:
                    raise KeyboardInterrupt()  # simulate user cancel

            with self.assertRaises(KeyboardInterrupt):
                self.executor.run_streaming_captured(
                    ["-u", "-c", _CHILD.format(pidfile=str(pidfile))],
                    cancelling_on_chunk, timeout=30,
                )
            pid = int(pidfile.read_text())
            self._assert_eventually_dead(pid)

    def test_timeout_kills_child(self):
        with tempfile.TemporaryDirectory() as td:
            pidfile = Path(td) / "child.pid"
            # Child detaches its pipes via dup2 (a plain close() does not
            # release the inherited pipe handles on Windows until exit) but
            # keeps running -> drain finishes, proc.wait(timeout) expires
            # -> kill path.
            script = (
                "import os, sys, time\n"
                f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
                "nul = open(os.devnull, 'wb')\n"
                "os.dup2(nul.fileno(), 1); os.dup2(nul.fileno(), 2)\n"
                "time.sleep(60)\n"
            )
            with self.assertRaises(subprocess.TimeoutExpired):
                self.executor.run_streaming_captured(
                    ["-u", "-c", script], self._on_chunk, timeout=2,
                )
            pid = int(pidfile.read_text())
            self._assert_eventually_dead(pid)

    def _assert_eventually_dead(self, pid):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not _process_alive(pid):
                return
            time.sleep(0.2)
        self.fail(f"child process {pid} still alive after kill")


if __name__ == "__main__":
    unittest.main()
