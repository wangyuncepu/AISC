"""v2.1.8 T2: SQLite bash history helper — schema, append, retain, edge cases."""

from __future__ import annotations

import importlib.util
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "aisc_bash_history", ROOT / "container" / "lib" / "aisc_bash_history.py"
)
assert _spec and _spec.loader
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)


class BashHistoryHelperTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "bash_history.db")
        self.addCleanup(self._tmp.cleanup)

    def _append(self, cmd: str, exit_code: int = 0, cwd: str = "/root/app",
                ws_hash: str = "abc123", session_id: str = "sess-1") -> None:
        with mock.patch.dict(os.environ, {
            "AISC_HIST_DB": self.db,
            "AISC_HIST_WS_HASH": ws_hash,
            "AISC_HIST_SESSION_ID": session_id,
            "AISC_HIST_CMD": cmd,
            "AISC_HIST_CWD": cwd,
            "AISC_HIST_EXIT": str(exit_code),
        }):
            H.main(["helper", "append"])

    def _rows(self) -> list[sqlite3.Row]:
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM history ORDER BY id"
        ).fetchall()
        conn.close()
        return rows

    def test_append_creates_schema_and_inserts(self):
        self._append("echo hello", exit_code=0)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cmd"], "echo hello")
        self.assertEqual(rows[0]["exit_code"], 0)
        self.assertEqual(rows[0]["cwd"], "/root/app")
        self.assertEqual(rows[0]["workspace_hash"], "abc123")
        self.assertEqual(rows[0]["source"], "terminal")

    def test_append_preserves_nonzero_exit_code(self):
        self._append("false", exit_code=1)
        self.assertEqual(self._rows()[0]["exit_code"], 1)

    def test_append_with_special_characters(self):
        # Quotes, newlines, unicode — parameterized SQL must handle all.
        self._append("echo 'single'\n\"double\" && 日本語", exit_code=0,
                     cwd="/root/app/dir with spaces")
        rows = self._rows()
        self.assertEqual(rows[0]["cmd"], "echo 'single'\n\"double\" && 日本語")
        self.assertEqual(rows[0]["cwd"], "/root/app/dir with spaces")

    def test_wal_mode_enabled(self):
        self._append("echo wal")
        conn = sqlite3.connect(self.db)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        self.assertEqual(mode, "wal")

    def test_retain_trims_to_limit(self):
        for i in range(15):
            self._append(f"cmd-{i}")
        with mock.patch.dict(os.environ, {"AISC_HIST_DB": self.db}):
            with mock.patch.object(H, "RETAIN_COUNT", 10):
                H.main(["helper", "retain"])
        rows = self._rows()
        self.assertEqual(len(rows), 10)
        # Kept the MOST RECENT 10 (cmd-5..cmd-14).
        self.assertEqual(rows[0]["cmd"], "cmd-5")
        self.assertEqual(rows[-1]["cmd"], "cmd-14")

    def test_init_idempotent(self):
        with mock.patch.dict(os.environ, {"AISC_HIST_DB": self.db}):
            H.main(["helper", "init"])
            H.main(["helper", "init"])  # double init: no error
        self._append("echo after-init")
        self.assertEqual(len(self._rows()), 1)

    def test_append_implicit_init(self):
        # append without prior init: schema created in-transaction.
        self._append("echo no-init")
        self.assertEqual(len(self._rows()), 1)

    def test_missing_db_env_fails_open(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code = H.main(["helper", "append"])
        self.assertEqual(code, 0)  # silent no-op

    def _flush(self, spool: str, ws_hash: str = "abc123",
               session_id: str = "sess-1") -> None:
        with mock.patch.dict(os.environ, {
            "AISC_HIST_DB": self.db,
            "AISC_HIST_WS_HASH": ws_hash,
            "AISC_HIST_SESSION_ID": session_id,
        }), mock.patch("sys.stdin", io.StringIO(spool)):
            H.main(["helper", "flush"])

    def test_flush_batch_inserts_escaped_tsv(self):
        # PERF P3a (D-13): one transaction for the whole spool; the shell
        # escapes \\ then \t/\n/\r — round-trip must restore verbatim.
        self._flush("0\t/root/app\techo hello\n"
                    "2\t/root/app\tprintf 'a\\tb\\nc\\\\d'\n"
                    "1\t/tmp/ws\tgit\\ status\n")
        rows = self._rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["cmd"], "echo hello")
        self.assertEqual(rows[0]["exit_code"], 0)
        self.assertEqual(rows[0]["workspace_hash"], "abc123")
        self.assertEqual(rows[1]["cmd"], "printf 'a\tb\nc\\d'")
        self.assertEqual(rows[1]["exit_code"], 2)
        self.assertEqual(rows[2]["cwd"], "/tmp/ws")

    def test_flush_skips_malformed_lines(self):
        self._flush("not-a-record\n7\t/root\techo ok\n\nbogus\tline\n")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cmd"], "echo ok")

    def test_unescape_single_pass_literal_backslash_sequences(self):
        # PERF P3a review finding (2026-09-06): an ORIGINAL command like
        # `printf 'x\ty'` (LITERAL backslash-t) escapes to wire `x\\ty`
        # (backslash doubled). The old sequential-replace unescape fired the
        # tab-escape on the tail and corrupted it to `x\<TAB>y`. Only a
        # single left-to-right pass that consumes escape PAIRS is correct.
        # Raw strings below = exact wire bytes; want uses raw = literal text.
        cases = [
            (r"x\\ty", r"x\ty"),   # literal backslash + t survives verbatim
            (r"x\\ny", r"x\ny"),   # literal backslash + n survives
            (r"a\tb", "a\tb"),     # wire \t -> REAL tab
            (r"a\nb", "a\nb"),     # wire \n -> REAL newline
            (r"a\rb", "a\rb"),     # wire \r -> REAL CR
            (r"a\\b", "a\\b"),     # wire \\ -> one backslash (a\b, 3 chars)
            (r"tab\then\real", "tab" + "\t" + "hen" + "\r" + "eal"),  # \r consumed
        ]
        for wire, want in cases:
            self.assertEqual(H._unescape(wire), want, f"wire={wire!r}")
        # The corruption case end-to-end: a printf command with literal \t.
        self._flush('0\t/w\tprintf \'x\\\\ty\'\n')
        rows = self._rows()
        self.assertEqual(rows[-1]["cmd"], "printf 'x\\ty'")

    def test_flush_empty_spool_is_noop(self):
        with mock.patch.dict(os.environ, {"AISC_HIST_DB": self.db}):
            H.main(["helper", "init"])
        self._flush("")
        self.assertEqual(len(self._rows()), 0)


if __name__ == "__main__":
    unittest.main()
