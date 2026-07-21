"""Provider catalog queries and user-defined provider management."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type
from urllib.parse import urlparse

from aisc.application.resources import locate_aisc_root, _RootSourceError
from aisc.domain.config import canonical_url, is_valid_provider_id


_AUTH_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


@dataclass
class ProviderListResult:
    data: Dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0
    error_code: str = ""
    error_message: str = ""


@dataclass
class ProviderShowResult:
    data: Dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0
    error_code: str = ""
    error_message: str = ""


@dataclass
class ProviderAddResult:
    data: Dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0
    error_code: str = ""
    error_message: str = ""


def user_provider_catalog_path(home: Optional[str] = None) -> Path:
    """Return the writable per-user catalog path."""
    home_path = Path(home).expanduser() if home is not None else Path.home()
    return home_path / ".aisc" / "providers.json"


def _base_catalog_path(root: Path) -> Path:
    """Resolve both the main-style and legacy develop catalog layouts."""
    current = root / "config" / "providers.json"
    if current.is_file():
        return current
    return root / "container" / "providers.json"


def _locate_root(explicit_root: Optional[str]) -> Tuple[Optional[Path], Optional[str]]:
    try:
        root = locate_aisc_root(explicit_root=explicit_root)
    except _RootSourceError as exc:
        return None, str(exc)
    if root is None:
        return None, (
            "AISC root not found. Use --aisc-root to specify a path, "
            "or run from within an AISC repository."
        )
    return root, None


def _read_catalog_document(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    from aisc.adapters.config_source import load_provider_catalog

    load_provider_catalog(raw)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("providers"), dict):
        raise ValueError("providers.json: invalid catalog object")
    return data


def _atomic_write_private(path: Path, data: bytes) -> None:
    """Atomically replace a private catalog without exposing partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.tmp"
    fd = -1
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise OSError("zero-progress catalog write")
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(str(tmp), str(path))
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def ensure_user_provider_catalog(
    explicit_root: Optional[str] = None,
    *,
    home: Optional[str] = None,
) -> Path:
    """Create the user catalog from the bundled catalog on first use."""
    root, error = _locate_root(explicit_root)
    if root is None:
        raise ValueError(error or "AISC root not found")
    target = user_provider_catalog_path(home)
    if target.is_file():
        _read_catalog_document(target)
        return target
    source = _base_catalog_path(root)
    document = _read_catalog_document(source)
    payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write_private(target, payload)
    return target


def _catalog_path_for_read(root: Path, home: Optional[str]) -> Path:
    user_path = user_provider_catalog_path(home)
    return user_path if user_path.is_file() else _base_catalog_path(root)


def _error_result(
    result_type: Type[Any], message: str, *, permission: bool = False, usage: bool = False,
) -> Any:
    return result_type(
        exit_code=9 if permission else (2 if usage else 1),
        error_code=("AISC_ERR_PERMISSION_DENIED" if permission else
                    "AISC_ERR_USAGE" if usage else "AISC_ERR_GENERAL"),
        error_message=message,
    )


def _load_for_result(
    result_type: Type[Any], explicit_root: Optional[str], home: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[Any]]:
    root, error = _locate_root(explicit_root)
    if root is None:
        return None, _error_result(result_type, error or "AISC root not found")
    path = _catalog_path_for_read(root, home)
    try:
        return _read_catalog_document(path), None
    except FileNotFoundError:
        return None, _error_result(result_type, f"Provider catalog not found: {path}")
    except PermissionError:
        return None, _error_result(result_type, f"Permission denied reading: {path}", permission=True)
    except (OSError, ValueError) as exc:
        return None, _error_result(result_type, f"Invalid provider catalog: {exc}")


def _public_provider(entry: Dict[str, Any], provider_id: str) -> Dict[str, Any]:
    return {
        "id": entry.get("id", provider_id),
        "name": entry.get("name", ""),
        "auth_type": entry.get("auth_type", ""),
        "auth_key_name": entry.get("auth_key_name", ""),
        "base_url": entry.get("base_url", ""),
        "aliases": list(entry.get("aliases") or []),
        "custom": bool(entry.get("custom", False)),
    }


def run_provider_list(
    explicit_root: Optional[str] = None, *, home: Optional[str] = None,
) -> ProviderListResult:
    document, error = _load_for_result(ProviderListResult, explicit_root, home)
    if error is not None:
        return error
    assert document is not None
    providers = document["providers"]
    return ProviderListResult(data={
        "schema_version": document["schema_version"],
        "providers": [_public_provider(providers[key], key) for key in sorted(providers)],
    })


def run_provider_show(
    name: str,
    explicit_root: Optional[str] = None,
    *,
    home: Optional[str] = None,
) -> ProviderShowResult:
    document, error = _load_for_result(ProviderShowResult, explicit_root, home)
    if error is not None:
        return error
    assert document is not None
    providers = document["providers"]
    entry = providers.get(name)
    provider_id = name
    if entry is None:
        for key, candidate in providers.items():
            if name in (candidate.get("aliases") or []):
                provider_id, entry = key, candidate
                break
    if entry is None:
        return _error_result(ProviderShowResult, f"Provider not found: {name}")
    return ProviderShowResult(data=_public_provider(entry, provider_id))


def _validate_add_input(
    *, provider_id: str, name: str, auth_type: str, auth_key_name: str,
    base_url: str, aliases: Sequence[str],
) -> Optional[str]:
    if not is_valid_provider_id(provider_id):
        return "Invalid provider id"
    if not name or not name.strip():
        return "Provider name must not be empty"
    if auth_type not in ("token", "api_key"):
        return "auth-type must be token or api_key"
    if not _AUTH_KEY_RE.fullmatch(auth_key_name or ""):
        return "Invalid auth key name"
    try:
        canonical_url(base_url)
    except (ValueError, TypeError):
        return "base-url must be a valid HTTP(S) URL without user info"
    if any(not is_valid_provider_id(alias) for alias in aliases):
        return "Every alias must use provider-id syntax"
    if len(set(aliases)) != len(aliases) or provider_id in aliases:
        return "Aliases must be unique and must not equal the provider id"
    return None


def run_provider_add(
    *,
    provider_id: str,
    name: str,
    auth_type: str,
    auth_key_name: str,
    base_url: str,
    aliases: Sequence[str] = (),
    model: str = "",
    default_opus: str = "",
    default_sonnet: str = "",
    default_haiku: str = "",
    subagent: str = "",
    effort: str = "",
    compact: str = "",
    overwrite: bool = False,
    explicit_root: Optional[str] = None,
    home: Optional[str] = None,
) -> ProviderAddResult:
    aliases = tuple(aliases)
    input_error = _validate_add_input(
        provider_id=provider_id, name=name, auth_type=auth_type,
        auth_key_name=auth_key_name, base_url=base_url, aliases=aliases,
    )
    if input_error:
        return _error_result(ProviderAddResult, input_error, usage=True)
    try:
        target = ensure_user_provider_catalog(explicit_root, home=home)
        document = _read_catalog_document(target)
    except PermissionError as exc:
        return _error_result(ProviderAddResult, f"Cannot write provider catalog: {exc}", permission=True)
    except (OSError, ValueError) as exc:
        return _error_result(ProviderAddResult, f"Cannot initialize provider catalog: {exc}")

    providers = document["providers"]
    existing = providers.get(provider_id)
    if existing is not None:
        if not overwrite:
            return _error_result(ProviderAddResult, f"Provider already exists: {provider_id}")
        if not existing.get("custom", False):
            return _error_result(ProviderAddResult, f"Built-in provider cannot be overwritten: {provider_id}")

    ignored_id = provider_id if existing is not None else None
    new_names = {provider_id, *aliases}
    wanted_url = canonical_url(base_url)
    for key, candidate in providers.items():
        if key == ignored_id:
            continue
        candidate_names = {key, *(candidate.get("aliases") or [])}
        if new_names & candidate_names:
            return _error_result(ProviderAddResult, "Provider id or alias conflicts with an existing provider")
        if candidate.get("auth_key_name") == auth_key_name:
            return _error_result(ProviderAddResult, "auth-key-name conflicts with an existing provider")
        candidate_url = candidate.get("base_url") or ""
        if candidate_url and canonical_url(candidate_url) == wanted_url:
            return _error_result(ProviderAddResult, "base-url conflicts with an existing provider")

    hostname = urlparse(base_url).hostname or provider_id
    entry = {
        "id": provider_id,
        "name": name.strip(),
        "aliases": list(aliases),
        "auth_type": auth_type,
        "auth_key_name": auth_key_name,
        "auth_prompt": name.strip(),
        "key_display": name.strip(),
        "base_url": base_url,
        "model": model,
        "default_opus": default_opus,
        "default_sonnet": default_sonnet,
        "default_haiku": default_haiku,
        "subagent": subagent,
        "effort": effort,
        "compact": compact,
        "clear_all": False,
        "url_fragment": hostname,
        "switch_msg": name.strip(),
        "help_desc": base_url,
        "custom": True,
    }
    providers[provider_id] = entry
    try:
        # Validate the merged document while retaining fields used by cs.
        from aisc.adapters.config_source import load_provider_catalog
        payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        load_provider_catalog(payload)
        _atomic_write_private(target, payload)
    except PermissionError as exc:
        return _error_result(ProviderAddResult, f"Cannot write provider catalog: {exc}", permission=True)
    except (OSError, ValueError) as exc:
        return _error_result(ProviderAddResult, f"Cannot write provider catalog: {exc}")
    return ProviderAddResult(data={
        "id": provider_id,
        "name": name.strip(),
        "catalog": str(target),
        "overwritten": existing is not None,
    })
