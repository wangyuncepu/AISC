"""Integration: build cancellation kills the Docker child (S0.5 DoD).

Verifies ``RealDockerExecutor.run_streaming_captured`` SIGKILLs the docker
client's process group when its read loop is interrupted (cancel), so a
cancelled build leaves no docker-client orphan. BuildKit daemon cleanup is
Docker's concern; the CLI's contract is to kill its own child process group.

Skips without Docker.
"""

import os
import shutil
import subprocess
import tempfile
import time
import unittest

from aisc.adapters.docker_ import RealDockerExecutor
from tests.integration.docker._session_helpers import docker_available, image_present

IMAGE = "super-claude:latest"


@unittest.skipUnless(
    os.name == "posix" and docker_available(),
    "requires POSIX (process-group signaling) + Docker daemon",
)
class TestBuildCancellationIntegration(unittest.TestCase):
    def test_cancel_killpgs_docker_child(self):
        tmp = tempfile.mkdtemp(prefix="aisc-cancel-")
        try:
            dockerfile = os.path.join(tmp, "Dockerfile")
            # alpine is tiny; the sleep keeps the build from completing before
            # the cancel fires.
            with open(dockerfile, "w") as f:
                f.write("FROM alpine\nRUN echo marker && sleep 60\n")
            tag = "aisc-cancel-test:latest"

            exec_ = RealDockerExecutor()

            def on_chunk(stream, chunk):
                # Cancel on the very first output chunk (BuildKit streams step
                # progress immediately), exercising the killpg path.
                raise KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                exec_.run_streaming_captured(
                    ["build", "-f", dockerfile, "-t", tag, tmp], on_chunk,
                    timeout=120,
                )

            # The docker build client (the CLI's child) must be gone. Poll briefly
            # since killpg + reap is async.
            deadline = time.time() + 10
            while time.time() < deadline:
                r = subprocess.run(
                    ["pgrep", "-f", f"docker build -f {dockerfile}"],
                    capture_output=True, text=True, timeout=5,
                )
                if not r.stdout.strip():
                    break
                time.sleep(0.5)
            assert not r.stdout.strip(), (
                f"docker build client still running after cancel: {r.stdout!r}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            # Best-effort: remove the partial image if any step completed.
            subprocess.run(["docker", "rmi", "-f", "aisc-cancel-test:latest"],
                           capture_output=True, text=True, timeout=15)


if __name__ == "__main__":
    unittest.main()
