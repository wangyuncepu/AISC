"""Provider token usage aggregation — application layer (IDEA-2 2c).

Bridges the Workbench to the in-container cc-switch usage data (proxy
request logs + session-log imports, both landing in ``proxy_request_logs``
per 2a probe). Per workspace: running container → live ``aisc-cc-provider
usage`` exec (the host never opens the WAL database directly — Windows
bind-mount lock semantics are unreliable); stopped container → cached
snapshot under ``<data-root>/cache/usage/``; nothing → ``source: none``.
The subscription section reuses ``network_subscription.show_subscription``
host-side. Time windows are computed host-side (local timezone) and passed
as an epoch cutoff, so "today" means the user's today.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.domain.models import CliError

PROTOCOL = "aisc.cc-switch-provider/v1"
_ADAPTER_PATH = "/usr/local/bin/aisc-cc-provider"
USAGE_TIMEOUT_S = 60.0
INSPECT_TIMEOUT_S = 10.0
RANGE_CHOICES = ("today", "7d", "30d")
CACHE_SCHEMA = "aisc.usage-cache/v1"

# The scope wrapper mirrors aisc.application.cc_switch_provider (kept in sync
# deliberately — importing that module would couple two unrelated data planes;
# the wrapper is the stable contract with the container's PID-1 environ).
_SCOPE_WRAPPER = "\n".join([
    'if [ ! -r "$1" ]; then',
    '  echo \'Error: Cannot read scope environment from PID 1\' >&2',
    '  exit 101',
    'fi',
    'unset CLAUDE_CONFIG_DIR CC_SWITCH_CONFIG_DIR CODEX_CONFIG_DIR CODEX_HOME',
    "while IFS= read -r -d '' entry; do",
    '  case "$entry" in',
    '    CLAUDE_CONFIG_DIR=*) CLAUDE_CONFIG_DIR=${entry#*=} ;;',
    '    CC_SWITCH_CONFIG_DIR=*) CC_SWITCH_CONFIG_DIR=${entry#*=} ;;',
    '    CODEX_CONFIG_DIR=*)     CODEX_CONFIG_DIR=${entry#*=}     ;;',
    '    CODEX_HOME=*)           CODEX_HOME=${entry#*=}           ;;',
    '  esac',
    'done < "$1"',
    'shift',
    'shift',
    'if [ -z "${CLAUDE_CONFIG_DIR:-}" ] || [ -z "${CC_SWITCH_CONFIG_DIR:-}" ]; then',
    "  echo 'Error: Cannot read scope environment from PID 1' >&2",
    '  exit 101',
    'fi',
    'export CLAUDE_CONFIG_DIR CC_SWITCH_CONFIG_DIR CODEX_CONFIG_DIR CODEX_HOME',
    'exec "$@"',
    '',
])


def _validate_range(range_key: str) -> str:
    if range_key not in RANGE_CHOICES:
        raise CliError(
            message=f"invalid range (must be {'|'.join(RANGE_CHOICES)}): {range_key}",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        )
    return range_key


def since_epoch_for(range_key: str, *, now: Optional[datetime] = None) -> float:
    """Local-timezone cutoff: today = local midnight; Nd = now - N*24h."""
    _validate_range(range_key)
    now = now or datetime.now()
    if range_key == "today":
        midnight = datetime.combine(now.date(), dt_time.min)
        return midnight.timestamp()
    days = int(range_key.rstrip("d"))
    return now.timestamp() - days * 86400.0


def _container_running(executor: Any, container: str) -> bool:
    result = executor.run_captured(
        ["inspect", "--format", "{{.State.Running}}", container],
        timeout=INSPECT_TIMEOUT_S,
    )
    return result.exit_code == 0 and (result.stdout or "").strip() == "true"


def _exec_usage_adapter(executor: Any, container: str, since: float) -> Optional[Dict[str, Any]]:
    """Run the in-container usage op; ``None`` when the call yields no data
    (container gone, adapter missing, envelope unusable)."""
    argv = [
        "exec", "-i", container,
        "bash", "-c",
        _SCOPE_WRAPPER,
        "aisc-scope", "/proc/1/environ", "--",
        _ADAPTER_PATH, "usage", "--since", f"{since:.0f}",
    ]
    result = executor.run_captured(argv, timeout=USAGE_TIMEOUT_S)
    stdout = (result.stdout or "").strip()
    if result.exit_code != 0 and not stdout:
        return None
    try:
        envelope = json.loads(stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return None
    if not isinstance(envelope, dict) or envelope.get("schema") != PROTOCOL \
            or not envelope.get("ok"):
        return None
    usage = envelope.get("usage")
    return usage if isinstance(usage, dict) else None


def _cache_path(ws_dir_name: str) -> Path:
    from aisc.application.data_root import shared_root

    return shared_root() / "cache" / "usage" / f"{ws_dir_name}.json"


def _write_cache(ws_dir_name: str, range_key: str, usage: Dict[str, Any]) -> None:
    path = _cache_path(ws_dir_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": CACHE_SCHEMA,
        "range": range_key,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "usage": usage,
    }
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_cache(ws_dir_name: str, range_key: str) -> Optional[Dict[str, Any]]:
    """Reuse a cached snapshot only when it answers the same question:
    same range key, and for ``today`` fetched on the same local date."""
    try:
        payload = json.loads(_cache_path(ws_dir_name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != CACHE_SCHEMA \
            or payload.get("range") != range_key:
        return None
    if range_key == "today":
        fetched = str(payload.get("fetched_at") or "")[:10]
        if fetched != datetime.now().astimezone().isoformat()[:10]:
            return None
    usage = payload.get("usage")
    return usage if isinstance(usage, dict) else None


def _normalize_providers(usage: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = usage.get("providers")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append({
            "app": str(row.get("app") or ""),
            "provider_id": str(row.get("provider_id") or ""),
            "provider_name": str(row.get("provider_name") or row.get("provider_id") or ""),
            "requests": int(row.get("requests") or 0),
            "success": int(row.get("success") or 0),
            "failed": int(row.get("failed") or 0),
            "tokens_total": int(row.get("tokens_total") or 0),
            "cost_estimate": float(row.get("cost_estimate") or 0.0),
            "currency": str(row.get("currency") or "USD"),
        })
    return out


def _normalize_models(usage: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = usage.get("models")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append({
            "app": str(row.get("app") or ""),
            "model": str(row.get("model") or ""),
            "requests": int(row.get("requests") or 0),
            "tokens_in": int(row.get("tokens_in") or 0),
            "tokens_out": int(row.get("tokens_out") or 0),
            "cost_estimate": float(row.get("cost_estimate") or 0.0),
        })
    return out


def _registry_entries(ws_dir: Path) -> Dict[str, Dict[str, Any]]:
    from aisc.adapters.container_registry import list_containers_readonly

    try:
        entries = list_containers_readonly(ws_dir / "runtime")
    except Exception:
        return {}
    return entries if isinstance(entries, dict) else {}


def usage_overview(
    range_key: str = "7d",
    workspace: Optional[str] = None,
    executor: Any = None,
) -> Dict[str, Any]:
    """Aggregate usage across all data-root workspaces (IDEA-2 D2)."""
    from aisc.adapters.docker_ import RealDockerExecutor
    from aisc.application.data_root import shared_root
    from aisc.application.network_subscription import show_subscription

    _validate_range(range_key)
    executor = executor or RealDockerExecutor()
    since = since_epoch_for(range_key)

    subscription = show_subscription()
    want_workspace = str(Path(workspace).resolve()) if workspace else None

    data_root = shared_root()
    ws_root = data_root / "workspaces"
    workspaces: List[Dict[str, Any]] = []
    totals: Dict[tuple, Dict[str, Any]] = {}

    for ws_dir in sorted(ws_root.glob("sha256-v1-*")) if ws_root.is_dir() else []:
        entries = _registry_entries(ws_dir)
        if not entries:
            continue
        ws_path = ""
        for meta in entries.values():
            if isinstance(meta, dict) and meta.get("workspace"):
                ws_path = str(meta.get("workspace"))
                break
        if want_workspace and str(Path(ws_path).resolve() if ws_path else "") != want_workspace:
            continue

        running_container: Optional[str] = None
        for name in entries:
            try:
                if _container_running(executor, name):
                    running_container = name
                    break
            except Exception:
                continue

        usage: Optional[Dict[str, Any]] = None
        source = "none"
        fetched_at: Optional[str] = None
        if running_container:
            usage = _exec_usage_adapter(executor, running_container, since)
            if usage is not None:
                source = "live"
                fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
                try:
                    _write_cache(ws_dir.name, range_key, usage)
                except OSError:
                    pass  # cache is best-effort
        if usage is None:
            cached = _read_cache(ws_dir.name, range_key)
            if cached is not None:
                usage = cached
                source = "cache"

        providers = _normalize_providers(usage or {})
        models = _normalize_models(usage or {})
        for row in providers:
            key = (row["app"], row["provider_id"])
            agg = totals.setdefault(key, {
                "app": row["app"], "provider_id": row["provider_id"],
                "provider_name": row["provider_name"], "requests": 0,
                "success": 0, "failed": 0, "tokens_total": 0,
                "cost_estimate": 0.0, "currency": row["currency"],
            })
            agg["requests"] += row["requests"]
            agg["success"] += row["success"]
            agg["failed"] += row["failed"]
            agg["tokens_total"] += row["tokens_total"]
            agg["cost_estimate"] = round(agg["cost_estimate"] + row["cost_estimate"], 4)

        workspaces.append({
            "workspace_hash": ws_dir.name,
            "workspace_path": ws_path,
            "running": running_container is not None,
            "container": running_container or "",
            "source": source,
            "fetched_at": fetched_at,
            "available": bool(usage and usage.get("available")),
            "providers": providers,
            "models": models,
        })

    totals_rows = sorted(totals.values(),
                         key=lambda r: r["tokens_total"], reverse=True)
    return {
        "subscription": subscription,
        "range": range_key,
        "since": since,
        "workspaces": workspaces,
        "totals": {
            "providers": totals_rows,
            "requests": sum(r["requests"] for r in totals_rows),
            "tokens_total": sum(r["tokens_total"] for r in totals_rows),
            "cost_estimate": round(sum(r["cost_estimate"] for r in totals_rows), 4),
        },
    }
