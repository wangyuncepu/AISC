"""Stage 4 (4b, A-DG03/A-DG07): SDK query backend equivalence + faults.

Uses a Fake docker-py client (recording + fault-injection) so the SDK query
path (preflight / inspect_image / list_containers / inspect_container) is
verified without a live daemon, and the results are asserted to carry the
same semantic fields as the CLI backend (A-DG03-1).
"""

import unittest
from unittest import mock

import docker

from aisc.adapters.docker_gateway import CliGateway, SdkGateway
from aisc.domain.gateway import (
    ContainerInspectResult,
    ContainerListResult,
    ImageInspectGatewayResult,
    PreflightResult,
)
from aisc.domain.models import ImageInspectResult, ImageInspectStatus, ProcessResult


# ---------------------------------------------------------------------------
# Fake docker-py client (recording + fault injection)
# ---------------------------------------------------------------------------

class _FakeImage:
    def __init__(self, name, tags):
        self.name = name
        self.tags = tags


class _FakeImages:
    def __init__(self, present, fault=None):
        # present: iterable of image refs; "repo:tag" kept as-is, bare repo
        # gets ":latest" appended (mirrors docker image semantics).
        self.present = set(present)
        self._fault = fault

    def get(self, name):
        if self._fault == "daemon_down":
            raise docker.errors.DockerException("Cannot connect to the Docker daemon")
        if name not in self.present:
            raise docker.errors.ImageNotFound(f"no such image: {name}")
        return _FakeImage(name, [name])


class _FakeContainer:
    def __init__(self, cid, name, image, status, attrs=None):
        self.id = cid
        self.name = name
        self.status = status
        self.image = _FakeImage(image, [image])
        self.attrs = attrs or {
            "Id": cid,
            "Config": {"Image": image, "Labels": {"io.aisc.kind": "runtime"}},
            "State": {"Status": status},
        }
        self._removed = False
        self._fault = None  # "start_down" | "stop_down" | "remove_down" | "wait_timeout" | None

    # -- lifecycle (mirrors docker-py) -------------------------------------

    def start(self):
        if self._fault == "start_down":
            raise docker.errors.DockerException("daemon unreachable during start")
        self._set_state("running")

    def stop(self, timeout=10):
        if self._fault == "stop_down":
            raise docker.errors.DockerException("daemon unreachable during stop")
        self._set_state("exited")

    def remove(self, force=False):
        if self._fault == "remove_down":
            raise docker.errors.DockerException("daemon unreachable during remove")
        self._removed = True
        self._set_state("removed")

    def wait(self, timeout=None):
        if self._fault == "wait_timeout":
            # docker-py surfaces this as requests.ReadTimeout, which is NOT a
            # DockerException — the gateway must classify it as TIMEOUT.
            import requests
            raise requests.exceptions.ReadTimeout("Connection aborted: timed out")
        return {"StatusCode": 0}

    def reload(self):
        if self._removed:
            raise docker.errors.NotFound("No such container")
        return None

    def _set_state(self, state):
        self.status = state
        self.attrs["State"]["Status"] = state


class _FakeContainers:
    def __init__(self, rows, fault=None):
        self.rows = rows
        self._fault = fault  # "daemon_down" | None

    def _check_fault(self):
        if self._fault == "daemon_down":
            raise docker.errors.DockerException("Cannot connect to the Docker daemon")

    def list(self, all=False):
        self._check_fault()
        return list(self.rows)

    def get(self, name_or_id):
        self._check_fault()
        for c in self.rows:
            if c.id == name_or_id or c.name == name_or_id:
                return c
        raise docker.errors.NotFound(f"no such container: {name_or_id}")


class _FakeApi:
    """Fake docker APIClient for the interactive exec path."""

    def __init__(self, *, fault=None, inspect_once=False, exit_code=0):
        self._fault = fault          # "exec_create_down" | "exec_start_down" | "exec_inspect_down" | None
        self._inspect_once = inspect_once  # first inspect reports not-running (fast exit)
        self._exit_code = exit_code
        self.calls = []

    def exec_create(self, container, cmd, **kwargs):
        self.calls.append(("exec_create", container, cmd))
        if self._fault == "exec_create_down":
            raise docker.errors.DockerException("daemon unreachable during exec_create")
        return {"Id": "exec-1234"}

    def exec_start(self, exec_id, **kwargs):
        self.calls.append(("exec_start", exec_id))
        if self._fault == "exec_start_down":
            raise docker.errors.APIError("exec start failed")
        import io
        return io.BytesIO(b"")  # empty socket: immediate EOF on drain

    def exec_inspect(self, exec_id):
        self.calls.append(("exec_inspect", exec_id))
        if self._fault == "exec_inspect_down":
            raise docker.errors.APIError("exec inspect failed")
        if self._inspect_once:
            return {"Running": False, "ExitCode": self._exit_code}
        return {"Running": True, "ExitCode": 0}  # callers must set once for fast tests

    def exec_resize(self, exec_id, **kwargs):
        self.calls.append(("exec_resize", exec_id))


class FakeClient:
    """Recording fake docker-py client with switchable faults."""

    def __init__(self, *, version=None, images=None, containers=None, fault=None, api=None):
        self._version = version or {"Version": "26.1.1", "ApiVersion": "1.44"}
        self._fault = fault  # "daemon_down" | "permission" | None
        self.images = images or _FakeImages({"super-claude:latest"}, fault=fault)
        self.containers = containers or _FakeContainers([], fault=fault)
        self.api = api or _FakeApi()
        self.calls = []

    def version(self):
        self.calls.append("version")
        if self._fault == "daemon_down":
            raise docker.errors.DockerException("Cannot connect to the Docker daemon")
        if self._fault == "permission":
            raise docker.errors.DockerException("permission denied")
        return self._version


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class SdkQueryTests(unittest.TestCase):
    def _gateway(self, client):
        return SdkGateway(client=client)

    def test_preflight_ok(self):
        client = FakeClient()
        g = self._gateway(client)
        r: PreflightResult = g.preflight()
        self.assertTrue(r.available)
        self.assertEqual(r.reason, "ok")
        self.assertEqual(r.docker_version, "26.1.1")
        self.assertTrue(r.engine_ok)
        self.assertEqual(r.operation.backend, "sdk")
        self.assertEqual(r.operation.exit_code, 0)
        self.assertEqual(client.calls, ["version"])

    def test_preflight_daemon_down(self):
        client = FakeClient(fault="daemon_down")
        r: PreflightResult = self._gateway(client).preflight()
        self.assertFalse(r.available)
        self.assertEqual(r.reason, "daemon_unreachable")
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_DAEMON_UNREACHABLE")
        self.assertEqual(r.operation.exit_code, 3)

    def test_inspect_image_exists(self):
        client = FakeClient(images=_FakeImages({"super-claude:latest"}))
        r: ImageInspectGatewayResult = self._gateway(client).inspect_image("super-claude:latest")
        self.assertEqual(r.status, ImageInspectStatus.EXISTS)
        self.assertEqual(r.operation.exit_code, 0)

    def test_inspect_image_missing(self):
        client = FakeClient(images=_FakeImages({"other:latest"}))
        r: ImageInspectGatewayResult = self._gateway(client).inspect_image("super-claude:latest")
        self.assertEqual(r.status, ImageInspectStatus.MISSING)
        self.assertEqual(r.operation.exit_code, 5)

    def test_inspect_image_daemon_down(self):
        client = FakeClient(fault="daemon_down")
        r: ImageInspectGatewayResult = self._gateway(client).inspect_image("img")
        self.assertEqual(r.status, ImageInspectStatus.DOCKER_UNAVAILABLE)
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_DAEMON_UNREACHABLE")

    def test_list_containers_maps_rows(self):
        rows = [
            _FakeContainer("abc123def456", "aisc-wb-1", "super-claude:latest", "running"),
            _FakeContainer("def456abc123", "aisc-wb-2", "super-claude:latest", "exited"),
        ]
        client = FakeClient(containers=_FakeContainers(rows))
        r: ContainerListResult = self._gateway(client).list_containers()
        self.assertEqual(len(r.containers), 2)
        self.assertEqual(r.containers[0].id, "abc123def456")
        self.assertEqual(r.containers[0].name, "aisc-wb-1")
        self.assertEqual(r.containers[0].state, "running")
        self.assertEqual(r.containers[0].image, "super-claude:latest")
        self.assertEqual(r.containers[0].labels["io.aisc.kind"], "runtime")

    def test_list_containers_daemon_down(self):
        client = FakeClient(fault="daemon_down")
        r: ContainerListResult = self._gateway(client).list_containers()
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_DAEMON_UNREACHABLE")
        self.assertEqual(r.containers, [])

    def test_inspect_container_ok(self):
        rows = [
            _FakeContainer("abc123def456", "aisc-wb-1", "super-claude:latest", "running"),
        ]
        client = FakeClient(containers=_FakeContainers(rows))
        r: ContainerInspectResult = self._gateway(client).inspect_container("aisc-wb-1")
        self.assertEqual(r.container_id, "abc123def456")
        self.assertEqual(r.name, "aisc-wb-1")
        self.assertEqual(r.state, "running")
        self.assertEqual(r.image, "super-claude:latest")
        self.assertEqual(r.labels["io.aisc.kind"], "runtime")
        self.assertEqual(r.operation.exit_code, 0)

    def test_inspect_container_not_found(self):
        client = FakeClient(containers=_FakeContainers([]))
        r: ContainerInspectResult = self._gateway(client).inspect_container("ghost")
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_NOT_FOUND")
        self.assertEqual(r.operation.exit_code, 1)


class SdkCliEquivalenceTests(unittest.TestCase):
    """A-DG03-1: SDK and CLI backends produce the same semantic result for the
    same input (status values / exit codes), even though the transport differs."""

    def test_inspect_status_matches_across_backends(self):
        # CLI: exists
        cli = CliGateway(executor=mock.Mock(
            inspect_image=mock.Mock(return_value=ImageInspectResult(
                status=ImageInspectStatus.EXISTS, image="img", message="",
            )),
        ))
        sdk = SdkGateway(client=FakeClient(images=_FakeImages({"img"})))
        self.assertEqual(cli.inspect_image("img").status, ImageInspectStatus.EXISTS)
        self.assertEqual(sdk.inspect_image("img").status, ImageInspectStatus.EXISTS)
        # Both exit 0 on exists.
        self.assertEqual(cli.inspect_image("img").operation.exit_code, 0)
        self.assertEqual(sdk.inspect_image("img").operation.exit_code, 0)

    def test_inspect_missing_maps_to_same_exit(self):
        cli = CliGateway(executor=mock.Mock(
            inspect_image=mock.Mock(return_value=ImageInspectResult(
                status=ImageInspectStatus.MISSING, image="img", message="nf",
            )),
        ))
        sdk = SdkGateway(client=FakeClient(images=_FakeImages({"other"})))
        self.assertEqual(cli.inspect_image("img").operation.exit_code, 5)
        self.assertEqual(sdk.inspect_image("img").operation.exit_code, 5)


class SdkLifecycleTests(unittest.TestCase):
    """A-DG03-1 (lifecycle) / A-DG07-1: start/stop/remove/wait + faults."""

    def _gw(self, rows, container_fault=None):
        rows = rows or [_FakeContainer("abc123def456", "aisc-wb-1", "super-claude:latest", "exited")]
        if container_fault:
            rows[0]._fault = container_fault
        return SdkGateway(client=FakeClient(containers=_FakeContainers(rows)))

    def test_start_ok(self):
        g = self._gw([])
        r = g.start_container("aisc-wb-1")
        self.assertEqual(r.operation.exit_code, 0)
        self.assertEqual(r.observed_state, "running")
        self.assertEqual(r.target, "aisc-wb-1")

    def test_start_daemon_down(self):
        g = self._gw([], container_fault="start_down")
        r = g.start_container("aisc-wb-1")
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_DAEMON_UNREACHABLE")

    def test_start_not_found(self):
        g = SdkGateway(client=FakeClient(containers=_FakeContainers([])))
        r = g.start_container("ghost")
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_NOT_FOUND")
        self.assertEqual(r.operation.exit_code, 1)

    def test_stop_ok(self):
        g = self._gw([])
        r = g.stop_container("aisc-wb-1", timeout=7)
        self.assertEqual(r.operation.exit_code, 0)
        self.assertEqual(r.observed_state, "stopped")

    def test_stop_daemon_down(self):
        g = self._gw([], container_fault="stop_down")
        r = g.stop_container("aisc-wb-1")
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_DAEMON_UNREACHABLE")

    def test_remove_ok(self):
        g = self._gw([])
        r = g.remove_container("aisc-wb-1", force=True)
        self.assertEqual(r.operation.exit_code, 0)
        self.assertEqual(r.observed_state, "removed")

    def test_remove_already_absent_is_idempotent_ok(self):
        # Removing a container that is already gone must NOT error (idempotent).
        g = SdkGateway(client=FakeClient(containers=_FakeContainers([])))
        r = g.remove_container("ghost")
        self.assertEqual(r.operation.exit_code, 0)
        self.assertEqual(r.observed_state, "removed")

    def test_remove_daemon_down(self):
        g = self._gw([], container_fault="remove_down")
        r = g.remove_container("aisc-wb-1")
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_DAEMON_UNREACHABLE")

    def test_wait_ok(self):
        g = self._gw([])
        r = g.wait_container("aisc-wb-1")
        self.assertEqual(r.operation.exit_code, 0)
        self.assertEqual(r.observed_state, "exited")

    def test_wait_timeout_is_stable_timed_out(self):
        g = self._gw([], container_fault="wait_timeout")
        r = g.wait_container("aisc-wb-1", timeout=2)
        self.assertTrue(r.timed_out)
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_TIMEOUT")
        self.assertEqual(r.operation.exit_code, 1)


class SdkCliLifecycleEquivalenceTests(unittest.TestCase):
    """A-DG03-1: lifecycle semantics identical across backends."""

    def test_stop_exit_codes_match(self):
        # SDK: normal stop → 0.
        sdk = SdkGateway(client=FakeClient(
            containers=_FakeContainers([_FakeContainer("abc123", "wb-1", "i", "exited")]),
        ))
        self.assertEqual(sdk.stop_container("wb-1").operation.exit_code, 0)
        # CLI: `docker stop` success → 0.
        cli = CliGateway(executor=mock.Mock(run_captured=mock.Mock(
            return_value=ProcessResult(stdout="", stderr="", exit_code=0),
        )))
        self.assertEqual(cli.stop_container("wb-1").operation.exit_code, 0)

    def test_not_found_exit_matches(self):
        sdk = SdkGateway(client=FakeClient(containers=_FakeContainers([])))
        self.assertEqual(sdk.start_container("ghost").operation.exit_code, 1)
        cli = CliGateway(executor=mock.Mock(run_captured=mock.Mock(
            return_value=ProcessResult(stdout="", stderr="Error: No such container", exit_code=1),
        )))
        self.assertEqual(cli.start_container("ghost").operation.exit_code, 1)


class SdkInteractiveTests(unittest.TestCase):
    """A-DG04-1: interactive exec lifecycle (create/start/stream/inspect/reap)."""

    def _gw(self, api):
        return SdkGateway(client=FakeClient(api=api))

    def test_open_interactive_full_lifecycle(self):
        """exec_create → exec_start → exec_inspect(once) → exit_code, threads reaped."""
        import os
        import sys as _sys
        import tempfile
        from unittest import mock as _mock

        api = _FakeApi(inspect_once=True, exit_code=7)
        g = self._gw(api)
        # Real empty temp file for stdin → immediate EOF, no fileno error.
        with tempfile.TemporaryFile() as stdin:
            with _mock.patch.object(_sys, "stdin", stdin):
                r = g.open_interactive("aisc-wb-1", ["bash", "-c", "exit 7"])

        self.assertEqual(r.operation.exit_code, 7)
        self.assertEqual(r.exit_code, 7)
        self.assertEqual(r.session_id, "exec-1234")
        self.assertTrue(r.waited)
        # Lifecycle order + reap (threads joined, no leaked daemon threads).
        created = [c for c in api.calls if c[0] == "exec_create"]
        started = [c for c in api.calls if c[0] == "exec_start"]
        inspected = [c for c in api.calls if c[0] == "exec_inspect"]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(started), 1)
        self.assertGreaterEqual(len(inspected), 1)

    def test_open_interactive_exec_create_not_found(self):
        class NotFoundApi(_FakeApi):
            def exec_create(self, container, cmd, **kwargs):
                raise docker.errors.NotFound("no such container")
        r = self._gw(NotFoundApi()).open_interactive("ghost", ["sh"])
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_NOT_FOUND")
        self.assertEqual(r.operation.exit_code, 1)

    def test_open_interactive_exec_start_failure_is_stable(self):
        api = _FakeApi(fault="exec_start_down")
        r = self._gw(api).open_interactive("aisc-wb-1", ["sh"])
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_UNKNOWN")
        self.assertEqual(r.session_id, "exec-1234")

    def test_open_interactive_inspect_error_reaps_threads(self):
        api = _FakeApi(fault="exec_inspect_down")
        r = self._gw(api).open_interactive("aisc-wb-1", ["sh"])
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_UNKNOWN")

    def test_open_interactive_resize_forwarded(self):
        """AISC_RESIZE_FILE drives exec_resize on the initial + watch path."""
        import os
        import sys as _sys
        import tempfile
        from unittest import mock as _mock

        api = _FakeApi(inspect_once=True)
        g = self._gw(api)
        with tempfile.NamedTemporaryFile("w", delete=False) as rf:
            rf.write("80 24\n")
            resize_path = rf.name
        try:
            with tempfile.TemporaryFile() as stdin:
                with _mock.patch.object(_sys, "stdin", stdin):
                    with _mock.patch.dict(os.environ, {"AISC_RESIZE_FILE": resize_path}):
                        g.open_interactive("aisc-wb-1", ["sh"])
        finally:
            os.unlink(resize_path)
        resized = [c for c in api.calls if c[0] == "exec_resize"]
        self.assertGreaterEqual(len(resized), 1)


if __name__ == "__main__":
    unittest.main()
