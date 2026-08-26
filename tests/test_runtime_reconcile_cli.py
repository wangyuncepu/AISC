"""runtime-lifecycle-ux Stage 1: CLI surface for reconcile + lease.

Parser contracts (the py3.14 nested-subparser traps live here — same
pattern as `runtime services`) and one end-to-end dispatch pass through
_cmd_runtime with a fake workspace, hermetic data root.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aisc.cli.main import _build_parser

INST_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
INST_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class ReconcileParserTests(unittest.TestCase):
    def test_reconcile_parses_required_options(self):
        args = _build_parser().parse_args(
            ["runtime", "reconcile", "--workspace", "C:/ws",
             "--instance-id", INST_A, "--workspace-key", "abc"]
        )
        self.assertEqual(args.command, "runtime")
        self.assertEqual(args.runtime_command, "reconcile")
        self.assertEqual(args.workspace, "C:/ws")
        self.assertEqual(args.instance_id, INST_A)
        self.assertEqual(args.workspace_key, "abc")

    def test_lease_children_require_instance_id(self):
        args = _build_parser().parse_args(
            ["runtime", "lease", "claim", "--workspace", "C:/ws",
             "--instance-id", INST_A]
        )
        self.assertEqual(args.runtime_command, "lease")
        self.assertEqual(args.runtime_lease_command, "claim")
        self.assertEqual(args.instance_id, INST_A)
        # inspect needs neither instance nor lease id
        args = _build_parser().parse_args(
            ["runtime", "lease", "inspect", "--workspace", "C:/ws"]
        )
        self.assertEqual(args.runtime_lease_command, "inspect")

    def test_lease_claim_without_instance_id_is_usage_error(self):
        # Children mark --instance-id required (the parent keeps it optional
        # — py3.14 rejects parent-required + child-required), so a missing
        # id dies at parse time with the standard usage exit.
        with self.assertRaises(SystemExit) as ctx:
            _build_parser().parse_args(
                ["runtime", "lease", "claim", "--workspace", "C:/ws"]
            )
        self.assertEqual(ctx.exception.code, 2)


class LeaseCommandRoundTripTests(unittest.TestCase):
    """cmd_runtime_lease against a hermetic data root."""

    def setUp(self):
        self._ws = tempfile.TemporaryDirectory()
        self._root = tempfile.TemporaryDirectory()
        self.ws = str(Path(self._ws.name) / "proj")
        Path(self.ws).mkdir(parents=True)
        self.addCleanup(self._ws.cleanup)
        self.addCleanup(self._root.cleanup)

    def _cmd(self, action, instance_id=None, lease_id=None):
        from aisc.cli.commands.runtime import cmd_runtime_lease

        # cmd_runtime_lease resolves the data root from os.environ — inject
        # the hermetic root (svc lesson: subprocess env vs process env).
        with mock.patch.dict(os.environ, {"AISC_DATA_ROOT": self._root.name}, clear=False):
            return cmd_runtime_lease(
                action=action, workspace=self.ws,
                instance_id=instance_id or "", lease_id=lease_id,
            )

    def test_claim_inspect_heartbeat_release_round_trip(self):
        claimed = self._cmd("claim", INST_A)
        self.assertEqual(claimed["outcome"], "claimed")
        lease_id = claimed["lease_id"]

        inspected = self._cmd("inspect")
        self.assertEqual(inspected["lease_id"], lease_id)

        beat = self._cmd("heartbeat", INST_A, lease_id)
        self.assertEqual(beat["lease_id"], lease_id)

        self.assertTrue(self._cmd("release", INST_A, lease_id)["released"])
        self.assertEqual(self._cmd("inspect")["lease"], None)

    def test_claim_conflict_raises_stable_code(self):
        from aisc.cli.commands.runtime import cmd_runtime_lease
        from aisc.domain.models import CliError, RuntimeErrorCode

        self._cmd("claim", INST_A)
        with mock.patch.dict(os.environ, {"AISC_DATA_ROOT": self._root.name}, clear=False):
            with self.assertRaises(CliError) as ctx:
                cmd_runtime_lease(action="claim", workspace=self.ws,
                                  instance_id=INST_B, lease_id=None)
        self.assertEqual(ctx.exception.error_code, RuntimeErrorCode.ACTIVE_WORKSPACE_LEASE)


class ReconcileDispatchTests(unittest.TestCase):
    """_cmd_runtime dispatch wiring for reconcile/lease (fake executor)."""

    def setUp(self):
        self._ws = tempfile.TemporaryDirectory()
        self._root = tempfile.TemporaryDirectory()
        self.ws = str(Path(self._ws.name) / "proj")
        Path(self.ws).mkdir(parents=True)
        self._env = {
            "AISC_DATA_ROOT": self._root.name,
        }
        self.addCleanup(self._ws.cleanup)
        self.addCleanup(self._root.cleanup)

    def test_dispatch_reconcile_returns_envelope(self):
        from aisc.cli.main import _cmd_runtime
        from tests.test_workspace_reconcile import ReconcileFakeExecutor

        args = _build_parser().parse_args(
            ["runtime", "reconcile", "--workspace", self.ws,
             "--instance-id", INST_A]
        )
        with mock.patch.dict(os.environ, self._env, clear=False):
            data, exit_code, errors = _cmd_runtime(args, "json")
        self.assertEqual(exit_code, 0)
        self.assertEqual(errors, [])
        self.assertEqual(data["classification"], "clean")
        self.assertTrue(data["can_proceed"])

    def test_workspace_key_mismatch_is_rejected(self):
        from aisc.cli.commands.runtime import cmd_runtime_reconcile
        from aisc.domain.models import CliError, RuntimeErrorCode
        from tests.test_workspace_reconcile import ReconcileFakeExecutor

        with mock.patch.dict(os.environ, self._env, clear=False):
            with self.assertRaises(CliError) as ctx:
                cmd_runtime_reconcile(
                    workspace=self.ws, instance_id=INST_A,
                    workspace_key="deadbeef",
                    executor=ReconcileFakeExecutor(),
                )
        self.assertEqual(ctx.exception.error_code, RuntimeErrorCode.WORKSPACE_INVALID)


if __name__ == "__main__":
    unittest.main()
