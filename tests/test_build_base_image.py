# -*- coding: utf-8 -*-
"""T8a (2.1.9 D-9): host-side base-image pre-pull through a mirror chain.

Evidence driving this: nairong's first build crawled docker.1ms.run for
~10 minutes and was abandoned — buildkit's FROM has no mirror fallback.
`_ensure_base_image` walks the chain (selected image first, then
NODE_IMAGE_MIRRORS), tags the first success to the bare local name, and
fails with guidance only when every candidate failed.
"""

import unittest
from pathlib import Path
from unittest import mock

from aisc.cli.commands.build import (
    _base_image_candidates,
    _ensure_base_image,
    _parse_build_env,
    _rewrite_node_image,
)
from aisc.domain.models import BuildPlan, ImageInspectResult, ImageInspectStatus, ProcessResult


def _plan(mirrors=(), node_image="docker.1ms.run/library/node:20-slim"):
    return BuildPlan(
        tag="super-claude:latest",
        root=".",
        dockerfile="container/Dockerfile",
        build_arg_use_cn_mirror="1",
        build_arg_node_image=node_image,
        node_image_mirrors=tuple(mirrors),
    )


class _RecordingExec:
    """Fake DockerExecutor: scripted inspect + pull/tag outcomes."""

    def __init__(self, local_exists=False, pull_results=None, tag_ok=True):
        self._local_exists = local_exists
        self._pull = dict(pull_results or {})
        self._tag_ok = tag_ok
        self.calls = []

    def inspect_image(self, name):
        self.calls.append(("inspect", name))
        status = (
            ImageInspectStatus.EXISTS
            if (self._local_exists and name == "node:20-slim")
            else ImageInspectStatus.MISSING
        )
        return ImageInspectResult(status=status, image=name, message="")

    def run_captured(self, argv, timeout=None):
        self.calls.append(("run", list(argv)))
        if argv[0] == "pull":
            return self._pull.get(argv[1], ProcessResult(stdout="", stderr="fail", exit_code=1))
        if argv[0] == "tag":
            ok = 0 if self._tag_ok else 1
            return ProcessResult(stdout="", stderr="", exit_code=ok)
        return ProcessResult(stdout="", stderr="", exit_code=0)


class BaseImageCandidatesTests(unittest.TestCase):
    def test_selected_first_then_mirrors_deduped(self):
        c = _base_image_candidates(
            _plan(mirrors=("docker.1ms.run/library", "docker.m.daocloud.io/library",
                           "docker.1ms.run/library/"))
        )
        self.assertEqual(
            c,
            [
                "docker.1ms.run/library/node:20-slim",
                "docker.m.daocloud.io/library/node:20-slim",
            ],
        )

    def test_bare_selection_stays_first(self):
        c = _base_image_candidates(
            _plan(node_image="node:20-slim", mirrors=("docker.1ms.run/library",))
        )
        self.assertEqual(c[0], "node:20-slim")
        self.assertIn("docker.1ms.run/library/node:20-slim", c)


class EnsureBaseImageTests(unittest.TestCase):
    def test_local_image_hit_skips_all_pulls(self):
        ex = _RecordingExec(local_exists=True)
        got = _ensure_base_image(ex, _plan(), emitter=None, streaming=False)
        self.assertEqual(got, "node:20-slim")
        self.assertEqual([c for c in ex.calls if c[0] == "run"], [])

    def test_chain_falls_through_to_second_mirror_and_tags(self):
        ex = _RecordingExec(
            pull_results={
                "docker.1ms.run/library/node:20-slim":
                    ProcessResult(stdout="", stderr="timeout", exit_code=1),
                "docker.m.daocloud.io/library/node:20-slim":
                    ProcessResult(stdout="", stderr="", exit_code=0),
            }
        )
        got = _ensure_base_image(
            ex, _plan(mirrors=("docker.m.daocloud.io/library", "dockerproxy.net/library")),
            emitter=None, streaming=False,
        )
        self.assertEqual(got, "node:20-slim")
        runs = [c[1] for c in ex.calls if c[0] == "run"]
        self.assertIn(["tag", "docker.m.daocloud.io/library/node:20-slim", "node:20-slim"], runs)
        # The third mirror was never attempted after the success.
        self.assertEqual(len(runs), 3)  # pull(m1), pull(m2), tag

    def test_tag_failure_returns_pulled_ref(self):
        ex = _RecordingExec(
            pull_results={
                "docker.1ms.run/library/node:20-slim":
                    ProcessResult(stdout="", stderr="", exit_code=0),
            },
            tag_ok=False,
        )
        got = _ensure_base_image(ex, _plan(), emitter=None, streaming=False)
        self.assertEqual(got, "docker.1ms.run/library/node:20-slim")

    def test_all_mirrors_fail_raises_with_guidance(self):
        from aisc.domain.models import CliError

        ex = _RecordingExec()
        with self.assertRaises(CliError) as ctx:
            _ensure_base_image(
                ex, _plan(mirrors=("docker.m.daocloud.io/library",)),
                emitter=None, streaming=False,
            )
        self.assertEqual(ctx.exception.exit_code, 4)
        self.assertIn("registry-mirrors", ctx.exception.message)
        self.assertIn("docker pull", ctx.exception.message)


class RewriteArgvTests(unittest.TestCase):
    def test_rewrites_node_image_only(self):
        argv = ["build", "--build-arg", "USE_CN_MIRROR=1",
                "--build-arg", "NODE_IMAGE=docker.1ms.run/library/node:20-slim",
                "-f", "container/Dockerfile"]
        out = _rewrite_node_image(argv, "node:20-slim")
        self.assertEqual(out[4], "NODE_IMAGE=node:20-slim")
        self.assertEqual(out[2], "USE_CN_MIRROR=1")  # untouched
        # Original list untouched (pure function).
        self.assertIn("NODE_IMAGE=docker.1ms.run/library/node:20-slim", argv)


class ParseBuildEnvMirrorsTests(unittest.TestCase):
    def test_mirrors_parsed_and_normalized(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config").mkdir()
            (Path(tmp) / "config" / "versions.env").write_text(
                "NODE_IMAGE=node:20-slim\n"
                "NODE_IMAGE_MIRRORS=docker.1ms.run/library, docker.m.daocloud.io/library/ ,\n",
                encoding="utf-8",
            )
            env = _parse_build_env(Path(tmp))
        self.assertEqual(
            env.node_image_mirrors,
            ("docker.1ms.run/library", "docker.m.daocloud.io/library"),
        )


if __name__ == "__main__":
    unittest.main()
