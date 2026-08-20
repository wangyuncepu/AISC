"""``aisc logs`` command layer (lifecycle-logging P2): tail/filter/path views
over the shared JSONL timeline, driven through the real parser + main
dispatch shape."""

import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aisc.applog import append_event
from aisc.cli.commands import logs as logs_cmd
from aisc.cli.main import _build_parser


def _args_show(lines=200, source="all"):
    ns = argparse.Namespace(logs_command="show", lines=lines, source=source)
    return ns


def _seed_events(root: Path):
    with patch.dict(os.environ, {"AISC_DATA_ROOT": str(root)}):
        append_event("app_start", source="app", detail="v1")
        append_event("op", level="error", source="app", run_id="r-1",
                     phase="network", outcome="error", error_code="AISC_ERR_X")
        append_event("cli_exit", source="cli", run_id="r-1",
                     command="network subscription show", exit_code=0,
                     duration_ms=42)
        append_event("container_ready", source="cli", container="aisc-wb-x",
                     runtime_id="rid")


class LogsCommandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._env = patch.dict(os.environ, {"AISC_DATA_ROOT": str(self.root)})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_show_returns_tail_with_filters(self):
        _seed_events(self.root)
        all_events = logs_cmd.cmd_logs_show(_args_show())
        self.assertEqual(all_events["total_matched"], 4)
        self.assertEqual([e["event"] for e in all_events["lines"]],
                         ["app_start", "op", "cli_exit", "container_ready"])

        cli_only = logs_cmd.cmd_logs_show(_args_show(source="cli"))
        self.assertEqual([e["event"] for e in cli_only["lines"]],
                         ["cli_exit", "container_ready"])

        tail2 = logs_cmd.cmd_logs_show(_args_show(lines=2))
        self.assertEqual(tail2["returned"], 2)
        self.assertEqual([e["event"] for e in tail2["lines"]],
                         ["cli_exit", "container_ready"])
        self.assertEqual(tail2["total_matched"], 4)

    def test_show_empty_and_unresolvable(self):
        data = logs_cmd.cmd_logs_show(_args_show())  # no file yet
        self.assertEqual(data["lines"], [])
        self.assertIsNotNone(data["path"])
        with patch.dict(os.environ, {"AISC_DATA_ROOT": "relative/path"}):
            data = logs_cmd.cmd_logs_show(_args_show())
        self.assertIsNone(data["path"])
        self.assertEqual(data["lines"], [])

    def test_show_skips_torn_lines(self):
        log = self.root / "logs" / "aisc.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"ts":"t","source":"cli","event":"ok"}\n'
                       '{"torn json\n', encoding="utf-8")
        data = logs_cmd.cmd_logs_show(_args_show())
        self.assertEqual([e["event"] for e in data["lines"]], ["ok"])

    def test_path(self):
        _seed_events(self.root)
        data = logs_cmd.cmd_logs_path(argparse.Namespace(logs_command="path"))
        self.assertTrue(str(self.root) in (data["path"] or ""))
        self.assertTrue(data["exists"])

    def test_parser_accepts_logs_group(self):
        parser = _build_parser()
        args = parser.parse_args(["logs", "show", "--lines", "10",
                                  "--source", "app"])
        self.assertEqual(args.command, "logs")
        self.assertEqual(args.logs_command, "show")
        self.assertEqual(args.lines, 10)
        self.assertEqual(args.source, "app")
        args = parser.parse_args(["logs", "path"])
        self.assertEqual(args.logs_command, "path")

    def test_source_ui_filter(self):
        # P4.5 writes source:"ui" events — the filter must accept them
        with patch.dict(os.environ, {"AISC_DATA_ROOT": str(self.root)}):
            append_event("ui_action", source="ui", action="doctor_run",
                         outcome="ok")
            data = logs_cmd.cmd_logs_show(_args_show(source="ui"))
        self.assertEqual([e["event"] for e in data["lines"]], ["ui_action"])

    def test_text_rendering(self):
        import io
        from contextlib import redirect_stdout

        _seed_events(self.root)
        data = logs_cmd.cmd_logs_show(_args_show(source="cli"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            logs_cmd.print_logs_text(data, is_show=True)
        out = buf.getvalue()
        self.assertIn("cli_exit", out)
        self.assertIn("run=r-1", out)
        self.assertIn("command=network subscription show", out)
        # path mode prints just the location
        pdata = logs_cmd.cmd_logs_path(argparse.Namespace(logs_command="path"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            logs_cmd.print_logs_text(pdata, is_show=False)
        self.assertIn("aisc.log", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
