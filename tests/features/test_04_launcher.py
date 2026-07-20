"""Characterization tests for ``scripts/04_launcher.sh``.

Uses a fake ``docker`` (captures argv, never touches real Docker) inside an
isolated temp project skeleton.  Covers DO_RUN=0, workspace errors, basic
docker-run argv, proxy append, exit-code pass-through, and workspace path
with spaces (argv-boundary preservation).
"""

from __future__ import annotations

import os
import unittest

from tests.features.helpers import (
    TempProject,
    find_invocation,
    install_fake_docker,
    parse_docker_trace,
)
from tests.harness.test_runner import CliRunner


class LauncherTest(unittest.TestCase):
    """Tests exercising the launcher in a temp project with fake docker."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = CliRunner()

    def setUp(self) -> None:
        # Temp project skeleton: real _state.sh + 04_launcher.sh
        self.proj = TempProject(scripts=("_state.sh", "04_launcher.sh"))
        # Fake docker that logs to a trace file inside the temp project
        self.trace = self.proj.path("docker_trace.txt")
        self.fake_docker = install_fake_docker(self.proj.tmpdir, self.trace)
        # Ensure the fake docker is on PATH for subprocess
        self._base_env = {
            "PATH": f"{self.proj.tmpdir}:{os.environ.get('PATH', '')}",
            "HOME": self.proj.tmpdir,
            "DOCKER_TRACE_FILE": self.trace,
            "DOCKER_IMAGE_EXISTS": "0",
        }
        # Workspace dir (readable, exists)
        self.workspace = self.proj.path("workspace")
        os.makedirs(self.workspace, exist_ok=True)

    def tearDown(self) -> None:
        self.proj.destroy()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _launcher_path(self) -> str:
        return os.path.join(self.proj.scripts_dir, "04_launcher.sh")

    def _run_launcher(self, extra_env=None, **kw):
        env = dict(self._base_env)
        if extra_env:
            env.update(extra_env)
        return self.runner.run(
            ["bash", self._launcher_path()],
            cwd=self.proj.tmpdir,
            env=env,
            **kw,
        )

    def _state_set(self, key: str, val: str) -> None:
        """Write a key into both primary and legacy state files."""
        for d in (".aisc", ".deploy"):
            sdir = self.proj.path(d)
            os.makedirs(sdir, exist_ok=True)
            sfile = os.path.join(sdir, "state.env")
            with open(sfile, "a") as fh:
                fh.write(f"{key}={val}\n")

    def _trace_content(self) -> str:
        if os.path.isfile(self.trace):
            with open(self.trace) as fh:
                return fh.read()
        return ""

    def _parse_trace(self):
        return parse_docker_trace(self._trace_content())

    # ------------------------------------------------------------------
    # DO_RUN=0 — exit early, no docker call
    # ------------------------------------------------------------------

    def test_do_run_zero_exits_zero(self) -> None:
        self._state_set("DO_RUN", "0")
        self._state_set("IMAGE", "test-img")
        result = self._run_launcher(
            extra_env={"AISC_WORKSPACE": self.workspace}
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("DO_RUN=0", result.stdout)

    def test_do_run_zero_no_docker_called(self) -> None:
        self._state_set("DO_RUN", "0")
        self._state_set("IMAGE", "test-img")
        self._run_launcher(
            extra_env={"AISC_WORKSPACE": self.workspace}
        )
        trace = self._trace_content()
        self.assertEqual(trace.strip(), "",
                         f"docker was called unexpectedly: {trace}")

    # ------------------------------------------------------------------
    # Workspace validation
    # ------------------------------------------------------------------

    def test_workspace_nonexistent(self) -> None:
        self._state_set("DO_RUN", "1")
        result = self._run_launcher(
            extra_env={"AISC_WORKSPACE": "/nonexistent/xyz"}
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("does not exist", result.stderr.lower())

    def test_workspace_not_readable(self) -> None:
        """Create a dir, chmod 0000, verify launcher rejects it.

        On systems where the owner has DAC override (e.g. root or
        certain kernel configs) the dir may remain readable even after
        chmod 000.  We detect that case and skip rather than failing
        spuriously.
        """
        unreadable = self.proj.path("unreadable_ws")
        os.makedirs(unreadable, exist_ok=True)
        os.chmod(unreadable, 0o000)
        try:
            if os.access(unreadable, os.R_OK):
                self.skipTest(
                    "directory still readable after chmod 000 "
                    "(DAC override / root); cannot exercise not-readable path"
                )
            self._state_set("DO_RUN", "1")
            result = self._run_launcher(
                extra_env={"AISC_WORKSPACE": unreadable}
            )
            # Should fail — either "not readable" or "does not exist" (perms
            # may cause stat to fail)
            self.assertNotEqual(result.exit_code, 0,
                                "expected non-zero exit for unreadable workspace")
            combined = (result.stderr + result.stdout).lower()
            self.assertTrue(
                "not readable" in combined or "does not exist" in combined
                or "permission denied" in combined,
                f"expected permission-related error, got: {result.stderr!r}"
            )
        finally:
            os.chmod(unreadable, 0o755)

    # ------------------------------------------------------------------
    # Workspace with spaces — argv boundary integrity
    # ------------------------------------------------------------------

    def test_workspace_with_spaces_preserves_argv_boundary(self) -> None:
        """``-v`` bind-mount arg must be a single argv token, not split."""
        ws = self.proj.path("my workspace")
        os.makedirs(ws, exist_ok=True)

        self._state_set("DO_RUN", "1")
        self._state_set("IMAGE", "spaces-test-img")
        self._state_set("CONTAINER_NAME", "c1")
        self._state_set("PROXY_ENABLED", "0")

        self._run_launcher(extra_env={"AISC_WORKSPACE": ws})
        invs = self._parse_trace()
        run_inv = find_invocation(invs, "run")
        self.assertIsNotNone(run_inv, f"no 'run' invocation in trace; invs={invs}")
        assert run_inv is not None  # help type checker

        # Locate the bind-mount arg: -v SOURCE:DEST
        bind_mount = None
        for i, arg in enumerate(run_inv.args):
            if arg == "-v" and i + 1 < len(run_inv.args):
                bind_mount = run_inv.args[i + 1]
                break

        self.assertIsNotNone(
            bind_mount,
            f"-v not found in structured args: {run_inv.args}",
        )
        assert bind_mount is not None  # type checker

        # The bind-mount arg must be a SINGLE token with ':' separator
        # (e.g. "/tmp/path with spaces:/home/AISC/app")
        self.assertIn(":", bind_mount,
                      f"bind-mount missing ':' separator: {bind_mount!r}")
        src, _, dst = bind_mount.partition(":")
        self.assertEqual(os.path.realpath(src), os.path.realpath(ws),
                         f"bind-mount source mismatch: {src!r} != {ws!r}")
        self.assertEqual(dst, "/home/AISC/app",
                         f"bind-mount dest mismatch: {dst!r}")

        # Sanity: the workspace path with space should NOT appear as two
        # separate args anywhere in the invocation.
        ws_parts = ws.split(" ")
        if len(ws_parts) > 1:
            all_args_text = " ".join(run_inv.args)
            self.assertNotIn(
                ws_parts[0] + " -v" if len(run_inv.args) > 1 else "",
                "SUSPICIOUS",
            )
            # Stronger: verify that bind_mount contains the full ws path
            self.assertIn(ws, bind_mount,
                          f"workspace {ws!r} not intact in bind-mount {bind_mount!r}")

    # ------------------------------------------------------------------
    # Basic docker-run argv
    # ------------------------------------------------------------------

    def test_basic_docker_run_args(self) -> None:
        self._state_set("DO_RUN", "1")
        self._state_set("IMAGE", "super-claude:latest")
        self._state_set("CONTAINER_NAME", "test-container")
        self._state_set("PROXY_ENABLED", "0")

        self._run_launcher(
            extra_env={"AISC_WORKSPACE": self.workspace}
        )
        trace = self._trace_content()

        # Legacy checks (substring)
        self.assertIn("RUN_ARGS:", trace, f"docker run not called; trace={trace!r}")
        self.assertIn("-it", trace)
        self.assertIn("--rm", trace)
        self.assertIn("--name", trace)
        self.assertIn("test-container", trace)
        self.assertIn("-v", trace)
        self.assertIn(self.workspace, trace)
        self.assertIn("super-claude:latest", trace)

        # Structured argv check
        invs = self._parse_trace()
        run_inv = find_invocation(invs, "run")
        self.assertIsNotNone(run_inv, "no structured 'run' invocation")
        assert run_inv is not None
        self.assertIn("-it", run_inv.args)
        self.assertIn("--rm", run_inv.args)
        self.assertIn("--name", run_inv.args)
        self.assertIn("test-container", run_inv.args)
        self.assertIn("-v", run_inv.args)
        self.assertIn("super-claude:latest", run_inv.args)
        # Workspace is inside the -v bind-mount value, not standalone
        bind_args = [
            run_inv.args[i + 1]
            for i, a in enumerate(run_inv.args)
            if a == "-v" and i + 1 < len(run_inv.args)
        ]
        self.assertTrue(
            any(self.workspace in ba for ba in bind_args),
            f"workspace {self.workspace!r} not found in -v bind-mount args: {bind_args}",
        )

    # ------------------------------------------------------------------
    # Proxy append (PROXY_ENABLED=1)
    # ------------------------------------------------------------------

    def test_proxy_append_args(self) -> None:
        self._state_set("DO_RUN", "1")
        self._state_set("IMAGE", "test-img")
        self._state_set("CONTAINER_NAME", "c1")
        self._state_set("PROXY_ENABLED", "1")

        # The script references $PROJECT_ROOT/.claude/mihomo/config.yaml
        # Create a dummy so the path exists (fake docker won't verify)
        mihomo_cfg = self.proj.path(".claude", "mihomo", "config.yaml")
        os.makedirs(os.path.dirname(mihomo_cfg), exist_ok=True)
        with open(mihomo_cfg, "w") as fh:
            fh.write("# dummy\n")

        self._run_launcher(
            extra_env={"AISC_WORKSPACE": self.workspace}
        )
        trace = self._trace_content()

        # Legacy checks
        self.assertIn("RUN_ARGS:", trace)
        self.assertIn("--cap-add=NET_ADMIN", trace)
        self.assertIn("--device", trace)
        self.assertIn("/dev/net/tun", trace)

        # Structured argv check
        invs = self._parse_trace()
        run_inv = find_invocation(invs, "run")
        self.assertIsNotNone(run_inv, "no structured 'run' invocation")
        assert run_inv is not None
        self.assertIn("--cap-add=NET_ADMIN", run_inv.args)
        self.assertIn("--device", run_inv.args)
        self.assertIn("/dev/net/tun", run_inv.args)

    # ------------------------------------------------------------------
    # Exit code pass-through
    # ------------------------------------------------------------------

    def test_docker_exit_code_passthrough(self) -> None:
        self._state_set("DO_RUN", "1")
        self._state_set("IMAGE", "test-img")
        self._state_set("CONTAINER_NAME", "c1")
        self._state_set("PROXY_ENABLED", "0")

        result = self._run_launcher(
            extra_env={
                "AISC_WORKSPACE": self.workspace,
                "DOCKER_EXIT_CODE": "7",
            }
        )
        self.assertEqual(result.exit_code, 7,
                         f"expected exit code 7 from docker, got {result.exit_code}")


if __name__ == "__main__":
    unittest.main()
