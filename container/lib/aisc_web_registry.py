#!/usr/bin/env python3
"""AISC web-service registry (container-side, svc-1).

Shared manifest logic for the ``aisc-web-expose`` / ``aisc-web-unexpose`` /
``aisc-web-list`` helpers and the ``aisc-web-gateway`` router: validation,
atomic writes, and fail-closed reads of ``/run/aisc/web-services/<port>.json``.

Contract: docs/plans/container-service-access/decisions.md (frozen svc-0).
The manifest never contains secrets — ports, labels and state only.

Environment overrides exist solely so host-side tests can exercise this
module outside a container:

- ``AISC_WEB_SERVICES_DIR`` (default ``/run/aisc/web-services``)
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "aisc.web-service/v1"
PORT_MIN = 1024
PORT_MAX = 65535
NAME_MAX = 64

_DECIMAL_RE = re.compile(r"^[0-9]+$")
# Manifest filenames are the port themselves; anything else is refused.
_SAFE_FILENAME_RE = re.compile(r"^[0-9]{4,5}\.json$")

DEFAULT_SERVICES_DIR = "/run/aisc/web-services"


class RegistryError(Exception):
    """Stable, user-facing registry failure (message is safe to print)."""


# ---------------------------------------------------------------------------
# Paths & validation
# ---------------------------------------------------------------------------

def services_dir() -> Path:
    return Path(os.environ.get("AISC_WEB_SERVICES_DIR") or DEFAULT_SERVICES_DIR)


def parse_port(text: str) -> int:
    """Strict decimal + range gate (decisions.md §5 helper contract)."""
    if not isinstance(text, str) or not _DECIMAL_RE.match(text):
        raise RegistryError(f"port must be a decimal integer: {text!r}")
    port = int(text)
    if not PORT_MIN <= port <= PORT_MAX:
        raise RegistryError(f"port out of range {PORT_MIN}..{PORT_MAX}: {port}")
    return port


def sanitize_name(name: Optional[str]) -> str:
    """Display-only label: strip, no control chars, <= 64 chars, empty OK."""
    if name is None:
        return ""
    stripped = str(name).strip()
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in stripped):
        raise RegistryError("service name must not contain control characters")
    if len(stripped) > NAME_MAX:
        raise RegistryError(f"service name longer than {NAME_MAX} characters")
    return stripped


def record_path(port: int) -> Path:
    if not PORT_MIN <= port <= PORT_MAX:
        raise RegistryError(f"port out of range {PORT_MIN}..{PORT_MAX}: {port}")
    return services_dir() / f"{port}.json"


# ---------------------------------------------------------------------------
# Read (fail closed) / write (atomic)
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode_record(data: Any, source: Path) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise RegistryError(f"malformed service record (not an object): {source.name}")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError(f"unsupported schema_version in {source.name}")
    port = data.get("port")
    if not isinstance(port, int) or isinstance(port, bool) \
            or not PORT_MIN <= port <= PORT_MAX:
        raise RegistryError(f"bad port in {source.name}")
    if data.get("state") != "registered":
        raise RegistryError(f"unsupported state in {source.name}")
    return data


def read_records(missing_ok: bool = False) -> Dict[int, Dict[str, Any]]:
    """Load all registrations, port -> record. Fail closed.

    Any unreadable directory or malformed/foreign-named file raises
    ``RegistryError`` — the gateway answers 503 AISC_WEB_REGISTRY_UNAVAILABLE
    rather than forwarding with an incomplete view. ``missing_ok=True``
    (helper ``list`` only) treats a not-yet-created directory as empty.
    """
    directory = services_dir()
    try:
        names = sorted(os.listdir(directory))
    except OSError as exc:
        if missing_ok and isinstance(exc, FileNotFoundError):
            return {}
        raise RegistryError(f"cannot read services dir: {exc}") from exc

    records: Dict[int, Dict[str, Any]] = {}
    for name in names:
        if not name.endswith(".json"):
            # Unrelated file (e.g. editor temp) — ignore but never execute it.
            continue
        if not _SAFE_FILENAME_RE.match(name):
            raise RegistryError(f"unsafe manifest filename: {name}")
        path = directory / name
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            raise RegistryError(f"malformed service record {name}: {exc}") from exc
        record = _decode_record(data, path)
        records[int(record["port"])] = record
    return records


def write_record(port: int, name: str) -> Dict[str, Any]:
    """Register (idempotent; re-register updates the label). Atomic write."""
    record = {
        "schema_version": SCHEMA_VERSION,
        "port": port,
        "protocol": "http",
        "name": sanitize_name(name),
        "state": "registered",
        "registered_at": _utc_now(),
        "pid": None,
    }
    directory = services_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass  # bind mounts may reject; registration still works
    fd, tmp = tempfile.mkstemp(prefix=f".{port}.", dir=str(directory), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, record_path(port))
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise RegistryError(f"failed to write service record: {exc}") from exc
    return record


def remove_record(port: int) -> bool:
    """Unregister; idempotent (missing record is success, per decisions §5)."""
    try:
        record_path(port).unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        raise RegistryError(f"failed to remove service record: {exc}") from exc


def list_records() -> List[Dict[str, Any]]:
    records = read_records()
    return [records[p] for p in sorted(records)]


# ---------------------------------------------------------------------------
# Helper CLIs (shared by the three thin executables)
# ---------------------------------------------------------------------------

def _usage_exit(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def main_expose(argv: List[str]) -> int:
    port_text: Optional[str] = None
    name = ""
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--name":
            i += 1
            if i >= len(argv):
                return _usage_exit("--name requires a value")
            name = argv[i]
        elif arg.startswith("--name="):
            name = arg[len("--name="):]
        elif port_text is None and not arg.startswith("-"):
            port_text = arg
        else:
            return _usage_exit(f"unexpected argument: {arg}")
        i += 1
    if port_text is None:
        return _usage_exit("usage: aisc-web-expose <port> [--name <label>]")
    try:
        port = parse_port(port_text)
        write_record(port, name)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f'aisc web service registered: port={port} name="{sanitize_name(name)}"')
    return 0


def main_unexpose(argv: List[str]) -> int:
    if len(argv) != 1 or argv[0].startswith("-"):
        return _usage_exit("usage: aisc-web-unexpose <port>")
    try:
        port = parse_port(argv[0])
        remove_record(port)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"aisc web service unregistered: port={port}")
    return 0


def main_list(argv: List[str]) -> int:
    if argv not in ([], ["--json"]):
        return _usage_exit("usage: aisc-web-list [--json]")
    as_json = argv == ["--json"]
    try:
        records = sorted(read_records(missing_ok=True).values(), key=lambda r: r["port"])
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    elif not records:
        print("(no web services registered; register with: aisc-web-expose <port>)")
    else:
        for r in records:
            print(f"{r['port']}  {r['protocol']}  {r['state']}  {r['name']}")
    return 0
