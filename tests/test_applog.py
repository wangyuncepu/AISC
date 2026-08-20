"""Lifecycle event log (lifecycle-logging P1) — applog append/rotate and the
run_id correlation chain (envelope ↔ log line)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aisc.applog import MAX_BYTES, append_event, log_file_path
from aisc.cli.output import build_envelope


def _read_lines(root: Path):
    path = root / "logs" / "aisc.log"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class ApplogTests(unittest.TestCase):
    def test_append_event_writes_secret_free_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"AISC_DATA_ROOT": tmp}):
                append_event("cli_exit", level="info", source="cli",
                             run_id="uuid-1", command="version", exit_code=0,
                             duration_ms=12)
                lines = _read_lines(Path(tmp))
                self.assertEqual(len(lines), 1)
                rec = lines[0]
                self.assertEqual(rec["event"], "cli_exit")
                self.assertEqual(rec["source"], "cli")
                self.assertEqual(rec["run_id"], "uuid-1")
                self.assertEqual(rec["command"], "version")
                self.assertIn("ts", rec)
                # fixed schema keys only
                self.assertEqual(
                    set(rec), {"ts", "level", "source", "event", "run_id",
                               "command", "exit_code", "duration_ms"})

    def test_rotation_rolls_to_history_and_drops_oldest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"AISC_DATA_ROOT": tmp}):
                with patch("aisc.applog.MAX_BYTES", 1):  # force rotate per write
                    for i in range(4):
                        append_event("e", detail=f"n{i}")
                self.assertTrue((root / "logs" / "aisc.log").exists())
                self.assertTrue((root / "logs" / "aisc.log.1").exists())
                self.assertTrue((root / "logs" / "aisc.log.2").exists())
                # KEEP_ROUNATED=2: the 4th write's rotation dropped the oldest
                details = []
                for name in ("aisc.log.2", "aisc.log.1", "aisc.log"):
                    p = root / "logs" / name
                    if p.exists():
                        details.extend(
                            json.loads(l)["detail"]
                            for l in p.read_text().splitlines() if l)
                self.assertNotIn("n0", details)  # oldest dropped
                self.assertIn("n3", details)

    def test_append_never_raises_on_unresolvable_root(self):
        # fail-closed resolver raises on a relative override; the appender
        # must swallow it (logging never breaks a command)
        with patch.dict(os.environ, {"AISC_DATA_ROOT": "relative/path"}):
            self.assertIsNone(log_file_path())
            append_event("e", detail="x")  # no raise

    def test_envelope_reuses_env_run_id(self):
        env_id = "11111111-2222-4333-8444-555555555555"
        with patch.dict(os.environ, {"AISC_RUN_ID": env_id}):
            envelope = build_envelope("version", 0, "test")
        self.assertEqual(envelope["meta"]["run_id"], env_id)
        # without env: self-generated, still a uuid-shaped value
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AISC_RUN_ID", None)
            envelope = build_envelope("version", 0, "test")
        self.assertNotEqual(envelope["meta"]["run_id"], env_id)
        self.assertTrue(envelope["meta"]["run_id"])

    def test_max_bytes_constant_documented_for_rust_parity(self):
        # the Rust appender mirrors this bound; changing it silently breaks
        # cross-side rotation
        self.assertEqual(MAX_BYTES, 2 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
