"""Container web-service access contract (svc-0, 2026-08-25).

Single source of truth for the cross-language constants and pure functions
behind "Agent 启动容器内 Web 服务 → 宿主机浏览器可访问":

- docs/plans/container-service-access.md (implementation plan)
- docs/plans/container-service-access/decisions.md (frozen contract)
- tests/fixtures/web-services/ (samples decoded identically by
  Python/Rust/TypeScript — the svc-0 stage gate)

Nothing here performs I/O; side-effectful pieces (host port allocation,
Docker argv, docker exec) live in application/adapters layers.

Secret-free by construction: ports/labels/state only, never request paths,
queries, headers or bodies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Frozen constants (mirrored in Rust web_services.rs / TS webServices.ts)
# ---------------------------------------------------------------------------

#: Fixed container-side port the in-container gateway listens on.
WEB_GATEWAY_CONTAINER_PORT = 45871

#: Host loopback port range allocated to runtime gateways (inclusive).
WEB_GATEWAY_HOST_PORT_MIN = 47000
WEB_GATEWAY_HOST_PORT_MAX = 47999

#: Registrable container service ports (non-privileged TCP only).
WEB_SERVICE_PORT_MIN = 1024
WEB_SERVICE_PORT_MAX = 65535

#: In-container manifest directory; one ``<port>.json`` per registered service.
WEB_SERVICES_DIR = "/run/aisc/web-services"

#: Schema stamped on every manifest record and every ``runtime services``
#: payload. Unknown schema versions fail closed at the decode boundary.
WEB_SERVICE_SCHEMA_V1 = "aisc.web-service/v1"
RUNTIME_SERVICES_SCHEMA_V1 = "aisc.runtime-services/v1"

#: v1 protocol: HTTP/1.1-over-TCP (+ WebSocket upgrade). HTTPS is deferred.
WEB_SERVICE_PROTOCOL = "http"

#: The gateway is host-published on loopback only, never 0.0.0.0.
WEB_GATEWAY_HOST_BIND = "127.0.0.1"

#: URL scheme for user-facing service URLs (frozen for v1).
WEB_SERVICE_URL_SCHEME = "http"

#: Hostname label the gateway routes on: ``p<container-port>.localhost``.
GATEWAY_HOST_SUFFIX = ".localhost"


class WebErrorCode:
    """Stable identifiers the in-container gateway returns on failures.

    Paired HTTP statuses (decisions.md §gateway errors):

    ============ ============================== ===============================
    identifier   HTTP                           meaning
    ============ ============================== ===============================
    BAD_HOST     400 AISC_WEB_BAD_HOST          Host is not p<port>.localhost
    PORT_INVALID 400 AISC_WEB_PORT_INVALID      port outside 1024..65535
    NOT_EXPOSED  404 AISC_WEB_PORT_NOT_EXPOSED  port not registered
    TARGET_DOWN  502 AISC_WEB_TARGET_UNAVAILABLE container target not listening
    REGISTRY     503 AISC_WEB_REGISTRY_UNAVAILABLE  manifest dir unreadable
    ============ ============================== ===============================
    """

    BAD_HOST = "AISC_WEB_BAD_HOST"
    PORT_INVALID = "AISC_WEB_PORT_INVALID"
    PORT_NOT_EXPOSED = "AISC_WEB_PORT_NOT_EXPOSED"
    TARGET_UNAVAILABLE = "AISC_WEB_TARGET_UNAVAILABLE"
    REGISTRY_UNAVAILABLE = "AISC_WEB_REGISTRY_UNAVAILABLE"


#: Why ``web_access.state`` is ``unavailable`` (UI shows the reason verbatim
#: via i18n; never invent values outside this set).
WEB_UNAVAILABLE_REASONS = (
    "legacy_runtime",       # container created before gateway publish existed
    "runtime_not_running",  # container stopped; mapping exists but port closed
    "gateway_unreachable",  # mapping exists, gateway did not accept (crashed?)
    "docker_unavailable",   # could not inspect the mapping
    "no_mapping",           # container has no 45871/tcp publish at all
)


# ---------------------------------------------------------------------------
# Pure validation / parsing helpers
# ---------------------------------------------------------------------------

_DECIMAL_RE = re.compile(r"^[0-9]+$")


def is_exposable_port(port: int) -> bool:
    """True when *port* is a registrable TCP port (1024..65535)."""
    return isinstance(port, int) and WEB_SERVICE_PORT_MIN <= port <= WEB_SERVICE_PORT_MAX


def parse_expose_port(text: str) -> int:
    """Parse a service port argument; strict decimal, bounded.

    Raises ``ValueError`` on anything that is not ``^[0-9]+$`` or falls
    outside 1024..65535 (negative, float, empty, trailing text, privileged).
    """
    if not isinstance(text, str) or not _DECIMAL_RE.match(text):
        raise ValueError(f"port must be a decimal integer: {text!r}")
    port = int(text)
    if not is_exposable_port(port):
        raise ValueError(f"port out of range {WEB_SERVICE_PORT_MIN}..{WEB_SERVICE_PORT_MAX}: {port}")
    return port


def sanitize_service_name(name: str) -> str:
    """Normalize a display-only service label.

    Rules (decisions.md §helper contract): plain short text, no control
    characters, at most 64 chars after stripping. Empty is allowed (unnamed
    service). The label never enters URLs or routing decisions.
    """
    if name is None:
        return ""
    stripped = str(name).strip()
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in stripped):
        raise ValueError("service name must not contain control characters")
    if len(stripped) > 64:
        raise ValueError("service name longer than 64 characters")
    return stripped


def build_service_url(container_port: int, host_port: int) -> str:
    """Canonical user-facing URL: ``http://p<container-port>.localhost:<host-port>/``.

    The only inputs are the two ports; path/query/fragment stay with the
    browser request. Service labels never appear in the URL.
    """
    if not is_exposable_port(container_port):
        raise ValueError(f"container port out of range: {container_port}")
    if not (1 <= int(host_port) <= 65535):
        raise ValueError(f"host port out of range: {host_port}")
    return f"{WEB_SERVICE_URL_SCHEME}://p{container_port}{GATEWAY_HOST_SUFFIX}:{int(host_port)}/"


_HOST_RE = re.compile(
    r"^p([0-9]{1,5})\.localhost\.?(?::([0-9]{1,5}))?$",
    re.IGNORECASE,
)


def parse_gateway_host(host_value: str) -> Optional[int]:
    """Extract the container service port from a request Host header.

    Accepts ``p<port>.localhost`` with an optional (ignored) gateway port
    suffix and an optional FQDN trailing dot, case-insensitive — exactly the
    forms Chromium/Edge/Firefox emit for the canonical URL. Returns ``None``
    for anything else (the gateway answers ``AISC_WEB_BAD_HOST``).

    The port value itself is returned unvalidated; the caller checks
    :func:`is_exposable_port` (→ ``AISC_WEB_PORT_INVALID``) and the manifest
    (→ ``AISC_WEB_PORT_NOT_EXPOSED``) in that order.
    """
    if not isinstance(host_value, str):
        return None
    match = _HOST_RE.match(host_value.strip())
    if match is None:
        return None
    return int(match.group(1))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class WebServiceRecord:
    """One manifest entry at ``/run/aisc/web-services/<port>.json``.

    Registered by the in-container helper (or host CLI exec'ing it); read
    per-request by the gateway. Atomic-write/permission rules live in the
    helper, not here. ``state`` is only ever ``registered`` in v1 — the
    helper never claims readiness.
    """

    port: int
    protocol: str = WEB_SERVICE_PROTOCOL
    name: str = ""
    state: str = "registered"
    registered_at: str = ""
    pid: Optional[int] = None
    schema_version: str = field(default=WEB_SERVICE_SCHEMA_V1, repr=False)

    def __post_init__(self) -> None:
        if not is_exposable_port(self.port):
            raise ValueError(f"service port out of range: {self.port}")
        if self.state != "registered":
            raise ValueError(f"unsupported service state: {self.state!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "port": self.port,
            "protocol": self.protocol,
            "name": self.name,
            "state": self.state,
            "registered_at": self.registered_at,
            "pid": self.pid,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebServiceRecord":
        """Decode strictly: unknown schema or bad fields raise ``ValueError``.

        Fail-closed is the contract — the gateway treats a raise here as
        ``AISC_WEB_REGISTRY_UNAVAILABLE`` and refuses to forward.
        """
        if not isinstance(data, dict):
            raise ValueError("service record must be a JSON object")
        schema = data.get("schema_version")
        if schema != WEB_SERVICE_SCHEMA_V1:
            raise ValueError(f"unsupported schema_version: {schema!r}")
        port = data.get("port")
        if not isinstance(port, int) or isinstance(port, bool):
            raise ValueError(f"port must be an integer: {port!r}")
        pid = data.get("pid")
        if pid is not None and (not isinstance(pid, int) or isinstance(pid, bool)):
            raise ValueError(f"pid must be an integer or null: {pid!r}")
        return cls(
            port=port,
            protocol=str(data.get("protocol") or WEB_SERVICE_PROTOCOL),
            name=str(data.get("name") or ""),
            state=str(data.get("state") or "registered"),
            registered_at=str(data.get("registered_at") or ""),
            pid=pid,
        )


@dataclass
class WebGatewayInfo:
    """Gateway reachability snapshot (``RuntimeSnapshot.web_access`` and
    ``RuntimeServicesResult.gateway`` share this shape).

    ``host_port``/``host`` come from ``docker inspect`` (the connectivity
    source of truth), never from guessing. 0/empty when unknown.
    """

    state: str = "unavailable"  # ready | unavailable
    container_port: int = WEB_GATEWAY_CONTAINER_PORT
    host_port: int = 0
    host: str = WEB_GATEWAY_HOST_BIND
    reason: str = ""  # one of WEB_UNAVAILABLE_REASONS, "" when ready

    def __post_init__(self) -> None:
        if self.state not in ("ready", "unavailable"):
            raise ValueError(f"gateway state must be ready|unavailable: {self.state!r}")
        if self.state == "ready" and self.reason:
            raise ValueError("ready gateway must not carry an unavailable reason")
        if self.reason and self.reason not in WEB_UNAVAILABLE_REASONS:
            raise ValueError(f"unknown unavailable reason: {self.reason!r}")

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "state": self.state,
            "container_port": self.container_port,
            "host_port": self.host_port,
            "host": self.host,
        }
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass
class WebServiceInfo:
    """One service row in a ``runtime services`` payload (URL attached)."""

    port: int
    protocol: str = WEB_SERVICE_PROTOCOL
    name: str = ""
    state: str = "registered"
    url: str = ""

    def __post_init__(self) -> None:
        if not is_exposable_port(self.port):
            raise ValueError(f"service port out of range: {self.port}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "port": self.port,
            "protocol": self.protocol,
            "name": self.name,
            "state": self.state,
            "url": self.url,
        }


@dataclass
class RuntimeServicesResult:
    """``aisc runtime services`` payload (schema ``aisc.runtime-services/v1``)."""

    runtime_id: str
    gateway: WebGatewayInfo = field(default_factory=WebGatewayInfo)
    services: List[WebServiceInfo] = field(default_factory=list)
    observed_at: str = ""
    schema_version: str = field(default=RUNTIME_SERVICES_SCHEMA_V1, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runtime_id": self.runtime_id,
            "gateway": self.gateway.to_dict(),
            "services": [s.to_dict() for s in self.services],
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeServicesResult":
        """Decode strictly (fixture gate): wrong schema or shape raises."""
        if not isinstance(data, dict):
            raise ValueError("runtime services payload must be a JSON object")
        if data.get("schema_version") != RUNTIME_SERVICES_SCHEMA_V1:
            raise ValueError(f"unsupported schema_version: {data.get('schema_version')!r}")
        gateway = WebGatewayInfo(
            state=str(data["gateway"]["state"]),
            container_port=int(data["gateway"]["container_port"]),
            host_port=int(data["gateway"]["host_port"]),
            host=str(data["gateway"]["host"]),
            reason=str(data["gateway"].get("reason") or ""),
        )
        services = [
            WebServiceInfo(
                port=int(s["port"]),
                protocol=str(s["protocol"]),
                name=str(s["name"]),
                state=str(s["state"]),
                url=str(s["url"]),
            )
            for s in data["services"]
        ]
        return cls(
            runtime_id=str(data["runtime_id"]),
            gateway=gateway,
            services=services,
            observed_at=str(data["observed_at"]),
        )


def web_access_unavailable(reason: str) -> WebGatewayInfo:
    """Shorthand for the degraded snapshot path (legacy/stopped/unreachable)."""
    return WebGatewayInfo(state="unavailable", reason=reason)
