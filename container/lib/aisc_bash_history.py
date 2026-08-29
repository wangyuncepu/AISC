#!/usr/bin/env python3
"""SQLite bash history helper — parameterized, no shell SQL injection.

v2.1.8 T2: invoked by /usr/local/share/aisc/bashrc via PROMPT_COMMAND.
Subcommands:
  init    — idempotent schema creation (CREATE IF NOT EXISTS + WAL + indexes)
  append  — insert one command record (env-driven; implicit init)
  retain  — keep only the most recent N rows (entrypoint calls once at boot)

All I/O via environment variables (AISC_HIST_DB etc.) — the bashrc
function passes them inline so no command-line argument can leak into SQL.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone

RETAIN_COUNT = 10_000

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS history ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " workspace_hash TEXT NOT NULL,"
    " terminal_session_id TEXT,"
    " cmd TEXT NOT NULL,"
    " cwd TEXT,"
    " started_at TEXT,"
    " exit_code INTEGER,"
    " source TEXT NOT NULL DEFAULT 'terminal'"
    ");"
    "CREATE INDEX IF NOT EXISTS idx_history_ts ON history(started_at DESC);"
    "CREATE INDEX IF NOT EXISTS idx_history_cmd ON history(cmd);"
)


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def cmd_init(db_path: str) -> int:
    conn = _connect(db_path)
    conn.close()
    return 0


def cmd_append(db_path: str) -> int:
    env = os.environ
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO history"
            " (workspace_hash, terminal_session_id, cmd, cwd, started_at, exit_code, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                env.get("AISC_HIST_WS_HASH", ""),
                env.get("AISC_HIST_SESSION_ID", ""),
                env.get("AISC_HIST_CMD", ""),
                env.get("AISC_HIST_CWD", ""),
                datetime.now(timezone.utc).isoformat(),
                int(env.get("AISC_HIST_EXIT", "0") or "0"),
                "terminal",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return 0


def cmd_retain(db_path: str) -> int:
    conn = _connect(db_path)
    try:
        conn.execute(
            "DELETE FROM history WHERE id NOT IN"
            " (SELECT id FROM history ORDER BY id DESC LIMIT ?)",
            (RETAIN_COUNT,),
        )
        conn.commit()
    finally:
        conn.close()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: aisc_bash_history.py init|append|retain", file=sys.stderr)
        return 2
    db_path = os.environ.get("AISC_HIST_DB", "")
    if not db_path:
        return 0  # fail-open: no DB path configured (temporary workspace)
    op = argv[1]
    if op == "init":
        return cmd_init(db_path)
    if op == "append":
        return cmd_append(db_path)
    if op == "retain":
        return cmd_retain(db_path)
    print(f"unknown op: {op}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
