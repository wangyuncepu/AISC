"""Workspace reconcile (runtime-lifecycle-ux Stage 1, 02 §3).

One idempotent operation answering "may this Workbench instance start a
runtime in this workspace, and what shall it do with leftovers?" — the
frontend never assembles list/inspect/remove sequences itself (02 §3:
"前端不得先 list、过一段时间再无锁 remove").

Classification (frozen):

- ``clean``                  — nothing to do; start.
- ``active_same_instance``   — this instance already holds the lease
                               (frontend focuses the existing workspace).
- ``stale_ephemeral``        — expired/legacy Workbench runtime recycled
                               (stop -> inspect -> remove -> prune);
                               safe to start.
- ``active_other_instance``  — a fresh lease belongs to another instance;
                               BLOCK (minimal block page in the UI).
- ``unknown_owner``          — registry/Docker evidence cannot prove AISC
                               ownership (owner missing / not workbench /
                               unverifiable); BLOCK, diagnostic path —
                               never auto-delete (safety invariant 1).
- ``stale_registry``         — registry entries whose containers are gone;
                               registry pruned (idempotently); start.
- ``docker_unavailable``     — no destructive action, no "not_found"
                               conclusions (safety invariant 3); BLOCK.

Lock order (frozen, cross-plan): docker-maintenance lock -> workspace
lock -> registry transaction. Reconcile is the reference implementer of
that order. Expiry of a lease NEVER authorizes deletion by itself — the
registry/Docker-label reconciliation below IS the required re-verification
(invariant 2; covers sleep-resume where the clock jumped past the TTL).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.adapters.container_registry import (
    list_containers_readonly,
    unregister,
)
from aisc.adapters.data_root_store import DataRootStore
from aisc.adapters.maintenance_lock import docker_maintenance_lock
from aisc.adapters.workspace_lease_store import WorkspaceLeaseStore
from aisc.application.data_root import DataRootResolver
from aisc.applog import append_event
from aisc.domain.models import RuntimeErrorCode
from aisc.domain.workspace_lease import WorkspaceLease

#: Envelope schema stamp (02 §3 JSON).
RECONCILE_SCHEMA = "aisc.runtime-reconcile/v1"

#: Registry metadata: lifecycle values reconcile recycles vs keeps.
LIFECYCLE_EPHEMERAL = "ephemeral"

#: retention values that keep the container alive across close (advanced).
RETENTION_KEEP = ("keep_stopped", "keep_running")


def _workspace_scoped_containers(ws_key: str, executor: Any) -> List[Dict[str, str]]:
    """Docker containers labeled ``io.aisc.workspace-key=<ws_key>``.

    Machine tab format via ``docker ps`` (labels ride the AISC ownership
    contract; the classification never trusts names alone for new
    resources). Empty on any Docker hiccup — callers treat that as
    "docker-side evidence unavailable", never as "no containers".
    """
    try:
        result = executor.run_captured(
            [
                "ps", "-a",
                "--filter", f"label=io.aisc.workspace-key={ws_key}",
                "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}\t"
                            "{{.Label \"io.aisc.runtime-id\"}}\t"
                            "{{.Label \"io.aisc.owner\"}}",
            ],
            timeout=10.0,
        )
    except Exception:
        return []
    if getattr(result, "exit_code", 1) != 0:
        return []
    rows: List[Dict[str, str]] = []
    for line in (result.stdout or "").splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) >= 3:
            rows.append({
                "container_id": parts[0],
                "container_name": parts[1],
                "status": parts[2],
                "runtime_id": parts[3] if len(parts) > 3 else "",
                "owner": parts[4] if len(parts) > 4 else "",
            })
    return rows


def _status_to_state(status: str) -> str:
    if not status:
        return "unknown"
    return "running" if status.startswith("Up") else "stopped"


def reconcile_workspace(
    workspace: str,
    instance_id: str,
    executor: Any,
    registry_root: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run one reconcile pass and return the frozen JSON envelope.

    ``env`` overrides the data-root environment (hermetic tests). The
    function reports; it never raises for classification outcomes — only
    for programming errors. Destructive actions touch ONLY resources
    proven owned (owner=workbench, ephemeral-or-legacy) after lease and
    Docker-side verification, under maintenance -> workspace locks.
    """
    from aisc.adapters.container_registry import workspace_lock
    from aisc.application.runtime import (
        _check_docker,
        _resolve_registry_root,
        workspace_key_for,
    )

    canonical = str(Path(workspace).resolve())
    ws_key = workspace_key_for(canonical)
    reg_root = _resolve_registry_root(canonical, registry_root)

    resolved = DataRootResolver(env=env).resolve(Path(canonical))
    store = DataRootStore(resolved)
    store.prepare()
    leases = WorkspaceLeaseStore(store, ws_key)

    def envelope(
        classification: str,
        *,
        runtime_id: Optional[str],
        can_proceed: bool,
        cleanup: Dict[str, Any],
        error_code: Optional[str] = None,
        technical_detail: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema_version": RECONCILE_SCHEMA,
            "workspace_key": ws_key,
            "classification": classification,
            "runtime_id": runtime_id,
            "can_proceed": can_proceed,
            "cleanup": cleanup,
            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error_code": error_code,
            "technical_detail": technical_detail,
        }
        action = {"clean": "skip", "stale_ephemeral": "remove", "stale_registry": "remove"}.get(
            classification, "block"
        )
        result = "ok" if error_code is None else "error"
        append_event(
            "runtime_reconcile", source="cli",
            workspace_hash=ws_key,
            classification=classification,
            action=action, result=result,
        )
        return payload

    # --- 1. Fresh lease short-circuits everything -------------------------
    lease: Optional[WorkspaceLease] = leases.inspect()
    if lease is not None and not lease.is_expired():
        if lease.held_by(instance_id):
            return envelope(
                "active_same_instance", runtime_id=None, can_proceed=False,
                cleanup=_no_cleanup(),
            )
        return envelope(
            "active_other_instance", runtime_id=None, can_proceed=False,
            cleanup=_no_cleanup(),
            error_code=RuntimeErrorCode.ACTIVE_WORKSPACE_LEASE,
            technical_detail="workspace leased by another Workbench instance",
        )

    # --- 2. Docker unavailable: no destructive action, no conclusions ------
    if not _check_docker(executor):
        return envelope(
            "docker_unavailable", runtime_id=None, can_proceed=False,
            cleanup=_no_cleanup(),
            error_code=RuntimeErrorCode.DOCKER_UNAVAILABLE,
            technical_detail="docker daemon/CLI unavailable; nothing removed",
        )

    # --- 3. Recycle stale owned runtimes under maintenance -> workspace ----
    cleanup = _no_cleanup()
    saw_unknown_owner = False
    saw_recycled = False
    saw_registry_prune = False
    last_runtime_id: Optional[str] = None
    failure: Optional[str] = None

    with docker_maintenance_lock(store):
        with workspace_lock(reg_root, ws_key, timeout=30.0):
            try:
                registry_entries = list_containers_readonly(reg_root)
            except Exception as exc:  # corrupted registry: fail closed
                return envelope(
                    "unknown_owner", runtime_id=None, can_proceed=False,
                    cleanup=cleanup,
                    error_code=RuntimeErrorCode.RUNTIME_OWNER_UNKNOWN,
                    technical_detail=f"registry unreadable: {exc}",
                )

            docker_rows = _workspace_scoped_containers(ws_key, executor)
            docker_by_name = {r["container_name"]: r for r in docker_rows}

            targets: List[Dict[str, Any]] = []
            for name, meta in registry_entries.items():
                if not isinstance(meta, dict):
                    continue
                if meta.get("workspace_key") != ws_key and meta.get("workspace") != canonical:
                    continue
                targets.append({"name": name, "meta": meta, "source": "registry"})
            for name, row in docker_by_name.items():
                if name not in registry_entries:
                    targets.append({"name": name, "meta": {}, "source": "docker_only"})

            for target in targets:
                name = target["name"]
                meta = target["meta"]
                owner = str(meta.get("owner") or row_owner(docker_by_name.get(name)))
                lifecycle = str(meta.get("lifecycle") or "")
                retention = str(meta.get("retention") or "")
                runtime_id = str(meta.get("runtime_id") or "")

                # Owned = workbench-created and ephemeral (or legacy: no
                # lifecycle field yet — product table row 3 recycles it).
                # Anything else: non-ephemeral/keep policies are silently
                # KEPT (advanced retention); unprovable ownership BLOCKS
                # (unknown_owner, invariant 1 — never auto-deleted).
                is_owned = owner == "workbench" and lifecycle in ("", LIFECYCLE_EPHEMERAL)
                if not is_owned:
                    saw_unknown_owner = True
                    continue
                if retention in RETENTION_KEEP:
                    continue

                state = docker_state(name, executor, docker_by_name)
                cleanup["attempted"] = True
                last_runtime_id = runtime_id or None
                if state == "not_found":
                    # Stale registry record: prune only, idempotent.
                    unregister(reg_root, name)
                    cleanup["registry_pruned"] = True
                    saw_registry_prune = True
                    continue
                if state == "running":
                    stop = executor.stop_container(name, timeout=10)
                    if stop.exit_code != 0:
                        failure = f"stop failed for {name}"
                        continue
                    cleanup["stopped"] = True
                rm = executor.remove_container(name, force=True)
                if rm.exit_code != 0:
                    failure = f"remove failed for {name}"
                    continue
                cleanup["removed"] = True
                saw_recycled = True
                if name in registry_entries:
                    unregister(reg_root, name)
                    cleanup["registry_pruned"] = True

            # Idempotency guard: a second pass must see nothing left to do
            # (verified by tests re-running reconcile end-to-end).
    if saw_unknown_owner:
        return envelope(
            "unknown_owner", runtime_id=last_runtime_id, can_proceed=False,
            cleanup=cleanup,
            error_code=RuntimeErrorCode.RUNTIME_OWNER_UNKNOWN,
            technical_detail="unowned/unverifiable runtime present; nothing deleted for it",
        )
    if failure is not None:
        # Cleanup attempted but incomplete: the leftovers are still there —
        # report the stale state honestly with can_proceed=False rather
        # than pretending any classification resolved cleanly.
        return envelope(
            "stale_ephemeral" if cleanup["attempted"] else "clean",
            runtime_id=last_runtime_id, can_proceed=False,
            cleanup=cleanup,
            error_code=RuntimeErrorCode.RUNTIME_RECONCILE_FAILED,
            technical_detail=failure,
        )
    if saw_recycled:
        classification = "stale_ephemeral"
    elif saw_registry_prune:
        classification = "stale_registry"
    else:
        classification = "clean"
    return envelope(
        classification, runtime_id=last_runtime_id, can_proceed=True,
        cleanup=cleanup,
    )


def row_owner(row: Optional[Dict[str, str]]) -> str:
    return (row or {}).get("owner", "")


def docker_state(name: str, executor: Any, docker_by_name: Dict[str, Dict[str, str]]) -> str:
    """Docker-side state for *name*: prefer the label query row; fall back
    to a direct inspect (also distinguishes not_found)."""
    if name in docker_by_name:
        return _status_to_state(docker_by_name[name]["status"])
    from aisc.application.runtime import _get_container_state

    return _get_container_state(name, executor) or "unknown"


def _no_cleanup() -> Dict[str, Any]:
    return {"attempted": False, "stopped": False, "removed": False, "registry_pruned": False}
