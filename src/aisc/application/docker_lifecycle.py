"""Docker resource lifecycle service (docker-resource-lifecycle A1/B).

Centralized scan / classification / cleanup / rebuild over AISC-owned
containers and workstation images. Every installer calls THIS through the
``aisc maintenance`` CLI — platform scripts never reimplement the filter
rules (02 §1/§2/§3/§4).

Ownership tiers (frozen):
- ``owned``         — labels prove it (io.aisc.managed / org.aisc.managed);
- ``legacy_owned``  — no labels but legacy evidence: registry record, the
                      ``aisc-wb-`` name pattern, or the historical
                      ``super-claude-station-`` name + super-claude repo
                      (containers); the exact default tag
                      ``super-claude:latest`` in an upgrade/uninstall
                      context (images);
- ``unverified``    — merely looks AISC-ish (name/repository similar).
                      Reported, NEVER deleted.

Safety invariants (02 §5): no global prune; never delete by repository
name alone; containers before images; volumes/networks untouched; Docker
unavailable never concludes "not_found"; re-scan before deleting; argv
and logs never carry secrets.

All Docker I/O rides machine formats (ps/images templates, inspect
``{{.Id}}``) — never human-text parsing. Cleanup/rebuild hold the shared
docker-maintenance lock (cross-plan order: maintenance -> workspace ->
registry). The runtime-create critical section (02 §4.1) attaches when
Stage C wires the installers' rebuild flow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from aisc.domain.models import CliError, RuntimeErrorCode, RuntimeExitCode

#: Exact default workstation tag (legacy evidence in upgrade/uninstall).
DEFAULT_IMAGE_TAG = "super-claude:latest"

SCAN_SCHEMA = "aisc.docker-scan/v1"
CLEANUP_SCHEMA = "aisc.docker-cleanup/v1"
REBUILD_SCHEMA = "aisc.docker-rebuild/v1"

#: docker ps template: id, name, image ref, status + the AISC labels.
_PS_FORMAT = (
    "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t"
    '{{.Label "io.aisc.managed"}}\t{{.Label "io.aisc.kind"}}\t'
    '{{.Label "io.aisc.owner"}}'
)
#: docker images template (no .Labels placeholder exists on `docker
#: images` — ownership comes from the server-side label filter below).
_IMAGES_FORMAT = "{{.Repository}}	{{.Tag}}	{{.ID}}"


def _ps_rows(executor: Any) -> List[Dict[str, str]]:
    try:
        result = executor.run_captured(
            ["ps", "-a", "--format", _PS_FORMAT], timeout=15.0
        )
    except Exception:
        return []
    if getattr(result, "exit_code", 1) != 0:
        return []
    rows: List[Dict[str, str]] = []
    for line in (result.stdout or "").splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 4:
            continue
        rows.append({
            "id": parts[0], "name": parts[1], "image": parts[2],
            "status": parts[3],
            "managed": parts[4] if len(parts) > 4 else "",
            "kind": parts[5] if len(parts) > 5 else "",
            "owner": parts[6] if len(parts) > 6 else "",
        })
    return rows


def _image_universe(executor: Any) -> List[Dict[str, Any]]:
    """All images as {repository, tag, id, ref} rows (no labels)."""
    try:
        result = executor.run_captured(
            ["images", "--format", _IMAGES_FORMAT], timeout=15.0
        )
    except Exception:
        return []
    if getattr(result, "exit_code", 1) != 0:
        return []
    rows: List[Dict[str, Any]] = []
    for line in (result.stdout or "").splitlines():
        parts = [p.strip() for p in line.split("	")]
        if len(parts) < 3:
            continue
        rows.append({
            "repository": parts[0], "tag": parts[1], "id": parts[2],
            "ref": f"{parts[0]}:{parts[1]}" if parts[1] != "<none>" else "",
        })
    return rows


def _filtered_image_ids(executor: Any, flag: str) -> List[str]:
    """Image IDs passing a server-side ``docker images --filter``."""
    try:
        result = executor.run_captured(
            ["images", "--filter", flag, "--format", "{{.ID}}"], timeout=15.0
        )
    except Exception:
        return []
    if getattr(result, "exit_code", 1) != 0:
        return []
    return [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]


def _registry_evidence(data_root: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    """All registry records across workspaces (legacy container evidence)."""
    from aisc.adapters.container_registry import list_containers_readonly
    from aisc.application.data_root import shared_root

    root = Path(data_root) if data_root else shared_root()
    evidence: Dict[str, Dict[str, Any]] = {}
    ws_root = root / "workspaces"
    if not ws_root.is_dir():
        return evidence
    for ws_dir in ws_root.iterdir():
        reg = ws_dir / "runtime"
        if not reg.is_dir():
            continue
        try:
            for name, meta in list_containers_readonly(reg).items():
                if isinstance(meta, dict):
                    evidence[name] = meta
        except Exception:
            continue  # one unreadable workspace registry never breaks the scan
    return evidence


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_containers(
    rows: Iterable[Dict[str, str]], registry: Dict[str, Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "owned": [], "legacy_owned": [], "unverified": [],
    }
    for row in rows:
        name = row["name"]
        image_repo = row["image"].split(":")[0]
        if row["managed"] == "true":
            ownership, reason = "owned", "label"
        elif name in registry:
            ownership, reason = "legacy_owned", "registry"
        elif name.startswith("aisc-wb-"):
            ownership, reason = "legacy_owned", "legacy-name"
        elif name.startswith("super-claude-station-") and image_repo == "super-claude":
            ownership, reason = "legacy_owned", "legacy-name"
        elif image_repo == "super-claude" or "aisc" in name.lower():
            ownership, reason = "unverified", "repository-only"
        else:
            continue  # not AISC-adjacent — none of our business
        buckets[ownership].append({
            "id": row["id"], "name": name, "image": row["image"],
            "ownership": ownership,
            "state": "running" if row["status"].startswith("Up") else "stopped",
            "reason": reason,
        })
    return buckets


def classify_images(
    rows: Iterable[Dict[str, Any]],
    *,
    context: str,
    owned_ids: Iterable[str] = (),
    dangling_ids: Iterable[str] = (),
    old_image_ids: Iterable[str] = (),
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """Three-tier image classification + evidence-backed dangling set.

    ``owned_ids`` come from the server-side ``label=org.aisc.managed=true``
    filter (docker images has no label template — the filter is the only
    reliable source); ``dangling_ids`` from ``dangling=true``.
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "owned": [], "legacy_owned": [], "unverified": [],
    }
    dangling: List[Dict[str, Any]] = []
    owned = {i for i in owned_ids if i}
    dangling_set = {i for i in dangling_ids if i}
    old_ids = {i for i in old_image_ids if i}
    for row in rows:
        entry = {
            "id": row["id"], "name": row["ref"] or row["id"],
            "image": row["ref"] or row["id"],
        }
        if row["repository"] == "<none>":
            # Dangling FIRST (no ref to untag — deletable by ID only).
            # Evidence: org.aisc label (survives on the image config) or the
            # upgrade's captured old_image_id (temporary proof).
            if row["id"] in owned or row["id"] in old_ids:
                dangling.append({
                    "id": row["id"], "name": row["id"], "image": row["id"],
                    "ownership": "owned", "state": "dangling",
                    "reason": "label" if row["id"] in owned else "upgrade-old-id",
                })
        elif row["id"] in owned:
            entry.update({"ownership": "owned", "state": "present", "reason": "label"})
            buckets["owned"].append(entry)
        elif row["ref"] == DEFAULT_IMAGE_TAG and context != "first_install":
            entry.update({"ownership": "legacy_owned", "state": "present",
                          "reason": "default-tag"})
            buckets["legacy_owned"].append(entry)
        elif row["repository"] == "super-claude":
            entry.update({"ownership": "unverified", "state": "present",
                          "reason": "repository-only"})
            buckets["unverified"].append(entry)
        else:
            continue  # not AISC-adjacent — none of our business
    return buckets, dangling


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def docker_scan(
    executor: Any,
    *,
    context: str = "upgrade",
    old_image_ids: Iterable[str] = (),
    data_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """One read-only classification pass (02 §2 envelope)."""
    from aisc.application.runtime import _check_docker

    available = _check_docker(executor)
    payload: Dict[str, Any] = {
        "schema_version": SCAN_SCHEMA,
        "docker": {"available": available, "reason": "ok" if available else "unavailable"},
        "containers": {"owned": [], "legacy_owned": [], "unverified": []},
        "images": {"owned": [], "legacy_owned": [], "unverified": []},
        "dangling_owned": [],
        "warnings": [],
    }
    if not available:
        return payload
    registry = _registry_evidence(data_root)
    payload["containers"] = classify_containers(_ps_rows(executor), registry)
    payload["images"], payload["dangling_owned"] = classify_images(
        _image_universe(executor),
        context=context,
        owned_ids=_filtered_image_ids(executor, "label=org.aisc.managed=true"),
        dangling_ids=_filtered_image_ids(executor, "dangling=true"),
        old_image_ids=old_image_ids,
    )
    return payload


def render_scan_text(payload: Dict[str, Any]) -> str:
    """Space-separated one-line-per-resource text for installers and shell
    scripts (NSIS/Inno/POSIX sh cannot parse JSON cheaply; this format is
    stable: ``<kind> <ownership> <id> <name>``).

    Example lines::

        docker available
        container owned cid123 aisc-wb-1
        image owned sha256:abc super-claude:latest
    """
    lines = [
        "docker available" if payload.get("docker", {}).get("available")
        else "docker unavailable"
    ]
    for kind in ("containers", "images"):
        buckets = payload.get(kind, {})
        for ownership in ("owned", "legacy_owned", "unverified"):
            for entry in buckets.get(ownership, []):
                lines.append(
                    f"{kind.rstrip('s')} {ownership} {entry.get('id', '')} "
                    f"{entry.get('name', '')}"
                )
    for entry in payload.get("dangling_owned", []):
        lines.append(f"image dangling-owned {entry.get('id', '')} {entry.get('id', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cleanup (02 §3 order; per-resource failure never aborts the rest)
# ---------------------------------------------------------------------------

def _is_no_such(stderr: str) -> bool:
    low = (stderr or "").lower()
    return "no such" in low or "not found" in low


def docker_cleanup(
    executor: Any,
    *,
    context: str = "upgrade",
    old_image_ids: Iterable[str] = (),
    data_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Upgrade context cleans CONTAINERS ONLY (01 §3 upgrade ordering):
    the tagged image must survive until docker-rebuild succeeds, or a
    failed rebuild would leave the user with no workstation image at all;
    the old image is then removed by ID via rebuild's old-ID handoff."""
    result: Dict[str, Any] = {
        "schema_version": CLEANUP_SCHEMA,
        "action": "cleanup",
        "containers": {"removed": [], "not_found": [], "failed": []},
        "images": {"removed": [], "not_found": [], "failed": []},
        "skipped_unverified": [],
        "warnings": [],
    }

    def _run(argv: List[str], timeout: float = 60.0):
        return executor.run_captured(argv, timeout=timeout)

    # Re-scan + re-verify (invariant 6: never trust a stale list).
    scan = docker_scan(executor, context=context, old_image_ids=old_image_ids,
                       data_root=data_root)
    if not scan["docker"]["available"]:
        raise CliError(
            message="Docker unavailable; cleanup refused (nothing concluded)",
            exit_code=RuntimeExitCode.DOCKER_UNAVAILABLE,
            error_code=RuntimeErrorCode.DOCKER_UNAVAILABLE,
        )
    for entry in scan["containers"]["unverified"] + scan["images"]["unverified"]:
        result["skipped_unverified"].append(entry["name"])

    from aisc.adapters.maintenance_lock import docker_maintenance_lock_at_root
    from aisc.application.data_root import shared_root

    root = Path(data_root) if data_root else shared_root()

    with docker_maintenance_lock_at_root(root):
        # 1-3. containers first (order: stop orderly, then force remove).
        for entry in scan["containers"]["owned"] + scan["containers"]["legacy_owned"]:
            name = entry["name"]
            if entry["state"] == "running":
                stop = _run(["stop", "-t", "10", name], timeout=30.0)
                if stop.exit_code != 0 and not _is_no_such(stop.stderr):
                    result["containers"]["failed"].append(name)
                    continue
            rm = _run(["rm", "-f", name], timeout=60.0)
            if rm.exit_code == 0 or _is_no_such(rm.stderr):
                bucket = "removed" if rm.exit_code == 0 else "not_found"
                result["containers"][bucket].append(name)
            else:
                result["containers"]["failed"].append(name)

        # 4-6. re-scan image references, then untag/delete by evidence.
        # Upgrade: images ride the rebuild handoff — skip entirely.
        removed_ids = set()
        if context == "upgrade":
            scan2 = {"images": {"owned": [], "legacy_owned": [], "unverified": []},
                     "dangling_owned": []}
        else:
            scan2 = docker_scan(executor, context=context, old_image_ids=old_image_ids,
                                data_root=data_root)
        for entry in scan2["images"]["owned"] + scan2["images"]["legacy_owned"]:
            ref = entry["image"]
            if entry["id"] in removed_ids:
                continue
            rm = _run(["rmi", ref], timeout=120.0)
            if rm.exit_code == 0:
                result["images"]["removed"].append(ref)
                removed_ids.add(entry["id"])
            elif _is_no_such(rm.stderr):
                result["images"]["not_found"].append(ref)
            else:
                # referenced by another tag/container or refused — kept.
                result["images"]["failed"].append(ref)
                result["warnings"].append(
                    f"image kept (still referenced or refused): {ref}"
                )
        # 7. dangling with evidence.
        for entry in scan2["dangling_owned"]:
            if entry["id"] in removed_ids:
                continue
            rm = _run(["rmi", entry["id"]], timeout=120.0)
            if rm.exit_code == 0:
                result["images"]["removed"].append(entry["id"])
                removed_ids.add(entry["id"])
            elif not _is_no_such(rm.stderr):
                result["images"]["failed"].append(entry["id"])
        # Volumes/networks: deliberately nothing (invariant 4).
    return result


# ---------------------------------------------------------------------------
# Rebuild (02 §4)
# ---------------------------------------------------------------------------

def docker_rebuild(
    executor: Any,
    *,
    root: str,
    tag: str = DEFAULT_IMAGE_TAG,
    old_image_id: str = "",
    no_cache: bool = True,
    pull: bool = False,
) -> Dict[str, Any]:
    """No-cache rebuild of the workstation image with old-ID handoff.

    Returns the 02 §4 result: old/new image ids, image_changed,
    old_image_action (removed | untagged | kept_referenced | not_found),
    reconcile_hint. Build failure PRESERVES the old image and reports
    failed=true (the caller decides the UX; nothing is deleted on failure).
    """
    from aisc.adapters.maintenance_lock import docker_maintenance_lock_at_root
    from aisc.application.data_root import shared_root
    from aisc.domain.models import BuildPlan

    build_root = Path(root)
    dockerfile = build_root / "Dockerfile"
    if not dockerfile.is_file():
        raise CliError(
            message=f"bundle root has no Dockerfile: {build_root}",
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code=RuntimeErrorCode.WORKSPACE_INVALID,
        )

    plan = BuildPlan(
        tag=tag, root=str(build_root), dockerfile=str(dockerfile),
        no_cache=no_cache, pull=pull,
    )
    with docker_maintenance_lock_at_root(shared_root()):
        build = executor.run_captured(plan.docker_argv, timeout=1800.0)
        new_id = _image_id_by_ref(executor, tag)
        if build.exit_code != 0 or not new_id:
            return {
                "schema_version": REBUILD_SCHEMA,
                "tag": tag,
                "old_image_id": old_image_id,
                "new_image_id": "",
                "image_changed": False,
                "old_image_action": "not_found" if not old_image_id else "kept_referenced",
                "reconcile_hint": "unchanged",
                "failed": True,
                "build_log_tail": _log_tail(build.stdout or ""),
            }
        changed = bool(old_image_id) and old_image_id != new_id
        action = "not_found"
        if old_image_id and changed:
            rm = executor.run_captured(["rmi", old_image_id], timeout=120.0)
            if rm.exit_code == 0:
                action = "removed"
            elif _is_no_such(rm.stderr):
                action = "not_found"
            else:
                action = "kept_referenced"  # still tagged elsewhere / in use
        return {
            "schema_version": REBUILD_SCHEMA,
            "tag": tag,
            "old_image_id": old_image_id,
            "new_image_id": new_id,
            "image_changed": changed,
            "old_image_action": action,
            "reconcile_hint": "image_changed" if changed else "unchanged",
            "failed": False,
            "build_log_tail": _log_tail(build.stdout or ""),
        }


def _image_id_by_ref(executor: Any, ref: str) -> str:
    try:
        result = executor.run_captured(
            ["image", "inspect", ref, "--format", "{{.Id}}"], timeout=15.0
        )
    except Exception:
        return ""
    if getattr(result, "exit_code", 1) != 0:
        return ""
    return (result.stdout or "").strip()


def _log_tail(stdout: str, lines: int = 20) -> str:
    tail = "\n".join(stdout.strip().splitlines()[-lines:])
    # Redaction-by-construction: build output contains no secrets; cap the
    # size so the envelope stays bounded either way.
    return tail[-4000:]
