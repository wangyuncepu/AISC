"""`aisc artifact` commands — Agent Artifact fact protocol (Stage 3, ART-02).

record/list/inspect/clear-session all return JSON-serializable dicts under the
``aisc.cli/v1`` envelope. The authoritative fact layer writes session-scoped
registries in the host data dir; the workspace is never touched (A-ART04-1).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.domain.artifacts import (
    ArtifactAction,
    ArtifactKind,
    ArtifactOpenWith,
    ArtifactProvenance,
    ArtifactRecord,
    normalize_media_type,
)
from aisc.domain.models import CliError, RuntimeErrorCode


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_workspace(workspace: Optional[str]) -> Path:
    return Path(workspace).resolve() if workspace else Path.cwd().resolve()


def _record_to_dict(rec: ArtifactRecord) -> Dict[str, Any]:
    return rec.to_dict()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_artifact_record(
    *,
    runtime_id: str,
    session_id: str,
    agent: str,
    path: str,
    action: str = ArtifactAction.CREATED,
    kind: str = ArtifactKind.DELIVERABLE,
    media_type: Optional[str] = None,
    label: str = "",
    open_with: str = ArtifactOpenWith.PREVIEW,
    previous_path: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute ``aisc artifact record``."""
    from aisc.application.artifact import record as _record

    ws = _resolve_workspace(workspace)
    try:
        mt = normalize_media_type(media_type)
        rec = ArtifactRecord(
            schema_version=1,
            artifact_id=str(uuid.uuid4()),
            workspace_relative_path=path,
            action=action,
            kind=kind,
            media_type=mt,
            label=label,
            open_with=open_with,
            producer={
                "agent": agent,
                "session_id": session_id,
                "runtime_id": runtime_id,
            },
            state="present",
            provenance=ArtifactProvenance.MANIFEST,
            recorded_at=_iso_now(),
            previous_path=previous_path,
            extra={},
        ).validate()
        saved = _record(ws, rec, session_id=session_id)
    except ValueError as exc:
        raise CliError(
            message=str(exc),
            exit_code=2,
            error_code="AISC_ERR_ARTIFACT_INVALID",
        ) from exc
    return {"artifact": _record_to_dict(saved)}


def cmd_artifact_list(
    *,
    workspace: Optional[str] = None,
    session_id: Optional[str] = None,
    kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute ``aisc artifact list``."""
    from aisc.application.artifact import list_records

    ws = _resolve_workspace(workspace)
    if kind is not None and kind not in ArtifactKind.ALL:
        raise CliError(
            message=f"invalid kind: {kind!r}",
            exit_code=2,
            error_code="AISC_ERR_ARTIFACT_INVALID",
        )
    records = list_records(ws, session_id=session_id, kind=kind)
    return {
        "schema_version": 1,
        "artifacts": [_record_to_dict(r) for r in records],
    }


def cmd_artifact_inspect(
    *,
    artifact_id: str,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute ``aisc artifact inspect``."""
    from aisc.application.artifact import inspect_record

    ws = _resolve_workspace(workspace)
    rec = inspect_record(ws, artifact_id)
    if rec is None:
        raise CliError(
            message=f"artifact not found: {artifact_id}",
            exit_code=1,
            error_code="AISC_ERR_ARTIFACT_NOT_FOUND",
        )
    return {"artifact": _record_to_dict(rec)}


def cmd_artifact_clear_session(
    *,
    runtime_id: str,
    session_id: str,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute ``aisc artifact clear-session``."""
    from aisc.application.artifact import clear_session

    ws = _resolve_workspace(workspace)
    clear_session(ws, session_id)
    return {
        "runtime_id": runtime_id,
        "session_id": session_id,
        "cleared": True,
    }


def print_artifact_text(
    sub: str,
    data: Optional[Dict[str, Any]],
    errors: List[Dict[str, Any]],
) -> None:
    """Human-readable output for `aisc artifact` (text mode)."""
    if errors:
        for err in errors:
            print(f"Error: {err.get('message', '')}", file=__import__("sys").stderr)
        return
    if sub == "record" and isinstance(data, dict) and data.get("artifact"):
        a = data["artifact"]
        print(f"recorded {a['artifact_id']}  {a['workspace_relative_path']}  "
              f"({a['kind']}, {a['action']})")
    elif sub == "list" and isinstance(data, dict):
        arts = data.get("artifacts", [])
        if not arts:
            print("(no artifacts)")
            return
        for a in arts:
            print(f"{a['artifact_id']}  {a['workspace_relative_path']}  "
                  f"({a['kind']}, {a['action']}, {a['state']})")
    elif sub == "inspect" and isinstance(data, dict) and data.get("artifact"):
        a = data["artifact"]
        print(f"artifact: {a['artifact_id']}")
        print(f"  path:     {a['workspace_relative_path']}")
        print(f"  kind:     {a['kind']}")
        print(f"  action:   {a['action']}")
        print(f"  state:    {a['state']}")
        print(f"  media:    {a.get('media_type') or '-'}")
        print(f"  label:    {a.get('label') or '-'}")
        print(f"  producer: {a.get('producer', {}).get('agent', '-')} "
              f"session={a.get('producer', {}).get('session_id', '-')}")
    elif sub == "clear-session":
        print("cleared")
