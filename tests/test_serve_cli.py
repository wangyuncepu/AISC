"""D-10 (FIX-2 F2-A): the generic `cli` op — one op covers every envelope
command by reusing the one-shot CLI's own dispatch under captured stdio.

In-process tests exercise the op directly via ``_run_op``; one subprocess
test pins the v1.3 ready banner (serve_protocol 3 + home) over real pipes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from aisc.cli.commands import serve as srv  # noqa: E402


def _argv(*items: str) -> list:
    return [sys.executable, "-m", "aisc", *items]


class CliOpInProcessTests(unittest.TestCase):
    """_run_op("cli", ...) plumbing: envelope roundtrip, guards, restores."""

    def _run(self, payload: dict) -> dict:
        return srv._run_op("cli", payload, None)

    def test_version_roundtrip_returns_envelope_triple(self) -> None:
        frame = self._run({"argv": ["version"]})
        self.assertTrue(frame["ok"])
        env = frame["envelope"]
        self.assertEqual(env["meta"]["exit_code"], 0)
        self.assertEqual(env["errors"], [])
        self.assertIn("cli_version", env["data"])

    def test_json_format_is_forced_when_omitted(self) -> None:
        # No --format in argv — the op must still speak envelope.
        frame = self._run({"argv": ["version"]})
        self.assertTrue(frame["ok"])
        self.assertIn("envelope", frame)

    def test_deny_interactive_and_streaming_commands(self) -> None:
        for bad in (["run", "./x"], ["shell"], ["switch"], ["serve", "--stdio"],
                    ["build", "-t", "x"], ["session", "open"]):
            frame = self._run({"argv": bad})
            self.assertTrue(frame["ok"])  # CliError -> envelope, not a crash
            self.assertEqual(frame["envelope"]["meta"]["exit_code"], 2)
            self.assertEqual(frame["envelope"]["errors"][0]["code"], "AISC_ERR_USAGE")

    def test_events_and_help_flags_rejected(self) -> None:
        for bad in (["doctor", "--events"], ["ps", "-h"], ["ps", "--help"]):
            frame = self._run({"argv": bad})
            self.assertEqual(frame["envelope"]["meta"]["exit_code"], 2)

    def test_argparse_error_prints_envelope_and_maps_exit_code(self) -> None:
        frame = self._run({"argv": ["definitely-not-a-command"]})
        self.assertTrue(frame["ok"])
        env = frame["envelope"]
        self.assertEqual(env["meta"]["exit_code"], 2)
        self.assertEqual(env["errors"][0]["code"], "AISC_ERR_USAGE")

    def test_empty_argv_is_usage_error(self) -> None:
        frame = self._run({"argv": []})
        self.assertEqual(frame["envelope"]["meta"]["exit_code"], 2)

    def test_run_id_env_is_set_during_and_restored_after(self) -> None:
        # The payload run_id threads into the INNER envelope's meta and the
        # remote's cli_exit log line (via AISC_RUN_ID); the serve result
        # frame wraps a fresh outer envelope, so the marker is asserted at
        # the env layer, not the outer meta.
        marker = "cli-op-run-id-42"
        prev = os.environ.get("AISC_RUN_ID")
        seen = {}

        import aisc.cli.main as main_mod
        from unittest import mock

        real_main = main_mod.main

        def spy(argv):
            seen["env"] = os.environ.get("AISC_RUN_ID")
            return real_main(argv)

        try:
            with mock.patch.object(main_mod, "main", spy):
                self._run({"argv": ["version"], "run_id": marker})
            self.assertEqual(seen.get("env"), marker)
            self.assertEqual(os.environ.get("AISC_RUN_ID"), prev)
        finally:
            if prev is None:
                os.environ.pop("AISC_RUN_ID", None)
            else:
                os.environ["AISC_RUN_ID"] = prev

    def test_stdin_is_swapped_and_restored(self) -> None:
        prev_stdin = sys.stdin
        # version doesn't read stdin; the swap itself must not leak
        self._run({"argv": ["version"], "stdin": ""})
        self.assertIs(sys.stdin, prev_stdin)

    def test_non_envelope_stdout_is_honest_error(self) -> None:
        from unittest import mock
        from aisc.cli import main as main_mod

        with mock.patch.object(main_mod, "main", side_effect=lambda argv: print("hello text")):
            frame = self._run({"argv": ["version"]})
        self.assertTrue(frame["ok"])
        env = frame["envelope"]
        self.assertGreater(env["meta"]["exit_code"], 0)
        self.assertEqual(env["errors"][0]["code"], "AISC_ERR_SERVE_CLI_OUTPUT")


class CliOpSubprocessTests(unittest.TestCase):
    def _spawn(self) -> subprocess.Popen:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.Popen(
            _argv("serve", "--stdio"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.addCleanup(proc.kill)
        return proc

    def _readline(self, proc: subprocess.Popen) -> dict:
        line = proc.stdout.readline()
        self.assertTrue(line.strip(), "serve closed stdout unexpectedly")
        return json.loads(line)

    def test_v13_banner_has_protocol_three_and_home(self) -> None:
        proc = self._spawn()
        banner = self._readline(proc)
        self.assertEqual(banner["type"], "ready")
        self.assertEqual(banner["serve_protocol"], 3)
        self.assertTrue(banner["home"], "ready banner must carry the remote home path")
        proc.stdin.close()

    def test_cli_op_over_real_pipes(self) -> None:
        proc = self._spawn()
        self._readline(proc)  # banner
        proc.stdin.write('{"id":"c1","op":"cli","args":{"argv":["version","--format","json"]}}\n')
        proc.stdin.flush()
        frame = self._readline(proc)
        self.assertEqual(frame["id"], "c1")
        self.assertTrue(frame["ok"])
        self.assertEqual(frame["envelope"]["meta"]["exit_code"], 0)
        self.assertIn("cli_version", frame["envelope"]["data"])
        proc.stdin.close()


if __name__ == "__main__":
    unittest.main()
