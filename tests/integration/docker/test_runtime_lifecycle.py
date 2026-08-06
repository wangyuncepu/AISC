"""Integration test: full runtime lifecycle with real Docker + super-claude image.

Satisfies the S0.2 DoD: "from empty Docker state, start -> remove full chain
passes, every JSON envelope and process exit code consistent".

Skips entirely if Docker is unavailable or the ``super-claude:latest`` image
is absent, so this never blocks PRs that only touch Python.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path


def get_aisc_executable():
    venv_bin = Path(sys.executable).parent
    aisc_path = venv_bin / "aisc"
    if not aisc_path.exists():
        raise unittest.SkipTest("aisc executable not found in venv")
    return str(aisc_path)


def _docker_available():
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False


def _image_present(image):
    try:
        r = subprocess.run(["docker", "image", "inspect", image],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


@unittest.skipUnless(_docker_available() and _image_present("super-claude:latest"),
                     "requires Docker daemon + super-claude:latest image")
class TestRuntimeLifecycleIntegration(unittest.TestCase):
    """End-to-end runtime start/list/inspect/stop/restart/remove via the CLI."""

    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="aisc-rt-it-")
        self.aisc = get_aisc_executable()
        self.runtime_id = str(uuid.uuid4())
        self.container_name = f"aisc-wb-{self.runtime_id.split('-', 1)[0]}"

    def tearDown(self):
        # Best-effort cleanup of any container/registry left behind.
        subprocess.run(["docker", "rm", "-f", self.container_name],
                       capture_output=True, text=True, timeout=15)
        # The runtime container runs as root and writes .claude/.codex/.cc-switch
        # into the bind-mounted workspace; remove those root-owned files via a
        # throwaway container so the host can delete the temp dir.
        subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "sh",
             "-v", f"{self.workspace}:/w", "super-claude:latest",
             "-c", "rm -rf /w/* /w/.[!.]* /w/..?* 2>/dev/null; exit 0"],
            capture_output=True, text=True, timeout=30,
        )
        shutil.rmtree(self.workspace, ignore_errors=True)

    def _run(self, *args):
        return subprocess.run(
            [self.aisc, "runtime", *args, "--workspace", self.workspace,
             "--format", "json"],
            capture_output=True, text=True, timeout=120,
        )

    def test_start_list_inspect_stop_restart_remove(self):
        # --- start ---
        r = self._run("start", "--runtime-id", self.runtime_id,
                      "--network", "direct", "--scope", "project")
        self.assertEqual(r.returncode, 0, f"start failed: {r.stderr}")
        start = json.loads(r.stdout)
        self.assertEqual(start["meta"]["exit_code"], 0)
        data = start["data"]
        self.assertEqual(data["state"], "running")
        self.assertTrue(data["ready"])
        self.assertFalse(data["reused"])
        self.assertEqual(data["container_name"], self.container_name)
        self.assertTrue(data["container_id"])

        # --- list ---
        r = self._run("list")
        self.assertEqual(r.returncode, 0, f"list failed: {r.stderr}")
        runtimes = json.loads(r.stdout)["data"]["runtimes"]
        self.assertTrue(any(rt["runtime_id"] == self.runtime_id for rt in runtimes))
        row = next(rt for rt in runtimes if rt["runtime_id"] == self.runtime_id)
        self.assertEqual(row["state"], "running")
        self.assertEqual(row["registry_state"], "registered")

        # --- inspect ---
        r = self._run("inspect", "--runtime-id", self.runtime_id)
        self.assertEqual(r.returncode, 0, f"inspect failed: {r.stderr}")
        snap = json.loads(r.stdout)["data"]
        self.assertEqual(snap["state"], "running")

        # --- stop ---
        r = self._run("stop", "--runtime-id", self.runtime_id)
        self.assertEqual(r.returncode, 0, f"stop failed: {r.stderr}")
        self.assertEqual(json.loads(r.stdout)["data"]["state"], "stopped")

        # stop is idempotent
        r = self._run("stop", "--runtime-id", self.runtime_id)
        self.assertEqual(r.returncode, 0, f"stop(2) failed: {r.stderr}")

        # --- restart ---
        r = self._run("restart", "--runtime-id", self.runtime_id)
        self.assertEqual(r.returncode, 0, f"restart failed: {r.stderr}")
        self.assertEqual(json.loads(r.stdout)["data"]["state"], "running")

        # --- remove running without force is rejected ---
        r = self._run("remove", "--runtime-id", self.runtime_id)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["meta"]["exit_code"], 16)

        # --- remove with force ---
        r = self._run("remove", "--runtime-id", self.runtime_id, "--force")
        self.assertEqual(r.returncode, 0, f"remove failed: {r.stderr}")
        self.assertEqual(json.loads(r.stdout)["data"]["state"], "not_found")

        # registry is now empty for this runtime
        r = self._run("inspect", "--runtime-id", self.runtime_id)
        self.assertEqual(json.loads(r.stdout)["data"]["state"], "not_found")

    def test_concurrent_project_start_only_one_succeeds(self):
        """Two concurrent project starts on the same workspace: exactly one
        wins, the other is rejected with RUNTIME_CONFLICT(14)."""
        rid_a = str(uuid.uuid4())
        rid_b = str(uuid.uuid4())
        name_a = f"aisc-wb-{rid_a.split('-', 1)[0]}"
        name_b = f"aisc-wb-{rid_b.split('-', 1)[0]}"
        self.addCleanup(lambda: subprocess.run(
            ["docker", "rm", "-f", name_a, name_b],
            capture_output=True, text=True, timeout=20))

        def launch(rid):
            return subprocess.Popen(
                [self.aisc, "runtime", "start", "--runtime-id", rid,
                 "--workspace", self.workspace, "--network", "direct",
                 "--scope", "project", "--format", "json"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )

        pa, pb = launch(rid_a), launch(rid_b)
        out_a, _ = pa.communicate(timeout=120)
        out_b, _ = pb.communicate(timeout=120)

        codes = {pa.returncode, pb.returncode}
        # Exactly one success (0) and one conflict (14).
        self.assertIn(0, codes, f"neither succeeded: a={pa.returncode} b={pb.returncode}")
        self.assertIn(14, codes, f"expected one conflict(14); codes={codes}")

        # The conflict process must report RUNTIME_CONFLICT and not be a success.
        if pa.returncode == 0:
            conflict_out = out_b
        else:
            conflict_out = out_a
        conflict_data = json.loads(conflict_out)
        self.assertEqual(conflict_data["meta"]["exit_code"], 14)


if __name__ == "__main__":
    unittest.main()
