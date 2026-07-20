"""Configuration source adapter — read-only discovery (S5.1).

Provides read-only source inventory and discovery.  Does NOT write secrets,
create directories, modify permissions, or connect to CLI.

Security:
* S5.1 only supports exact-path inventory with basic symlink rejection.
* Parent component race / Windows reparse → deferred to S5.3.
* Production discover_sources uses a fixed safe reader; tests use monkeypatch.
"""

from __future__ import annotations

import json as _json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from aisc.domain.config import (
    CredentialResult, CredentialStatus, PathPolicy, ProviderCatalog,
    ProviderSpec, ReasonCode, SourceDescriptor, StateEntry, StateIssue,
    LegacyStateReport, classify_credentials, is_valid_provider_id,
)
from aisc.schemas.config_schema import (
    merge_state, parse_api_keys, parse_raw_state_bytes, parse_settings,
)

# ---------------------------------------------------------------------------
# Fixed source inventory
# ---------------------------------------------------------------------------

def _build_source_inventory() -> List[SourceDescriptor]:
    return [
        SourceDescriptor("w-aisc-secrets-api-keys", "workspace",
            (".aisc", "secrets", "api-keys"), "api_keys"),
        SourceDescriptor("w-cc-config-api-keys", "workspace",
            (".cc-config", "api-keys"), "api_keys"),
        SourceDescriptor("w-claude-api-keys", "workspace",
            (".claude", "api-keys"), "api_keys"),
        SourceDescriptor("w-claude-settings", "workspace",
            (".claude", "settings.json"), "settings"),
        SourceDescriptor("r-aisc-state-env", "aisc_root",
            (".aisc", "state.env"), "state"),
        SourceDescriptor("r-deploy-state-env", "aisc_root",
            (".deploy", "state.env"), "state"),
    ]


# ---------------------------------------------------------------------------
# Root validation & source path resolution
# ---------------------------------------------------------------------------

def _resolve_source_path(desc: SourceDescriptor, policy: PathPolicy) -> Optional[Path]:
    if desc.root_kind == "workspace":
        root = policy.workspace
    else:
        root = policy.aisc_root
    if root is None:
        return None
    root_path = Path(os.path.abspath(root))
    try:
        st = os.lstat(root_path)
        if stat.S_ISLNK(st.st_mode):
            return None
    except OSError:
        return None
    # Reject relative escapes
    if ".." in desc.relative_parts or "." in desc.relative_parts:
        return None
    result = root_path.joinpath(*desc.relative_parts)
    return result


# ---------------------------------------------------------------------------
# Safe reader — rejects symlinks
# ---------------------------------------------------------------------------

def _safe_read(file_path: Path) -> bytes:
    """Read a file with safety checks: lstat, O_NOFOLLOW, fstat regular file."""
    try:
        st = os.lstat(file_path)
    except OSError:
        raise
    if stat.S_ISLNK(st.st_mode):
        raise OSError("Refusing to follow symlink")
    try:
        fd = os.open(str(file_path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise
    try:
        fd_st = os.fstat(fd)
        if not stat.S_ISREG(fd_st.st_mode):
            raise OSError("Not a regular file")
        return os.read(fd, 10 * 1024 * 1024)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Provider catalog loader (B11: strict, from bytes)
# ---------------------------------------------------------------------------

def load_provider_catalog(raw: bytes) -> ProviderCatalog:
    """Load and validate provider catalog from raw JSON bytes.

    Strict: every provider entry must have id, name, auth_type,
    auth_key_name, base_url with correct types.  Error messages never
    echo input keys or values.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("providers.json: invalid UTF-8")
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError:
        raise ValueError("providers.json: invalid JSON")
    if not isinstance(data, dict):
        raise ValueError("providers.json: not a JSON object")
    sv = data.get("schema_version")
    if isinstance(sv, bool) or not isinstance(sv, int) or sv != 1:
        raise ValueError("providers.json: invalid schema_version")
    providers_raw = data.get("providers")
    if not isinstance(providers_raw, dict) or not providers_raw:
        raise ValueError("providers.json: providers missing or empty")

    specs: Dict[str, ProviderSpec] = {}
    for key, entry in providers_raw.items():
        if not isinstance(entry, dict):
            raise ValueError("providers.json: provider entry not object")

        # id — required, string, must equal catalog key
        if "id" not in entry:
            raise ValueError("providers.json: missing id field")
        pid = entry["id"]
        if not isinstance(pid, str):
            raise ValueError("providers.json: id must be string")
        if pid != key:
            raise ValueError("providers.json: id does not match key")
        if not is_valid_provider_id(pid):
            raise ValueError("providers.json: invalid provider id format")

        # name — required, non-empty string
        if "name" not in entry:
            raise ValueError("providers.json: missing name field")
        name = entry["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("providers.json: name must be non-empty string")

        # auth_type — required, token or api_key
        if "auth_type" not in entry:
            raise ValueError("providers.json: missing auth_type field")
        auth_type = entry["auth_type"]
        if not isinstance(auth_type, str) or auth_type not in ("token", "api_key"):
            raise ValueError("providers.json: auth_type must be token or api_key")

        # auth_key_name — required, non-empty string
        if "auth_key_name" not in entry:
            raise ValueError("providers.json: missing auth_key_name field")
        auth_key_name = entry["auth_key_name"]
        if not isinstance(auth_key_name, str) or not auth_key_name.strip():
            raise ValueError("providers.json: auth_key_name must be non-empty string")

        # base_url — required field, string (allowed empty)
        if "base_url" not in entry:
            raise ValueError("providers.json: missing base_url field")
        base_url = entry["base_url"]
        if not isinstance(base_url, str):
            raise ValueError("providers.json: base_url must be string")

        # aliases — optional, list of strings
        raw_aliases = entry.get("aliases")
        aliases: Tuple[str, ...] = ()
        if isinstance(raw_aliases, list) and all(isinstance(a, str) for a in raw_aliases):
            aliases = tuple(raw_aliases)

        specs[key] = ProviderSpec(id=pid, name=name, auth_type=auth_type,
                                  auth_key_name=auth_key_name, base_url=base_url,
                                  aliases=aliases)
    return ProviderCatalog.build(specs, schema_version=sv)


# ---------------------------------------------------------------------------
# Source discovery — production API, fixed reader
# ---------------------------------------------------------------------------

def discover_sources(
    *, policy: PathPolicy, catalog: Optional[ProviderCatalog] = None,
) -> Tuple[List[CredentialResult], LegacyStateReport, Dict[str, str]]:
    """Read-only discovery of legacy sources.

    Production API uses the built-in _safe_read.  Test injection via monkeypatch
    of _safe_read or the _parse_* functions, not a reader callback parameter.
    """
    inventory = _build_source_inventory()
    secrets: List[CredentialResult] = []
    source_statuses: Dict[str, str] = {}
    aisc_raw: List[Tuple[str, str, str, int]] = []
    deploy_raw: List[Tuple[str, str, str, int]] = []
    aisc_issues: List[StateIssue] = []
    deploy_issues: List[StateIssue] = []

    for src in inventory:
        sid = src.source_id
        file_path = _resolve_source_path(src, policy)
        if file_path is None:
            source_statuses[sid] = "skipped:not_located"
            continue
        fp_str = str(file_path)
        try:
            raw = _safe_read(file_path)
        except FileNotFoundError:
            source_statuses[sid] = "missing"
            continue
        except PermissionError:
            source_statuses[sid] = "permission_denied"
            continue
        except OSError:
            source_statuses[sid] = "error"
            continue
        source_statuses[sid] = "ok"

        if src.source_type == "api_keys":
            parsed = parse_api_keys(raw, source_id=sid, source_path=fp_str, catalog=catalog)
            secrets.extend(parsed)
        elif src.source_type == "settings":
            parsed = parse_settings(raw, source_id=sid, source_path=fp_str, catalog=catalog)
            secrets.extend(parsed)
        elif src.source_type == "state":
            entries, issues = parse_raw_state_bytes(raw, source_label=src.relative_parts[0])
            if sid == "r-aisc-state-env":
                aisc_raw.extend(entries)
                aisc_issues.extend(issues)
            else:
                deploy_raw.extend(entries)
                deploy_issues.extend(issues)

    state_report = merge_state(aisc_raw, deploy_raw, aisc_issues, deploy_issues)
    classified = classify_credentials(secrets)
    return classified, state_report, source_statuses
