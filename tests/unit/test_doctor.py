"""Unit tests for aisc.application.doctor — doctor checks with fake processes."""

import os
import stat as st_module
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from aisc.application.doctor import (
    run_doctor,
    _check_docker_cli,
    _check_docker_daemon,
    _check_docker_permission,
    _check_docker_buildx,
    _check_tun_device,
    _check_aisc_root,
    _check_root_files,
    _check_git,
    _check_docker_compose,
    _check_root_writable,
    _check_launcher,
    _check_brief_py_syntax,
    _compute_exit_code,
    EXIT_OK,
    EXIT_DOCKER_UNAVAILABLE,
    EXIT_PERMISSION_DENIED,
    EXIT_GENERAL,
    ERR_DOCKER_UNAVAILABLE,
    ERR_GENERAL,
    DOCKER_TIMEOUT,
    GIT_TIMEOUT,
    COMPOSE_TIMEOUT,
)
from aisc.domain.models import (
    CheckResult,
    CheckStatus,
    DoctorReport,
    ProcessResult,
)


# ---------------------------------------------------------------------------
# Fake process runner for deterministic testing
# ---------------------------------------------------------------------------

class FakeProcessRunner:
    def __init__(self):
        self._results: dict = {}
        self._calls: List[List[str]] = []

    def set_result(self, key: str, result: ProcessResult) -> None:
        self._results[key] = result

    def run(self, argv: List[str], timeout: Optional[float] = None) -> ProcessResult:
        self._calls.append(argv)
        # Try most specific matches first, fall back to generic
        candidates: List[str] = []

        # Most specific: docker <sub> <sub2> → "docker buildx version"
        if len(argv) >= 4:
            candidates.append("docker " + " ".join(argv[1:4]))
        if len(argv) >= 3:
            candidates.append("docker " + " ".join(argv[1:3]))
            candidates.append(" ".join(argv[1:3]))  # "buildx version"
        if len(argv) >= 2:
            candidates.append("docker " + argv[1])  # "docker info"
            candidates.append(" ".join(argv[-2:]))  # last two
        candidates.append(" ".join(argv))           # full command
        candidates.append(argv[0])                  # bare command

        for caller in candidates:
            if caller in self._results:
                return self._results[caller]
        return ProcessResult(stdout="fake output\n", stderr="", exit_code=0)

    @property
    def calls(self) -> List[List[str]]:
        return self._calls


# ---------------------------------------------------------------------------
# Tests: individual check functions
# ---------------------------------------------------------------------------

class TestCheckDockerCli(unittest.TestCase):
    def test_available(self):
        r = FakeProcessRunner()
        r.set_result("/usr/bin/docker", ProcessResult(
            stdout="Docker version 24.0.7\n", stderr="", exit_code=0,
        ))
        result = _check_docker_cli("/usr/bin/docker", r)
        self.assertEqual(result.status, CheckStatus.PASS)
        self.assertIn("Docker version", result.message)

    def test_not_found(self):
        r = FakeProcessRunner()
        r.set_result("/usr/bin/docker", ProcessResult(
            stdout="", stderr="", exit_code=-1, command_not_found=True,
        ))
        result = _check_docker_cli("/usr/bin/docker", r)
        self.assertEqual(result.status, CheckStatus.FAIL)

    def test_error(self):
        r = FakeProcessRunner()
        r.set_result("/usr/bin/docker", ProcessResult(
            stdout="", stderr="some error", exit_code=1,
        ))
        result = _check_docker_cli("/usr/bin/docker", r)
        self.assertEqual(result.status, CheckStatus.FAIL)

    def test_timeout(self):
        r = FakeProcessRunner()
        r.set_result("/usr/bin/docker", ProcessResult(
            stdout="", stderr="", exit_code=-1, timed_out=True,
        ))
        result = _check_docker_cli("/usr/bin/docker", r)
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertIn("timed out", result.message.lower())

    def test_uses_injected_docker_path(self):
        r = FakeProcessRunner()
        r.set_result("/custom/path/docker", ProcessResult(
            stdout="Docker version\n", stderr="", exit_code=0,
        ))
        result = _check_docker_cli("/custom/path/docker", r)
        self.assertEqual(result.status, CheckStatus.PASS)
        # Verify the runner was called with the custom path
        self.assertIn(["/custom/path/docker", "--version"], r._calls)


class TestCheckDockerDaemon(unittest.TestCase):
    def test_running(self):
        r = FakeProcessRunner()
        r.set_result("/usr/bin/docker", ProcessResult(
            stdout="Containers: 1\n", stderr="", exit_code=0,
        ))
        result = _check_docker_daemon("/usr/bin/docker", r, True)
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_not_running(self):
        r = FakeProcessRunner()
        r.set_result("/usr/bin/docker", ProcessResult(
            stdout="", stderr="Cannot connect", exit_code=1,
        ))
        result = _check_docker_daemon("/usr/bin/docker", r, True)
        self.assertEqual(result.status, CheckStatus.FAIL)

    def test_skip_when_cli_missing(self):
        r = FakeProcessRunner()
        result = _check_docker_daemon("/usr/bin/docker", r, False)
        self.assertEqual(result.status, CheckStatus.SKIP)

    def test_timeout(self):
        r = FakeProcessRunner()
        r.set_result("/usr/bin/docker", ProcessResult(
            stdout="", stderr="", exit_code=-1, timed_out=True,
        ))
        result = _check_docker_daemon("/usr/bin/docker", r, True)
        self.assertEqual(result.status, CheckStatus.FAIL)


class TestCheckDockerPermission(unittest.TestCase):
    def test_ok(self):
        r = FakeProcessRunner()
        r.set_result("docker ps", ProcessResult(stdout="", stderr="", exit_code=0))
        result = _check_docker_permission("/usr/bin/docker", r, True, False)
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_permission_denied(self):
        r = FakeProcessRunner()
        r.set_result("docker ps", ProcessResult(
            stdout="", stderr="permission denied", exit_code=1,
        ))
        result = _check_docker_permission("/usr/bin/docker", r, True, False)
        self.assertEqual(result.status, CheckStatus.FAIL)

    def test_skip_when_cli_missing(self):
        r = FakeProcessRunner()
        result = _check_docker_permission("/usr/bin/docker", r, False, False)
        self.assertEqual(result.status, CheckStatus.SKIP)

    def test_skip_when_daemon_failed(self):
        r = FakeProcessRunner()
        result = _check_docker_permission("/usr/bin/docker", r, True, True)
        self.assertEqual(result.status, CheckStatus.SKIP)


class TestCheckBuildx(unittest.TestCase):
    def test_available(self):
        r = FakeProcessRunner()
        r.set_result("docker buildx version", ProcessResult(
            stdout="github.com/docker/buildx v0.12\n", stderr="", exit_code=0,
        ))
        result = _check_docker_buildx("/usr/bin/docker", r, True, False)
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_not_available(self):
        r = FakeProcessRunner()
        r.set_result("docker buildx version", ProcessResult(
            stdout="", stderr="not found", exit_code=1,
        ))
        result = _check_docker_buildx("/usr/bin/docker", r, True, False)
        self.assertEqual(result.status, CheckStatus.WARN)

    def test_skip_when_cli_missing(self):
        r = FakeProcessRunner()
        result = _check_docker_buildx("/usr/bin/docker", r, False, False)
        self.assertEqual(result.status, CheckStatus.SKIP)


class TestCheckTunDevice(unittest.TestCase):
    def test_linux_tun_char_device(self):
        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.stat") as mock_stat:
                import stat as st_mod
                mock_stat.return_value.st_mode = st_mod.S_IFCHR
                result = _check_tun_device()
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_linux_tun_not_char_device(self):
        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_mode = 0o100644  # regular file
                result = _check_tun_device()
        self.assertEqual(result.status, CheckStatus.WARN)

    def test_linux_tun_file_not_found(self):
        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
                result = _check_tun_device()
        self.assertEqual(result.status, CheckStatus.WARN)

    def test_linux_tun_oserror(self):
        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.stat", side_effect=OSError("permission")):
                result = _check_tun_device()
        self.assertEqual(result.status, CheckStatus.WARN)

    def test_non_linux_skips(self):
        with patch("sys.platform", "darwin"):
            result = _check_tun_device()
        self.assertEqual(result.status, CheckStatus.SKIP)

    def test_windows_skips(self):
        with patch("sys.platform", "win32"):
            result = _check_tun_device()
        self.assertEqual(result.status, CheckStatus.SKIP)


class TestCheckAiscRoot(unittest.TestCase):
    def test_found(self):
        result = _check_aisc_root(Path("/repo"), root_error=None)
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_not_found(self):
        result = _check_aisc_root(None, root_error=None)
        self.assertEqual(result.status, CheckStatus.WARN)

    def test_explicit_invalid(self):
        result = _check_aisc_root(None, root_error="--aisc-root /bad: not a directory")
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertIn("--aisc-root /bad", result.message)


class TestCheckRootFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_all_files_exist(self):
        for f in ["VERSION", "container/Dockerfile", "config/versions.env"]:
            p = self.root / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("content")
        results = _check_root_files(self.root)
        self.assertTrue(all(r.status == CheckStatus.PASS for r in results))

    def test_missing_file(self):
        (self.root / "VERSION").write_text("content")
        results = _check_root_files(self.root)
        statuses = {r.name: r.status for r in results}
        self.assertEqual(statuses.get("root-file:VERSION"), CheckStatus.PASS)
        self.assertIn(CheckStatus.FAIL, statuses.values())

    def test_no_root_skips(self):
        results = _check_root_files(None)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, CheckStatus.SKIP)


class TestCheckGit(unittest.TestCase):
    def test_available(self):
        r = FakeProcessRunner()
        r.set_result("/usr/bin/git", ProcessResult(
            stdout="git version 2.39.2\n", stderr="", exit_code=0,
        ))
        result = _check_git("/usr/bin/git", r)
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_not_available(self):
        r = FakeProcessRunner()
        r.set_result("/usr/bin/git", ProcessResult(
            stdout="", stderr="", exit_code=-1, command_not_found=True,
        ))
        result = _check_git("/usr/bin/git", r)
        self.assertEqual(result.status, CheckStatus.WARN)


class TestCheckDockerCompose(unittest.TestCase):
    def test_available(self):
        r = FakeProcessRunner()
        r.set_result("docker compose version", ProcessResult(
            stdout="Docker Compose version v2.24.0\n", stderr="", exit_code=0,
        ))
        result = _check_docker_compose("/usr/bin/docker", r, True)
        self.assertEqual(result.status, CheckStatus.PASS)
        self.assertIn("Docker Compose", result.message)

    def test_not_available_subcommand_missing(self):
        r = FakeProcessRunner()
        r.set_result("docker compose version", ProcessResult(
            stdout="", stderr="docker: 'compose' is not a docker command.",
            exit_code=1, command_not_found=True,
        ))
        result = _check_docker_compose("/usr/bin/docker", r, True)
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertIn("subcommand not available", result.message)
        # hint should be user-actionable
        self.assertIsNotNone(result.hint)
        self.assertIn("install", (result.hint or "").lower())

    def test_timeout(self):
        r = FakeProcessRunner()
        r.set_result("docker compose version", ProcessResult(
            stdout="", stderr="", exit_code=-1, timed_out=True,
        ))
        result = _check_docker_compose("/usr/bin/docker", r, True)
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertIn("timed out", result.message.lower())

    def test_cli_unavailable_skips(self):
        r = FakeProcessRunner()
        result = _check_docker_compose(None, r, False)
        self.assertEqual(result.status, CheckStatus.SKIP)

    def test_exit_code_nonzero(self):
        r = FakeProcessRunner()
        r.set_result("docker compose version", ProcessResult(
            stdout="", stderr="unknown error", exit_code=1,
        ))
        result = _check_docker_compose("/usr/bin/docker", r, True)
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertIn("docker compose version", result.hint or "")

    def test_unknown_command_without_runner_flag_is_unavailable(self):
        r = FakeProcessRunner()
        r.set_result("docker compose version", ProcessResult(
            stdout="", stderr="docker: unknown command: docker compose", exit_code=1,
        ))
        result = _check_docker_compose("/usr/bin/docker", r, True)
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertIn("Install", result.hint or "")


class TestCheckRootWritable(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_writable(self):
        result = _check_root_writable(self.root)
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_not_writable(self):
        with patch("os.access", return_value=False):
            result = _check_root_writable(self.root)
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertIn("not be writable", result.message.lower())

    def test_root_not_a_directory(self):
        f = self.root / "notadir"
        f.write_text("x")
        result = _check_root_writable(f)
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertIn("not a directory", result.message.lower())

    def test_root_does_not_exist(self):
        result = _check_root_writable(self.root / "nonexistent")
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertIn("does not exist", result.message.lower())

    def test_no_root_skips(self):
        result = _check_root_writable(None)
        self.assertEqual(result.status, CheckStatus.SKIP)

    def test_oserror_caught(self):
        with patch("pathlib.Path.exists", side_effect=OSError("permission denied")):
            result = _check_root_writable(self.root)
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertIn("Cannot check", result.message)

    def test_hint_is_user_actionable(self):
        """Assert hint is a concrete suggestion, not empty."""
        with patch("os.access", return_value=False):
            result = _check_root_writable(self.root)
        self.assertIsNotNone(result.hint)
        self.assertGreater(len(result.hint), 0)


class TestCheckLauncher(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_windows_skips(self):
        with patch("sys.platform", "win32"):
            results = _check_launcher(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, CheckStatus.SKIP)
        self.assertEqual(results[0].name, "launcher")

    def test_linux_start_sh_executable(self):
        script = self.root / "start.sh"
        script.write_text("#!/bin/bash\necho hi")
        script.chmod(0o755)
        with patch("sys.platform", "linux"):
            results = _check_launcher(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, CheckStatus.PASS)
        self.assertEqual(results[0].name, "launcher:start.sh")

    def test_linux_start_sh_not_executable(self):
        script = self.root / "start.sh"
        script.write_text("#!/bin/bash\necho hi")
        script.chmod(0o644)
        with patch("sys.platform", "linux"):
            results = _check_launcher(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, CheckStatus.WARN)
        self.assertIn("not executable", results[0].message.lower())
        # hint should include chmod command
        self.assertIsNotNone(results[0].hint)
        self.assertIn("chmod", results[0].hint)

    def test_linux_start_sh_missing(self):
        with patch("sys.platform", "linux"):
            results = _check_launcher(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, CheckStatus.WARN)
        self.assertIn("not found", results[0].message.lower())

    def test_linux_start_sh_not_regular_file(self):
        # create a directory with same name
        (self.root / "start.sh").mkdir()
        with patch("sys.platform", "linux"):
            results = _check_launcher(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, CheckStatus.WARN)
        self.assertIn("not a regular file", results[0].message.lower())

    def test_macos_checks_both_scripts(self):
        script_sh = self.root / "start.sh"
        script_sh.write_text("#!/bin/bash\necho hi")
        script_sh.chmod(0o755)
        script_cmd = self.root / "start.command"
        script_cmd.write_text("#!/bin/bash\necho hi")
        script_cmd.chmod(0o755)
        with patch("sys.platform", "darwin"):
            results = _check_launcher(self.root)
        self.assertEqual(len(results), 2)
        names = [r.name for r in results]
        self.assertIn("launcher:start.sh", names)
        self.assertIn("launcher:start.command", names)
        self.assertTrue(all(r.status == CheckStatus.PASS for r in results))

    def test_macos_start_command_not_executable(self):
        self.root.joinpath("start.sh").write_text("#!/bin/bash\necho hi")
        self.root.joinpath("start.sh").chmod(0o755)
        cmd = self.root / "start.command"
        cmd.write_text("#!/bin/bash\necho hi")
        cmd.chmod(0o644)
        with patch("sys.platform", "darwin"):
            results = _check_launcher(self.root)
        sh_result = next(r for r in results if r.name == "launcher:start.sh")
        cmd_result = next(r for r in results if r.name == "launcher:start.command")
        self.assertEqual(sh_result.status, CheckStatus.PASS)
        self.assertEqual(cmd_result.status, CheckStatus.WARN)
        self.assertIn("chmod +x start.command", cmd_result.hint)

    def test_no_root_skips(self):
        with patch("sys.platform", "linux"):
            results = _check_launcher(None)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, CheckStatus.SKIP)

    def test_oserror_caught(self):
        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.exists", side_effect=OSError("I/O error")):
                results = _check_launcher(self.root)
        self.assertEqual(results[0].status, CheckStatus.WARN)
        self.assertIn("Cannot check", results[0].message)


class TestCheckBriefPySyntax(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create_brief_py(self, content: str) -> Path:
        fpath = self.root / "apps" / "ai-brief" / "brief.py"
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
        return fpath

    def test_valid_syntax(self):
        self._create_brief_py("print('hello')\n")
        result = _check_brief_py_syntax(self.root)
        self.assertEqual(result.status, CheckStatus.PASS)
        self.assertIn("valid", result.message.lower())

    def test_syntax_error(self):
        self._create_brief_py("def broken(\n")
        result = _check_brief_py_syntax(self.root)
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertIn("Syntax error", result.message)
        self.assertIn("line", result.message.lower())
        # detail includes file path and line number
        self.assertIsNotNone(result.detail)
        self.assertIn("brief.py", result.detail)
        # message should not leak file content
        self.assertNotIn("broken", result.message)
        # hint exists and is actionable
        self.assertIsNotNone(result.hint)
        self.assertIn("Fix", result.hint)

    def test_syntax_error_line_number_in_detail(self):
        self._create_brief_py("# line 1\n# line 2\ndef bad(\n# line 4\n")
        result = _check_brief_py_syntax(self.root)
        # detail should have file:lineno
        self.assertIn(":", result.detail)
        # the line number should be in the detail
        self.assertIn("3", result.detail)

    def test_file_missing(self):
        result = _check_brief_py_syntax(self.root)
        self.assertEqual(result.status, CheckStatus.WARN)
        self.assertIn("not found", result.message.lower())

    def test_read_error(self):
        # create a directory instead of file to trigger IsADirectoryError (OSError)
        dirpath = self.root / "apps" / "ai-brief" / "brief.py"
        dirpath.mkdir(parents=True, exist_ok=True)
        result = _check_brief_py_syntax(self.root)
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertIn("Cannot read", result.message)

    def test_no_root_skips(self):
        result = _check_brief_py_syntax(None)
        self.assertEqual(result.status, CheckStatus.SKIP)


class TestComputeExitCode(unittest.TestCase):
    def test_all_pass(self):
        checks = [
            CheckResult(name="docker-cli", status=CheckStatus.PASS, message="ok"),
        ]
        exit_code, err_code, _ = _compute_exit_code(checks)
        self.assertEqual(exit_code, EXIT_OK)

    def test_docker_cli_missing_priority_3(self):
        checks = [
            CheckResult(name="docker-cli", status=CheckStatus.FAIL, message="missing"),
        ]
        exit_code, err_code, _ = _compute_exit_code(checks)
        self.assertEqual(exit_code, EXIT_DOCKER_UNAVAILABLE)

    def test_docker_daemon_fail_priority_3(self):
        checks = [
            CheckResult(name="docker-cli", status=CheckStatus.PASS, message="ok"),
            CheckResult(name="docker-daemon", status=CheckStatus.FAIL, message="down"),
        ]
        exit_code, err_code, _ = _compute_exit_code(checks)
        self.assertEqual(exit_code, EXIT_DOCKER_UNAVAILABLE)

    def test_permission_only_priority_9(self):
        checks = [
            CheckResult(name="docker-cli", status=CheckStatus.PASS, message="ok"),
            CheckResult(name="docker-daemon", status=CheckStatus.PASS, message="ok"),
            CheckResult(name="docker-permission", status=CheckStatus.FAIL, message="perm"),
        ]
        exit_code, err_code, _ = _compute_exit_code(checks)
        self.assertEqual(exit_code, EXIT_PERMISSION_DENIED)

    def test_explicit_root_invalid_priority_1(self):
        checks = [
            CheckResult(name="docker-cli", status=CheckStatus.PASS, message="ok"),
            CheckResult(name="aisc-root", status=CheckStatus.FAIL, message="invalid"),
        ]
        exit_code, err_code, _ = _compute_exit_code(checks)
        self.assertEqual(exit_code, EXIT_GENERAL)


# ---------------------------------------------------------------------------
# run_doctor integration tests
# ---------------------------------------------------------------------------

class TestRunDoctor(unittest.TestCase):
    def test_all_pass_with_which(self):
        r = FakeProcessRunner()
        r.set_result("/docker/path", ProcessResult(
            stdout="Docker version 24\n", stderr="", exit_code=0,
        ))
        r.set_result("/usr/bin/docker", ProcessResult(
            stdout="Docker version 24\n", stderr="", exit_code=0,
        ))
        r.set_result("docker info", ProcessResult(stdout="ok", stderr="", exit_code=0))
        r.set_result("docker ps", ProcessResult(stdout="", stderr="", exit_code=0))
        r.set_result("docker buildx version", ProcessResult(
            stdout="buildx v1\n", stderr="", exit_code=0,
        ))
        r.set_result("/git/path", ProcessResult(
            stdout="git version 2.39\n", stderr="", exit_code=0,
        ))

        def fake_which(name: str) -> Optional[str]:
            if name == "docker":
                return "/docker/path"
            if name == "git":
                return "/git/path"
            return None

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for f in ["VERSION", "container/Dockerfile", "config/versions.env"]:
                p = root / f
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("x")

            with patch("sys.platform", "linux"):
                original_stat = Path.stat
                def selective_stat(self, follow_symlinks=True):
                    if str(self) == "/dev/net/tun":
                        import stat as st_mod
                        from unittest.mock import Mock
                        m = Mock()
                        m.st_mode = st_mod.S_IFCHR
                        return m
                    return original_stat(self, follow_symlinks=follow_symlinks)

                with patch.object(Path, "stat", selective_stat):
                    report = run_doctor(runner=r, root=root, which=fake_which)

        self.assertEqual(report.exit_code, EXIT_OK)
        self.assertEqual(report.summary["failures"], 0)
        # First call should use the resolved /docker/path for --version
        self.assertIn(["/docker/path", "--version"], r._calls)

    def test_docker_cli_zero_calls_when_which_returns_none(self):
        """When which returns None for docker: FAIL, exit 3, zero subprocess calls."""
        r = FakeProcessRunner()

        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
                report = run_doctor(runner=r, root=None, which=lambda name: None)

        # docker-cli must be FAIL (not SKIP) — Docker not found
        docker_cli = next(c for c in report.checks if c.name == "docker-cli")
        self.assertEqual(docker_cli.status, CheckStatus.FAIL,
                         "docker-cli should be FAIL when which returns None")

        # daemon/permission/buildx must be SKIP (no subprocess calls)
        for name in ("docker-daemon", "docker-permission", "docker-buildx"):
            c = next(cc for cc in report.checks if cc.name == name)
            self.assertEqual(c.status, CheckStatus.SKIP,
                             f"{name} should be SKIP when CLI unavailable")

        # Exit code must be 3 (DOCKER_UNAVAILABLE)
        self.assertEqual(report.exit_code, EXIT_DOCKER_UNAVAILABLE)
        self.assertEqual(report.error_code, ERR_DOCKER_UNAVAILABLE)

        # No calls for docker or git should have been made
        for call in r._calls:
            for item in call:
                self.assertNotIn("docker", item)
                self.assertNotIn("git", item)

    def test_docker_cli_missing_exit_3(self):
        r = FakeProcessRunner()
        r.set_result("/docker/path", ProcessResult(
            stdout="", stderr="", exit_code=-1, command_not_found=True,
        ))

        def fake_which(name: str) -> Optional[str]:
            return "/docker/path" if name == "docker" else "/git/path"

        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
                report = run_doctor(runner=r, root=None, which=fake_which)

        self.assertEqual(report.exit_code, EXIT_DOCKER_UNAVAILABLE)

        # Docker-permission and daemon should be SKIP
        perm = next(c for c in report.checks if c.name == "docker-permission")
        self.assertEqual(perm.status, CheckStatus.SKIP)

    def test_permission_only_exit_9(self):
        r = FakeProcessRunner()
        r.set_result("/docker/path", ProcessResult(
            stdout="Docker version\n", stderr="", exit_code=0,
        ))
        r.set_result("docker info", ProcessResult(stdout="ok", stderr="", exit_code=0))
        r.set_result("docker ps", ProcessResult(
            stdout="", stderr="permission denied", exit_code=1,
        ))
        r.set_result("docker buildx version", ProcessResult(
            stdout="buildx\n", stderr="", exit_code=0,
        ))

        def fake_which(name: str) -> Optional[str]:
            return "/docker/path" if name == "docker" else "/git/path"

        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
                report = run_doctor(runner=r, root=None, which=fake_which)

        self.assertEqual(report.exit_code, EXIT_PERMISSION_DENIED)
        self.assertEqual(report.error_code, "AISC_ERR_PERMISSION_DENIED")

    def test_buildx_warn_does_not_fail(self):
        r = FakeProcessRunner()
        r.set_result("/docker/path", ProcessResult(
            stdout="Docker version\n", stderr="", exit_code=0,
        ))
        r.set_result("docker info", ProcessResult(stdout="ok", stderr="", exit_code=0))
        r.set_result("docker ps", ProcessResult(stdout="", stderr="", exit_code=0))
        r.set_result("docker buildx version", ProcessResult(
            stdout="", stderr="not found", exit_code=1,
        ))

        def fake_which(name: str) -> Optional[str]:
            return "/docker/path" if name == "docker" else "/git/path"

        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
                report = run_doctor(runner=r, root=None, which=fake_which)

        self.assertEqual(report.exit_code, EXIT_OK)
        buildx = next(c for c in report.checks if c.name == "docker-buildx")
        self.assertEqual(buildx.status, CheckStatus.WARN)

    def test_explicit_root_invalid_in_report(self):
        r = FakeProcessRunner()
        r.set_result("/docker/path", ProcessResult(
            stdout="Docker version\n", stderr="", exit_code=0,
        ))

        def fake_which(name: str) -> Optional[str]:
            return "/docker/path" if name == "docker" else "/git/path"

        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
                report = run_doctor(
                    runner=r, root=None,
                    root_error="--aisc-root /bad: not a directory",
                    which=fake_which,
                )

        root_check = next(c for c in report.checks if c.name == "aisc-root")
        self.assertEqual(root_check.status, CheckStatus.FAIL)
        self.assertIn("--aisc-root /bad", root_check.message)
        self.assertEqual(report.exit_code, EXIT_GENERAL)

    def test_timeout_constants(self):
        """Verify timeout constants are defined."""
        self.assertGreater(DOCKER_TIMEOUT, 0)
        self.assertGreater(GIT_TIMEOUT, 0)
        self.assertGreater(COMPOSE_TIMEOUT, 0)


if __name__ == "__main__":
    unittest.main()
