"""Lifecycle event log (P1, lifecycle-logging round) — the CLI-side appender.

One JSONL event per line in ``<shared data root>/logs/aisc.log``, appended by
BOTH the Python CLI (``source: "cli"``) and the Workbench's Rust side
(``source: "app"``) — a single timeline a ``run_id`` threads end to end
(the Workbench injects ``AISC_RUN_ID`` into child env; the envelope reuses it).

Red line (allowed-fields-only, mirrors the diagnostic bundle's D6-05/06
philosophy): stdin payloads, subscription URLs, API keys, PTY content, full
environments and absolute workspace paths NEVER enter the log. The schema is
fixed-key by construction — redaction by design, not by filtering.

Failure policy: logging must never break a command — every write is
best-effort; resolver/IO errors are swallowed (the in-memory op path and the
stdout envelope remain authoritative).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

#: Rotation bounds — byte sizes kept identical to the Rust side
#: (workbench/src-tauri/src/logging.rs) so either appender rotates the file.
MAX_BYTES = 2 * 1024 * 1024
KEEP_ROUNATED = 2  # aisc.log + .1 + .2

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "aisc.log"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_file_path(*, env=None) -> Optional[Path]:
    """Resolve the shared log file path; None when the data root can't be
    resolved (fail-open — callers then skip logging)."""
    try:
        from aisc.application.data_root import shared_root

        root = shared_root(env if env is not None else os.environ)
    except Exception:
        return None
    return root / LOG_DIR_NAME / LOG_FILE_NAME


def _rotate(path: Path) -> None:
    """Size-capped rotation: aisc.log -> aisc.log.1 -> aisc.log.2 (oldest
    dropped)."""
    try:
        if not path.exists() or path.stat().st_size < MAX_BYTES:
            return
        for i in range(KEEP_ROUNATED - 1, 0, -1):
            src = path.with_name(f"{path.name}.{i}")
            dst = path.with_name(f"{path.name}.{i + 1}")
            if src.exists():
                src.replace(dst)
        path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        pass  # rotation failure must never block the append


def append_event(
    event: str,
    *,
    level: str = "info",
    source: str = "cli",
    run_id: Optional[str] = None,
    detail: Optional[str] = None,
    env=None,
    **fields: Any,
) -> None:
    """Append one lifecycle event; never raises.

    ``fields`` are extra fixed-schema keys (``command``, ``exit_code``,
    ``duration_ms``, ``error_code`` …) — callers pass only allowlisted,
    secret-free values.
    """
    path = log_file_path(env=env if env is not None else os.environ)
    if path is None:
        return
    record: Dict[str, Any] = {
        "ts": _utc_now(),
        "level": level,
        "source": source,
        "event": event,
    }
    if run_id:
        record["run_id"] = run_id
    if detail:
        record["detail"] = detail
    record.update(fields)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
    except Exception:
        return  # best-effort by contract
