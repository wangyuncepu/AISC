"""Contract tests for ``aisc build --events`` (Workbench S0.5).

Per docs/gui-planning/05-cli-gui-contract.md §4.1: stdout is pure aisc.cli/v1
JSONL; fixed event set (build.start/plan/output/complete/failed/cancelled);
real-time build.output (not end-of-build replay); exactly one terminal event;
seq monotonic. Docker is mocked; the cancel-kill path is covered by
tests/integration/docker/test_build_cancellation.py.
"""

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from aisc.adapters.docker_ import FakeDockerExecutor
from aisc.cli.commands.build import BuildPlan, BuildResult, run_build
from aisc.cli.output import JsonlEmitter
from aisc.domain.models import CliError, ImageInspectResult, ImageInspectStatus


def _plan():
    return BuildPlan(tag="test:latest", root=".", dockerfile="Dockerfile")


def _run_with_capture(func):
    """Run *func* with stdout captured; return (events, exc)."""
    buf = io.StringIO()
    exc = None
    try:
        with contextlib.redirect_stdout(buf):
            func()
    except BaseException as e:  # noqa: BLE001 - test captures SystemExit/CliError
        exc = e
    events = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    return events, exc


class _CancelFake(FakeDockerExecutor):
    """Streams one chunk then raises KeyboardInterrupt (cancel mid-build)."""

    def run_streaming_captured(self, docker_argv, on_chunk, *, timeout=None):
        on_chunk("stderr", "Step 1/3\n")
        raise KeyboardInterrupt()


class TestBuildOutputStream(unittest.TestCase):
    def _fake(self, chunks, exit_code=0):
        fake = FakeDockerExecutor()
        fake.set_default_inspect(
            ImageInspectResult(status=ImageInspectStatus.MISSING, image=""))
        fake.set_streaming_chunks(chunks)
        fake.set_streaming_exit(exit_code)
        return fake

    def test_success_emits_start_plan_output(self):
        fake = self._fake([("stderr", "Step 1/3\n"), ("stderr", "Step 2/3\n")], 0)
        em = JsonlEmitter(command="build")
        events, exc = _run_with_capture(
            lambda: run_build(_plan(), emitter=em, executor=fake, streaming=False))
        assert exc is None, exc
        types = [e["type"] for e in events]
        assert types[0] == "build.start"
        assert types[1] == "build.plan"
        assert "build.output" in types
        # Success: run_build emits no terminal (main.py emits build.complete).
        assert not em.terminated

    def test_build_output_carries_stream_and_chunk(self):
        fake = self._fake([("stderr", "Step 1\n"), ("stdout", "done\n")], 0)
        em = JsonlEmitter(command="build")
        events, _ = _run_with_capture(
            lambda: run_build(_plan(), emitter=em, executor=fake, streaming=False))
        outputs = [e for e in events if e["type"] == "build.output"]
        assert outputs[0]["data"] == {"stream": "stderr", "chunk": "Step 1\n"}
        assert outputs[1]["data"] == {"stream": "stdout", "chunk": "done\n"}

    def test_failure_raises_after_output(self):
        fake = self._fake([("stderr", "error detail\n")], 1)
        em = JsonlEmitter(command="build")
        events, exc = _run_with_capture(
            lambda: run_build(_plan(), emitter=em, executor=fake, streaming=False))
        assert isinstance(exc, CliError)
        assert exc.exit_code == 4
        assert exc.error_code == "AISC_ERR_BUILD_FAILED"
        # Output was streamed before the failure (real-time, not replayed).
        assert any(e["type"] == "build.output" for e in events)
        assert not em.terminated  # terminal emitted by main.py on CliError

    def test_cancel_emits_build_cancelled_terminal(self):
        em = JsonlEmitter(command="build")
        events, exc = _run_with_capture(
            lambda: run_build(_plan(), emitter=em, executor=_CancelFake(), streaming=False))
        assert isinstance(exc, SystemExit)
        assert exc.code == 130
        types = [e["type"] for e in events]
        assert types[-1] == "build.cancelled"
        assert events[-1]["data"]["exit_code"] == 130
        assert events[-1]["data"]["image_tag"] == "test:latest"
        assert events[-1]["data"]["reason"] == "cancelled"
        assert em.terminated  # exactly one terminal event

    def test_stdout_pure_jsonl_seq_monotonic(self):
        fake = self._fake([("stderr", "a\n"), ("stderr", "b\n"), ("stderr", "c\n")], 0)
        em = JsonlEmitter(command="build")
        events, _ = _run_with_capture(
            lambda: run_build(_plan(), emitter=em, executor=fake, streaming=False))
        # Every line parsed as JSON (pure JSONL); required fields present.
        for i, e in enumerate(events, 1):
            assert e["protocol"] == "aisc.cli/v1"
            assert e["command"] == "build"
            assert e["run_id"] == events[0]["run_id"]
            assert e["seq"] == i  # monotonic from 1
            assert "type" in e and "ts" in e and "data" in e

    def test_dry_run_emits_start_plan_no_output(self):
        fake = self._fake([], 0)
        em = JsonlEmitter(command="build")
        plan = BuildPlan(tag="test:latest", root=".", dockerfile="Dockerfile", dry_run=True)
        events, _ = _run_with_capture(
            lambda: run_build(plan, emitter=em, executor=fake, streaming=False))
        types = [e["type"] for e in events]
        assert types == ["build.start", "build.plan"]
        assert "build.output" not in types


class TestBuildTerminalViaMain(unittest.TestCase):
    """main() emits the build.complete/failed terminal (run_build mocked)."""

    @patch("aisc.application.resources.locate_aisc_root", return_value=Path("/tmp"))
    @patch("aisc.cli.commands.build.plan_build", return_value=_plan())
    @patch("aisc.cli.commands.build.run_build", return_value=BuildResult())
    def test_main_success_emits_build_complete(self, _run, _plan_p, _root):
        from aisc.cli.main import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                main(["build", "--tag", "test:latest", "--events"])
        assert cm.exception.code == 0
        events = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]
        assert events[-1]["type"] == "build.complete"
        assert events[-1]["data"]["exit_code"] == 0
        assert events[-1]["seq"] == len(events)

    @patch("aisc.application.resources.locate_aisc_root", return_value=Path("/tmp"))
    @patch("aisc.cli.commands.build.plan_build", return_value=_plan())
    @patch("aisc.cli.commands.build.run_build")
    def test_main_failure_emits_build_failed(self, _run, _plan_p, _root):
        from aisc.cli.main import main
        _run.side_effect = CliError(
            message="Docker build failed (exit 1)",
            exit_code=4, error_code="AISC_ERR_BUILD_FAILED",
            data=BuildResult().to_dict(),
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                main(["build", "--tag", "test:latest", "--events"])
        assert cm.exception.code == 4
        events = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]
        assert events[-1]["type"] == "build.failed"
        assert events[-1]["data"]["exit_code"] == 4
        assert events[-1]["data"]["error_code"] == "AISC_ERR_BUILD_FAILED"


if __name__ == "__main__":
    unittest.main()
