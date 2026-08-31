"""v2.1.9 T3a (R2): `aisc artifact record` ID defaults from the session env.

The Workbench injects AISC_RUNTIME_ID (docker create), AISC_TERMINAL_SESSION_ID
and AISC_AGENT (session wrapper) into every agent process. The record parser
uses them as argparse defaults so agents don't need to know their own IDs —
this is what makes the artifact SKILL's command template honest.
"""

from __future__ import annotations

import argparse
import os
import unittest
from unittest import mock

import pytest

from aisc.cli import main as cli_main
from aisc.domain.models import CliError

RT = "3212ee97-1af9-4412-a836-47311b63e139"
SID = "8848aaa1-1234-4abc-8def-123456789abc"


def _parse(argv, env):
    """Build the CLI parser under *env* (defaults are read at build time),
    then parse *argv*."""
    with mock.patch.dict(os.environ, env, clear=False):
        for k in ("AISC_RUNTIME_ID", "AISC_TERMINAL_SESSION_ID", "AISC_AGENT"):
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in env.items()})
        parser = cli_main._build_parser()
        return parser.parse_args(argv)


class TestRecordEnvDefaults(unittest.TestCase):
    def test_env_supplies_missing_ids(self):
        ns = _parse(
            ["artifact", "record", "--agent", "codex", "--path", "docs/x.md"],
            {"AISC_RUNTIME_ID": RT, "AISC_TERMINAL_SESSION_ID": SID},
        )
        self.assertEqual(ns.runtime_id, RT)
        self.assertEqual(ns.session_id, SID)
        self.assertEqual(ns.agent, "codex")

    def test_flags_override_env(self):
        ns = _parse(
            ["artifact", "record", "--runtime-id", RT, "--session-id", SID,
             "--agent", "claude", "--path", "x"],
            {"AISC_RUNTIME_ID": "ffffffff-ffff-4fff-8fff-ffffffffffff",
             "AISC_TERMINAL_SESSION_ID": "00000000-0000-4000-8000-000000000000",
             "AISC_AGENT": "codex"},
        )
        self.assertEqual(ns.runtime_id, RT)
        self.assertEqual(ns.session_id, SID)
        self.assertEqual(ns.agent, "claude")

    def test_agent_defaults_from_env(self):
        ns = _parse(
            ["artifact", "record", "--path", "x"],
            {"AISC_RUNTIME_ID": RT, "AISC_TERMINAL_SESSION_ID": SID,
             "AISC_AGENT": "codex"},
        )
        self.assertEqual(ns.agent, "codex")

    def test_agent_required_without_env(self):
        with pytest.raises(SystemExit):
            _parse(
                ["artifact", "record", "--path", "x"],
                {"AISC_RUNTIME_ID": RT, "AISC_TERMINAL_SESSION_ID": SID},
            )


class TestRecordMissingIdsUsageError(unittest.TestCase):
    def _dispatch(self, env):
        ns = argparse.Namespace(
            command="artifact",
            artifact_command="record",
            runtime_id=None,
            session_id=None,
            agent="claude",
            path="x",
            action="created",
            kind="deliverable",
            media_type=None,
            label="",
            open_with="preview",
            previous_path=None,
            workspace=None,
        )
        with mock.patch.dict(os.environ, env, clear=False):
            return cli_main._cmd_artifact(ns, "json")

    def test_missing_ids_reported_with_env_hint(self):
        with pytest.raises(CliError) as exc:
            self._dispatch({})
        assert exc.value.exit_code == 2
        assert exc.value.error_code == "AISC_ERR_USAGE"
        assert "AISC_RUNTIME_ID" in exc.value.message

    def test_one_missing_id_still_reported(self):
        with pytest.raises(CliError) as exc:
            self._dispatch({})
        assert "--session-id" in exc.value.message
