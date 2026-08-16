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
from aisc.domain.models import ImageInspectResult, ImageInspectStatus


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


class FakeClient:
    """Recording fake docker-py client with switchable faults."""

    def __init__(self, *, version=None, images=None, containers=None, fault=None):
        self._version = version or {"Version": "26.1.1", "ApiVersion": "1.44"}
        self._fault = fault  # "daemon_down" | "permission" | None
        self.images = images or _FakeImages({"super-claude:latest"}, fault=fault)
        self.containers = containers or _FakeContainers([], fault=fault)
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


if __name__ == "__main__":
    unittest.main()
