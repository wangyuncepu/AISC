"""mihomo subscription management — application layer (IDEA-2, D1-D4).

Storage (Stage 7 data root; the file below is what gets ro-mounted at
``/etc/mihomo/config.yaml`` — the container's ``mihomo-build-config.js`` is
the sole conversion authority, so the raw subscription is stored verbatim)::

    <data-root>/config/mihomo/subscription.yaml     raw subscription file
    <data-root>/config/network-subscription.json    snapshot (full URL for refresh)

Policies (02-data-contracts.md §1-§4, §6):
- the full URL only ever lives in the snapshot file under the data root;
  envelopes, logs and diagnostics only ever see ``mask_url`` output;
- ``subscription-userinfo`` response header is parsed tolerantly
  (``total=0`` = unlimited, ``expire`` may be absent, garbage pairs skipped);
- downloads use an injectable stdlib-urllib transport with a clash-family
  User-Agent (providers gate payload format by UA); TLS-handshake kills are
  classified as ``..._TLS_REJECTED`` so the UI can guide manual content
  import (D4 — fingerprint-filtering providers drop script-stack handshakes);
- legacy ``<aisc_root>/.claude/mihomo/config.yaml`` is adopted once (copied,
  never moved) when the data-root target is absent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from aisc.domain.models import CliError


SUBSCRIPTION_SCHEMA = "aisc.network-subscription/v1"

#: Clash-family UA: subscription panels gate payload format on it (browser
#: UAs get the HTML panel; clash clients get the config payload).
USER_AGENT = "clash-verge/v2.2.0 (aisc)"

DEFAULT_TIMEOUT_S = 30.0
MAX_URL_LENGTH = 2048

ERROR_FETCH = "AISC_ERR_NETWORK_SUBSCRIPTION_FETCH"
ERROR_HTTP = "AISC_ERR_NETWORK_SUBSCRIPTION_HTTP"
ERROR_INVALID_URL = "AISC_ERR_NETWORK_SUBSCRIPTION_INVALID_URL"
ERROR_NOT_CONFIGURED = "AISC_ERR_NETWORK_SUBSCRIPTION_NOT_CONFIGURED"
ERROR_EMPTY = "AISC_ERR_NETWORK_SUBSCRIPTION_EMPTY"
ERROR_TLS_REJECTED = "AISC_ERR_NETWORK_SUBSCRIPTION_TLS_REJECTED"

#: Injectable transport: (url, headers, timeout) -> (status, headers, body).
#: Headers keys are lowercased; body is the raw response bytes. ``HTTPError``
#: is returned as a normal 4xx/5xx result; transport-level failures raise.
Transport = Callable[[str, Dict[str, str], float], Tuple[int, Dict[str, str], bytes]]

_USERINFO_KEYS = ("upload", "download", "total", "expire")


def default_transport(url: str, headers: Dict[str, str], timeout: float) -> Tuple[int, Dict[str, str], bytes]:
    """stdlib urllib transport (mirrors ``cc_switch_resolver.default_transport``
    but returns raw bytes — the subscription payload is not JSON).

    ``HTTPError`` surfaces as a normal 4xx/5xx result; transport-level
    failures (``URLError``/``OSError``) propagate raw — ``_fetch`` owns the
    classification so custom transports behave identically.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        return int(exc.code), {k.lower(): v for k, v in exc.headers.items()}, raw or b""


def _classify_transport_error(exc: urllib.error.URLError) -> CliError:
    """Map a transport-level failure onto a stable code.

    Handshake-phase kills (server closes right after ClientHello — the
    fingerprint-filtering behaviour probed in 2a §6.1) surface as
    ``ssl.SSLError``-family reasons or hard connection resets; those get
    ``TLS_REJECTED`` so the UI can suggest content import (D4). Everything
    else (unreachable, timeouts) is a plain fetch failure.
    """
    reason = exc.reason
    if isinstance(reason, ssl.SSLError):
        return CliError(
            message=(
                "subscription source rejected the connection during TLS "
                "handshake (client fingerprint filtering). Import the config "
                "content manually instead ('aisc network subscription "
                "import-file', stdin = full subscription content)."
            ),
            exit_code=1,
            error_code=ERROR_TLS_REJECTED,
        )
    if isinstance(reason, ConnectionResetError):
        return CliError(
            message=(
                "subscription source reset the connection during TLS "
                "handshake. If it persists, import the config content "
                "manually ('aisc network subscription import-file')."
            ),
            exit_code=1,
            error_code=ERROR_TLS_REJECTED,
        )
    return CliError(
        message=(
            f"subscription source unreachable: {reason}. Check network/proxy "
            "availability, or import the config content manually "
            "('aisc network subscription import-file')."
        ),
        exit_code=1,
        error_code=ERROR_FETCH,
    )


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def subscription_config_path(env: Optional[Mapping[str, str]] = None) -> Path:
    """``<data-root>/config/mihomo/subscription.yaml`` (does not create it)."""
    from aisc.application.data_root import shared_root

    return shared_root(env) / "config" / "mihomo" / "subscription.yaml"


def _snapshot_path(env: Optional[Mapping[str, str]] = None) -> Path:
    from aisc.application.data_root import shared_root

    return shared_root(env) / "config" / "network-subscription.json"


def _legacy_config_path(legacy_root: Optional[Path]) -> Optional[Path]:
    if legacy_root is not None:
        return Path(legacy_root) / ".claude" / "mihomo" / "config.yaml"
    from aisc.application.resources import locate_aisc_root, _RootSourceError

    try:
        root = locate_aisc_root()
    except _RootSourceError:
        return None
    if root is None:
        return None
    return Path(root) / ".claude" / "mihomo" / "config.yaml"


def resolve_subscription_config_path(
    explicit: Optional[str] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    legacy_root: Optional[Path] = None,
    adopt_legacy: bool = True,
) -> Optional[str]:
    """Resolve which host file a ``network=proxy`` run should mount.

    Order: explicit path (returned verbatim — callers validate) → data-root
    subscription → legacy ``<aisc_root>/.claude/mihomo/config.yaml``. With
    ``adopt_legacy=True`` the legacy file is *copied* into the data root once
    (idempotent, source untouched); with ``adopt_legacy=False`` the legacy
    path itself is returned (read-only callers must stay side-effect free).
    Returns ``None`` when nothing exists (TUN without config stays valid).
    """
    if explicit:
        return str(explicit)
    target = subscription_config_path(env)
    if target.is_file():
        return str(target)
    legacy = _legacy_config_path(legacy_root)
    if legacy is not None and legacy.is_file():
        if not adopt_legacy:
            return str(legacy)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.adopt.{os.getpid()}")
        tmp.write_bytes(legacy.read_bytes())
        os.replace(tmp, target)
        return str(target)
    return None


# ---------------------------------------------------------------------------
# Parsing / masking
# ---------------------------------------------------------------------------

def parse_userinfo(value: str) -> Optional[Dict[str, int]]:
    """Parse a ``subscription-userinfo`` header value.

    ``upload=..; download=..; total=..; expire=..`` — semicolon-separated
    ``k=v`` pairs, whitespace tolerated, unknown keys and malformed pairs
    skipped. Returns ``None`` when nothing usable is present. Values are raw
    non-negative integers (bytes / unix seconds); presentation converts.
    """
    if not value:
        return None
    out: Dict[str, int] = {}
    for pair in value.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, _, raw = pair.partition("=")
        key = key.strip().lower()
        raw = raw.strip()
        if key not in _USERINFO_KEYS or not raw.isdigit():
            continue
        out[key] = int(raw)
    return out or None


# ---------------------------------------------------------------------------
# Node-name usage fallback (挂账②): many airports send NO userinfo header but
# embed the plan facts as FAKE PROXY NODES ("已用流量：4.03 GB", "剩余流量：
# 9999995.97 GB", "套餐总量：10000000 GB", "套餐到期：永久有效"). When the
# header is absent, the raw subscription text is scanned for these patterns
# and the result is mapped onto the header's userinfo shape (upload+download
# = used ⇒ everything lands in `download`; derivations fill the gaps).
# ---------------------------------------------------------------------------

_UNIT_MULT = {
    "B": 1, "KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000, "TB": 10**12,
    "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4,
}
_TRAFFIC_VALUE = r"([0-9][0-9.,]*)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)"
_NODE_USAGE_PATTERNS = {
    "used": re.compile(r"(?:已用|已使用|使用量)[^:：\n]{0,6}[:：]\s*" + _TRAFFIC_VALUE, re.I),
    "remaining": re.compile(r"(?:剩余|可用|余量)[^:：\n]{0,6}[:：]\s*" + _TRAFFIC_VALUE, re.I),
    "total": re.compile(r"(?:总流量|套餐总量|流量总量|总量)[^:：\n]{0,6}[:：]\s*" + _TRAFFIC_VALUE, re.I),
}
_EXPIRE_LINE_RE = re.compile(r"(?:到期|过期|有效期|expire)[^:：\n]{0,6}[:：]\s*([^|｜,，\n\r]{1,40})", re.I)
_PERMANENT_RE = re.compile(r"永久|不过期|长期|never", re.I)
_EXPIRE_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                        "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M",
                        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d")


def _traffic_to_bytes(value: str, unit: str) -> Optional[int]:
    try:
        return int(float(value.replace(",", "")) * _UNIT_MULT[unit.upper()])
    except (ValueError, KeyError, OverflowError):
        return None


def parse_node_name_userinfo(text: str) -> Optional[Dict[str, int]]:
    """Extract plan usage from fake-node names in the subscription text.

    Returns the header-shaped dict (``download`` carries the used bytes) or
    ``None`` when nothing recognizable is present. Derivations: any one of
    used/total missing is filled from the other two when possible; a
    permanent-plan keyword omits ``expire``; a parseable date becomes an
    epoch."""
    found: Dict[str, int] = {}
    for name, pattern in _NODE_USAGE_PATTERNS.items():
        m = pattern.search(text)
        if m:
            amount = _traffic_to_bytes(m.group(1), m.group(2))
            if amount is not None:
                found[name] = amount
    used = found.get("used")
    remaining = found.get("remaining")
    total = found.get("total")
    if total is None and used is not None and remaining is not None:
        total = used + remaining
    elif used is None and total is not None and remaining is not None:
        used = total - remaining
    if used is None or (total is None and remaining is None):
        return None

    out: Dict[str, int] = {"upload": 0, "download": used}
    if total is not None:
        out["total"] = total
    m = _EXPIRE_LINE_RE.search(text)
    if m:
        raw = m.group(1).strip()
        if not _PERMANENT_RE.search(raw):
            for fmt in _EXPIRE_DATE_FORMATS:
                try:
                    out["expire"] = int(datetime.strptime(raw, fmt).timestamp())
                    break
                except ValueError:
                    continue
    return out


def mask_url(url: str) -> Optional[str]:
    """Deterministic display form: scheme + host survive, path truncated,
    query replaced by ``****``, fragment dropped. ``None`` for garbage."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    path = parts.path or "/"
    if len(path) > 8:
        path = path[:8] + "…"
    masked = f"{parts.scheme}://{parts.netloc}{path}"
    if parts.query:
        masked += "?****"
    return masked


def _validate_url(url: str) -> str:
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise CliError(
            message="subscription URL is empty or longer than "
                    f"{MAX_URL_LENGTH} characters",
            exit_code=2,
            error_code=ERROR_INVALID_URL,
        )
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise CliError(
            message="subscription URL must be an absolute http(s) URL",
            exit_code=2,
            error_code=ERROR_INVALID_URL,
        )
    return url


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def _sha256_hex(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _load_snapshot(env: Optional[Mapping[str, str]] = None) -> Optional[Dict[str, Any]]:
    try:
        raw = _snapshot_path(env).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _envelope_data(
    *,
    configured: bool,
    source: Optional[str],
    url_masked: Optional[str],
    fetched_at: Optional[str],
    config_sha256: Optional[str],
    has_config_file: bool,
    userinfo: Optional[Dict[str, int]],
    userinfo_source: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "configured": configured,
        "source": source,
        "url_masked": url_masked,
        "fetched_at": fetched_at,
        "config_sha256": config_sha256,
        "has_config_file": has_config_file,
        "userinfo": userinfo,
    }
    if userinfo_source is not None:
        data["userinfo_source"] = userinfo_source
    if config_path is not None:
        data["config_path"] = config_path
    return data


# ---------------------------------------------------------------------------
# Operations (envelope data per 02-data-contracts.md §4)
# ---------------------------------------------------------------------------

def _fetch(
    url: str,
    *,
    transport: Transport,
    timeout: float,
) -> Tuple[bytes, Dict[str, str]]:
    """Fetch with one retry on transient failures (4xx never retries)."""
    attempts = 2
    last_error: Optional[CliError] = None
    for attempt in range(attempts):
        err: Optional[CliError] = None
        try:
            status, headers, body = transport(url, {"User-Agent": USER_AGENT}, timeout)
        except urllib.error.URLError as exc:
            err = _classify_transport_error(exc)
        except CliError as exc:
            err = exc
        except (TimeoutError, OSError) as exc:
            err = CliError(
                message=f"subscription download failed: {exc}",
                exit_code=1,
                error_code=ERROR_FETCH,
            )
        if err is not None:
            # TLS_REJECTED is deterministic — retrying only burns the budget.
            if err.error_code == ERROR_TLS_REJECTED or attempt == attempts - 1:
                raise err
            last_error = err
            continue
        if 200 <= status < 300:
            if not body:
                raise CliError(
                    message="subscription source returned an empty body",
                    exit_code=1,
                    error_code=ERROR_EMPTY,
                )
            return body, headers
        if 400 <= status < 500:
            raise CliError(
                message=f"subscription source returned HTTP {status}",
                exit_code=1,
                error_code=ERROR_HTTP,
                data={"http_status": status},
            )
        # 5xx (or unexpected): retry once, then fail as FETCH.
        last_error = CliError(
            message=f"subscription source returned HTTP {status}",
            exit_code=1,
            error_code=ERROR_FETCH,
            data={"http_status": status},
        )
    assert last_error is not None
    raise last_error


def import_subscription(
    url: str,
    *,
    transport: Optional[Transport] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Download a subscription, store it, return the envelope data.

    The URL is a credential — callers must pass it via stdin, never argv.
    ``transport`` resolves lazily so tests can patch
    ``network_subscription.default_transport`` at module level.
    """
    transport = transport or default_transport
    url = _validate_url(url)
    body, headers = _fetch(url, transport=transport, timeout=timeout)
    userinfo = parse_userinfo(headers.get("subscription-userinfo", ""))
    userinfo_source = "header" if userinfo else None
    if userinfo is None:
        # 挂账②: airports without the header embed the facts as fake nodes.
        userinfo = parse_node_name_userinfo(body.decode("utf-8", "replace"))
        if userinfo is not None:
            userinfo_source = "node-names"
    return _persist(
        url=url, body=body, userinfo=userinfo, userinfo_source=userinfo_source,
        source="download", env=env,
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def import_subscription_content(
    content: bytes,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Store manually supplied subscription content (D4 fallback for
    fingerprint-filtering sources). No URL — and no header either, so the
    node-name fallback is the only usage source."""
    if not content or not content.strip():
        raise CliError(
            message="subscription content is empty",
            exit_code=2,
            error_code=ERROR_EMPTY,
        )
    userinfo = parse_node_name_userinfo(content.decode("utf-8", "replace"))
    return _persist(
        url=None, body=content, userinfo=userinfo,
        userinfo_source="node-names" if userinfo else None,
        source="manual", env=env,
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def _persist(
    *,
    url: Optional[str],
    body: bytes,
    userinfo: Optional[Dict[str, int]],
    userinfo_source: Optional[str],
    source: str,
    env: Optional[Mapping[str, str]],
    fetched_at: str,
) -> Dict[str, Any]:
    config_path = subscription_config_path(env)
    _atomic_write(config_path, body)
    snapshot: Dict[str, Any] = {
        "schema": SUBSCRIPTION_SCHEMA,
        "url": url,
        "source": source,
        "fetched_at": fetched_at,
        "config_sha256": _sha256_hex(body),
        "userinfo": userinfo,
        "userinfo_source": userinfo_source,
    }
    _atomic_write(
        _snapshot_path(env),
        json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    return _envelope_data(
        configured=True,
        source=source,
        url_masked=mask_url(url) if url else None,
        fetched_at=fetched_at,
        config_sha256=snapshot["config_sha256"],
        has_config_file=True,
        userinfo=userinfo,
        userinfo_source=userinfo_source,
        config_path=str(config_path),
    )


def refresh_subscription(
    *,
    transport: Optional[Transport] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Re-fetch the stored subscription URL."""
    transport = transport or default_transport
    snapshot = _load_snapshot(env)
    url = (snapshot or {}).get("url")
    if not url or not isinstance(url, str):
        raise CliError(
            message="no subscription URL stored (import one first, or use "
                    "import-file for manually supplied content)",
            exit_code=1,
            error_code=ERROR_NOT_CONFIGURED,
        )
    return import_subscription(url, transport=transport, timeout=timeout, env=env)


def show_subscription(
    *,
    env: Optional[Mapping[str, str]] = None,
    legacy_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Secret-free snapshot of the current subscription state (no fetch)."""
    # One-time legacy adoption so an existing CLI-wizard config keeps working
    # from the data root without a manual copy.
    resolve_subscription_config_path(env=env, legacy_root=legacy_root, adopt_legacy=True)

    config_path = subscription_config_path(env)
    snapshot = _load_snapshot(env) or {}
    if not config_path.is_file():
        return _envelope_data(
            configured=False, source=None, url_masked=None, fetched_at=None,
            config_sha256=None, has_config_file=False, userinfo=None,
        )
    try:
        sha = _sha256_hex(config_path.read_bytes())
    except OSError:
        sha = None
    userinfo = snapshot.get("userinfo")
    if not isinstance(userinfo, dict):
        userinfo = None
    userinfo_source = snapshot.get("userinfo_source")
    if userinfo_source not in ("header", "node-names"):
        userinfo_source = None
    url = snapshot.get("url")
    return _envelope_data(
        configured=True,
        source=snapshot.get("source") or "manual",
        url_masked=mask_url(url) if isinstance(url, str) else None,
        fetched_at=snapshot.get("fetched_at"),
        config_sha256=sha,
        has_config_file=True,
        userinfo=userinfo,
        userinfo_source=userinfo_source,
        config_path=str(config_path),
    )


def clear_subscription(
    *,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Remove the stored subscription (config file + snapshot). The legacy
    repo-root file, if any, is deliberately left untouched."""
    for path in (subscription_config_path(env), _snapshot_path(env)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise CliError(
                message=f"failed to remove {path}: {exc}",
                exit_code=1,
                error_code="AISC_ERR_GENERAL",
            ) from exc
    return {"configured": False}
