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


if __name__ == "__main__":
    unittest.main()
