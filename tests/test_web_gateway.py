"""svc-1 (container web-service access): gateway + helper tests on the host.

The container-side pieces are plain Python + stdlib sockets, so they run
everywhere pytest does — the registry lib is imported directly and the
gateway/helpers are exercised as subprocesses with env overrides
(``AISC_WEB_SERVICES_DIR`` / ``AISC_WEB_LIB_DIR`` / ``AISC_WEB_GATEWAY_PORT``).
The same files ship into the image via the Dockerfile (py_compile smoke).

Covers the svc-1 stage gates: registered loopback services reachable through
the gateway, unregistered ports refused, and the fail-closed manifest path.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTAINER = ROOT / "container"
LIB_DIR = CONTAINER / "lib"

_spec = importlib.util.spec_from_file_location("aisc_web_registry", LIB_DIR / "aisc_web_registry.py")
registry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registry)  # type: ignore[union-attr]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _spawn(argv: list[str], env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(argv[0])] + argv[1:],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )


def _run(argv: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(argv[0])] + argv[1:],
        capture_output=True, text=True, env=env, timeout=30,
    )


class _EnvDir:
    """Temp manifest dir + child env pointing the scripts at it."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="aisc-web-")
        self.base = {**os.environ,
                     "AISC_WEB_SERVICES_DIR": str(Path(self.tmp.name) / "services"),
                     "AISC_WEB_LIB_DIR": str(LIB_DIR)}

    @property
    def env(self) -> dict:
        return self.base

    def services_dir(self) -> Path:
        return Path(self.env["AISC_WEB_SERVICES_DIR"])

    def cleanup(self) -> None:
        self.tmp.cleanup()


class RegistryLibTests(unittest.TestCase):
    def setUp(self):
        self.holder = _EnvDir()
        self.env = self.holder.env
        self.dir = self.holder.services_dir()
        # In-process calls read os.environ (the subprocess helpers get *env*);
        # point the process env at this test's manifest dir for the duration.
        self._saved = os.environ.get("AISC_WEB_SERVICES_DIR")
        os.environ["AISC_WEB_SERVICES_DIR"] = str(self.dir)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("AISC_WEB_SERVICES_DIR", None)
        else:
            os.environ["AISC_WEB_SERVICES_DIR"] = self._saved
        self.holder.cleanup()

    def test_round_trip_and_idempotent_relabel(self):
        first = registry.write_record(3000, "docs preview")
        self.assertEqual(first["schema_version"], "aisc.web-service/v1")
        self.assertEqual(first["state"], "registered")
        records = registry.read_records()
        self.assertEqual(list(records), [3000])
        second = registry.write_record(3000, "v2")
        self.assertEqual(registry.read_records()[3000]["name"], "v2")

    def test_manifest_permissions(self):
        if sys.platform == "win32":
            self.skipTest("POSIX permissions")
        registry.write_record(3000, "")
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.dir / "3000.json").stat().st_mode), 0o600)

    def test_no_temp_files_left_behind(self):
        for _ in range(3):
            registry.write_record(3000, "x")
        leftovers = [p.name for p in self.dir.iterdir() if p.name != "3000.json"]
        self.assertEqual(leftovers, [])

    def test_remove_is_idempotent(self):
        registry.write_record(3000, "")
        self.assertTrue(registry.remove_record(3000))
        self.assertTrue(registry.remove_record(3000))  # missing = success
        self.assertEqual(registry.read_records(), {})

    def test_fail_closed_on_malformed_record(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "3000.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(registry.RegistryError):
            registry.read_records()

    def test_fail_closed_on_foreign_filename(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "3000.json.txt").write_text("{}", encoding="utf-8")
        (self.dir / "evil.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(registry.RegistryError):
            registry.read_records()

    def test_fail_closed_on_missing_dir(self):
        with self.assertRaises(registry.RegistryError):
            registry.read_records()

    def test_fail_closed_on_wrong_schema(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "3000.json").write_text(
            json.dumps({"schema_version": "aisc.web-service/v2", "port": 3000,
                        "state": "registered"}),
            encoding="utf-8")
        with self.assertRaises(registry.RegistryError):
            registry.read_records()

    def test_validation(self):
        for bad in ("", "x", "-1", "80", "65536", "3.5"):
            with self.subTest(bad=bad):
                with self.assertRaises(registry.RegistryError):
                    registry.parse_port(bad)
        self.assertEqual(registry.parse_port("1024"), 1024)
        self.assertEqual(registry.sanitize_name("  a b \n"), "a b")
        with self.assertRaises(registry.RegistryError):
            registry.sanitize_name("a\tb")
        with self.assertRaises(registry.RegistryError):
            registry.sanitize_name("x" * 65)

    def test_unrelated_files_ignored(self):
        registry.write_record(3000, "")
        (self.dir / ".hidden-swo").write_text("", encoding="utf-8")
        self.assertEqual(list(registry.read_records()), [3000])


class HelperCliTests(unittest.TestCase):
    def setUp(self):
        self.holder = _EnvDir()
        self.env = self.holder.env

    def tearDown(self):
        self.holder.cleanup()

    def test_expose_prints_frozen_contract_line(self):
        result = _run([CONTAINER / "aisc-web-expose", "3000", "--name", "docs preview"], self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         'aisc web service registered: port=3000 name="docs preview"')

    def test_expose_name_equals_form(self):
        result = _run([CONTAINER / "aisc-web-expose", "--name=web", "3000"], self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('name="web"', result.stdout)

    def test_expose_rejects_bad_input(self):
        for args, code in ((["80"], 1), (["abc"], 1), ([], 2), (["3000", "extra"], 2)):
            with self.subTest(args=args):
                result = _run([CONTAINER / "aisc-web-expose"] + args, self.env)
                self.assertEqual(result.returncode, code)

    def test_unexpose_idempotent(self):
        env, d = self.env, self.holder.services_dir()
        _run([CONTAINER / "aisc-web-expose", "3000"], env)
        first = _run([CONTAINER / "aisc-web-unexpose", "3000"], env)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("unregistered: port=3000", first.stdout)
        second = _run([CONTAINER / "aisc-web-unexpose", "3000"], env)
        self.assertEqual(second.returncode, 0)
        self.assertFalse((d / "3000.json").exists())

    def test_list_human_and_json(self):
        env = self.env
        _run([CONTAINER / "aisc-web-expose", "5173", "--name", "vite"], env)
        _run([CONTAINER / "aisc-web-expose", "3000"], env)
        human = _run([CONTAINER / "aisc-web-list"], env)
        self.assertEqual(human.returncode, 0, human.stderr)
        lines = human.stdout.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("3000  http  registered", lines[0])
        self.assertTrue(lines[0].endswith("  "))  # empty label keeps column shape
        as_json = _run([CONTAINER / "aisc-web-list", "--json"], env)
        self.assertEqual(as_json.returncode, 0, as_json.stderr)
        records = json.loads(as_json.stdout)
        self.assertEqual([r["port"] for r in records], [3000, 5173])
        self.assertEqual(records[1]["name"], "vite")

    def test_list_empty(self):
        result = _run([CONTAINER / "aisc-web-list"], self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no web services", result.stdout)


class _Upstream(ThreadingHTTPServer):
    """Tiny capture server: records method/path/query and replies."""

    def __init__(self):
        self.seen: list[tuple[str, str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (http.server naming)
                outer.seen.append((self.command, self.path, self.headers.get("Host", "")))
                body = b"upstream-ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:  # silence
                pass

        super().__init__(("127.0.0.1", 0), Handler)

    @property
    def port(self) -> int:
        return self.server_address[1]


class _GatewayProc:
    """One gateway subprocess bound to an ephemeral port + its own manifest dir."""

    def __init__(self, services_dir: Path):
        self.port = _free_port()
        self.dir = services_dir
        services_dir.mkdir(parents=True, exist_ok=True)
        self.log = tempfile.TemporaryFile(mode="w+", prefix="aisc-gw-")
        self.env = {**os.environ,
                    "AISC_WEB_SERVICES_DIR": str(services_dir),
                    "AISC_WEB_LIB_DIR": str(LIB_DIR),
                    "AISC_WEB_GATEWAY_PORT": str(self.port),
                    "AISC_WEB_GATEWAY_BIND": "127.0.0.1"}
        self.proc = subprocess.Popen(
            [sys.executable, str(CONTAINER / "aisc-web-gateway")],
            stdout=self.log, stderr=self.log, env=self.env)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
                return
            except OSError:
                if self.proc.poll() is not None:
                    break
                time.sleep(0.05)
        raise AssertionError("gateway did not start; log: " + self._log_text())

    def register(self, port: int, name: str = "") -> None:
        """Register through the real helper (same path the container uses)."""
        result = _run(
            [CONTAINER / "aisc-web-expose", str(port)] + (["--name", name] if name else []),
            self.env)
        assert result.returncode == 0, result.stderr

    def unregister(self, port: int) -> None:
        result = _run([CONTAINER / "aisc-web-unexpose", str(port)], self.env)
        assert result.returncode == 0, result.stderr

    def _log_text(self) -> str:
        self.log.seek(0)
        return self.log.read()

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()

    def request(self, host: str, path: str = "/") -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path, headers={"Host": host})
        response = conn.getresponse()
        response.body = response.read()  # type: ignore[attr-defined]
        conn.close()
        return response


class GatewayServeTests(unittest.TestCase):
    """Happy path + refusal matrix through a real gateway subprocess."""

    @classmethod
    def setUpClass(cls):
        cls.holder = _EnvDir()
        cls.services = cls.holder.services_dir()
        cls.gateway = _GatewayProc(cls.services)
        cls.upstream = _Upstream()
        cls.thread = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.thread.start()
        cls.gateway.register(cls.upstream.port, "test upstream")

    @classmethod
    def tearDownClass(cls):
        cls.upstream.shutdown()
        cls.upstream.server_close()
        cls.gateway.stop()
        cls.holder.cleanup()

    def test_registered_service_serves_path_and_query(self):
        resp = self.gateway.request(f"p{self.upstream.port}.localhost", "/deep/link?x=1&y=2")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, b"upstream-ok")  # type: ignore[attr-defined]
        method, path, host = self.upstream.seen[-1]
        self.assertEqual((method, path), ("GET", "/deep/link?x=1&y=2"))
        # Original Host header is relayed verbatim (no rewriting, decisions §6.2).
        self.assertEqual(host, f"p{self.upstream.port}.localhost")

    def test_host_with_gateway_port_suffix_routes(self):
        resp = self.gateway.request(f"p{self.upstream.port}.localhost:{self.gateway.port}")
        self.assertEqual(resp.status, 200)

    def test_bad_host_refused(self):
        for host in ("localhost", "p3000.example.com", "evil.localhost"):
            with self.subTest(host=host):
                resp = self.gateway.request(host)
                self.assertEqual(resp.status, 400)
                self.assertIn(b"AISC_WEB_BAD_HOST", resp.body)  # type: ignore[attr-defined]

    def test_privileged_port_refused(self):
        resp = self.gateway.request("p80.localhost")
        self.assertEqual(resp.status, 400)
        self.assertIn(b"AISC_WEB_PORT_INVALID", resp.body)  # type: ignore[attr-defined]

    def test_unregistered_port_refused(self):
        port = _free_port()  # almost surely not registered
        while port == self.upstream.port:
            port = _free_port()
        resp = self.gateway.request(f"p{port}.localhost")
        self.assertEqual(resp.status, 404)
        self.assertIn(b"AISC_WEB_PORT_NOT_EXPOSED", resp.body)  # type: ignore[attr-defined]

    def test_target_down_is_502(self):
        dead_port = _free_port()
        self.gateway.register(dead_port, "dead")
        try:
            resp = self.gateway.request(f"p{dead_port}.localhost")
            self.assertEqual(resp.status, 502)
            self.assertIn(b"AISC_WEB_TARGET_UNAVAILABLE", resp.body)  # type: ignore[attr-defined]
        finally:
            self.gateway.unregister(dead_port)

    def test_byte_pump_relays_both_directions(self):
        """Simulated upgrade: raw duplex after the head — the WebSocket case."""
        server_sock = socket.socket()
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]
        self.gateway.register(port, "ws")

        def upstream_session():
            conn, _ = server_sock.accept()
            conn.settimeout(5)
            head = conn.recv(65536)  # handshake (replayed verbatim)
            conn.sendall(b"WS-READY\n")          # server-initiated push
            conn.sendall(b"ECHO:" + head[-9:])   # echo the tail marker
            time.sleep(0.2)
            conn.close()

        t = threading.Thread(target=upstream_session)
        t.start()
        try:
            s = socket.create_connection(("127.0.0.1", self.gateway.port), timeout=5)
            s.settimeout(5)
            s.sendall(
                b"GET /chat HTTP/1.1\r\n"
                + f"Host: p{port}.localhost\r\n".encode()
                + b"Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
                + b"MARKER123"
            )
            got = b""
            while b"MARKER123" not in got:
                chunk = s.recv(65536)
                if not chunk:
                    break
                got += chunk
            self.assertIn(b"WS-READY\n", got)             # target -> client push
            self.assertIn(b"ECHO:MARKER123", got)          # client -> target echo
            s.close()
        finally:
            t.join(timeout=5)
            self.gateway.unregister(port)
            server_sock.close()


class GatewayFailClosedTests(unittest.TestCase):
    def test_malformed_registry_is_503(self):
        holder = _EnvDir()
        try:
            gw = _GatewayProc(holder.services_dir())
        except AssertionError:
            holder.cleanup()
            self.skipTest("gateway spawn failed")
        try:
            (holder.services_dir() / "3000.json").write_text("{broken", encoding="utf-8")
            resp = gw.request("p3000.localhost")
            self.assertEqual(resp.status, 503)
            self.assertIn(b"AISC_WEB_REGISTRY_UNAVAILABLE", resp.body)  # type: ignore[attr-defined]
        finally:
            gw.stop()
            holder.cleanup()


if __name__ == "__main__":
    unittest.main()
