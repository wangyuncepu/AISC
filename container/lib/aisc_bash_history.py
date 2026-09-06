#!/usr/bin/env python3
"""SQLite bash history helper — parameterized, no shell SQL injection.

v2.1.8 T2: invoked by /usr/local/share/aisc/bashrc via PROMPT_COMMAND.
Subcommands:
  init    — idempotent schema creation (CREATE IF NOT EXISTS + WAL + indexes)
  append  — insert one command record (env-driven; implicit init)
  flush   — PERF P3a (D-13): batch-insert a TSV spool from stdin in ONE
            transaction (the shell buffers records and flushes at 20 lines /
            60s / exit — one python3 spawn per ~20 commands instead of per
            command; `append` kept for compatibility). This batching trades
            an accepted loss window for spawn reduction: SIGKILL, container
            force-stop, or host crash may lose records still buffered in the
            shell. Normal exit and SIGTERM flush via the shell EXIT trap.
  retain  — keep only the most recent N rows (entrypoint calls once at boot)

All I/O via environment variables (AISC_HIST_DB etc.) — the bashrc
function passes them inline so no command-line argument can leak into SQL.
The flush TSV rides stdin: `exit_code<TAB>cwd<TAB>cmd` per line, with
backslash/tab/newline/CR escaped by the shell (pure parameter expansion).
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


def _unescape(s: str) -> str:
    """Reverse the shell-side escape in ONE left-to-right pass.

    Sequential `replace` calls are WRONG here: a wire `x\\\\t` (literal
    backslash + escaped-tab… no — a LITERAL backslash-then-t in the original
    command escapes to `x\\\\t` on the wire, and a tab-escape replace would
    fire on the tail `\\\\t` first, corrupting it to backslash+TAB). Only a
    single scan that consumes escape PAIRS is correct."""
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "t":
                out.append("\t")
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            # Unknown escape: keep the backslash literally (writer bug or
            # foreign producer — never corrupt, never crash).
        out.append(c)
        i += 1
    return "".join(out)


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


def cmd_flush(db_path: str) -> int:
    """Batch-insert the stdin TSV spool in one transaction.

    started_at = flush time (batch granularity — history UX doesn't need
    per-command timestamps; documented trade). Malformed lines are skipped,
    never fatal to the batch (fail-open, same contract as `append`)."""
    env = os.environ
    data = sys.stdin.read()
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for line in data.split("\n"):
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            exit_code = int(parts[0])
        except ValueError:
            continue
        rows.append((
            env.get("AISC_HIST_WS_HASH", ""),
            env.get("AISC_HIST_SESSION_ID", ""),
            _unescape(parts[2]),   # cmd
            _unescape(parts[1]),   # cwd
            now,
            exit_code,
            "terminal",
        ))
    if not rows:
        return 0
    conn = _connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO history"
            " (workspace_hash, terminal_session_id, cmd, cwd, started_at, exit_code, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
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
        print("usage: aisc_bash_history.py init|append|flush|retain", file=sys.stderr)
        return 2
    db_path = os.environ.get("AISC_HIST_DB", "")
    if not db_path:
        return 0  # fail-open: no DB path configured (temporary workspace)
    op = argv[1]
    if op == "init":
        return cmd_init(db_path)
    if op == "append":
        return cmd_append(db_path)
    if op == "flush":
        return cmd_flush(db_path)
    if op == "retain":
        return cmd_retain(db_path)
    print(f"unknown op: {op}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
