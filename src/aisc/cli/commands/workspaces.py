"""F2-C addendum (user request 2026-09-09): ``aisc workspaces`` — the
machine-wide management view of CLI-activated workspaces.

Scans every workspace registry under the data root, joins the activation
history for aliases, and cross-references live Docker state. ``--stop``
sweeps the RUNNING CLI-owned activations (Workbench-managed runtimes are
never touched — the GUI owns their lifecycle).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aisc.adapters.container_registry import (
    gc as registry_gc,
    list_containers,
    unregister,
)
from aisc.adapters.docker_ import DockerExecutor, RealDockerExecutor
from aisc.application.data_root import DataRootResolver


def registry_entries(
    executor: Optional[DockerExecutor] = None,
    data_root: Optional[str] = None,
) -> Tuple[List[Any], set]:
    """Every ``(name, meta)`` across all workspace registries (CLI and
    Workbench-owned alike — the caller filters), plus the set of registry
    DEFAULT pointers (the bare ``aisc claude`` target of each workspace —
    r2 #B: stars must mark the pointer, not "same workspace").

    Lazy-GCs each registry so stale records from deleted containers do not
    surface. *data_root* (a dir containing ``workspaces/``) overrides the
    resolved shared root — injection seam for tests and ``aisc ps``.
    """
    from aisc.adapters.container_registry import get_default

    base = Path(data_root) if data_root else DataRootResolver().resolve_shared_root()
    shared = base / "workspaces"
    out: List[Any] = []
    defaults: set = set()
    if not shared.is_dir():
        return out, defaults
    for reg_dir in sorted(shared.glob("*/runtime")):
        if (reg_dir / "containers.json").is_file():
            try:
                registry_gc(reg_dir, executor)
            except Exception:
                pass
            out.extend(list_containers(reg_dir).items())
            try:
                d = get_default(reg_dir)
            except Exception:
                d = ""
            if d:
                defaults.add(d)
    return out, defaults


def docker_states(executor: DockerExecutor) -> Tuple[Dict[str, str], bool]:
    """name → docker status string (one ``docker ps -a`` round trip).

    Second element: whether docker answered at all. When False the map is
    empty and callers must NOT read absence as "container gone".
    """
    proc = executor.run_captured([
        "ps", "-a", "--format", "{{.Names}}\t{{.Status}}",
    ])
    states: Dict[str, str] = {}
    if proc.exit_code != 0:
        return states, False
    for line in (proc.stdout or "").splitlines():
        name, _, status = line.partition("\t")
        if name:
            states[name] = status
    return states, True


def cmd_workspaces(
    executor: Optional[DockerExecutor] = None,
) -> List[Dict[str, Any]]:
    """List every CLI-activated workspace with live Docker state."""
    exec_ = executor or RealDockerExecutor()
    from aisc.cli.commands.runs import list_runs

    alias_by_path = {r.get("path", ""): r.get("alias", "") for r in list_runs()}
    states, _docker_ok = docker_states(exec_)
    entries, defaults = registry_entries(exec_)

    rows: List[Dict[str, Any]] = []
    for cname, meta in entries:
        meta = meta or {}
        if meta.get("owner") == "workbench":
            continue
        name = str(cname)
        if not name:
            continue
        ws = str(meta.get("workspace", ""))
        status = states.get(name, "")
        rows.append({
            "workspace": ws,
            "alias": alias_by_path.get(ws, ""),
            "container": name,
            "image": str(meta.get("image", "")),
            "status": status,
            "running": status.startswith("Up"),
            # r2 #E: which row a bare `aisc claude` actually lands in —
            # the registry default pointer, not "any row of that workspace"
            "active": name in defaults,
        })
    rows.sort(key=lambda r: (not r["running"], r["workspace"]))
    return rows


def cmd_workspaces_stop(
    executor: Optional[DockerExecutor] = None,
) -> Dict[str, Any]:
    """Stop + remove every RUNNING CLI-owned activation (the batch sweep)."""
    exec_ = executor or RealDockerExecutor()
    from aisc.application.data_root import DataRootResolver

    rows = [r for r in cmd_workspaces(executor=exec_) if r["running"]]
    stopped: List[Dict[str, Any]] = []
    shared = DataRootResolver().resolve_shared_root() / "workspaces"
    for row in rows:
        name = row["container"]
        stop = exec_.run_captured(["stop", name], timeout=30.0)
        rm = exec_.run_captured(["rm", "-f", name], timeout=30.0)
        # unregister from its workspace registry (best-effort locate)
        try:
            for reg_dir in shared.glob("*/runtime"):
                if (reg_dir / "containers.json").is_file():
                    unregister(reg_dir, name)
        except Exception:
            pass
        stopped.append({
            "workspace": row["workspace"],
            "alias": row["alias"],
            "container": name,
            "exit_code": rm.exit_code if rm.exit_code != 0 else stop.exit_code,
        })
    return {"stopped": stopped, "running_found": len(rows)}


def print_workspaces_text(rows: List[Dict[str, Any]]) -> None:
    """Human table: alias, status, workspace (ACTIVE workspace starred)."""
    if not rows:
        print("当前没有 CLI 激活的工作区 — aisc run <路径> 开始")
        return
    width = max(len(r.get("alias", "") or "-") for r in rows) + 2
    for r in rows:
        alias = (r.get("alias", "") or "-") + (" *" if r.get("active") else "")
        status = r.get("status", "") or "(容器不存在)"
        print(f"  {alias:<{width}} {status:<22} {r['workspace']}")
    print("批量停止运行中的: aisc workspaces --stop · 单个: aisc stop")