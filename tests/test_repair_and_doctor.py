"""Regression tests for Docker repair and doctor interaction boundaries."""

import argparse
import io
import os
import unittest
from unittest.mock import patch

from aisc.application import repair
from aisc.cli.main import _cmd_doctor
from aisc.domain.models import CheckResult, CheckStatus, DoctorReport, ProcessResult


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def _doctor_report(message: str) -> DoctorReport:
    return DoctorReport(
        checks=[
            CheckResult(
                name="docker-cli",
                status=CheckStatus.FAIL,
                message=message,
            )
        ],
        exit_code=3,
        error_code="AISC_ERR_DOCKER_UNAVAILABLE",
    )


class DoctorInteractionTests(unittest.TestCase):
    def _args(self) -> argparse.Namespace:
        return argparse.Namespace(aisc_root=None)

    def test_json_mode_never_prompts_or_emits_plaintext(self):
        report = _doctor_report("Docker CLI not found")
        stdout = TtyBuffer()
        with patch("aisc.application.doctor.run_doctor", return_value=report), patch(
            "aisc.application.resources.locate_aisc_root", return_value=None
        ), patch(
            "aisc.application.repair.install_docker_interactive"
        ) as install, patch("sys.stdin", TtyBuffer()), patch("sys.stdout", stdout):
            data, returned_report = _cmd_doctor(self._args(), "json")

        install.assert_not_called()
        self.assertEqual(stdout.getvalue(), "")
        self.assertIs(returned_report, report)
        self.assertEqual(data["host"], report.to_dict())

    def test_cli_timeout_is_not_treated_as_missing_installation(self):
        report = _doctor_report("Docker CLI timed out")
        with patch("aisc.application.doctor.run_doctor", return_value=report), patch(
            "aisc.application.resources.locate_aisc_root", return_value=None
        ), patch(
            "aisc.application.repair.install_docker_interactive"
        ) as install, patch("sys.stdin", TtyBuffer()), patch(
            "sys.stdout", TtyBuffer()
        ):
            _cmd_doctor(self._args(), "text")

        install.assert_not_called()

    def test_missing_cli_prompts_only_in_interactive_text_mode(self):
        report = _doctor_report("Docker CLI not found")
        with patch(
            "aisc.application.doctor.run_doctor", side_effect=[report, report]
        ) as run_doctor, patch(
            "aisc.application.resources.locate_aisc_root", return_value=None
        ), patch(
            "aisc.application.repair.install_docker_interactive", return_value=True
        ) as install, patch("sys.stdin", TtyBuffer()), patch(
            "sys.stdout", TtyBuffer()
        ):
            _cmd_doctor(self._args(), "text")

        install.assert_called_once_with()
        self.assertEqual(run_doctor.call_count, 2)


class MacosDockerInstallTests(unittest.TestCase):
    class FakeRunner:
        def __init__(self) -> None:
            self.streaming_calls = []
            self.calls = []

        def run_streaming(self, argv, timeout=None):
            self.streaming_calls.append((argv, timeout))
            return ProcessResult(exit_code=0)

        def run(self, argv, timeout=None):
            self.calls.append((argv, timeout))
            return ProcessResult(exit_code=0)

    def test_homebrew_install_is_executable_and_updates_current_path(self):
        runner = self.FakeRunner()
        brew = "/opt/homebrew/bin/brew"

        with patch.object(repair, "_find_brew_executable", return_value=brew), patch.dict(
            os.environ, {"PATH": "/usr/bin"}, clear=False
        ), patch("sys.stdout", io.StringIO()):
            success, _ = repair.install_docker_macos(runner, install_brew_first=True)
            updated_path = os.environ["PATH"]

        self.assertTrue(success)
        self.assertEqual(
            runner.streaming_calls[0][0],
            [
                "/bin/bash",
                "-c",
                "curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh | /bin/bash",
            ],
        )
        self.assertEqual(
            runner.streaming_calls[1][0],
            [brew, "install", "--cask", "docker"],
        )
        self.assertTrue(updated_path.startswith(f"/opt/homebrew/bin{os.pathsep}"))
        self.assertEqual(runner.calls[0][0], ["open", "-a", "Docker"])


if __name__ == "__main__":
    unittest.main()
