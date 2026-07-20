"""Skill validator — tree validation and dependency scanning for MVP.

All pure functions operating on in-memory data.
No license detection, no risk scanning, no approvals.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

from aisc.domain.skill_models import (
    FetchedTree,
    SkillFileEntry,
    ValidationResult,
)


@dataclass(frozen=True)
class ValidationLimits:
    """Configurable size/count limits for skill tree validation."""
    max_files: int = 100
    max_total_bytes: int = 5 * 1024 * 1024  # 5 MiB
    max_file_bytes: int = 1 * 1024 * 1024   # 1 MiB


_FORBIDDEN_PATH_COMPONENTS = frozenset({".git", "__pycache__", ".gitmodules"})
_LFS_POINTER_SIGNATURE = b"version https://git-lfs.github.com/spec/v1"
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_BACKSLASH_RE = re.compile(r"\\")
# Reject backslash, colon (Windows drive/ADS), trailing dot/space in any path component
_UNSAFE_PATH_CHARS_RE = re.compile(r"[\\:]")
_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_NAME_KEY_RE = re.compile(r"^name:\s*(.+)$", re.MULTILINE)

_SLASH_CMD_RE = re.compile(r"(?:^|\s)/([a-zA-Z][a-zA-Z0-9_-]*)\b")

_NON_SKILL_COMMANDS: FrozenSet[str] = frozenset({
    "help", "clear", "compact", "context", "cost",
    "doctor", "init", "login", "logout", "mcp",
    "memory", "ide", "terminal", "todo", "status",
    "bashes", "bug", "config", "permissions",
    "add-dir", "agents", "output-style", "pr-comments",
    "upgrade", "quit", "reset", "resume",
})


# ---------------------------------------------------------------------------
# SKILL.md frontmatter
# ---------------------------------------------------------------------------

def parse_skill_name(frontmatter_content: bytes) -> str:
    """Extract skill name from SKILL.md YAML frontmatter (regex, non-executing)."""
    try:
        text = frontmatter_content.decode("utf-8", errors="replace")
    except Exception:
        return ""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return ""
    frontmatter = m.group(1)
    name_m = _NAME_KEY_RE.search(frontmatter)
    if not name_m:
        return ""
    name = name_m.group(1).strip()
    if len(name) >= 2 and name[0] == name[-1] and name[0] in ('"', "'"):
        name = name[1:-1]
    # Safe name check
    if _CONTROL_RE.search(name) or "\x00" in name:
        return ""
    if "/" in name or ".." in name:
        return ""
    return name


def normalize_skill_name(name: str) -> str:
    """Validate a skill name against canonical safe pattern.

    Only accepts names matching ``[a-z0-9][a-z0-9_-]*`` (1-64 chars).
    Rejects names that need silent transformation (spaces, uppercase, special chars).
    This prevents collision between ``foo bar`` and ``foo-bar``.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("Skill name must be non-empty string")
    if len(name) > 64:
        raise ValueError(f"Skill name exceeds 64 characters: {name!r}")
    if not re.match(r'^[a-z0-9][a-z0-9_-]*$', name):
        raise ValueError(
            f"Skill name {name!r} does not match required pattern "
            f"[a-z0-9][a-z0-9_-]*. Supply a canonical name."
        )
    return name


# ---------------------------------------------------------------------------
# Tree validation
# ---------------------------------------------------------------------------

def validate_tree(
    tree: FetchedTree,
    limits: Optional[ValidationLimits] = None,
) -> ValidationResult:
    """Validate a fetched skill tree before materialization.

    Checks:
      - Exactly one root SKILL.md
      - All paths safe (no traversal, absolute, control, .git, LFS)
      - File count / total size / per-file size within limits
      - Extracts skill name from frontmatter
    """
    limits = limits or ValidationLimits()
    result = ValidationResult()

    files_dict = tree.files

    # Check SKILL.md
    skill_md_content = files_dict.get("SKILL.md")
    if skill_md_content is None:
        result.valid = False
        result.errors.append("Missing root SKILL.md in fetched tree")
        return result

    skill_name = parse_skill_name(skill_md_content)
    result.skill_name = skill_name
    if not skill_name:
        result.valid = False
        result.errors.append("Could not parse skill name from SKILL.md frontmatter")
        return result

    # File count
    if len(files_dict) > limits.max_files:
        result.valid = False
        result.errors.append(f"Too many files: {len(files_dict)} > {limits.max_files}")

    total_size = 0
    files_seen: Dict[str, str] = {}  # case-folded -> original
    file_entries: List[SkillFileEntry] = []

    for rel_path, content in sorted(files_dict.items()):
        # Path safety
        path_ok, path_err = _validate_path(rel_path)
        if not path_ok:
            result.valid = False
            result.errors.append(path_err)
            continue

        # Case-fold collision
        folded = _casefold_path(rel_path)
        if folded in files_seen:
            result.valid = False
            result.errors.append(
                f"Case-fold collision: {rel_path!r} conflicts with {files_seen[folded]!r}"
            )
            continue
        files_seen[folded] = rel_path

        # NUL / control
        if b"\x00" in rel_path.encode("utf-8"):
            result.valid = False
            result.errors.append(f"NUL byte in path: {rel_path!r}")
            continue
        if _CONTROL_RE.search(rel_path):
            result.valid = False
            result.errors.append(f"Control characters in path: {rel_path!r}")
            continue

        size = len(content)
        total_size += size

        if size > limits.max_file_bytes:
            result.valid = False
            result.errors.append(
                f"File {rel_path!r} too large: {size} bytes > {limits.max_file_bytes}"
            )

        # LFS pointer
        if size < 200 and _LFS_POINTER_SIGNATURE in content:
            result.valid = False
            result.errors.append(f"LFS pointer file detected: {rel_path!r}")

        # Nested .git
        if ".git" in rel_path.split("/"):
            result.valid = False
            result.errors.append(f"Nested .git detected: {rel_path!r}")

        sha256 = hashlib.sha256(content).hexdigest()
        file_entries.append(SkillFileEntry(path=rel_path, sha256=sha256, size=size))

    if total_size > limits.max_total_bytes:
        result.valid = False
        result.errors.append(
            f"Total size too large: {total_size} bytes > {limits.max_total_bytes}"
        )

    result.files = tuple(sorted(file_entries, key=lambda f: f.path))
    return result


def _validate_path(path: str) -> Tuple[bool, str]:
    """Validate a single relative path. Returns (valid, error_message)."""
    if not path:
        return False, "Empty path"
    if path.startswith("/"):
        return False, f"Absolute path: {path!r}"
    # Cross-platform: reject backslash (Windows separator) and colon (drive/ADS)
    if _BACKSLASH_RE.search(path):
        return False, f"Backslash in path: {path!r}"
    if _UNSAFE_PATH_CHARS_RE.search(path):
        return False, f"Unsafe character (\\ or :) in path: {path!r}"
    parts = path.split("/")
    if ".." in parts:
        return False, f"Path traversal (..) in: {path!r}"
    if "." in parts:
        return False, f"Dot component in path: {path!r}"
    if b"\x00" in path.encode("utf-8"):
        return False, f"NUL byte in path: {path!r}"
    if _CONTROL_RE.search(path):
        return False, f"Control character in path: {path!r}"
    for part in parts:
        if not part:
            return False, f"Empty path component in: {path!r}"
        if part in _FORBIDDEN_PATH_COMPONENTS:
            return False, f"Forbidden path component {part!r} in: {path!r}"
        # Reject trailing dot or space in any component
        if part != part.rstrip(". "):
            return False, f"Trailing dot/space in path component {part!r}"
        # Reject Windows reserved names (case-insensitive)
        if part.upper() in _WINDOWS_RESERVED:
            return False, f"Windows reserved name {part!r} in path"
    return True, ""


def _casefold_path(path: str) -> str:
    return "/".join(part.lower() for part in path.split("/"))


# ---------------------------------------------------------------------------
# Dependency scanning (slash references only)
# ---------------------------------------------------------------------------

def scan_dependencies(tree: FetchedTree) -> FrozenSet[str]:
    """Scan SKILL.md and agent config files for slash command references.

    Only detects references (e.g. /grilling).  Does not resolve or block.
    """
    detected: set = set()
    for rel_path, content in tree.files.items():
        if not _is_scannable(rel_path):
            continue
        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            continue
        for m in _SLASH_CMD_RE.finditer(text):
            cmd = m.group(1).lower()
            if cmd not in _NON_SKILL_COMMANDS:
                detected.add(cmd)
    return frozenset(detected)


def _is_scannable(rel_path: str) -> bool:
    if rel_path == "SKILL.md":
        return True
    if rel_path.startswith("agents/") and (rel_path.endswith(".yaml") or rel_path.endswith(".yml")):
        return True
    return False
