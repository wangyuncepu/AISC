"""``aisc network subscription`` command layer (IDEA-2, 2b).

Thin wrappers over ``aisc.application.network_subscription``. The
subscription URL is a credential: it rides stdin (``import`` reads one URL
line; ``import-file`` reads the full subscription content), never argv.
"""

from __future__ import annotations

import sys
from typing import Any, Dict

from aisc.domain.models import CliError


def _read_stdin_text(*, what: str) -> str:
    raw = sys.stdin.read()
    if not raw.strip():
        raise CliError(
            message=f"{what} on stdin is required (secrets never ride argv)",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        )
    return raw


def cmd_network_subscription_import(args: Any) -> Dict[str, Any]:
    from aisc.application.network_subscription import import_subscription

    url = _read_stdin_text(what="a subscription URL").strip()
    return import_subscription(url)


def cmd_network_subscription_import_file(args: Any) -> Dict[str, Any]:
    from aisc.application.network_subscription import import_subscription_content

    content = sys.stdin.buffer.read()
    return import_subscription_content(content)


def cmd_network_subscription_store_downloaded(args: Any) -> Dict[str, Any]:
    """挂账①: stdin carries a JSON document {url, content_b64, userinfo} —
    the body of a Rust-side (reqwest) download. b64 keeps the payload
    byte-exact through the text stdin channel."""
    import base64
    import json

    from aisc.application.network_subscription import store_downloaded

    raw = sys.stdin.read()
    try:
        request = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise CliError(
            message=f"store-downloaded request is not valid JSON: {exc}",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        ) from exc
    if not isinstance(request, dict):
        raise CliError(
            message="store-downloaded request must be a JSON object",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        )
    b64 = str(request.get("content_b64") or "")
    try:
        content = base64.b64decode(b64, validate=True) if b64 else b""
    except Exception as exc:
        raise CliError(
            message=f"content_b64 is not valid base64: {exc}",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        ) from exc
    url = request.get("url")
    userinfo = request.get("userinfo")
    return store_downloaded(
        str(url) if isinstance(url, str) and url else None,
        content,
        str(userinfo) if isinstance(userinfo, str) else "",
    )


def cmd_network_subscription_refresh(args: Any) -> Dict[str, Any]:
    from aisc.application.network_subscription import refresh_subscription

    return refresh_subscription()


def cmd_network_subscription_show(args: Any) -> Dict[str, Any]:
    from aisc.application.network_subscription import show_subscription

    return show_subscription()


def cmd_network_subscription_clear(args: Any) -> Dict[str, Any]:
    from aisc.application.network_subscription import clear_subscription

    if not getattr(args, "confirm", False):
        raise CliError(
            message="clear requires --confirm",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        )
    return clear_subscription()


def print_network_subscription_text(data: Dict[str, Any]) -> None:
    """Human-readable output (secret-free: masked URL only)."""
    if not isinstance(data, dict):
        return
    if not data.get("configured"):
        print("No subscription configured.")
        print("Import one:  aisc network subscription import   (URL on stdin)")
        print("       or:    aisc network subscription import-file (content on stdin)")
        return
    print(f"Source:      {data.get('source') or 'manual'}")
    print(f"URL:         {data.get('url_masked') or '(manually imported)'}")
    print(f"Updated:     {data.get('fetched_at') or '(unknown)'}")
    print(f"Config:      {data.get('config_path') or ''} ({data.get('config_sha256') or '?'})")
    userinfo = data.get("userinfo")
    if isinstance(userinfo, dict) and userinfo:
        total = userinfo.get("total")
        used = userinfo.get("upload", 0) + userinfo.get("download", 0)
        if total:
            pct = min(100.0, used * 100.0 / total)
            print(f"Usage:       {used} / {total} bytes ({pct:.1f}%)")
        else:
            print(f"Usage:       {used} bytes (unlimited plan)")
        if "expire" in userinfo:
            print(f"Expires:     epoch {userinfo['expire']}")
    else:
        print("Usage:       (subscription provided no usage header)")
