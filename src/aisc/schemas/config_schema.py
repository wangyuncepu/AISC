"""Config schema validation and legacy parsers (S5.1 Oracle ora-6 final)."""

from __future__ import annotations

import json as _json
import re
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from aisc.domain.config import (
    CredentialCandidate, CredentialResult, CredentialStatus, CredentialValue,
    IssueSeverity, ProviderCatalog, ProviderSpec, ReasonCode, SchemaIssue,
    StateEntry, StateIssue, LegacyStateReport,
    _FIXED_UNKNOWN_KEY_MARKER, _safe_key_display,
    canonical_url, is_valid_provider_id, parse_secret_ref,
)

# ---------------------------------------------------------------------------
# Config schema validation
# ---------------------------------------------------------------------------

ALLOWED_TOP_KEYS = frozenset({"schema_version", "provider", "defaults"})
ALLOWED_PROVIDER_KEYS = frozenset({"id", "auth"})
ALLOWED_AUTH_KEYS = frozenset({"secret_ref"})
ALLOWED_DEFAULTS_KEYS = frozenset({"profile", "network"})
ALLOWED_PROFILES = frozenset({"safe", "unsafe"})
ALLOWED_NETWORKS = frozenset({"direct", "proxy"})


def validate_config(data: Any, *, is_workspace: bool = False) -> List[SchemaIssue]:
    issues: List[SchemaIssue] = []
    if not isinstance(data, dict):
        issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="(root)",
            reason_code="config_not_object", message="Config must be a JSON object"))
        return issues

    sv = data.get("schema_version")
    if sv is None:
        issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="schema_version",
            reason_code="schema_version_missing", message="Missing required field"))
    elif isinstance(sv, bool) or not isinstance(sv, int):
        issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="schema_version",
            reason_code="schema_version_type", message="schema_version must be integer"))
    elif sv != 1:
        issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="schema_version",
            reason_code="schema_version_unsupported", message="Unsupported schema_version"))

    for key in data:
        if key not in ALLOWED_TOP_KEYS:
            issues.append(SchemaIssue(severity=IssueSeverity.WARNING, path="(root)",
                reason_code="unknown_key", message="Unknown key — preserved but ignored"))

    provider = data.get("provider")
    if provider is not None:
        if not isinstance(provider, dict):
            issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider",
                reason_code="provider_not_object", message="provider must be object"))
        else:
            _validate_provider(provider, issues, is_workspace)
    elif not is_workspace:
        pass  # provider is optional at top level

    defaults = data.get("defaults")
    if defaults is not None:
        if not isinstance(defaults, dict):
            issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="defaults",
                reason_code="defaults_not_object", message="defaults must be object"))
        else:
            _validate_defaults(defaults, issues)
    return issues


def _validate_provider(provider: Mapping, issues: List[SchemaIssue], is_workspace: bool):
    for key in provider:
        if key not in ALLOWED_PROVIDER_KEYS:
            issues.append(SchemaIssue(severity=IssueSeverity.WARNING, path="provider",
                reason_code="unknown_key", message="Unknown provider key"))
    pid = provider.get("id")
    if pid is None:
        issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider.id",
            reason_code="provider_id_missing", message="Missing provider.id"))
    elif not isinstance(pid, str):
        issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider.id",
            reason_code="provider_id_type", message="provider.id must be string"))
    elif not is_valid_provider_id(pid):
        issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider.id",
            reason_code="provider_id_invalid", message="Invalid provider id"))
    auth = provider.get("auth")
    if auth is not None:
        if not isinstance(auth, dict):
            issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider.auth",
                reason_code="auth_not_object", message="provider.auth must be object"))
        else:
            if is_workspace:
                issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider.auth",
                    reason_code="workspace_auth_forbidden", message="Workspace config must not have auth"))
            _validate_auth(auth, issues, pid if isinstance(pid, str) else "")
    elif not is_workspace:
        issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider.auth",
            reason_code="provider_auth_missing", message="User config must include auth.secret_ref"))


def _validate_auth(auth: Mapping, issues: List[SchemaIssue], provider_id: str):
    for key in auth:
        if key not in ALLOWED_AUTH_KEYS:
            issues.append(SchemaIssue(severity=IssueSeverity.WARNING, path="provider.auth",
                reason_code="unknown_key", message="Unknown auth key"))
    sr = auth.get("secret_ref")
    if sr is None:
        issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider.auth.secret_ref",
            reason_code="secret_ref_missing", message="Missing secret_ref"))
    elif not isinstance(sr, str):
        issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider.auth.secret_ref",
            reason_code="secret_ref_type", message="secret_ref must be string"))
    else:
        try:
            resolved = parse_secret_ref(sr)
            if provider_id and resolved != provider_id:
                issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider.auth.secret_ref",
                    reason_code="secret_ref_mismatch", message="secret_ref does not match provider.id"))
        except ValueError:
            issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="provider.auth.secret_ref",
                reason_code="secret_ref_invalid", message="Invalid secret_ref"))


def _validate_defaults(defaults: Mapping, issues: List[SchemaIssue]):
    for key in defaults:
        if key not in ALLOWED_DEFAULTS_KEYS:
            issues.append(SchemaIssue(severity=IssueSeverity.WARNING, path="defaults",
                reason_code="unknown_key", message="Unknown defaults key"))
    profile = defaults.get("profile")
    if profile is not None:
        if not isinstance(profile, str):
            issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="defaults.profile",
                reason_code="profile_type", message="profile must be string"))
        elif profile not in ALLOWED_PROFILES:
            issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="defaults.profile",
                reason_code="profile_invalid", message="Invalid profile"))
    network = defaults.get("network")
    if network is not None:
        if not isinstance(network, str):
            issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="defaults.network",
                reason_code="network_type", message="network must be string"))
        elif network not in ALLOWED_NETWORKS:
            issues.append(SchemaIssue(severity=IssueSeverity.ERROR, path="defaults.network",
                reason_code="network_invalid", message="Invalid network"))


# ---------------------------------------------------------------------------
# Legacy api-keys parser — byte-level, A1/A3/A6
# ---------------------------------------------------------------------------

def _split_lines_bytes(raw: bytes) -> List[bytes]:
    lines: List[bytes] = []
    for part in raw.split(b"\n"):
        if part.endswith(b"\r"):
            part = part[:-1]
        lines.append(part)
    return lines


def _validate_value_bytes(val: bytes) -> Optional[str]:
    if not val:
        return ReasonCode.MALFORMED_VALUE_EMPTY
    if b"\x00" in val:
        return ReasonCode.MALFORMED_VALUE_NUL
    if b"\r" in val or b"\n" in val:
        return ReasonCode.MALFORMED_VALUE_CRLF
    if val[:3] == b"\xef\xbb\xbf":
        return ReasonCode.MALFORMED_VALUE_BOM
    return None


def _is_empty_or_comment(view: bytes) -> bool:
    """Check if *view* is empty or starts with '#' (ASCII)."""
    stripped = view.lstrip()  # only left-strip for comment check
    return not stripped or stripped[:1] == b"#"


def parse_api_keys(
    raw: bytes, source_id: str, source_path: str, *,
    catalog: Optional[ProviderCatalog] = None,
) -> List[CredentialResult]:
    """Legacy api-keys byte-level parser.

    A1: Only left-strip line for empty/comment view; value is raw from first '='.
    A3: Duplicate-different → all candidates share same provider_id, all CONFLICT.
    """
    results: List[CredentialResult] = []
    auth_map = catalog.by_auth_key_name() if catalog else {}
    first_seen: Dict[str, Tuple[bytes, int]] = {}
    key_entries: Dict[str, List[CredentialResult]] = {}

    if raw.startswith(b"\xef\xbb\xbf"):
        results.append(CredentialResult(status=CredentialStatus.MALFORMED,
            reason_code=ReasonCode.MALFORMED_VALUE_BOM, message="File starts with BOM"))
        return results

    line_bytes_list = _split_lines_bytes(raw)
    for idx, line_bytes in enumerate(line_bytes_list):
        lineno = idx + 1
        if _is_empty_or_comment(line_bytes):
            continue

        eq_pos = line_bytes.find(b"=")
        if eq_pos < 0:
            results.append(CredentialResult(status=CredentialStatus.MALFORMED,
                reason_code=ReasonCode.MALFORMED_LINE, message=f"Line {lineno}: no '='"))
            continue

        key_bytes = line_bytes[:eq_pos]
        value_bytes = line_bytes[eq_pos + 1:]  # raw, no strip

        rejection = _validate_value_bytes(value_bytes)
        if rejection:
            results.append(CredentialResult(status=CredentialStatus.MALFORMED,
                reason_code=rejection, message=f"Line {lineno}: {rejection}"))
            continue

        try:
            key_str = key_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            results.append(CredentialResult(status=CredentialStatus.MALFORMED,
                reason_code=ReasonCode.MALFORMED_UTF8, message=f"Line {lineno}: invalid UTF-8"))
            continue

        try:
            value_bytes.decode("utf-8")
        except UnicodeDecodeError:
            results.append(CredentialResult(status=CredentialStatus.MALFORMED,
                reason_code=ReasonCode.MALFORMED_UTF8, message=f"Line {lineno}: invalid UTF-8 in value"))
            continue

        cv = CredentialValue(value_bytes)
        in_catalog = key_str in auth_map
        matches = auth_map.get(key_str, [])
        provider_id = matches[0].id if len(matches) == 1 else None
        status = CredentialStatus.OK if len(matches) == 1 else (CredentialStatus.UNMAPPED if len(matches) == 0 else CredentialStatus.UNMAPPED)
        rc = ReasonCode.OK if len(matches) == 1 else (ReasonCode.UNMAPPED if len(matches) == 0 else ReasonCode.UNMAPPED_AMBIGUOUS)

        cand = CredentialCandidate(source_id=source_id, value=cv, line_no=lineno)
        object.__setattr__(cand, "_src_path", source_path)
        object.__setattr__(cand, "_key", key_str)
        object.__setattr__(cand, "_from_cat", in_catalog)

        if key_str in first_seen:
            prev_val, _ = first_seen[key_str]
            status = CredentialStatus.DUPLICATE_DIFFERENT if cv._raw != prev_val else CredentialStatus.DUPLICATE_SAME
            rc = ReasonCode.DUPLICATE_DIFFERENT if cv._raw != prev_val else ReasonCode.DUPLICATE_SAME
            # A3: set provider_id from matches even on duplicate
            cand_provider = matches[0].id if len(matches) == 1 else None
        else:
            first_seen[key_str] = (cv._raw, lineno)
            cand_provider = provider_id

        r = CredentialResult(status=status, candidate=cand, provider_id=cand_provider,
            reason_code=rc, message=f"Line {lineno}")
        key_entries.setdefault(key_str, []).append(r)
        results.append(r)

    # Post-process
    for key_str, entries in key_entries.items():
        has_diff = any(e.status == CredentialStatus.DUPLICATE_DIFFERENT for e in entries)
        if has_diff:
            # A3: determine provider_id from first OK/UNMAPPED entry
            provider_id = None
            for e in entries:
                if e.provider_id:
                    provider_id = e.provider_id
                    break
            for e in entries:
                if e.status in (CredentialStatus.OK, CredentialStatus.DUPLICATE_SAME,
                                 CredentialStatus.DUPLICATE_DIFFERENT):
                    e.status = CredentialStatus.CONFLICT
                    e.reason_code = ReasonCode.CONFLICT
                    e.provider_id = provider_id
        else:
            for e in entries:
                if e.status == CredentialStatus.DUPLICATE_SAME:
                    e.status = CredentialStatus.AUDIT
                    e.reason_code = ReasonCode.AUDIT_DUPLICATE

    return results


# ---------------------------------------------------------------------------
# Legacy settings.json parser — A2: auth_type matching, B5
# ---------------------------------------------------------------------------

def parse_settings(
    raw: bytes, source_id: str, source_path: str, *,
    catalog: Optional[ProviderCatalog] = None,
) -> List[CredentialResult]:
    results: List[CredentialResult] = []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        results.append(CredentialResult(status=CredentialStatus.MALFORMED,
            reason_code=ReasonCode.MALFORMED_UTF8, message="Settings: invalid UTF-8"))
        return results
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError:
        results.append(CredentialResult(status=CredentialStatus.MALFORMED,
            reason_code=ReasonCode.MALFORMED_JSON, message="Settings: invalid JSON"))
        return results
    if not isinstance(data, dict):
        results.append(CredentialResult(status=CredentialStatus.MALFORMED,
            reason_code=ReasonCode.MALFORMED_JSON, message="Settings: not object"))
        return results
    env = data.get("env")
    if env is not None and not isinstance(env, dict):
        results.append(CredentialResult(status=CredentialStatus.MALFORMED,
            reason_code=ReasonCode.MALFORMED_ENV_TYPE, message="Settings.env: not object"))
        return results
    if not isinstance(env, dict):
        return results

    settings_base_url = env.get("ANTHROPIC_BASE_URL", "")
    token_raw = env.get("ANTHROPIC_AUTH_TOKEN")
    key_raw = env.get("ANTHROPIC_API_KEY")

    entries: List[Tuple[str, Any, str]] = []
    if token_raw is not None:
        entries.append(("token", token_raw, "ANTHROPIC_AUTH_TOKEN"))
    if key_raw is not None:
        entries.append(("api_key", key_raw, "ANTHROPIC_API_KEY"))

    candidates: List[Tuple[CredentialCandidate, str, str, Optional[str]]] = []
    for auth_type, raw_val, field_name in entries:
        if not isinstance(raw_val, str):
            results.append(CredentialResult(status=CredentialStatus.MALFORMED,
                reason_code=ReasonCode.MALFORMED_ENV_TYPE, message=f"Settings.{field_name}: not string"))
            continue
        if any(c in raw_val for c in ("\x00", "\r", "\n")):
            results.append(CredentialResult(status=CredentialStatus.MALFORMED,
                reason_code=ReasonCode.MALFORMED_VALUE_CRLF if "\r" in raw_val or "\n" in raw_val else ReasonCode.MALFORMED_VALUE_NUL,
                message=f"Settings.{field_name}: invalid char"))
            continue
        if not raw_val.strip():
            continue
        cv = CredentialValue(raw_val.encode("utf-8"))
        cand = CredentialCandidate(source_id=source_id, value=cv)
        object.__setattr__(cand, "_src_path", source_path)
        object.__setattr__(cand, "_key", field_name)
        object.__setattr__(cand, "_fname", field_name)
        object.__setattr__(cand, "_from_cat", False)
        providers = _match_settings_url(settings_base_url, catalog)
        # A2: filter by auth_type match to field
        matching = [p for p in providers if p.auth_type == auth_type]
        if len(matching) == 1:
            candidates.append((cand, auth_type, field_name, matching[0].id))
        else:
            candidates.append((cand, auth_type, field_name, None))

    if len(candidates) == 2:
        c1, at1, fn1, pid1 = candidates[0]
        c2, at2, fn2, pid2 = candidates[1]
        if c1.value._raw == c2.value._raw:
            # Same value: canonical by matching field
            if pid1 is not None and pid2 is None:
                _emit_settings(results, c1, pid1, CredentialStatus.OK, ReasonCode.OK)
                _emit_settings(results, c2, None, CredentialStatus.DUPLICATE_SAME, ReasonCode.DUPLICATE_SAME)
            elif pid2 is not None and pid1 is None:
                _emit_settings(results, c2, pid2, CredentialStatus.OK, ReasonCode.OK)
                _emit_settings(results, c1, None, CredentialStatus.DUPLICATE_SAME, ReasonCode.DUPLICATE_SAME)
            elif pid1 is not None and pid2 is not None:
                _emit_settings(results, c1, pid1, CredentialStatus.OK, ReasonCode.OK)
                _emit_settings(results, c2, pid2, CredentialStatus.DUPLICATE_SAME, ReasonCode.DUPLICATE_SAME)
            else:
                _emit_settings(results, c1, None, CredentialStatus.UNMAPPED, ReasonCode.UNMAPPED)
                _emit_settings(results, c2, None, CredentialStatus.UNMAPPED, ReasonCode.UNMAPPED)
        else:
            _emit_settings(results, c1, pid1, CredentialStatus.CONFLICT, ReasonCode.CONFLICT)
            _emit_settings(results, c2, pid2, CredentialStatus.CONFLICT, ReasonCode.CONFLICT)
    elif len(candidates) == 1:
        c, at, fn, pid = candidates[0]
        url_providers = _match_settings_url(settings_base_url, catalog)
        if pid is not None:
            _emit_settings(results, c, pid, CredentialStatus.OK, ReasonCode.OK)
        else:
            _emit_settings(results, c, None, CredentialStatus.UNMAPPED,
                          ReasonCode.UNMAPPED_AUTH_TYPE if url_providers else ReasonCode.UNMAPPED)

    return results


def _emit_settings(results, cand, pid, status, rc):
    results.append(CredentialResult(status=status, candidate=cand, provider_id=pid,
        reason_code=rc, message=f"Settings credential"))


def _match_settings_url(base_url: str, catalog: Optional[ProviderCatalog]) -> List[ProviderSpec]:
    if not catalog or not base_url:
        return []
    try:
        can = canonical_url(base_url)
    except ValueError:
        return []
    return catalog.by_base_url().get(can, [])


# ---------------------------------------------------------------------------
# Legacy state parser — A5: strict models, no raw key/value in issues
# ---------------------------------------------------------------------------

_STATE_KEYS = frozenset({"IMAGE", "PROXY_ENABLED", "CONTAINER_NAME"})


def parse_raw_state_bytes(raw: bytes, source_label: str) -> Tuple[List[Tuple[str, str, str, int]], List[StateIssue]]:
    entries: List[Tuple[str, str, str, int]] = []
    issues: List[StateIssue] = []
    lines = _split_lines_bytes(raw)
    for idx, line_bytes in enumerate(lines):
        lineno = idx + 1
        if _is_empty_or_comment(line_bytes):
            continue
        if b"=" not in line_bytes:
            issues.append(StateIssue(source=source_label, line_no=lineno,
                reason_code="malformed_line", message="No '=' separator"))
            continue
        eq_pos = line_bytes.find(b"=")
        try:
            key = line_bytes[:eq_pos].decode("utf-8").strip()
        except UnicodeDecodeError:
            issues.append(StateIssue(source=source_label, line_no=lineno,
                reason_code="malformed_utf8", message="Invalid UTF-8"))
            continue
        value_bytes = line_bytes[eq_pos + 1:]
        try:
            value = value_bytes.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(StateIssue(source=source_label, line_no=lineno,
                reason_code="malformed_utf8", message="Invalid UTF-8 in value"))
            continue

        # Validate
        if key not in _STATE_KEYS:
            issues.append(StateIssue(source=source_label, line_no=lineno,
                reason_code="unknown_key", message="Unknown state key"))
            continue
        if key == "PROXY_ENABLED" and value not in ("0", "1"):
            issues.append(StateIssue(source=source_label, line_no=lineno,
                reason_code="proxy_enabled_invalid", message="PROXY_ENABLED must be 0 or 1"))
            continue
        if key in ("IMAGE", "CONTAINER_NAME") and not value.strip():
            issues.append(StateIssue(source=source_label, line_no=lineno,
                reason_code="empty_value", message="Value must not be empty"))
            continue
        entries.append((key, value, source_label, lineno))
    return entries, issues


def merge_state(
    aisc_entries: List[Tuple[str, str, str, int]],
    deploy_entries: List[Tuple[str, str, str, int]],
    aisc_issues: List[StateIssue],
    deploy_issues: List[StateIssue],
) -> LegacyStateReport:
    """Merge .aisc and .deploy state.

    A5: same-source duplicate → last-one-wins, earlier marked shadowed.
    Returns LegacyStateReport with effective, all_entries, issues.
    """
    def _dedup_source(entries: List[Tuple[str, str, str, int]], source: str) -> List[StateEntry]:
        seen: Dict[str, list] = {}
        for key, val, src, lineno in entries:
            seen.setdefault(key, []).append((key, val, src, lineno))
        result: List[StateEntry] = []
        for key, occurrences in seen.items():
            if len(occurrences) == 1:
                k, v, s, l = occurrences[0]
                result.append(StateEntry(key=k, value=v, source=s, line_no=l))
            else:
                # Last-one-wins, earlier shadowed
                for i, (k, v, s, l) in enumerate(occurrences):
                    shadowed = (i < len(occurrences) - 1)
                    result.append(StateEntry(key=k, value=v, source=s, line_no=l, shadowed=shadowed))
        return result

    aisc_deduped = _dedup_source(aisc_entries, ".aisc")
    deploy_deduped = _dedup_source(deploy_entries, ".deploy")

    effective: Dict[str, StateEntry] = {}
    all_known: List[StateEntry] = list(deploy_deduped)
    # Deploy: last-one-wins within source (overwrite, not setdefault)
    for e in deploy_deduped:
        effective[e.key] = e
    for e in aisc_deduped:
        all_known.append(e)
        if e.key in effective:
            for de in deploy_deduped:
                if de.key == e.key:
                    de.shadowed = True
        effective[e.key] = e

    eff = sorted(effective.values(), key=lambda e: e.key)
    all_e = sorted(all_known, key=lambda e: (e.key, 0 if e.source == ".deploy" else 1))
    all_issues = list(aisc_issues) + list(deploy_issues)
    return LegacyStateReport(effective=eff, all_entries=all_e, issues=all_issues)
