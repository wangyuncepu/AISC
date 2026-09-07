"""2.1.10 R1: ``aisc serve --stdio`` frame protocol contract.

Two layers (AISC-R1-02):
- subprocess round-trips: ready banner, version/ps ops, all error frames,
  EOF shutdown, missing --stdio usage error;
- in-process: CliError → envelope errors, unexpected exception → ok:false
  (serve never dies from a bad op).
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SYS_AISC = [sys.executable, "-m", "aisc"]


def _argv(*args: str) -> list:
    exe = os.environ.get("AISC_CLI_EXECUTABLE")
    return [exe, *args] if exe else [*SYS_AISC, *args]


class ServeSubprocessTests(unittest.TestCase):
    """Popen round-trips over real stdio pipes."""

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

    def test_ready_banner_then_version_then_eof_exit_zero(self) -> None:
        proc = self._spawn()
        banner = self._readline(proc)
        self.assertEqual(banner["type"], "ready")
        self.assertEqual(banner["serve_protocol"], 1)
        self.assertTrue(banner["cli_version"])

        proc.stdin.write('{"id":"u1","op":"version","args":[]}\n')
        proc.stdin.flush()
        frame = self._readline(proc)
        self.assertEqual(frame["id"], "u1")
        self.assertTrue(frame["ok"])
        env = frame["envelope"]
        self.assertEqual(env["meta"]["command"], "version")
        self.assertEqual(env["meta"]["exit_code"], 0)
        self.assertEqual(env["errors"], [])
        self.assertEqual(env["data"]["cli_version"], banner["cli_version"])
        # capabilities ride the version envelope — the pairing surface
        self.assertIn("capabilities", env["data"])

        proc.stdin.close()  # EOF
        self.assertEqual(proc.wait(timeout=10), 0)

    def test_ps_op_returns_array_data(self) -> None:
        proc = self._spawn()
        self._readline(proc)  # banner
        proc.stdin.write('{"id":"p1","op":"ps","args":[]}\n')
        proc.stdin.flush()
        frame = self._readline(proc)
        self.assertEqual(frame["id"], "p1")
        self.assertTrue(frame["ok"])
        self.assertIsInstance(frame["envelope"]["data"], list)
        proc.stdin.close()
        proc.wait(timeout=10)

    def test_error_frames_never_kill_the_process(self) -> None:
        proc = self._spawn()
        self._readline(proc)  # banner
        for payload in (
            "not json at all",
            '{"id":"c1","op":"nope","args":[]}',
            '{"id":"c2"}',
        ):
            proc.stdin.write(payload + "\n")
            proc.stdin.flush()
            frame = self._readline(proc)
            self.assertFalse(frame["ok"], payload)
        # still alive: a follow-up op works
        proc.stdin.write('{"id":"ok1","op":"version","args":[]}\n')
        proc.stdin.flush()
        frame = self._readline(proc)
        self.assertTrue(frame["ok"])
        proc.stdin.close()
        self.assertEqual(proc.wait(timeout=10), 0)

    def test_blank_lines_are_skipped(self) -> None:
        proc = self._spawn()
        self._readline(proc)
        proc.stdin.write("\n\n")
        proc.stdin.write('{"id":"b1","op":"version","args":[]}\n')
        proc.stdin.flush()
        frame = self._readline(proc)
        self.assertEqual(frame["id"], "b1")
        self.assertTrue(frame["ok"])
        proc.stdin.close()
        proc.wait(timeout=10)

    def test_missing_stdio_flag_is_usage_error(self) -> None:
        proc = subprocess.run(
            _argv("serve"), capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )
        self.assertEqual(proc.returncode, 2)


class ServeInProcessTests(unittest.TestCase):
    """Direct calls into the serve module — no subprocess."""

    def test_cli_error_maps_to_envelope_errors(self) -> None:
        from aisc.cli.commands import serve as srv
        from aisc.domain.models import CliError

        def boom(_args):
            raise CliError(message="nope", exit_code=7,
                           error_code="AISC_ERR_TEST", hint="do better")

        with mock.patch.dict(srv.OPS, {"boom": boom}):
            frame = srv._run_op("boom", [])
        self.assertTrue(frame["ok"])  # controlled failure is still a result
        env = frame["envelope"]
        self.assertEqual(env["meta"]["exit_code"], 7)
        self.assertEqual(env["errors"][0]["code"], "AISC_ERR_TEST")
        self.assertEqual(env["errors"][0]["hint"], "do better")

    def test_unexpected_exception_is_error_frame_not_crash(self) -> None:
        from aisc.cli.commands import serve as srv

        def boom(_args):
            raise RuntimeError("kaboom")

        with mock.patch.dict(srv.OPS, {"boom": boom}):
            frame = srv._run_op("boom", [])
        self.assertFalse(frame["ok"])
        self.assertIn("kaboom", frame["error"])

    def test_serve_loop_over_stringio(self) -> None:
        from aisc.cli.commands import serve as srv

        stdin = io.StringIO('{"id":"x","op":"version","args":[]}\n')
        stdout = io.StringIO()
        rc = srv._serve_loop(stdin, stdout)
        self.assertEqual(rc, 0)
        lines = [json.loads(l) for l in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0]["type"], "ready")
        self.assertEqual(lines[-1]["id"], "x")
        self.assertTrue(lines[-1]["ok"])

    def test_doctor_op_carries_report_exit_code(self) -> None:
        """doctor's exit code must ride the envelope (0 or 3), not a hard 0 —
        the one-shot CLI contract, preserved through serve."""
        from aisc.cli.commands import serve as srv
        from aisc.domain.models import DoctorReport

        fake_report = DoctorReport(
            exit_code=3,
            error_code="AISC_ERR_DOCKER_UNAVAILABLE",
        )
        with mock.patch("aisc.cli.main._cmd_doctor",
                        return_value=({"host": {"checks": []}}, fake_report)):
            frame = srv._run_op("doctor", [])
        self.assertTrue(frame["ok"])
        self.assertEqual(frame["envelope"]["meta"]["exit_code"], 3)


if __name__ == "__main__":
    unittest.main()
