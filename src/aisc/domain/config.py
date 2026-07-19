"""Domain models for configuration, secrets, and source discovery (S5.1).

All models are pure — zero I/O.
Secret-bearing types use ``__slots__`` with opaque storage; all representations are redacted.
No ``__hash__`` on secret types.  ``CredentialValue`` rejects pickle.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlparse, urlunparse

# ---------------------------------------------------------------------------
# Provider ID grammar
# ---------------------------------------------------------------------------

_PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_FORBIDDEN_SUBSTRINGS = ("/", "\\", "..")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def is_valid_provider_id(raw: str) -> bool:
    if not isinstance(raw, str) or not raw:
        return False
    if not _PROVIDER_ID_RE.match(raw):
        return False
    if any(bad in raw for bad in _FORBIDDEN_SUBSTRINGS):
        return False
    if _CONTROL_CHARS_RE.search(raw):
        return False
    if raw.endswith(".") or raw.endswith(" "):
        return False
    return True


# ---------------------------------------------------------------------------
# Secret reference
# ---------------------------------------------------------------------------

_SECRET_REF_RE = re.compile(r"^provider:([a-z0-9][a-z0-9._-]{0,63})$")


def parse_secret_ref(raw: str) -> str:
    if not isinstance(raw, str):
        raise ValueError("secret_ref must be a string")
    m = _SECRET_REF_RE.match(raw)
    if not m:
        raise ValueError("secret_ref must be exactly 'provider:<provider_id>'")
    provider_id = m.group(1)
    if any(bad in provider_id for bad in _FORBIDDEN_SUBSTRINGS):
        raise ValueError("secret_ref contains forbidden characters")
    if _CONTROL_CHARS_RE.search(provider_id):
        raise ValueError("secret_ref contains control characters")
    if provider_id.endswith(".") or provider_id.endswith(" "):
        raise ValueError("secret_ref has trailing dot or space")
    return provider_id


# ---------------------------------------------------------------------------
# Path policy — with root validation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlatformPathConfig:
    config_dir: str
    state_dir: str
    secrets_dir: str


def _validate_absolute_root(name: str, value: Optional[str]) -> Optional[str]:
    """Validate a root path: must be None or absolute non-empty non-relative."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped != value:
        raise ValueError(f"{name} has leading/trailing whitespace")
    if not value:
        raise ValueError(f"{name} must not be empty")
    import os
    if not os.path.isabs(value):
        raise ValueError(f"{name} must be an absolute path")
    return value


@dataclass(frozen=True)
class PathPolicy:
    """All known directory roots for config/state/secret discovery.

    Construction rejects empty/relative/whitespace-padded roots.
    Root symlink policy: S5.1 rejects root symlinks (fail-closed).
    """
    platform: PlatformPathConfig
    workspace: Optional[str] = None
    aisc_root: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "workspace",
                           _validate_absolute_root("workspace", self.workspace))
        object.__setattr__(self, "aisc_root",
                           _validate_absolute_root("aisc_root", self.aisc_root))


# ---------------------------------------------------------------------------
# Credential value — opaque, no leaking, no pickle
# ---------------------------------------------------------------------------

class CredentialValue:
    """Opaque credential value.

    * ``__slots__`` — no ``__dict__``.
    * No ``__hash__``.
    * ``__str__`` / ``__repr__`` always redacted.
    * ``__reduce_ex__`` raises to prevent accidental pickle.
    * ``same_value()`` uses constant-time comparison.
    * ``_reveal_for_io()`` is the only path to raw bytes (internal/IO only).
    """
    __slots__ = ("_raw",)

    def __init__(self, raw: bytes) -> None:
        self._raw: bytes = raw

    def _reveal_for_io(self) -> bytes:
        """Internal: return raw bytes (use only for I/O)."""
        return self._raw

    def same_value(self, other: CredentialValue) -> bool:
        """Constant-time comparison with *other*."""
        if not isinstance(other, CredentialValue):
            return False
        return hmac.compare_digest(self._raw, other._raw)

    def to_safe_dict(self) -> Dict[str, str]:
        return {"redacted": "****"}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CredentialValue):
            return NotImplemented
        return hmac.compare_digest(self._raw, other._raw)

    def __deepcopy__(self, memo=None):
        return CredentialValue(self._raw)

    def __reduce_ex__(self, protocol):  # type: ignore[override]
        raise TypeError("CredentialValue is not picklable")

    def __str__(self) -> str:
        return "****"

    def __repr__(self) -> str:
        return "CredentialValue('****')"

    def __hash__(self):  # type: ignore[override]
        raise TypeError("unhashable type: CredentialValue")


# ---------------------------------------------------------------------------
# Credential candidate — controlled repr, no arbitrary key_name/path
# ---------------------------------------------------------------------------

_FIXED_UNKNOWN_KEY_MARKER = "inline_key"


def _safe_key_display(key_name: str, field_name: str = "",
                      from_catalog: bool = False, source_type: str = "") -> str:
    """Return a controlled display for key_name/field_name.

    * If *from_catalog* is True, the key is a known auth_key_name and may be shown.
    * If *field_name* is one of the known settings fields, show that.
    * Otherwise, return the fixed marker.
    """
    if field_name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
        return field_name
    if from_catalog:
        return key_name
    return _FIXED_UNKNOWN_KEY_MARKER


@dataclass
class CredentialCandidate:
    """A single credential read from a source file.

    source_id, value, line_no are dataclass fields visible to asdict.
    Internal _source_path, _key_name, _field_name, _from_catalog are stored
    as non-field attributes (not visible to dataclasses.asdict).
    """
    source_id: str
    value: CredentialValue = field(default_factory=lambda: CredentialValue(b""))
    line_no: int = 0

    def __post_init__(self):
        # Non-field internal attributes (hidden from asdict)
        object.__setattr__(self, "_src_path", "")
        object.__setattr__(self, "_key", "")
        object.__setattr__(self, "_fname", "")
        object.__setattr__(self, "_from_cat", False)

    @property
    def display_key(self) -> str:
        return _safe_key_display(self._key, self._fname, self._from_cat)

    def __repr__(self) -> str:
        return (
            f"CredentialCandidate(source_id={self.source_id!r},"
            f" line={self.line_no}"
            f"{'' if not self._fname else ', field=' + self._fname!r}"
            f", value={self.value!r})"
        )

    def __str__(self) -> str:
        return repr(self)


# ---------------------------------------------------------------------------
# Credential result status
# ---------------------------------------------------------------------------

class ReasonCode:
    OK = "ok"
    MALFORMED_LINE = "malformed_line"
    MALFORMED_UTF8 = "malformed_utf8"
    MALFORMED_JSON = "malformed_json"
    MALFORMED_ENV_TYPE = "malformed_env_type"
    MALFORMED_VALUE_NUL = "malformed_value_nul"
    MALFORMED_VALUE_CRLF = "malformed_value_crlf"
    MALFORMED_VALUE_EMPTY = "malformed_value_empty"
    MALFORMED_VALUE_BOM = "malformed_value_bom"
    DUPLICATE_SAME = "duplicate_same"
    DUPLICATE_DIFFERENT = "duplicate_different"
    UNMAPPED = "unmapped"
    UNMAPPED_AMBIGUOUS = "unmapped_ambiguous"
    UNMAPPED_AUTH_TYPE = "unmapped_auth_type"
    CONFLICT = "conflict"
    ALREADY_CURRENT = "already_current"
    SKIPPED_NOT_LOCATED = "skipped:not_located"
    AUDIT_DUPLICATE = "audit_duplicate"


class CredentialStatus(str, Enum):
    OK = "ok"
    MALFORMED = "malformed"
    DUPLICATE_SAME = "duplicate_same"
    DUPLICATE_DIFFERENT = "duplicate_different"
    UNMAPPED = "unmapped"
    CONFLICT = "conflict"
    ALREADY_CURRENT = "already_current"
    SKIPPED_NOT_LOCATED = "skipped:not_located"
    AUDIT = "audit"


@dataclass
class CredentialResult:
    status: CredentialStatus
    candidate: Optional[CredentialCandidate] = None
    provider_id: Optional[str] = None
    reason_code: str = ""
    message: str = ""

    def __repr__(self) -> str:
        pid = self.provider_id or "-"
        return f"CredentialResult(status={self.status.value!r}, provider_id={pid!r}, reason_code={self.reason_code!r})"

    def to_summary(self) -> Dict[str, Any]:
        return {"status": self.status.value, "reason_code": self.reason_code,
                "provider_id": self.provider_id, "message": self.message}


# ---------------------------------------------------------------------------
# Credential classifier — cross-source aggregation
# ---------------------------------------------------------------------------

def classify_credentials(results: List[CredentialResult]) -> List[CredentialResult]:
    """Classify credentials across all sources.

    If any entry in a provider group is already CONFLICT, the entire group
    stays CONFLICT (no downgrade to OK/AUDIT).
    """
    groups: Dict[str, List[CredentialResult]] = {}
    for r in results:
        pid = r.provider_id
        if pid and r.candidate and r.status in (CredentialStatus.OK, CredentialStatus.CONFLICT):
            groups.setdefault(pid, []).append(r)

    classified: List[CredentialResult] = []
    for pid, entries in groups.items():
        if any(e.status == CredentialStatus.CONFLICT for e in entries):
            for e in entries:
                classified.append(CredentialResult(status=CredentialStatus.CONFLICT,
                    candidate=e.candidate, provider_id=pid,
                    reason_code=ReasonCode.CONFLICT,
                    message="Conflict — different values for same provider"))
        else:
            # Compare explicitly without sets (CredentialValue has no hash)
            multi = False
            raw0 = entries[0].candidate.value._raw if entries else None
            for e in entries[1:]:
                if e.candidate and e.candidate.value._raw != raw0:
                    multi = True
                    break
            if multi:
                for e in entries:
                    classified.append(CredentialResult(status=CredentialStatus.CONFLICT,
                        candidate=e.candidate, provider_id=pid,
                        reason_code=ReasonCode.CONFLICT,
                        message="Different secret values for same provider"))
            else:
                for i, e in enumerate(entries):
                    if i == 0:
                        classified.append(CredentialResult(status=CredentialStatus.OK,
                            candidate=e.candidate, provider_id=pid, reason_code=ReasonCode.OK,
                            message="Canonical credential"))
                    else:
                        classified.append(CredentialResult(status=CredentialStatus.AUDIT,
                            candidate=e.candidate, provider_id=pid,
                            reason_code=ReasonCode.AUDIT_DUPLICATE,
                            message="Duplicate identical credential (audit)"))

    for r in results:
        pid = r.provider_id
        if pid and pid in groups and r.status in (CredentialStatus.OK, CredentialStatus.CONFLICT):
            continue
        classified.append(r)
    return classified


# ---------------------------------------------------------------------------
# Provider spec & catalog
# ---------------------------------------------------------------------------

_AUTH_TYPE_VALUES = frozenset({"token", "api_key"})
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _is_safe_env_key(name: str) -> bool:
    return bool(name) and bool(_ENV_KEY_RE.match(name)) and len(name) <= 128


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    auth_type: str
    auth_key_name: str
    base_url: str = ""
    aliases: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderCatalog:
    _providers: Mapping[str, ProviderSpec]
    schema_version: int = 1

    @property
    def providers(self) -> Mapping[str, ProviderSpec]:
        return self._providers

    @classmethod
    def build(cls, providers: Dict[str, ProviderSpec], schema_version: int = 1) -> ProviderCatalog:
        if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != 1:
            raise ValueError("schema_version invalid")
        if not providers:
            raise ValueError("no providers")
        for key, spec in providers.items():
            if not is_valid_provider_id(key):
                raise ValueError("invalid provider id")
            if spec.id != key:
                raise ValueError("provider id mismatch")
            if spec.auth_type not in _AUTH_TYPE_VALUES:
                raise ValueError("invalid auth_type")
            if not _is_safe_env_key(spec.auth_key_name):
                raise ValueError("invalid auth_key_name")
            if not isinstance(spec.base_url, str):
                raise ValueError("base_url type")
        auth_counts: Dict[str, List[str]] = {}
        for key, spec in providers.items():
            auth_counts.setdefault(spec.auth_key_name, []).append(key)
        for ak, pids in auth_counts.items():
            if len(pids) > 1:
                raise ValueError("duplicate auth_key_name")
        url_counts: Dict[str, List[str]] = {}
        for key, spec in providers.items():
            if spec.base_url:
                c = canonical_url(spec.base_url)
                url_counts.setdefault(c, []).append(key)
        for url, pids in url_counts.items():
            if len(pids) > 1:
                raise ValueError("duplicate canonical base_url")
        return cls(_providers=MappingProxyType(dict(providers)), schema_version=schema_version)

    def by_auth_key_name(self) -> Dict[str, List[ProviderSpec]]:
        result: Dict[str, List[ProviderSpec]] = {}
        for p in self._providers.values():
            result.setdefault(p.auth_key_name, []).append(p)
        return result

    def by_base_url(self) -> Dict[str, List[ProviderSpec]]:
        result: Dict[str, List[ProviderSpec]] = {}
        for p in self._providers.values():
            if p.base_url:
                result.setdefault(canonical_url(p.base_url), []).append(p)
        return result


# ---------------------------------------------------------------------------
# URL canonicalization
# ---------------------------------------------------------------------------

def canonical_url(raw: str) -> str:
    """Normalize API base URL: lowercase scheme/hostname, strip default ports,
    add trailing slash to *path only*, preserve path/query/fragment case."""
    if not raw:
        return raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("unsupported scheme")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("missing hostname")
    if parsed.username is not None:
        raise ValueError("userinfo forbidden")
    port = parsed.port
    scheme = parsed.scheme.lower()
    if ":" in hostname:
        netloc = f"[{hostname.lower()}]"
    else:
        netloc = hostname.lower()
    if not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        if port is not None:
            netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, parsed.fragment))


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    id: str
    auth: Optional[ProviderAuthConfig] = None

@dataclass
class ProviderAuthConfig:
    secret_ref: str = ""

@dataclass
class DefaultsConfig:
    profile: str = "safe"
    network: str = "direct"

@dataclass
class ConfigV1:
    schema_version: int = 1
    provider: Optional[ProviderConfig] = None
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    _extra_keys: Dict[str, Any] = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Source inventory
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceDescriptor:
    source_id: str
    root_kind: str
    relative_parts: Tuple[str, ...]
    source_type: str
    description: str = ""


# ---------------------------------------------------------------------------
# Schema issues
# ---------------------------------------------------------------------------

class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"

@dataclass
class SchemaIssue:
    severity: IssueSeverity
    path: str = ""
    reason_code: str = ""
    message: str = ""

    def __repr__(self) -> str:
        return f"{self.severity.value.upper()}: {self.path} [{self.reason_code}] — {self.message}"


# ---------------------------------------------------------------------------
# Legacy state — entries and diagnostic issues
# ---------------------------------------------------------------------------

@dataclass
class StateEntry:
    """A valid, known legacy state key-value pair (internal value ok, safe repr)."""
    key: str
    value: str = field(repr=False)
    source: str
    line_no: int = 0
    shadowed: bool = False

    def __repr__(self) -> str:
        return f"StateEntry(key={self.key!r}, source={self.source!r}, line={self.line_no})"

    def to_summary(self) -> Dict[str, Any]:
        return {"key": self.key, "source": self.source, "line_no": self.line_no,
                "shadowed": self.shadowed}


@dataclass
class StateIssue:
    """A diagnostic issue for unknown/malformed state lines (no raw data stored)."""
    source: str
    line_no: int
    reason_code: str
    message: str = ""

    def __repr__(self) -> str:
        return f"StateIssue(source={self.source!r}, line={self.line_no}, reason_code={self.reason_code!r})"


@dataclass
class LegacyStateReport:
    """Read-only report of legacy state files.

    *effective*: winning known entries (.aisc > .deploy), last-one-wins per source.
    *all_entries*: every known entry including shadowed.
    *issues*: diagnostic StateIssue for unknown/malformed/invalid lines.
    """
    effective: List[StateEntry] = field(default_factory=list)
    all_entries: List[StateEntry] = field(default_factory=list)
    issues: List[StateIssue] = field(default_factory=list)
