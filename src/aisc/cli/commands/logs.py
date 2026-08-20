"""``aisc logs`` command layer (lifecycle-logging P2).

Read-only views over the shared JSONL timeline
(``<data root>/logs/aisc.log``): `show` returns the recent event tail
(filtered by writer), `path` prints the file location. Lines are secret-free
by construction (P1's allowlisted schema) — this layer adds no redaction
because there is nothing sensitive to redact.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from aisc.applog import log_file_path


def cmd_logs_show(args: Any) -> Dict[str, Any]:
    lines = int(getattr(args, "lines", 200) or 200)
    source = getattr(args, "source", "all") or "all"
    path = log_file_path()
    events: List[Dict[str, Any]] = []
    if path is not None and path.exists():
        # Current file only — rotated (.1/.2) stay cold history. The file is
        # size-capped (≤2MB) so a full read is cheap.
        raw = path.read_text(encoding="utf-8", errors="replace")
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue  # a torn line (crash mid-append) never breaks the view
            if not isinstance(rec, dict):
                continue
            if source != "all" and rec.get("source") != source:
                continue
            events.append(rec)
    return {
        "path": str(path) if path is not None else None,
        "source": source,
        "returned": len(events[-lines:]),
        "total_matched": len(events),
        "lines": events[-lines:],
    }


def cmd_logs_path(args: Any) -> Dict[str, Any]:
    path = log_file_path()
    return {
        "path": str(path) if path is not None else None,
        "exists": bool(path is not None and path.exists()),
    }


def print_logs_text(data: Dict[str, Any], is_show: bool) -> None:
    """Human-readable output."""
    if not isinstance(data, dict):
        return
    path = data.get("path")
    if not is_show:
        print(path or "(log location unresolvable — data root error)")
        return
    if path is None:
        print("(log location unresolvable — data root error)")
        return
    lines = data.get("lines") or []
    if not lines:
        print(f"No events recorded yet ({path})")
        return
    for rec in lines:
        ts = str(rec.get("ts", ""))[:19]
        level = str(rec.get("level", "?")).upper()
        src = rec.get("source", "?")
        event = rec.get("event", "?")
        extras = []
        if rec.get("run_id"):
            extras.append(f"run={str(rec['run_id'])[:13]}")
        for key in ("action", "command", "phase", "container", "outcome",
                    "exit_code", "duration_ms", "error_code", "state",
                    "detail"):
            if key in rec and rec[key] is not None:
                extras.append(f"{key}={rec[key]}")
        suffix = " ".join(extras)
        print(f"{ts} {level:<5} {src:<3} {event}  {suffix}".rstrip())
    shown = data.get("returned", len(lines))
    total = data.get("total_matched", len(lines))
    if shown < total:
        print(f"-- showing {shown} of {total} matched events ({path})")
