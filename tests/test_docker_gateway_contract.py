"""Stage 4 (4a, A-DG01/A-DG02): DockerGateway contract tests.

Covers the gateway protocol shape, operation envelope fields, factory backend
selection, the `DockerExecutor = DockerGateway` compat alias, and CLI-backend
delegation.  SDK-backend behavior against a live/fake client is covered in the
4b query tests.
"""

import unittest
from unittest import mock

from aisc.adapters.docker_gateway import (
    AutoGateway,
    CliGateway,
    DockerExecutor,
    DockerGateway,
    SdkGateway,
    create_docker_gateway,
)
from aisc.domain.gateway import (
    GatewayOperation,
    GatewayResult,
    ImageInspectGatewayResult,
    LifecycleResult,
    PreflightResult,
)
from aisc.domain.models import (
    BuildPlan,
    DockerPreflightResult,
    ImageInspectResult,
    ImageInspectStatus,
    ProcessResult,
)


class GatewayAliasTests(unittest.TestCase):
    def test_docker_executor_is_docker_gateway_alias(self):
        """D4-02: existing `DockerExecutor` name keeps working."""
        self.assertIs(DockerExecutor, DockerGateway)

    def test_gateway_is_runtime_checkable_protocol(self):
        self.assertTrue(hasattr(DockerGateway, "preflight"))
        self.assertTrue(hasattr(DockerGateway, "inspect_image"))


class FactoryTests(unittest.TestCase):
    def test_factory_selects_backend(self):
        self.assertIsInstance(create_docker_gateway("sdk"), SdkGateway)
        self.assertIsInstance(create_docker_gateway("cli"), CliGateway)
        self.assertIsInstance(create_docker_gateway("auto"), AutoGateway)

    def test_default_is_auto(self):
        self.assertIsInstance(create_docker_gateway(), AutoGateway)

    def test_factory_injects_client(self):
        client = mock.Mock()
        g = create_docker_gateway("sdk", client=client)
        self.assertIs(g.client, client)


class OperationEnvelopeTests(unittest.TestCase):
    def test_result_carries_envelope_fields(self):
        """A-DG02-1: operation_id/backend/exit/duration/error/cleanup present."""
        op = GatewayOperation(
            operation_id="abc123",
            backend="sdk",
            exit_code=3,
            duration_ms=42,
            error_code="DOCKER_ERR_DAEMON_UNREACHABLE",
            error_message="boom",
            cleanup_status="ok",
        )
        r = GatewayResult(operation=op)
        self.assertFalse(r.ok)
        self.assertEqual(r.operation.backend, "sdk")
        self.assertEqual(r.operation.duration_ms, 42)
        self.assertEqual(r.operation.cleanup_status, "ok")
        self.assertEqual(r.operation.error_code, "DOCKER_ERR_DAEMON_UNREACHABLE")

    def test_result_ok_semantics(self):
        ok_op = GatewayOperation(exit_code=0, backend="cli")
        self.assertTrue(GatewayResult(operation=ok_op).ok)
        timed_op = GatewayOperation(exit_code=-1, timed_out=True, backend="sdk")
        self.assertTrue(GatewayResult(operation=timed_op).timed_out)
        self.assertFalse(GatewayResult(operation=timed_op).ok)


class CliGatewayTests(unittest.TestCase):
    def _exec(self, **kwargs):
        executor = mock.Mock()
        executor.preflight.return_value = DockerPreflightResult(
            docker_path="/usr/bin/docker", available=True, reason="ok",
        )
        executor.inspect_image.return_value = ImageInspectResult(
            status=ImageInspectStatus.EXISTS, image="img", message="",
        )
        executor.list_containers.return_value = ProcessResult(
            stdout="id  name\n", stderr="", exit_code=0,
        )
        executor.inspect_container.return_value = ProcessResult(
            stdout="{}", stderr="", exit_code=0,
        )
        executor.run_captured.return_value = ProcessResult(stdout="", stderr="", exit_code=0)
        executor.open_interactive.return_value = ProcessResult(stdout="", stderr="", exit_code=0)
        return executor

    def test_cli_preflight_delegates_and_maps(self):
        executor = self._exec()
        g = CliGateway(executor=executor)
        r: PreflightResult = g.preflight()
        executor.preflight.assert_called_once()
        self.assertTrue(r.available)
        self.assertEqual(r.reason, "ok")
        self.assertEqual(g.backend, "cli")
        self.assertEqual(r.operation.backend, "cli")

    def test_cli_inspect_maps_status(self):
        executor = self._exec()
        executor.inspect_image.return_value = ImageInspectResult(
            status=ImageInspectStatus.MISSING, image="img", message="not found",
        )
        g = CliGateway(executor=executor)
        r: ImageInspectGatewayResult = g.inspect_image("img")
        self.assertEqual(r.status, ImageInspectStatus.MISSING)
        self.assertEqual(r.operation.exit_code, 5)

    def test_cli_lifecycle_via_argv(self):
        executor = self._exec()
        g = CliGateway(executor=executor)
        r: LifecycleResult = g.stop_container("wb-1", timeout=7)
        argv = executor.run_captured.call_args[0][0]
        self.assertEqual(argv, ["stop", "-t", "7", "wb-1"])
        self.assertEqual(r.observed_state, "stopped")
        self.assertEqual(g.backend, "cli")

    def test_cli_build_delegates(self):
        executor = self._exec()
        g = CliGateway(executor=executor)
        plan = BuildPlan(tag="t:1", root="/tmp", dockerfile="Dockerfile")
        g.build_image(plan)
        executor.run_captured.assert_called_once()


class StructuredContainerResultsTests(unittest.TestCase):
    """A0 (docker-ownership-foundation): list/inspect stably carry labels,
    image ref and the content-addressed image ID — the ownership
    classification service (A1) builds on exactly these fields."""

    def _sdk_list_client(self):
        container = mock.Mock()
        container.id = "aaaaaaaaaaaaaaaa"
        container.name = "/aisc-wb-test".lstrip("/")
        container.status = "running"
        container.image.tags = ["super-claude:latest"]
        container.attrs = {
            "State": {"Status": "running"},
            "Config": {"Labels": {"io.aisc.managed": "true"}, "Image": "super-claude:latest"},
            "Image": "sha256:bbbb",
        }
        client = mock.Mock()
        client.containers.list.return_value = [container]
        return client, container

    def test_sdk_list_carries_labels_and_image_id(self):
        client, container = self._sdk_list_client()
        g = SdkGateway(client=client)
        rows = g.list_containers(all=True).containers
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].labels, {"io.aisc.managed": "true"})
        self.assertEqual(rows[0].image, "super-claude:latest")
        self.assertEqual(rows[0].image_id, "sha256:bbbb")

    def test_sdk_inspect_carries_labels_and_image_id(self):
        client, container = self._sdk_list_client()
        inspect_attrs = {
            "Id": "aaaaaaaaaaaaaaaa",
            "Name": "/aisc-wb-test",
            "State": {"Status": "running"},
            "Config": {"Image": "super-claude:latest", "Labels": {"io.aisc.kind": "runtime"}},
            "Image": "sha256:bbbb",
        }
        container.attrs = inspect_attrs
        client.containers.get.return_value = container
        g = SdkGateway(client=client)
        r = g.inspect_container("aisc-wb-test")
        self.assertEqual(r.image, "super-claude:latest")       # ref
        self.assertEqual(r.image_id, "sha256:bbbb")            # content ID ≠ ref
        self.assertEqual(r.labels, {"io.aisc.kind": "runtime"})
        self.assertEqual(r.name, "aisc-wb-test")

    def test_cli_list_parses_tab_format_rows(self):
        executor = mock.Mock()
        executor.list_containers.return_value = ProcessResult(
            exit_code=0,
            stdout="aaaa\taisc-wb-1\tsuper-claude:latest\tUp 2 hours\nbbbb\tother\talpine:3\tExited (0)",
        )
        g = CliGateway(executor=executor)
        rows = g.list_containers(all=True).containers
        self.assertEqual([r.id for r in rows], ["aaaa", "bbbb"])
        self.assertEqual(rows[0].name, "aisc-wb-1")
        self.assertEqual(rows[0].image, "super-claude:latest")
        self.assertEqual(rows[0].status, "Up 2 hours")
        # docker ps cannot provide labels / image ID — documented empties.
        self.assertEqual(rows[0].labels, {})
        self.assertEqual(rows[0].image_id, "")

    def test_cli_inspect_parses_machine_json(self):
        import json as _json

        payload = [{
            "Id": "aaaa",
            "Name": "/aisc-wb-2",
            "State": {"Status": "exited"},
            "Config": {
                "Image": "super-claude:latest",
                "Labels": {"io.aisc.managed": "true", "io.aisc.kind": "runtime"},
            },
            "Image": "sha256:cccc",
        }]
        executor = mock.Mock()
        executor.inspect_container.return_value = ProcessResult(
            exit_code=0, stdout=_json.dumps(payload),
        )
        g = CliGateway(executor=executor)
        r = g.inspect_container("aisc-wb-2")
        self.assertEqual(r.container_id, "aaaa")
        self.assertEqual(r.name, "aisc-wb-2")
        self.assertEqual(r.state, "exited")
        self.assertEqual(r.image, "super-claude:latest")
        self.assertEqual(r.labels["io.aisc.kind"], "runtime")
        self.assertEqual(r.image_id, "sha256:cccc")

    def test_cli_inspect_garbage_stays_fail_closed(self):
        executor = mock.Mock()
        executor.inspect_container.return_value = ProcessResult(
            exit_code=0, stdout="not json at all",
        )
        g = CliGateway(executor=executor)
        r = g.inspect_container("x")
        self.assertEqual(r.container_id, "")
        self.assertEqual(r.image_id, "")
        self.assertEqual(r.operation.exit_code, 0)  # transport ok; fields empty


if __name__ == "__main__":
    unittest.main()
