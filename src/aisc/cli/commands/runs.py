"""F2-C (fix2-design.md): the CLI-side activation history — ``cli-runs.json``.

Distinct from the Workbench's ``history.json`` (that one carries tab layouts
and GUI semantics); this is the light, CLI-owned record of `aisc run`
activations: ABSOLUTE workspace paths + the config snapshot a resume needs.
Cap-bounded, newest-first.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.domain.models import CliError

#: Keep the history small — it is a picker, not an archive.
HISTORY_CAP = 20

_SCHEMA = {"schema_version": 1}


def _history_path() -> Path:
    """The machine-global history file under <data root>/config/ — resolved
    via the workspace-independent shared-root API (anchoring on cwd would
    false-positive the data-root/workspace overlap gate from $HOME)."""
    from aisc.application.data_root import DataRootResolver

    root = DataRootResolver().resolve_shared_root()
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    return config / "cli-runs.json"


def _load(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("runs"), list):
            return data
    except (OSError, ValueError):
        pass
    return {**_SCHEMA, "runs": []}


def _save(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def record(workspace: str, image: str, network: str, label: str,
           alias: str = "") -> None:
    """Upsert one activation (absolute path key); newest first, capped.

    *alias* is the user's `--name` for the workspace — the resume key when
    set (an empty alias means "resume by index or path only")."""
    path = _history_path()
    data = _load(path)
    ws = str(Path(workspace))
    runs: List[Dict[str, Any]] = [r for r in data["runs"] if r.get("path") != ws]
    runs.insert(0, {
        "path": ws,
        "image": image,
        "network": network,
        "label": label,
        "alias": alias,
        "last_used_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    data["runs"] = runs[:HISTORY_CAP]
    _save(path, data)


def set_active(workspace: str) -> None:
    """Record the machine-global ACTIVE workspace (the default target for
    `aisc claude`/`codex`/`stop`). Written by every activation."""
    path = _history_path().parent / "cli-active.json"
    path.write_text(json.dumps({"workspace": str(Path(workspace))},
                               ensure_ascii=False), encoding="utf-8")


def get_active() -> Optional[str]:
    path = _history_path().parent / "cli-active.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ws = data.get("workspace")
        return str(ws) if isinstance(ws, str) and ws else None
    except (OSError, ValueError):
        return None


def list_runs() -> List[Dict[str, Any]]:
    return list(_load(_history_path())["runs"])


def resolve_resume(spec: str) -> Optional[Dict[str, Any]]:
    """Resolve a resume target: exact ALIAS → 1-based index (newest = 1) →
    exact path. The alias is the strongest key (unique by construction — a
    second registration with the same alias replaces the first)."""
    runs = list_runs()
    spec = spec.strip()
    for r in runs:
        if spec and r.get("alias") == spec:
            return r
    if spec.isdigit():
        idx = int(spec)
        if 1 <= idx <= len(runs):
            return runs[idx - 1]
        return None
    target = str(Path(spec))
    for r in runs:
        if r.get("path") == target:
            return r
    return None


def require_resume(spec: str) -> Dict[str, Any]:
    rec = resolve_resume(spec)
    if rec is None:
        raise CliError(
            message=f"no activation history matches {spec!r} — see `aisc runs`",
            exit_code=2, error_code="AISC_ERR_USAGE",
        )
    return rec
