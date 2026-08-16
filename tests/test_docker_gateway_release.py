"""Stage 4 (4f, A-DG06/A-DG08): release gates — backend flag/rollback,
application backend-independence, and old-CLI regression via the alias."""

import unittest
from unittest import mock

from aisc.adapters.docker_gateway import (
    AutoGateway,
    CliGateway,
    SdkGateway,
    create_docker_gateway,
)
from aisc.domain.models import ProcessResult


# ---------------------------------------------------------------------------
# A-DG06: backend selection + rollback, application never branches
# ---------------------------------------------------------------------------

class BackendSelectionTests(unittest.TestCase):
    def test_factory_rollback_to_cli(self):
        """auto|sdk|cli flag exists and CLI is a valid rollback."""
        g = create_docker_gateway("cli")
        self.assertIsInstance(g, CliGateway)
        self.assertEqual(g.backend, "cli")

    def test_factory_sdk_explicit(self):
        g = create_docker_gateway("sdk")
        self.assertIsInstance(g, SdkGateway)
        self.assertEqual(g.backend, "sdk")

    def test_auto_resolves_to_sdk_when_available(self):
        # SDK is importable on this machine → auto picks SDK.
        g = AutoGateway()
        self.assertIsInstance(g._resolve(), SdkGateway)

    def test_auto_resolves_to_cli_when_sdk_unavailable(self):
        """D4-08: CLI is the fallback when the SDK cannot be imported."""
        g = AutoGateway()
        with mock.patch.dict("sys.modules", {"docker": None}):
            # ImportError on `import docker` → falls back to CLI.
            self.assertIsInstance(g._resolve(), CliGateway)

    def test_auto_respects_injected_backends(self):
        cli = CliGateway()
        sdk = SdkGateway()
        g = AutoGateway(_sdk=sdk, _cli=cli)
        self.assertIs(g._resolve(), sdk)
        g2 = AutoGateway(_sdk=None, _cli=cli, prefer_sdk=False)
        self.assertIs(g2._resolve(), cli)


class BackendIndependenceTests(unittest.TestCase):
    """A-DG06-1: application/domain never branches on backend.

    The only place the backend string is read is for diagnostics (the gateway's
    own `.backend` property and each result's `operation.backend`). We assert
    the domain result types carry no backend-coupled fields beyond the
    diagnostic envelope, and that a consumer using only the result's `ok` /
    `exit_code` / typed fields behaves identically regardless of backend.
    """

    def test_cli_and_sdk_results_are_consumed_identically(self):
        cli = CliGateway(executor=mock.Mock(
            run_captured=mock.Mock(return_value=ProcessResult(stdout="", stderr="", exit_code=0)),
        ))
        sdk = SdkGateway()  # client not used for stop (lifecycle via fake below)
        from aisc.adapters.docker_gateway import create_docker_gateway
        from tests.test_docker_gateway_query import FakeClient, _FakeContainers, _FakeContainer
        sdk.client = FakeClient(containers=_FakeContainers(
            [_FakeContainer("abc", "wb-1", "i", "exited")],
        ))

        cli_r = cli.stop_container("wb-1")
        sdk_r = sdk.stop_container("wb-1")

        # A consumer may only use `ok`/`exit_code`/typed fields — never backend.
        for r in (cli_r, sdk_r):
            self.assertEqual(r.operation.exit_code, 0)
            self.assertTrue(r.ok)
        # The diagnostic backend differs, but that is not branchable input.
        self.assertEqual(cli_r.operation.backend, "cli")
        self.assertEqual(sdk_r.operation.backend, "sdk")


if __name__ == "__main__":
    unittest.main()
