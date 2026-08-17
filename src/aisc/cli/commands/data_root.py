"""``aisc data-root`` commands (Stage 7, 7d) — doctor / migrate / rollback.

Non-interactive by contract (03-ux-flow): conflicts and unconsented unknowns
exit non-zero via CliError instead of guessing. All output is
JSON-serializable for the aisc.cli/v1 envelope; text mode prints a short
summary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from aisc.adapters.data_root_store import DataRootStore
from aisc.application.data_migration import MigrationExecutor
from aisc.application.data_root import DataRootResolver


def _executor(workspace: Optional[str]) -> MigrationExecutor:
    ws = Path(workspace).resolve() if workspace else Path.cwd()
    resolved = DataRootResolver().resolve(ws)
    return MigrationExecutor(ws, resolved, store=DataRootStore(resolved))


def cmd_data_root_doctor(workspace: Optional[str] = None) -> Dict[str, Any]:
    return _executor(workspace).doctor()


def cmd_data_root_migrate(
    workspace: Optional[str] = None,
    *,
    dry_run: bool = False,
    quarantine_unknown: bool = False,
) -> Dict[str, Any]:
    executor = _executor(workspace)
    if dry_run:
        return executor.dry_run()
    return executor.migrate(quarantine_unknown=quarantine_unknown).to_dict()


def cmd_data_root_rollback(
    workspace: Optional[str] = None,
    manifest: Optional[str] = None,
) -> Dict[str, Any]:
    return _executor(workspace).rollback(
        manifest_path=Path(manifest) if manifest else None
    ).to_dict()


def print_data_root_text(data: Any) -> None:
    """Minimal human-readable output for text mode."""
    if not isinstance(data, dict):
        return
    if "legacy" in data and "data_root" in data:
        root = data["data_root"]
        print(f"data root : {root.get('root', '')} ({root.get('origin')})")
        print(f"writable  : {root.get('writable')}")
        print(f"ws hash   : {root.get('workspace_hash', '')}")
        legacy = data.get("legacy") or {}
        counts = legacy.get("counts") or {}
        print("legacy    : "
              f"owned={counts.get('owned', 0)} transient={counts.get('transient', 0)} "
              f"unknown={counts.get('unknown', 0)} conflict={counts.get('conflict', 0)}")
        pending = data.get("pending_manifest")
        if pending:
            print(f"manifest  : {pending}")
        return
    if "plan" in data:
        print(f"dry-run   : {data['plan'].get('copy_count', 0)} file(s) to copy, "
              f"~{data['plan'].get('owned_bytes', 0)} bytes")
        for conflict in data.get("conflicts", []):
            print(f"CONFLICT  : {conflict}")
        for unknown in data.get("unknowns", []):
            print(f"UNKNOWN   : {unknown}")
        return
    outcome = data.get("outcome")
    if outcome == "rolled_back":
        print(f"rolled back: removed={data.get('removed', 0)} "
              f"kept={data.get('kept', 0)} restored={data.get('restored', 0)}")
    else:
        print(f"migration {outcome}: copied={data.get('copied', 0)} "
              f"skipped={data.get('skipped', 0)} quarantined={data.get('quarantined', 0)}")
    if data.get("markers"):
        print(f"markers   : {', '.join(data['markers'])}")
