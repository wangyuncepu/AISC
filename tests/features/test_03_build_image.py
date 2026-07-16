"""Characterization tests for ``scripts/03_build_image.sh`` — image build.

Uses a fake ``docker`` with controlled stdin to avoid real network / Docker
calls.  Freezes structural expectations (root context, Dockerfile path, tag,
build args).  Marked as *characterization* because the script's interactive
prompts make it fragile to test exhaustively — structural invariants are what
we protect.

Where easy, key paths are also verified via structured argv (preserving
token boundaries) rather than relying solely on substring matching.
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


class BuildImageTest(unittest.TestCase):
    """Characterization: structural invariants of 03_build_image.sh."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = CliRunner()

    def setUp(self) -> None:
        self.proj = TempProject(scripts=("_state.sh", "03_build_image.sh"))
        self.trace = self.proj.path("docker_trace.txt")
        self.fake_docker = install_fake_docker(self.proj.tmpdir, self.trace)
        self._base_env = {
            "PATH": f"{self.proj.tmpdir}:{os.environ.get('PATH', '')}",
            "HOME": self.proj.tmpdir,
            "DOCKER_TRACE_FILE": self.trace,
            "DOCKER_IMAGE_EXISTS": "0",
        }
        # Create a minimal Dockerfile so the script passes its existence check
        df_dir = self.proj.path("container")
        os.makedirs(df_dir, exist_ok=True)
        with open(os.path.join(df_dir, "Dockerfile"), "w") as fh:
            fh.write("FROM alpine\n")
        # Prime state with IMAGE (so state_get finds it)
        self._write_state("IMAGE", "super-claude:latest")

    def tearDown(self) -> None:
        self.proj.destroy()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _build_script(self) -> str:
        return os.path.join(self.proj.scripts_dir, "03_build_image.sh")

    def _run(self, input_text: str, extra_env=None, **kw):
        env = dict(self._base_env)
        if extra_env:
            env.update(extra_env)
        return self.runner.run(
            ["bash", self._build_script()],
            cwd=self.proj.tmpdir,
            env=env,
            input_text=input_text,
            timeout=10,
            **kw,
        )

    def _write_state(self, key: str, val: str) -> None:
        for d in (".aisc", ".deploy"):
            sdir = self.proj.path(d)
            os.makedirs(sdir, exist_ok=True)
            sfile = os.path.join(sdir, "state.env")
            with open(sfile, "a") as fh:
                fh.write(f"{key}={val}\n")

    def _trace(self) -> str:
        if os.path.isfile(self.trace):
            with open(self.trace) as fh:
                return fh.read()
        return ""

    def _parse_trace(self):
        return parse_docker_trace(self._trace())

    # ------------------------------------------------------------------
    # Dockerfile missing
    # ------------------------------------------------------------------

    def test_missing_dockerfile_exits_one(self) -> None:
        """Remove the Dockerfile → script should exit 1 before interactive prompts."""
        os.remove(self.proj.path("container", "Dockerfile"))
        # No stdin needed because it should fail before any read
        result = self._run(input_text="")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Dockerfile", result.stdout + result.stderr)

    # ------------------------------------------------------------------
    # Build invariants (fake docker + controlled stdin)
    # ------------------------------------------------------------------

    def test_build_uses_correct_root_context(self) -> None:
        """docker build context should be PROJECT_ROOT (temp dir)."""
        # Answers: cache=Y (enter), mirror=n, run=n
        self._run(input_text="\nn\nn\n")
        trace = self._trace()
        # Legacy substring check
        self.assertIn("BUILD_ARGS:", trace,
                      f"docker build not called; trace={trace!r}")
        self.assertIn(self.proj.tmpdir, trace,
                      f"build context {self.proj.tmpdir} not in trace:\n{trace}")

        # Structured argv: build context is the last positional arg
        invs = self._parse_trace()
        build_inv = find_invocation(invs, "build")
        self.assertIsNotNone(build_inv, "no structured 'build' invocation")
        assert build_inv is not None
        self.assertTrue(len(build_inv.args) >= 1,
                        f"build invocation has no args: {build_inv.args}")
        last_arg = build_inv.args[-1]
        self.assertEqual(
            os.path.realpath(last_arg), os.path.realpath(self.proj.tmpdir),
            f"build context (last arg) mismatch: {last_arg!r} != {self.proj.tmpdir!r}",
        )

    def test_build_uses_correct_dockerfile_path(self) -> None:
        """docker build -f should point to container/Dockerfile."""
        self._run(input_text="\nn\nn\n")
        expected_df = self.proj.path("container", "Dockerfile")
        trace = self._trace()
        # Legacy substring check
        self.assertIn(expected_df, trace,
                      f"Dockerfile path {expected_df} not in trace:\n{trace}")

        # Structured argv: -f should be followed by the Dockerfile path as a
        # single token (preserves argv boundaries).
        invs = self._parse_trace()
        build_inv = find_invocation(invs, "build")
        self.assertIsNotNone(build_inv, "no structured 'build' invocation")
        assert build_inv is not None
        args = build_inv.args
        df_arg: str | None = None
        for i, a in enumerate(args):
            if a == "-f" and i + 1 < len(args):
                df_arg = args[i + 1]
                break
        self.assertIsNotNone(df_arg, f"-f flag not found in args: {args}")
        assert df_arg is not None  # narrow for type checker
        self.assertEqual(
            os.path.realpath(df_arg), os.path.realpath(expected_df),
            f"Dockerfile path mismatch via argv: {df_arg!r} != {expected_df!r}",
        )

    def test_build_uses_correct_tag(self) -> None:
        """-t should match the IMAGE from state."""
        self._run(input_text="\nn\nn\n")
        trace = self._trace()
        self.assertIn("-t", trace)
        self.assertIn("super-claude:latest", trace)

    def test_build_passes_use_cn_mirror_arg(self) -> None:
        """--build-arg USE_CN_MIRROR=... must be present."""
        self._run(input_text="\nn\nn\n")
        trace = self._trace()
        self.assertIn("--build-arg", trace)
        # USE_CN_MIRROR will be 0 (we answered "n" to mirror prompt)
        self.assertIn("USE_CN_MIRROR=0", trace)

    def test_build_passes_node_image_arg(self) -> None:
        """--build-arg NODE_IMAGE=... must be present."""
        self._run(input_text="\nn\nn\n")
        trace = self._trace()
        self.assertIn("NODE_IMAGE=node:20-slim", trace)

    # ------------------------------------------------------------------
    # DO_RUN=0 after build + "don't run" answer
    # ------------------------------------------------------------------

    def test_sets_do_run_zero_on_n_answer(self) -> None:
        """Answer 'n' to '立即运行容器?' → state_set DO_RUN 0."""
        result = self._run(input_text="\nn\nn\n")
        self.assertEqual(result.exit_code, 0)
        # Check state files for DO_RUN=0
        state = self.proj.path(".aisc", "state.env")
        self.assertTrue(os.path.isfile(state), f"state file missing: {state}")
        with open(state) as fh:
            content = fh.read()
        self.assertIn("DO_RUN=0", content,
                      f"DO_RUN=0 not found in state:\n{content}")


if __name__ == "__main__":
    unittest.main()
