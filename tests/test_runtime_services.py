"""svc-2 (container web-service access): host-side runtime wiring tests.

Covers the host port allocator, the ``--publish`` argv on runtime create,
bind-conflict retry, registry metadata (and its fingerprint independence),
reuse/heal, ``web_access`` on inspect (legacy degrade), and the
``aisc runtime services`` data plane against a fake executor — no Docker
daemon required. The gateway subprocess itself is covered by
tests/test_web_gateway.py (svc-1).
"""

from __future__ import annotations

# Keep run/start paths hermetic (same guard as test_runtime_lifecycle).
import os as _os
import tempfile as _tempfile
_os.environ.setdefault("AISC_DATA_ROOT", _tempfile.mkdtemp(prefix="aisc-test-data-"))
import json
import socket
import unittest
from pathlib import Path

from aisc.adapters.container_registry import (
    list_containers_readonly,
    register as registry_register,
)
from aisc.application.runtime import (
    compute_config_fingerprint,
    inspect_runtime,
    start_runtime,
)
from aisc.application.web_gateway import (
    GatewayPortError,
    allocate_gateway_host_port,
    docker_publish_argv,
    expose_runtime_service,
    is_bind_conflict,
    probe_gateway,
    read_gateway_mapping,
    registry_host_ports,
    runtime_services,
    snapshot_web_access,
    unexpose_runtime_service,
)
from aisc.domain.models import (
    CliError,
    DockerPreflightResult,
    ImageInspectResult,
    ImageInspectStatus,
    ProcessResult,
    RuntimeExitCode,
)
from aisc.domain.web_services import (
    WEB_GATEWAY_CONTAINER_PORT,
    WEB_GATEWAY_HOST_PORT_MAX,
    WEB_GATEWAY_HOST_PORT_MIN,
)

RID = "550e8400-e29b-41d4-a716-446655440000"


class ServicesFakeExecutor:
    """Fake Docker executor with gateway-aware inspect + exec dispatch.

    ``run`` records every full argv; containers carry a gateway binding that
    appears in ``NetworkSettings.Ports`` when running and only in
    ``HostConfig.PortBindings`` when stopped. ``exec`` answers the three
    container helpers from an in-memory manifest.
    """

    def __init__(self, *, ready=True, bind_conflicts=0, image_exists=True):
        self.ready = ready
        self.image_exists = image_exists
        self.bind_conflicts = bind_conflicts  # first N run attempts fail
        self.run_calls: list[list[str]] = []
        self.exec_calls: list[list[str]] = []
        self.inspect_calls = 0
        self.manifest: dict[int, dict] = {}
        self.containers: dict[str, dict] = {}

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _arg_after(argv, flag):
        for i, a in enumerate(argv):
            if a == flag and i + 1 < len(argv):
                return argv[i + 1]
        return ""

    @staticmethod
    def _label_val(argv, label):
        needle = f"{label}="
        for a in argv:
            idx = a.find(needle)
            if idx >= 0:
                return a[idx + len(needle):]
        return ""

    def _status_str(self, state):
        return "Up 2 seconds" if state == "running" else "Exited (0) 1s ago"

    def add_runtime(self, name, rid, *, state="running", host_port=0):
        self.containers[name] = {
            "container_id": f"cid-{name}",
            "state": state,
            "runtime_id": rid,
            "workspace_key": "wskey",
            "owner": "workbench",
            "image": "super-claude:latest",
            "host_port": host_port,
        }

    # -- DockerExecutor protocol ---------------------------------------
    def preflight(self):
        return DockerPreflightResult(docker_path="/usr/bin/docker",
                                     available=True, reason="ok")

    def inspect_image(self, name):
        if self.image_exists:
            return ImageInspectResult(status=ImageInspectStatus.EXISTS, image=name,
                                      image_id="sha256:fake-image")
        return ImageInspectResult(status=ImageInspectStatus.MISSING, image=name)

    def run_captured(self, argv, *, timeout=None):
        cmd = argv[0] if argv else ""
        if cmd == "run":
            self.run_calls.append(list(argv))
            if self.bind_conflicts > 0:
                self.bind_conflicts -= 1
                port = self._publish_host_port(argv)
                return ProcessResult(
                    stdout="", exit_code=1,
                    stderr=f"docker: Error response from daemon: Bind for 127.0.0.1:{port} "
                           f"failed: port is already allocated")
            name = self._arg_after(argv, "--name")
            rid = self._label_val(argv, "io.aisc.runtime-id")
            self.containers[name] = {
                "container_id": f"cid-{name}",
                "state": "running" if self.ready else "stopped",
                "runtime_id": rid,
                "workspace_key": self._label_val(argv, "io.aisc.workspace-key"),
                "owner": self._label_val(argv, "io.aisc.owner"),
                "image": argv[-1],
                "host_port": self._publish_host_port(argv),
            }
            return ProcessResult(stdout=f"cid-{name}", stderr="", exit_code=0)
        if cmd == "exec":
            self.exec_calls.append(list(argv))
            name = argv[1]
            c = self.containers.get(name)
            if not c or c["state"] != "running":
                return ProcessResult(stdout="", stderr="container not running", exit_code=1)
            tool = argv[2].rsplit("/", 1)[-1]
            if tool == "aisc-web-list":
                return ProcessResult(stdout=json.dumps(
                    [self.manifest[p] for p in sorted(self.manifest)]),
                    stderr="", exit_code=0)
            if tool == "aisc-web-expose":
                port = int(argv[3])
                self.manifest[port] = {"schema_version": "aisc.web-service/v1",
                                       "port": port, "protocol": "http",
                                       "name": "", "state": "registered"}
                return ProcessResult(
                    stdout=f"aisc web service registered: port={port} name=\"\"",
                    stderr="", exit_code=0)
            if tool == "aisc-web-unexpose":
                self.manifest.pop(int(argv[3]), None)
                return ProcessResult(stdout="", stderr="", exit_code=0)
            # aisc-session-wrapper style (runtime-context cat)
            if "cat" in argv:
                return ProcessResult(stdout=json.dumps({
                    "schema_version": "aisc.runtime-context/v1",
                    "runtime_id": c["runtime_id"]}), stderr="", exit_code=0)
            return ProcessResult(stdout="", stderr="unknown tool", exit_code=1)
        if cmd == "ps":
            rid = self._label_val(argv, "io.aisc.runtime-id")
            lines = []
            for name, c in self.containers.items():
                if rid and c["runtime_id"] != rid:
                    continue
                if "io.aisc.managed=true" in " ".join(argv):
                    lines.append("\t".join([c["container_id"], name, c["image"],
                                            self._status_str(c["state"]), c["runtime_id"],
                                            c["workspace_key"], c["owner"]]))
                else:
                    lines.append("\t".join([c["container_id"], name,
                                            self._status_str(c["state"])]))
            return ProcessResult(stdout="\n".join(lines), stderr="", exit_code=0)
        if cmd == "start":
            name = argv[1]
            if name in self.containers:
                self.containers[name]["state"] = "running"
            return ProcessResult(stdout="", stderr="", exit_code=0)
        return ProcessResult(stdout="", stderr="", exit_code=0)

    @staticmethod
    def _publish_host_port(argv):
        for i, a in enumerate(argv):
            if a == "--publish" and i + 1 < len(argv):
                spec = argv[i + 1]
                if spec.startswith("127.0.0.1:"):
                    return int(spec.split(":")[1])
        return 0

    def inspect_container(self, name):
        self.inspect_calls += 1
        c = self.containers.get(name)
        if c is None:
            return ProcessResult(stdout="", stderr="No such container", exit_code=1)
        binding = [{"HostIp": "127.0.0.1", "HostPort": str(c["host_port"])}] \
            if c["host_port"] else None
        data = [{
            "State": {"Running": c["state"] == "running"},
            "NetworkSettings": {
                "Ports": {f"{WEB_GATEWAY_CONTAINER_PORT}/tcp": binding} if binding else {},
            },
            "HostConfig": {
                "PortBindings": {f"{WEB_GATEWAY_CONTAINER_PORT}/tcp": binding} if binding else {},
            },
        }]
        return ProcessResult(stdout=json.dumps(data), stderr="", exit_code=0)

    def stop_container(self, name, timeout=10):
        c = self.containers.get(name)
        if c is None:
            return ProcessResult(stdout="", stderr="No such container", exit_code=1)
        c["state"] = "stopped"
        return ProcessResult(stdout="", stderr="", exit_code=0)

    def remove_container(self, name, force=False):
        if name not in self.containers:
            return ProcessResult(stdout="", stderr="No such container", exit_code=1)
        del self.containers[name]
        return ProcessResult(stdout="", stderr="", exit_code=0)


def _make_workspace():
    return Path(_tempfile.mkdtemp())


def _bind_free_range_port() -> int:
    """Occupy one port inside the frozen range, keep it bound for the test."""
    for port in range(WEB_GATEWAY_HOST_PORT_MIN, WEB_GATEWAY_HOST_PORT_MAX + 1):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            return port, s
        except OSError:
            s.close()
    raise AssertionError("no bindable port in the frozen range")


class PortAllocatorTests(unittest.TestCase):
    def test_returns_port_in_range(self):
        port = allocate_gateway_host_port()
        self.assertTrue(WEB_GATEWAY_HOST_PORT_MIN <= port <= WEB_GATEWAY_HOST_PORT_MAX)

    def test_skips_bound_and_excluded_ports(self):
        bound, sock = _bind_free_range_port()
        try:
            for _ in range(5):
                port = allocate_gateway_host_port(exclude=set())
                self.assertNotEqual(port, bound)
            port = allocate_gateway_host_port(exclude={bound})
            self.assertNotEqual(port, bound)
        finally:
            sock.close()

    def test_excluded_only_still_gets_a_port(self):
        blocked = set(range(WEB_GATEWAY_HOST_PORT_MIN, WEB_GATEWAY_HOST_PORT_MIN + 50))
        port = allocate_gateway_host_port(exclude=blocked)
        self.assertNotIn(port, blocked)

    def test_bind_conflict_detection(self):
        self.assertTrue(is_bind_conflict(
            "docker: Error response from daemon: Bind for 127.0.0.1:47000 failed: "
            "port is already allocated"))
        self.assertTrue(is_bind_conflict("listen tcp4 0.0.0.0:4711: bind: address already in use"))
        self.assertFalse(is_bind_conflict("no such image"))
        self.assertFalse(is_bind_conflict(""))

    def test_publish_argv_shape(self):
        self.assertEqual(
            docker_publish_argv(47831),
            ["--publish", f"127.0.0.1:47831:{WEB_GATEWAY_CONTAINER_PORT}/tcp"],
        )

    def test_registry_host_ports(self):
        entries = {
            "a": {"web_gateway_host_port": 47001},
            "b": {"web_gateway_host_port": 0},
            "c": {},  # legacy record
            "d": {"web_gateway_host_port": "not-a-number"},
        }
        self.assertEqual(registry_host_ports(entries), {47001})


class StartPublishTests(unittest.TestCase):
    def test_start_publishes_loopback_gateway(self):
        ws = _make_workspace()
        ex = ServicesFakeExecutor()
        result = start_runtime(RID, str(ws), "super-claude:latest", "direct",
                               "project", "workbench", executor=ex,
                               registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertEqual(result.state, "running")
        publish_args = [a for a in ex.run_calls[0] if a.startswith("127.0.0.1:")]
        self.assertEqual(len(publish_args), 1)
        host_port = int(publish_args[0].split(":")[1])
        self.assertTrue(WEB_GATEWAY_HOST_PORT_MIN <= host_port <= WEB_GATEWAY_HOST_PORT_MAX)
        self.assertTrue(publish_args[0].endswith(f":{WEB_GATEWAY_CONTAINER_PORT}/tcp"))

        # registry records the allocated port; fingerprint ignores it
        meta = list_containers_readonly(ws / ".aisc")[result.container_name]
        self.assertEqual(meta["web_gateway_host_port"], host_port)
        expected_fp = compute_config_fingerprint(
            "super-claude:latest", "direct", "project", str(ws.resolve()))
        self.assertEqual(meta["config_fingerprint"], expected_fp)

    def test_bind_conflict_retries_next_port(self):
        ws = _make_workspace()
        ex = ServicesFakeExecutor(bind_conflicts=2)
        result = start_runtime(RID, str(ws), "super-claude:latest", "direct",
                               "project", "workbench", executor=ex,
                               registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertEqual(len(ex.run_calls), 3)
        ports = [ex._publish_host_port(c) for c in ex.run_calls]
        self.assertEqual(len(set(ports)), 3, "each attempt uses a fresh port")
        meta = list_containers_readonly(ws / ".aisc")[result.container_name]
        self.assertEqual(meta["web_gateway_host_port"], ports[2])

    def test_reuse_keeps_container_and_mapping(self):
        ws = _make_workspace()
        ex = ServicesFakeExecutor()
        first = start_runtime(RID, str(ws), "super-claude:latest", "direct",
                              "project", "workbench", executor=ex,
                              registry_root=ws / ".aisc", ready_timeout=2.0)
        runs_before = len(ex.run_calls)
        second = start_runtime(RID, str(ws), "super-claude:latest", "direct",
                               "project", "workbench", executor=ex,
                               registry_root=ws / ".aisc", ready_timeout=2.0)
        self.assertTrue(second.reused)
        self.assertEqual(len(ex.run_calls), runs_before, "no new docker run on reuse")
        self.assertEqual(first.container_name, second.container_name)


class WebAccessSnapshotTests(unittest.TestCase):
    def _ex_with(self, name="aisc-wb-x", state="running", host_port=47831):
        ex = ServicesFakeExecutor()
        ex.add_runtime(name, RID, state=state, host_port=host_port)
        return ex, name

    def test_ready_when_running_and_probe_disabled(self):
        ex, name = self._ex_with()
        gw = snapshot_web_access(ex, name, "running",
                                 registry_has_gateway=True, probe=False)
        self.assertEqual(gw.state, "ready")
        self.assertEqual(gw.host_port, 47831)
        self.assertEqual(gw.to_dict().get("reason", ""), "")

    def test_probe_detects_listener(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(16)  # backlog room for the probe connects (no accept loop)
        port = server.getsockname()[1]
        try:
            self.assertTrue(probe_gateway(port, timeout=1.0))
            self.assertFalse(probe_gateway(port + 1, timeout=0.2))
            ex = ServicesFakeExecutor()
            ex.add_runtime("c", RID, state="running", host_port=port)
            gw = snapshot_web_access(ex, "c", "running",
                                     registry_has_gateway=True, probe=True)
            self.assertEqual(gw.state, "ready")
        finally:
            server.close()

    def test_stopped_reports_runtime_not_running_without_extra_inspect(self):
        ex, name = self._ex_with(state="stopped")
        calls_before = ex.inspect_calls
        gw = snapshot_web_access(ex, name, "stopped", registry_has_gateway=True)
        self.assertEqual(gw.state, "unavailable")
        self.assertEqual(gw.reason, "runtime_not_running")
        # the 5s poll must not pay a mapping inspect for stopped runtimes
        self.assertEqual(ex.inspect_calls, calls_before)

    def test_legacy_runtime_without_mapping(self):
        ex, name = self._ex_with(host_port=0)
        gw = snapshot_web_access(ex, name, "running", registry_has_gateway=False)
        self.assertEqual(gw.reason, "legacy_runtime")

    def test_drifted_mapping_reports_no_mapping(self):
        ex, name = self._ex_with(host_port=0)
        gw = snapshot_web_access(ex, name, "running", registry_has_gateway=True)
        self.assertEqual(gw.reason, "no_mapping")

    def test_docker_unavailable(self):
        gw = snapshot_web_access(ServicesFakeExecutor(), "x", None, False)
        self.assertEqual(gw.reason, "docker_unavailable")

    def test_read_mapping_parses_inspect(self):
        ex, name = self._ex_with()
        mapping = read_gateway_mapping(ex, name)
        self.assertEqual(mapping, {"host_ip": "127.0.0.1", "host_port": 47831,
                                   "active": True})
        missing = read_gateway_mapping(ex, "no-such")
        self.assertIsNone(missing)


class InspectWebAccessTests(unittest.TestCase):
    def test_inspect_attaches_ready_web_access(self):
        ws = _make_workspace()
        ex = ServicesFakeExecutor()
        start_runtime(RID, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        snap = inspect_runtime(RID, executor=ex, registry_root=ws / ".aisc")
        wa = snap.to_dict()["web_access"]
        self.assertEqual(wa["state"], "unavailable")  # probe finds no real listener
        self.assertEqual(wa["reason"], "gateway_unreachable")

    def test_inspect_legacy_registry_record_degrades(self):
        ws = _make_workspace()
        ex = ServicesFakeExecutor()
        # Simulate a legacy runtime: container without a publish + registry
        # record without web_gateway_host_port (image_id present so no heal).
        ex.add_runtime("aisc-wb-legacy", RID, state="running", host_port=0)
        registry_register(ws / ".aisc", "aisc-wb-legacy", {
            "image": "super-claude:latest", "workspace": str(ws),
            "network": "direct", "label": "", "runtime_id": RID,
            "owner": "workbench", "scope": "project",
            "config_fingerprint": "sha256:whatever", "container_id": "cid-x",
            "workspace_key": "wskey", "image_id": "sha256:fake-image",
        })
        snap = inspect_runtime(RID, executor=ex, registry_root=ws / ".aisc")
        wa = snap.to_dict()["web_access"]
        self.assertEqual(wa["state"], "unavailable")
        self.assertEqual(wa["reason"], "legacy_runtime")

    def test_inspect_not_found(self):
        ws = _make_workspace()
        ex = ServicesFakeExecutor()
        snap = inspect_runtime(RID, executor=ex, registry_root=ws / ".aisc")
        self.assertEqual(snap.to_dict()["web_access"]["reason"], "runtime_not_running")


class RuntimeServicesDataPlaneTests(unittest.TestCase):
    def _running_runtime(self):
        ws = _make_workspace()
        ex = ServicesFakeExecutor()
        start_runtime(RID, str(ws), "super-claude:latest", "direct", "project",
                      "workbench", executor=ex, registry_root=ws / ".aisc",
                      ready_timeout=2.0)
        return ws, ex

    @staticmethod
    def _gateway_listener(ex):
        """Hold a loopback listener on the fake gateway's host port so the
        probe path (used by expose/unexpose) sees a "running gateway"."""
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        port = listener.getsockname()[1]
        for c in ex.containers.values():
            c["host_port"] = port
        return listener

    def test_services_lists_registered_with_urls(self):
        ws, ex = self._running_runtime()
        ex.manifest[3000] = {"schema_version": "aisc.web-service/v1", "port": 3000,
                             "protocol": "http", "name": "docs preview",
                             "state": "registered"}
        result = runtime_services(RID, executor=ex, registry_root=ws / ".aisc",
                                  probe=False)
        data = result.to_dict()
        self.assertEqual(data["schema_version"], "aisc.runtime-services/v1")
        self.assertEqual(data["gateway"]["state"], "ready")
        host_port = data["gateway"]["host_port"]
        self.assertEqual(data["services"][0]["url"],
                         f"http://p3000.localhost:{host_port}/")
        self.assertEqual(data["services"][0]["name"], "docs preview")

    def test_services_empty_and_malformed_records_skipped(self):
        ws, ex = self._running_runtime()
        ex.manifest[1] = {"port": "bogus"}
        result = runtime_services(RID, executor=ex, registry_root=ws / ".aisc",
                                  probe=False)
        self.assertEqual(result.services, [])

    def test_services_degrades_when_helper_missing(self):
        ws, ex = self._running_runtime()
        # exec answers unknown tool with failure → empty list, no crash
        result = runtime_services(RID, executor=ex, registry_root=ws / ".aisc",
                                  probe=False)
        self.assertEqual(result.services, [])

    def test_expose_and_unexpose_round_trip(self):
        ws, ex = self._running_runtime()
        listener = self._gateway_listener(ex)
        try:
            result = expose_runtime_service(RID, "3000", "web", executor=ex,
                                            registry_root=ws / ".aisc")
            self.assertEqual([s.port for s in result.services], [3000])
            expose_call = next(c for c in ex.exec_calls
                               if c[2].endswith("aisc-web-expose"))
            self.assertIn("--name", expose_call)
            self.assertIn("3000", expose_call)
            result = unexpose_runtime_service(RID, "3000", executor=ex,
                                              registry_root=ws / ".aisc")
            self.assertEqual(result.services, [])
        finally:
            listener.close()

    def test_expose_rejects_bad_port_and_name(self):
        ws, ex = self._running_runtime()
        with self.assertRaises(CliError) as cm:
            expose_runtime_service(RID, "80", "", executor=ex,
                                   registry_root=ws / ".aisc")
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.USAGE_ERROR)
        with self.assertRaises(CliError):
            expose_runtime_service(RID, "3000", "a\tb", executor=ex,
                                   registry_root=ws / ".aisc")

    def test_expose_rejects_not_ready_gateway(self):
        ws, ex = self._running_runtime()
        for name, c in ex.containers.items():
            c["state"] = "stopped"
        with self.assertRaises(CliError) as cm:
            expose_runtime_service(RID, "3000", "", executor=ex,
                                   registry_root=ws / ".aisc")
        self.assertEqual(cm.exception.exit_code, RuntimeExitCode.RUNTIME_NOT_RUNNING)


class RunFakeExecutor:
    """Minimal executor for `aisc run` paths: run/inspect only."""

    def __init__(self, bind_conflicts=0, auto_remove=True):
        self.bind_conflicts = bind_conflicts
        self.auto_remove = auto_remove
        self.run_calls: list[list[str]] = []
        self.exists = True

    def preflight(self):
        return DockerPreflightResult(docker_path="/usr/bin/docker",
                                     available=True, reason="ok")

    def inspect_image(self, name):
        return ImageInspectResult(status=ImageInspectStatus.EXISTS, image=name,
                                  image_id="sha256:fake")

    def run_captured(self, argv, *, timeout=None):
        cmd = argv[0] if argv else ""
        if cmd == "run":
            self.run_calls.append(list(argv))
            if self.bind_conflicts > 0:
                self.bind_conflicts -= 1
                return ProcessResult(stdout="", exit_code=1,
                                     stderr="Bind for 127.0.0.1:x failed: "
                                            "port is already allocated")
            self.exists = not self.auto_remove  # --rm: gone after exit
            return ProcessResult(stdout="cid-run", stderr="", exit_code=0)
        if cmd == "inspect":
            if not self.exists:
                return ProcessResult(stdout="", exit_code=1,
                                     stderr="Error: No such object: x")
            return ProcessResult(stdout="true\n", stderr="", exit_code=0)
        return ProcessResult(stdout="", stderr="", exit_code=0)

    def run_streaming(self, argv, *, timeout=None):
        return ProcessResult(stdout="", stderr="", exit_code=0)

    @staticmethod
    def _publish_port(argv):
        for a in argv:
            if a.startswith("127.0.0.1:"):
                return int(a.split(":")[1])
        return 0


class RunPathGatewayTests(unittest.TestCase):
    def test_plan_run_publishes_loopback_gateway(self):
        from aisc.cli.commands.run import plan_run

        ws = _make_workspace()
        plan = plan_run(image="super-claude:latest", workspace=str(ws),
                        name="t", network="direct")
        self.assertTrue(WEB_GATEWAY_HOST_PORT_MIN <= plan.web_gateway_host_port
                        <= WEB_GATEWAY_HOST_PORT_MAX)
        publishes = [a for a in plan.docker_argv if a.startswith("127.0.0.1:")]
        self.assertEqual(len(publishes), 1)
        self.assertTrue(publishes[0].endswith(f":{WEB_GATEWAY_CONTAINER_PORT}/tcp"))
        # dry-run shows the same publish plan without calling Docker
        self.assertIn("--publish", plan.docker_argv)

    def test_run_metadata_and_bind_conflict_retry(self):
        from aisc.cli.commands.run import run_container, plan_run

        ws = _make_workspace()
        plan = plan_run(image="super-claude:latest", workspace=str(ws),
                        name="t", network="direct")
        ex = RunFakeExecutor(bind_conflicts=1)
        result = run_container(plan, capture=True, executor=ex)
        self.assertTrue(result.executed)
        self.assertEqual(len(ex.run_calls), 2, "one bind-conflict retry")
        first_port = ex._publish_port(ex.run_calls[0])
        second_port = ex._publish_port(ex.run_calls[1])
        self.assertNotEqual(first_port, second_port)
        # exactly one publish spec per attempt argv (never stacks)
        for call in ex.run_calls:
            self.assertEqual(len([a for a in call if a.startswith("127.0.0.1:")]), 1)
        self.assertEqual(result.web_gateway["host_port"], second_port)
        self.assertEqual(result.web_gateway["container_port"], WEB_GATEWAY_CONTAINER_PORT)
        data = result.to_dict()
        self.assertEqual(data["web_gateway"]["host_port"], second_port)

    def test_rm_run_leaves_no_registry_entry(self):
        from aisc.adapters.container_registry import list_containers
        from aisc.cli.commands.run import plan_run, run_container

        ws = _make_workspace()
        reg = ws / ".aisc"
        reg.mkdir()
        plan = plan_run(image="super-claude:latest", workspace=str(ws),
                        name="t", network="direct")
        ex = RunFakeExecutor(auto_remove=True)
        result = run_container(plan, capture=True, executor=ex, aisc_root=reg)
        self.assertEqual(result.container_exit_code, 0)
        # --rm: the container is gone, so the GC pass prunes the entry.
        self.assertEqual(list_containers(reg), {})


class AllocatorExhaustionTests(unittest.TestCase):
    def test_exhaustion_raises_stable_error(self):
        # Block the whole range by binding every port in it is impractical;
        # instead verify the error type surfaces from a tiny fake range via
        # the exclude set covering everything we can reach cheaply — the
        # allocator scans the full 1000-port range, so drive exhaustion by
        # monkeypatching the module constants.
        import aisc.application.web_gateway as wg

        saved = (wg.WEB_GATEWAY_HOST_PORT_MIN, wg.WEB_GATEWAY_HOST_PORT_MAX)
        try:
            wg.WEB_GATEWAY_HOST_PORT_MIN = 49900
            wg.WEB_GATEWAY_HOST_PORT_MAX = 49902
            bound = [socket.socket() for _ in range(3)]
            for s in bound:
                s.bind(("127.0.0.1", 0))  # unlikely to collide; exhaustion via exclude below
            # Direct exclusion covers the whole fake range.
            with self.assertRaises(GatewayPortError):
                wg.allocate_gateway_host_port(exclude={49900, 49901, 49902})
            for s in bound:
                s.close()
        finally:
            wg.WEB_GATEWAY_HOST_PORT_MIN, wg.WEB_GATEWAY_HOST_PORT_MAX = saved


if __name__ == "__main__":
    unittest.main()
