"""Integration test: container web-service access with real Docker (svc-6).

End-to-end over the real super-claude image: runtime start publishes the
gateway, `aisc runtime services` exposes/lists, an in-container loopback
HTTP server becomes reachable from the host through the canonical URL, and
unregistered/unexposed ports are refused. Skips when Docker, the image, or
the in-image gateway (svc-1) is absent so pre-rebuild checkouts still pass.
"""

import http.client
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


def get_aisc_executable():
    """The CLI under test — venv `aisc` by default, or ``AISC_CLI_EXECUTABLE``
    (same convention as tests/test_cli_fixtures.py: point it at the frozen
    sidecar to exercise the shipped binary)."""
    import os
    import sys

    override = os.environ.get("AISC_CLI_EXECUTABLE")
    if override:
        return override
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


def _gateway_in_image(image):
    """The svc-1 gateway/helper must be baked in (skips pre-rebuild images)."""
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "sh", image,
             "-c", "command -v aisc-web-gateway && command -v aisc-web-expose"],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0
    except Exception:
        return False


@unittest.skipUnless(
    _docker_available() and _image_present("super-claude:latest")
    and _gateway_in_image("super-claude:latest"),
    "requires Docker daemon + super-claude:latest image with the svc-1 gateway",
)
class TestWebServicesIntegration(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="aisc-web-it-")
        self.aisc = get_aisc_executable()
        self.runtime_id = str(uuid.uuid4())
        self.container_name = f"aisc-wb-{self.runtime_id.split('-', 1)[0]}"
        self.registry_root = None  # filled after start

    def tearDown(self):
        subprocess.run(["docker", "rm", "-f", self.container_name],
                       capture_output=True, text=True, timeout=15)
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

    def _services(self):
        r = self._run("services", "--runtime-id", self.runtime_id)
        self.assertEqual(r.returncode, 0, f"services failed: {r.stderr}")
        return json.loads(r.stdout)["data"]

    def _get_via_gateway(self, host_port, host, path="/"):
        # *.localhost resolution is a browser concern; the test drives the
        # same wire bytes at 127.0.0.1 with the canonical Host header.
        conn = http.client.HTTPConnection("127.0.0.1", host_port, timeout=10)
        conn.request("GET", path, headers={"Host": host})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_runtime_web_services_end_to_end(self):
        # --- start: the container must come up with a published gateway ---
        r = self._run("start", "--runtime-id", self.runtime_id,
                      "--network", "direct", "--scope", "project")
        self.assertEqual(r.returncode, 0, f"start failed: {r.stderr}")

        # --- inspect carries ready web_access (gateway probed live) ---
        r = self._run("inspect", "--runtime-id", self.runtime_id)
        self.assertEqual(r.returncode, 0, f"inspect failed: {r.stderr}")
        web_access = json.loads(r.stdout)["data"]["web_access"]
        self.assertEqual(web_access["state"], "ready", web_access)
        host_port = web_access["host_port"]
        self.assertTrue(47000 <= host_port <= 47999, host_port)

        # --- services: empty but gateway-ready ---
        data = self._services()
        self.assertEqual(data["schema_version"], "aisc.runtime-services/v1")
        self.assertEqual(data["gateway"]["state"], "ready")
        self.assertEqual(data["services"], [])

        # --- unregistered port is refused ---
        status, body = self._get_via_gateway(host_port, "p3999.localhost")
        self.assertEqual(status, 404)
        self.assertIn(b"AISC_WEB_PORT_NOT_EXPOSED", body)

        # --- start a loopback-only HTTP server inside the container ---
        subprocess.run(
            ["docker", "exec", "-d", self.container_name,
             "python3", "-m", "http.server", "3000", "--bind", "127.0.0.1"],
            capture_output=True, text=True, timeout=30, check=True,
        )

        # --- expose via the host CLI (same manifest as the in-container helper) ---
        r = self._run("services", "expose", "--runtime-id", self.runtime_id,
                      "--port", "3000", "--name", "it http")
        self.assertEqual(r.returncode, 0, f"expose failed: {r.stderr}")
        data = json.loads(r.stdout)["data"]
        self.assertEqual(len(data["services"]), 1)
        svc = data["services"][0]
        self.assertEqual(svc["port"], 3000)
        self.assertEqual(svc["name"], "it http")
        self.assertEqual(svc["url"], f"http://p3000.localhost:{host_port}/")

        # --- the canonical URL serves the container loopback service ---
        status, _body = self._get_via_gateway(host_port, "p3000.localhost", "/?x=1")
        self.assertEqual(status, 200)

        # --- a second registered port is refused while its target is down ---
        r = self._run("services", "expose", "--runtime-id", self.runtime_id,
                      "--port", "5173")
        self.assertEqual(r.returncode, 0, r.stderr)
        status, body = self._get_via_gateway(host_port, "p5173.localhost")
        self.assertEqual(status, 502)
        self.assertIn(b"AISC_WEB_TARGET_UNAVAILABLE", body)

        # --- bad host is refused ---
        status, body = self._get_via_gateway(host_port, "evil.localhost")
        self.assertEqual(status, 400)
        self.assertIn(b"AISC_WEB_BAD_HOST", body)

        # --- unexpose closes the door; list reflects it ---
        r = self._run("services", "unexpose", "--runtime-id", self.runtime_id,
                      "--port", "3000")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)["data"]
        self.assertEqual([s["port"] for s in data["services"]], [5173])
        status, body = self._get_via_gateway(host_port, "p3000.localhost")
        self.assertEqual(status, 404)

        # --- stop: gateway reports runtime_not_running, no openable state ---
        r = self._run("stop", "--runtime-id", self.runtime_id)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self._run("inspect", "--runtime-id", self.runtime_id)
        web_access = json.loads(r.stdout)["data"]["web_access"]
        self.assertEqual(web_access["state"], "unavailable")
        self.assertEqual(web_access["reason"], "runtime_not_running")

        # --- restart keeps the SAME mapping (URL does not drift) ---
        r = self._run("restart", "--runtime-id", self.runtime_id)
        self.assertEqual(r.returncode, 0, r.stderr)
        web_access = json.loads(
            self._run("inspect", "--runtime-id", self.runtime_id).stdout
        )["data"]["web_access"]
        self.assertEqual(web_access["state"], "ready")
        self.assertEqual(web_access["host_port"], host_port)


if __name__ == "__main__":
    unittest.main()
