"""Domain models for skill-bundle import — MVP, zero-I/O.

skills-lock.json v2 is the sole source of truth.
No skills.json, approvals, license, risk scanner, timestamps.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# ---------------------------------------------------------------------------
# URL parsing — GitHub HTTPS-only
# ---------------------------------------------------------------------------

_ACCEPTED_HOSTS: FrozenSet[str] = frozenset({"github.com", "raw.githubusercontent.com"})

_BLOB_TREE_RE = re.compile(
    r"^/([^/]+)/([^/]+)/(?:blob|tree)/([^/]+)(?:/(.+))?$"
)

_RAW_RE = re.compile(r"^/([^/]+)/([^/]+)/([^/]+)/(.+)$")

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ParsedGitHubURL:
    owner: str
    repo: str
    requested_ref: str
    directory: str
    full_url: str

    @property
    def slug(self) -> str: return f"{self.owner}/{self.repo}"
    @property
    def is_sha(self) -> bool: return bool(_SHA40_RE.match(self.requested_ref))


def parse_github_url(raw: str) -> ParsedGitHubURL:
    """Parse and validate a GitHub HTTPS skill URL.

    Accepted:
      - https://github.com/<owner>/<repo>/blob/<ref>/.../SKILL.md
      - https://github.com/<owner>/<repo>/tree/<ref>/<non-empty-path>
      - https://raw.githubusercontent.com/<owner>/<repo>/<ref>/.../SKILL.md
    """
    from urllib.parse import urlparse, unquote

    if not isinstance(raw, str): raise ValueError("URL must be a string")
    raw_stripped = raw.strip()
    if raw_stripped != raw: raise ValueError("URL has leading/trailing whitespace")
    parsed = urlparse(raw)

    if parsed.scheme != "https":
        raise ValueError(f"Only HTTPS URLs accepted, got scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host: raise ValueError("URL has no hostname")
    host_lower = host.lower()
    if host_lower not in _ACCEPTED_HOSTS:
        raise ValueError(f"Host {host!r} not accepted. Accepted: github.com, raw.githubusercontent.com")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must not contain credentials")
    if host_lower == "github.com":
        if parsed.query: raise ValueError("github.com URL must not contain query parameters")
        if parsed.fragment: raise ValueError("github.com URL must not contain fragment")
    if host_lower == "raw.githubusercontent.com":
        if parsed.query: raise ValueError("raw.githubusercontent.com URL must not contain query parameters")
        if parsed.fragment: raise ValueError("raw.githubusercontent.com URL must not contain fragment")

    path = unquote(parsed.path) if parsed.path else ""
    if "\x00" in path: raise ValueError("URL path contains NUL byte")
    if re.search(r"[\x00-\x1f\x7f]", path): raise ValueError("URL path contains control characters")
    if ".." in path.split("/"): raise ValueError("URL path contains traversal (..)")

    if host_lower == "github.com":
        m = _BLOB_TREE_RE.match(path)
        if not m:
            raise ValueError(f"github.com URL path must match /<owner>/<repo>/(blob|tree)/<ref>/<path>, got: {path!r}")
        owner, repo, ref, tail = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        if repo.endswith(".git"): repo = repo[:-4]
        is_blob = "/blob/" in path
        if not owner or not repo or not ref: raise ValueError("github.com URL has empty owner, repo, or ref")
        if is_blob:
            if not tail.endswith("/SKILL.md"):
                raise ValueError(f"Blob URL must end with /SKILL.md, got {tail.split('/')[-1]!r}")
            if tail == "SKILL.md": raise ValueError("Blob URL must include a containing directory")
            directory = "/".join(tail.split("/")[:-1])
        else:
            directory = tail
            if not directory: raise ValueError("Tree URL must specify a non-empty directory")
    else:  # raw
        m = _RAW_RE.match(path)
        if not m: raise ValueError(f"raw URL must match /<owner>/<repo>/<ref>/<path>, got: {path!r}")
        owner, repo, ref, full_path = m.group(1), m.group(2), m.group(3), m.group(4)
        if repo.endswith(".git"): repo = repo[:-4]
        if not owner or not repo or not ref or not full_path:
            raise ValueError("raw URL has empty owner, repo, ref, or path")
        if not full_path.endswith("/SKILL.md"):
            raise ValueError(f"raw URL must end with /SKILL.md, got {full_path.split('/')[-1]!r}")
        if full_path == "SKILL.md": raise ValueError("raw URL must include a containing directory")
        directory = "/".join(full_path.split("/")[:-1])

    if "/" in ref and not _SHA40_RE.match(ref):
        raise ValueError(f"Ambiguous ref {ref!r} contains '/'")
    for name, val in [("owner", owner), ("repo", repo)]:
        if not val: raise ValueError(f"URL has empty {name}")
        if "/" in val: raise ValueError(f"URL {name} {val!r} contains '/'")
        if re.search(r"[\x00-\x1f\x7f]", val): raise ValueError(f"URL {name} contains control chars")
        if val.startswith(".") or val.endswith("."): raise ValueError(f"URL {name} {val!r} has leading/trailing dot")

    return ParsedGitHubURL(owner=owner, repo=repo, requested_ref=ref, directory=directory, full_url=raw_stripped)


# ---------------------------------------------------------------------------
# Lock v2 types
# ---------------------------------------------------------------------------

_REQUIRED_ROOT_KEYS = frozenset({"version", "skills"})
_REQUIRED_ENTRY_KEYS = frozenset({
    "name", "source_url", "requested_ref", "resolved_commit",
    "directory", "owner", "repo", "files", "dependencies",
})
_REQUIRED_FILE_KEYS = frozenset({"path", "sha256", "size"})
_REQUIRED_DEP_OBJECT_KEYS = frozenset({"detected_references"})

_SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BACKSLASH_RE = re.compile(r"\\")
_UNSAFE_PATH_RE = re.compile(r"[\\:]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_RESERVED = frozenset({
    "CON","PRN","AUX","NUL","COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
    "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9",
})


@dataclass(frozen=True)
class SkillFileEntry:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class SkillLockEntryV2:
    name: str
    source_url: str
    requested_ref: str
    resolved_commit: str
    directory: str
    owner: str = ""
    repo: str = ""
    files: Tuple[SkillFileEntry, ...] = ()
    detected_references: FrozenSet[str] = frozenset()


@dataclass
class SkillLockV2:
    version: int = 2
    skills: Dict[str, SkillLockEntryV2] = field(default_factory=dict)
    def get(self, name: str) -> Optional[SkillLockEntryV2]: return self.skills.get(name)
    def __contains__(self, name: str) -> bool: return name in self.skills


# ---------------------------------------------------------------------------
# Validation / fetch types
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    skill_name: str = ""
    files: Tuple[SkillFileEntry, ...] = ()


@dataclass(frozen=True)
class ResolvedRef:
    requested_ref: str
    resolved_commit: str
    owner: str
    repo: str
    def __post_init__(self):
        if not _SHA40_RE.match(self.resolved_commit):
            raise ValueError(f"resolved_commit must be 40-char hex SHA, got {self.resolved_commit!r}")


@dataclass
class FetchedTree:
    commit: str
    files: Dict[str, bytes] = field(default_factory=dict)


@dataclass
class CheckResult:
    in_sync: bool = True
    drift_items: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Transaction error — carries primary, cleanup, committed flag
# ---------------------------------------------------------------------------

class TransactionError(Exception):
    def __init__(self, message: str, primary: BaseException,
                 cleanup_errors: Optional[List[str]] = None,
                 committed: bool = False):
        super().__init__(message)
        self.primary = primary
        self.cleanup_errors = cleanup_errors or []
        self.committed = committed
        self.__cause__ = primary


# ---------------------------------------------------------------------------
# Strict lock deserialization
# ---------------------------------------------------------------------------

def deserialize_lock_v2(data: bytes) -> SkillLockV2:
    """Parse v2 lock JSON with exhaustive shape validation."""
    try:
        raw = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid skills-lock.json v2 JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Lock root must be an object")
    _validate_lock_dict_keys(raw, _REQUIRED_ROOT_KEYS, frozenset({"version","skills"}), "root")
    if raw.get("version") != 2:
        raise ValueError(f"Expected version 2, got {raw.get('version')!r}")

    skills_raw = raw.get("skills", {})
    if not isinstance(skills_raw, dict):
        raise ValueError("'skills' must be an object")

    skills: Dict[str, SkillLockEntryV2] = {}
    for key_name, entry_raw in skills_raw.items():
        _validate_lock_key(key_name)
        if not isinstance(entry_raw, dict):
            raise ValueError(f"Entry {key_name!r} must be an object")
        skills[key_name] = _deserialize_entry_v2(key_name, entry_raw)
    return SkillLockV2(version=2, skills=skills)


def _validate_lock_dict_keys(d: dict, required: frozenset, allowed: frozenset, label: str) -> None:
    """Reject unknown keys and missing required keys."""
    extra = set(d) - allowed
    if extra:
        raise ValueError(f"{label} has unknown keys: {sorted(extra)}")
    missing = required - set(d)
    if missing:
        raise ValueError(f"{label} missing required keys: {sorted(missing)}")


def _validate_lock_key(name: str) -> None:
    if not name or not isinstance(name, str):
        raise ValueError(f"Lock key must be non-empty string, got {name!r}")
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(f"Lock key {name!r} must match [a-z0-9][a-z0-9_-]*")
    if len(name) > 64:
        raise ValueError(f"Lock key {name!r} exceeds 64 chars")


def _validate_safe_path_component(part: str, context: str) -> None:
    if not part: raise ValueError(f"{context}: empty path component")
    if part != part.rstrip(". "): raise ValueError(f"{context}: component {part!r} has trailing dot/space")
    if part.upper() in _WINDOWS_RESERVED: raise ValueError(f"{context}: component {part!r} is Windows reserved")


def _deserialize_entry_v2(key_name: str, raw: dict) -> SkillLockEntryV2:
    _validate_lock_dict_keys(raw, _REQUIRED_ENTRY_KEYS, _REQUIRED_ENTRY_KEYS, f"entry {key_name!r}")

    entry_name = raw.get("name")
    if not isinstance(entry_name, str) or not _SAFE_NAME_RE.match(entry_name):
        raise ValueError(f"Entry {key_name!r}: name must be canonical [a-z0-9_-]*")
    if len(entry_name) > 64:
        raise ValueError(f"Entry {key_name!r}: name exceeds 64 chars")
    if entry_name != key_name:
        raise ValueError(f"Entry key {key_name!r} != stored name {entry_name!r}")

    source_url = raw.get("source_url","")
    if not isinstance(source_url, str) or not source_url:
        raise ValueError(f"Entry {key_name!r}: source_url required")
    # Validate URL consistency
    try:
        parsed = parse_github_url(source_url)
    except ValueError as e:
        raise ValueError(f"Entry {key_name!r}: invalid source_url: {e}") from e

    requested_ref = raw.get("requested_ref","")
    if not isinstance(requested_ref, str) or not requested_ref:
        raise ValueError(f"Entry {key_name!r}: requested_ref required")

    resolved_commit = raw.get("resolved_commit","")
    if not isinstance(resolved_commit, str) or not re.match(r"^[0-9a-f]{40}$", resolved_commit):
        raise ValueError(f"Entry {key_name!r}: resolved_commit must be 40 lowercase hex")

    directory = raw.get("directory","")
    if not isinstance(directory, str):
        raise ValueError(f"Entry {key_name!r}: directory must be string")

    owner = raw.get("owner","")
    if not isinstance(owner, str): raise ValueError(f"Entry {key_name!r}: owner must be string")
    repo = raw.get("repo","")
    if not isinstance(repo, str): raise ValueError(f"Entry {key_name!r}: repo must be string")

    # Validate consistency with parsed URL
    if parsed.owner != owner or parsed.repo != repo or parsed.directory != directory:
        raise ValueError(f"Entry {key_name!r}: source_url ({source_url}) inconsistent with owner/repo/directory ({owner}/{repo}/{directory})")
    if parsed.requested_ref != requested_ref:
        raise ValueError(f"Entry {key_name!r}: source_url ref ({parsed.requested_ref}) != requested_ref ({requested_ref})")

    # --- Files ---
    files_raw = raw.get("files",[])
    if not isinstance(files_raw, list):
        raise ValueError(f"Entry {key_name!r}: files must be list")
    if not files_raw:
        raise ValueError(f"Entry {key_name!r}: files inventory must be non-empty")

    files: List[SkillFileEntry] = []
    seen_paths: Dict[str, str] = {}
    has_skill_md = False
    for i, f in enumerate(files_raw):
        if not isinstance(f, dict):
            raise ValueError(f"Entry {key_name!r}: file[{i}] must be object")
        _validate_lock_dict_keys(f, _REQUIRED_FILE_KEYS, _REQUIRED_FILE_KEYS, f"entry {key_name!r} file[{i}]")

        path = f["path"]
        if not isinstance(path, str) or not path:
            raise ValueError(f"Entry {key_name!r}: file[{i}] path required")
        if path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"Entry {key_name!r}: file[{i}] unsafe path {path!r}")
        if _BACKSLASH_RE.search(path): raise ValueError(f"Entry {key_name!r}: file[{i}] backslash in path")
        if _UNSAFE_PATH_RE.search(path): raise ValueError(f"Entry {key_name!r}: file[{i}] unsafe char in path")
        if _CONTROL_RE.search(path): raise ValueError(f"Entry {key_name!r}: file[{i}] control char in path")
        for part in path.split("/"):
            _validate_safe_path_component(part, f"entry {key_name!r} file[{i}]")

        folded = "/".join(p.lower() for p in path.split("/"))
        if folded in seen_paths:
            raise ValueError(f"Entry {key_name!r}: case-fold collision {path!r} vs {seen_paths[folded]!r}")
        seen_paths[folded] = path
        if path == "SKILL.md": has_skill_md = True

        sha256 = f["sha256"]
        if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
            raise ValueError(f"Entry {key_name!r}: file[{i}] sha256 must be 64 lowercase hex")
        size = f["size"]
        if not isinstance(size, int) or size < 0:
            raise ValueError(f"Entry {key_name!r}: file[{i}] size must be non-negative int")
        files.append(SkillFileEntry(path=path, sha256=sha256, size=size))

    if not has_skill_md:
        raise ValueError(f"Entry {key_name!r}: files must contain root SKILL.md")

    # --- Dependencies ---
    dep_raw = raw.get("dependencies",{})
    if not isinstance(dep_raw, dict):
        raise ValueError(f"Entry {key_name!r}: dependencies must be object")
    _validate_lock_dict_keys(dep_raw, _REQUIRED_DEP_OBJECT_KEYS, _REQUIRED_DEP_OBJECT_KEYS,
                             f"entry {key_name!r} dependencies")
    refs_raw = dep_raw.get("detected_references",[])
    if not isinstance(refs_raw, list):
        raise ValueError(f"Entry {key_name!r}: detected_references must be list")
    detected = set()
    for ref in refs_raw:
        if not isinstance(ref, str): raise ValueError(f"Entry {key_name!r}: dependency must be string")
        if not _SAFE_NAME_RE.match(ref): raise ValueError(f"Entry {key_name!r}: dependency {ref!r} not canonical")
        if ref in detected: raise ValueError(f"Entry {key_name!r}: duplicate dependency {ref!r}")
        detected.add(ref)

    return SkillLockEntryV2(name=entry_name, source_url=source_url, requested_ref=requested_ref,
        resolved_commit=resolved_commit, directory=directory, owner=owner, repo=repo,
        files=tuple(files), detected_references=frozenset(detected))

import json  # at end to avoid circular issues with parse_github_url which uses urllib
