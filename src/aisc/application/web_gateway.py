"""Host-side web-gateway lifecycle (svc-2, docs/plans/container-service-access.md).

Wires the container-side gateway (svc-1) into the runtime lifecycle:

- host loopback port allocation (bind-probe, conflict retry);
- the ``--publish 127.0.0.1:<host>:45871/tcp`` argv for ``docker run``;
- mapping reads from ``docker inspect`` (connectivity source of truth);
- the ``web_access`` snapshot attached to ``RuntimeSnapshot``;
- the ``aisc runtime services`` data plane (list/expose/unexpose via
  ``docker exec`` of the container helpers).

Secret-free: payloads carry ports/labels/state only. Events never log
paths, queries, headers or bodies.
"""

from __future__ import annotations

import json
import socket
from typing import Any, Dict, List, Optional, Set

from aisc.domain.models import CliError, RuntimeErrorCode, RuntimeExitCode
from aisc.domain.web_services import (
    RUNTIME_SERVICES_SCHEMA_V1,
    WEB_GATEWAY_CONTAINER_PORT,
    WEB_GATEWAY_HOST_BIND,
    WEB_GATEWAY_HOST_PORT_MAX,
    WEB_GATEWAY_HOST_PORT_MIN,
    WebGatewayInfo,
    WebServiceInfo,
    build_service_url,
    parse_expose_port,
    sanitize_service_name,
)

_ALLOCATION_ATTEMPTS = 5  # bind-conflict retries before giving up

# docker daemon port-bind failure signatures (case-insensitive substrings).
_BIND_CONFLICT_MARKERS = (
    "port is already allocated",
    "address already in use",
    "bind for 0.0.0.0",
    "bind for 127.0.0.1",
    "bind for 172.",
)


class GatewayPortError(CliError):
    """Host port allocation exhausted / persistently conflicting."""

    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
            error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
            data=data,
        )


def is_bind_conflict(stderr: str) -> bool:
    lowered = (stderr or "").lower()
    return any(marker in lowered for marker in _BIND_CONFLICT_MARKERS)


# ---------------------------------------------------------------------------
# Host port allocation (decisions.md §7)
# ---------------------------------------------------------------------------

def allocate_gateway_host_port(exclude: Optional[Set[int]] = None,
                               start_hint: Optional[int] = None) -> int:
    """Bind-probe one free loopback port in the frozen 47000..47999 range.

    *exclude* carries ports reserved by other runtimes' registry records —
    skipped without probing so two starts cannot pick the same candidate.
    Probing binds ``127.0.0.1:<port>``, closes the socket, and returns the
    port; the Docker publish that follows owns it for real. TOCTOU between
    probe and publish is absorbed by the create-retry loop in
    :func:`runtime.start_runtime`.
    """
    taken = set(exclude or ())
    hint = start_hint or WEB_GATEWAY_HOST_PORT_MIN
    candidates = [p for p in range(hint, WEB_GATEWAY_HOST_PORT_MAX + 1)
                  if p not in taken]
    candidates += [p for p in range(WEB_GATEWAY_HOST_PORT_MIN, hint)
                   if p not in taken]
    for port in candidates:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            sock.bind((WEB_GATEWAY_HOST_BIND, port))
            return port
        except OSError:
            continue
        finally:
            sock.close()
    raise GatewayPortError(
        "No free host port in "
        f"{WEB_GATEWAY_HOST_PORT_MIN}..{WEB_GATEWAY_HOST_PORT_MAX} for the web gateway"
    )


def docker_publish_argv(host_port: int) -> List[str]:
    """The loopback publish argv for ``docker run``."""
    return [
        "--publish",
        f"{WEB_GATEWAY_HOST_BIND}:{host_port}:{WEB_GATEWAY_CONTAINER_PORT}/tcp",
    ]


def registry_host_ports(entries: Dict[str, Dict[str, Any]]) -> Set[int]:
    """Ports reserved by other runtimes' registry entries (0/missing ignored)."""
    out: Set[int] = set()
    for meta in (entries or {}).values():
        if not isinstance(meta, dict):
            continue
        try:
            port = int(meta.get("web_gateway_host_port") or 0)
        except (TypeError, ValueError):
            continue
        if WEB_GATEWAY_HOST_PORT_MIN <= port <= WEB_GATEWAY_HOST_PORT_MAX:
            out.add(port)
    return out


# ---------------------------------------------------------------------------
# Docker inspect mapping read
# ---------------------------------------------------------------------------

def read_gateway_mapping(executor: Any, container_name: str) -> Optional[Dict[str, Any]]:
    """Read the gateway publish mapping from ``docker inspect``.

    Returns ``{"host_ip", "host_port", "active"}`` or ``None`` when the
    container is absent/unknown. ``active=True`` means the binding lives in
    ``NetworkSettings.Ports`` (established, running); a binding visible only
    in ``HostConfig.PortBindings`` is configured but not established
    (stopped container / failed publish).
    """
    key = f"{WEB_GATEWAY_CONTAINER_PORT}/tcp"
    try:
        result = executor.inspect_container(container_name)
    except Exception:
        return None
    if result.exit_code != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return None

    def _first_binding(raw: Any) -> Optional[Dict[str, Any]]:
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            return raw[0]
        return None

    active = _first_binding(
        (data.get("NetworkSettings") or {}).get("Ports", {}).get(key))
    if active is not None:
        return {"host_ip": str(active.get("HostIp") or WEB_GATEWAY_HOST_BIND),
                "host_port": int(active.get("HostPort") or 0),
                "active": True}
    configured = _first_binding(
        (data.get("HostConfig") or {}).get("PortBindings", {}).get(key))
    if configured is not None:
        try:
            port = int(configured.get("HostPort") or 0)
        except (TypeError, ValueError):
            return None
        if port:
            return {"host_ip": str(configured.get("HostIp") or WEB_GATEWAY_HOST_BIND),
                    "host_port": port, "active": False}
    return None


def probe_gateway(host_port: int, timeout: float = 0.5) -> bool:
    """TCP-connect probe of the published gateway on loopback."""
    try:
        with socket.create_connection((WEB_GATEWAY_HOST_BIND, host_port),
                                      timeout=timeout):
            return True
    except OSError:
        return False


def snapshot_web_access(executor: Any,
                        container_name: str,
                        docker_state: Optional[str],
                        registry_has_gateway: bool,
                        probe: bool = True) -> WebGatewayInfo:
    """Compose the ``web_access`` view (decisions.md §3.2 reason rules)."""
    if docker_state is None or docker_state == "unknown":
        return WebGatewayInfo(state="unavailable", reason="docker_unavailable")
    if docker_state == "not_found":
        return WebGatewayInfo(state="unavailable", reason="runtime_not_running")

    mapping = read_gateway_mapping(executor, container_name) if container_name else None
    host_port = mapping["host_port"] if mapping else 0

    if docker_state != "running":
        return WebGatewayInfo(state="unavailable", reason="runtime_not_running",
                              host_port=host_port)
    if mapping is None:
        reason = "no_mapping" if registry_has_gateway else "legacy_runtime"
        return WebGatewayInfo(state="unavailable", reason=reason)
    if not mapping["active"]:
        return WebGatewayInfo(state="unavailable", reason="no_mapping",
                              host_port=host_port)
    if probe and not probe_gateway(mapping["host_port"]):
        return WebGatewayInfo(state="unavailable", reason="gateway_unreachable",
                              host_port=host_port)
    return WebGatewayInfo(state="ready", host_port=host_port)


# ---------------------------------------------------------------------------
# `aisc runtime services` data plane
# ---------------------------------------------------------------------------

_HELPER_LIST = "/usr/local/bin/aisc-web-list"
_HELPER_EXPOSE = "/usr/local/bin/aisc-web-expose"
_HELPER_UNEXPOSE = "/usr/local/bin/aisc-web-unexpose"


def _resolve_runtime(runtime_id: str, executor: Any, registry_root: Any):
    """Validate the id and resolve (container_name, docker_state, meta)."""
    from aisc.application.runtime import (
        _find_docker_container_by_runtime_id,
        validate_uuid_v4,
    )
    from aisc.adapters.container_registry import find_by_runtime_id

    if not validate_uuid_v4(runtime_id):
        raise CliError(
            message=f"Invalid runtime ID (must be UUID v4): {runtime_id}",
            exit_code=RuntimeExitCode.INVALID_RUNTIME_ID,
            error_code=RuntimeErrorCode.INVALID_RUNTIME_ID,
        )
    meta: Dict[str, Any] = {}
    container_name = ""
    found = find_by_runtime_id(registry_root, runtime_id)
    if found is not None:
        container_name, meta = found
    else:
        dc = _find_docker_container_by_runtime_id(runtime_id, executor)
        if dc is not None:
            container_name = dc["container_name"]
    return container_name, meta


def _exec_container(executor: Any, container_name: str, argv: List[str],
                    timeout: float = 15.0):
    return executor.run_captured(["exec", container_name] + argv, timeout=timeout)


def list_container_services(executor: Any, container_name: str) -> List[Dict[str, Any]]:
    """Read the manifest list via the container helper; degraded to []."""
    result = _exec_container(executor, container_name, [_HELPER_LIST, "--json"])
    if result.exit_code != 0:
        return []  # old image without the helper — degrade, never crash
    try:
        records = json.loads(result.stdout.strip() or "[]")
    except (ValueError, TypeError):
        return []
    if not isinstance(records, list):
        return []
    return [r for r in records if isinstance(r, dict)]


def runtime_services(runtime_id: str,
                     executor: Any,
                     registry_root: Any,
                     probe: bool = True):
    """``aisc runtime services`` — gateway info + registered services."""
    from aisc.application.runtime import _get_container_state, iso_now
    from aisc.domain.web_services import RuntimeServicesResult

    container_name, meta = _resolve_runtime(runtime_id, executor, registry_root)
    docker_state = _get_container_state(container_name, executor) if container_name else "not_found"
    gateway = snapshot_web_access(
        executor, container_name, docker_state,
        registry_has_gateway=bool(meta.get("web_gateway_host_port")),
        probe=probe,
    )

    services: List[WebServiceInfo] = []
    if gateway.state == "ready" and gateway.host_port:
        for record in list_container_services(executor, container_name):
            try:
                port = int(record.get("port") or 0)
                if not 1024 <= port <= 65535:
                    continue
                services.append(WebServiceInfo(
                    port=port,
                    protocol=str(record.get("protocol") or "http"),
                    name=str(record.get("name") or ""),
                    state=str(record.get("state") or "registered"),
                    url=build_service_url(port, gateway.host_port),
                ))
            except (ValueError, TypeError):
                continue  # malformed record — skip, never fail the listing

    return RuntimeServicesResult(
        runtime_id=runtime_id, gateway=gateway, services=services,
        observed_at=iso_now(),
    )


def _require_running_gateway(executor: Any, registry_root: Any, runtime_id: str):
    """Shared gate for expose/unexpose: a running, gateway-ready container."""
    container_name, meta = _resolve_runtime(runtime_id, executor, registry_root)
    if not container_name:
        raise CliError(
            message=f"Runtime not found: {runtime_id}",
            exit_code=RuntimeExitCode.GENERAL_ERROR,
            error_code=RuntimeErrorCode.RUNTIME_NOT_FOUND,
        )
    from aisc.application.runtime import _get_container_state

    state = _get_container_state(container_name, executor)
    gateway = snapshot_web_access(
        executor, container_name, state,
        registry_has_gateway=bool(meta.get("web_gateway_host_port")),
    )
    if state != "running" or gateway.state != "ready":
        reason = gateway.reason or "runtime_not_running"
        raise CliError(
            message=(
                f"Web gateway not ready ({reason}). "
                f"Runtime state: {state or 'not_found'}."
            ),
            exit_code=RuntimeExitCode.RUNTIME_NOT_RUNNING
            if state != "running" else RuntimeExitCode.RUNTIME_OPERATION_FAILED,
            error_code=RuntimeErrorCode.RUNTIME_NOT_RUNNING
            if state != "running" else RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
            data={"runtime_id": runtime_id, "web_access": gateway.to_dict()},
        )
    return container_name


def _parse_port_or_usage_error(port_text: str) -> int:
    try:
        return parse_expose_port(port_text)
    except ValueError as exc:
        raise CliError(
            message=str(exc),
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code="AISC_ERR_USAGE",
        ) from exc


def _parse_name_or_usage_error(name: str) -> str:
    try:
        return sanitize_service_name(name)
    except ValueError as exc:
        raise CliError(
            message=str(exc),
            exit_code=RuntimeExitCode.USAGE_ERROR,
            error_code="AISC_ERR_USAGE",
        ) from exc


def expose_runtime_service(runtime_id: str, port_text: str, name: str,
                           executor: Any, registry_root: Any):
    """``aisc runtime services expose`` — exec the container helper."""
    from aisc.applog import append_event

    port = _parse_port_or_usage_error(port_text)
    label = _parse_name_or_usage_error(name)
    container_name = _require_running_gateway(executor, registry_root, runtime_id)

    argv = [_HELPER_EXPOSE, str(port)] + (["--name", label] if label else [])
    result = _exec_container(executor, container_name, argv)
    if result.exit_code != 0:
        raise CliError(
            message=f"Failed to register service port {port}: "
                    f"{(result.stderr or '').strip()[:200]}",
            exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
            error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
            data={"runtime_id": runtime_id, "port": port},
        )
    append_event("web_service_registered", source="cli",
                 container=container_name, runtime_id=runtime_id,
                 container_port=port, protocol="http")
    return runtime_services(runtime_id, executor, registry_root)


def unexpose_runtime_service(runtime_id: str, port_text: str,
                             executor: Any, registry_root: Any):
    """``aisc runtime services unexpose`` — exec the container helper."""
    from aisc.applog import append_event

    port = _parse_port_or_usage_error(port_text)
    container_name = _require_running_gateway(executor, registry_root, runtime_id)

    result = _exec_container(executor, container_name, [_HELPER_UNEXPOSE, str(port)])
    if result.exit_code != 0:
        raise CliError(
            message=f"Failed to unregister service port {port}: "
                    f"{(result.stderr or '').strip()[:200]}",
            exit_code=RuntimeExitCode.RUNTIME_OPERATION_FAILED,
            error_code=RuntimeErrorCode.RUNTIME_OPERATION_FAILED,
            data={"runtime_id": runtime_id, "port": port},
        )
    append_event("web_service_unregistered", source="cli",
                 container=container_name, runtime_id=runtime_id,
                 container_port=port)
    return runtime_services(runtime_id, executor, registry_root)
