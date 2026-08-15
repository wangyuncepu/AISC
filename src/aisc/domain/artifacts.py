"""Agent Artifact domain model and path policy (Stage 3, ART-01).

The authoritative fact layer for Agent deliverables: ``aisc.artifact/v1``.
Deliberately SEPARATE from ``packaging/artifact.py`` (release bundle builder) —
different schema, different namespace, different module. See
docs/plans/aisc-next/stage-3-workspace-artifacts/.

Invariants (D3-01..D3-08):
- Skill provides semantics (title/category/open suggestion), not facts.
- Only ``aisc artifact record`` writes an authoritative record (provenance
  ``manifest``). The watcher is a read model, never a fact writer.
- Agents submit workspace-relative paths; host absolute resolution is the
  Rust side's job after canonical containment.
- ``extra`` is free-form but must not carry secrets.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

ARTIFACT_PROTOCOL = "aisc.artifact/v1"
ARTIFACT_SCHEMA_VERSION = 1

# UUID v4-ish (structural check; the CLI generates real UUIDs).
_ARTIFACT_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Control characters / separators never allowed in a relative path.
_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_RESERVED = re.compile(
    r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)"
)


class ArtifactAction:
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    ALL = (CREATED, MODIFIED, DELETED, RENAMED)


class ArtifactKind:
    DELIVERABLE = "deliverable"
    SOURCE_CHANGE = "source_change"
    GENERATED_OUTPUT = "generated_output"
    ALL = (DELIVERABLE, SOURCE_CHANGE, GENERATED_OUTPUT)


class ArtifactState:
    PRESENT = "present"
    DELETED = "deleted"
    MOVED = "moved"
    MISSING = "missing"
    ALL = (PRESENT, DELETED, MOVED, MISSING)


class ArtifactOpenWith:
    PREVIEW = "preview"
    SYSTEM = "system"
    REVEAL = "reveal"
    NONE = "none"
    ALL = (PREVIEW, SYSTEM, REVEAL, NONE)


class ArtifactProvenance:
    MANIFEST = "manifest"  # authoritative: written by `aisc artifact record`
    WORKSPACE_CHANGE = "workspace_change"  # read model: watcher only


def validate_relative_path(raw: str) -> str:
    """Validate a workspace-relative path and return it normalized (POSIX).

    Rejects (A-ART05-* / R3-01):
    - empty or whitespace-only paths;
    - absolute paths (leading ``/``), Windows drive/UNC/root prefixes;
    - NUL and other control characters;
    - ``..`` traversal (any position);
    - backslash separators (``\\`` on Windows; cross-platform we reject them so
      a path written on one OS cannot silently mean something else on another);
    - Windows reserved device names (CON, NUL, …).

    Returns the normalized forward-slash path. Raises ValueError on violation.
    """
    if not raw or not raw.strip():
        raise ValueError("artifact path must not be empty")

    if _FORBIDDEN.search(raw):
        raise ValueError("artifact path contains control characters")

    # Backslashes: on POSIX they are legal filename bytes but ambiguous here;
    # reject to keep identity consistent across OSes (Windows is the strict one).
    if "\\" in raw:
        raise ValueError("artifact path must use '/' separators, not '\\'")

    if raw.startswith("/"):
        raise ValueError("artifact path must be relative (no leading '/')")

    # Windows drive / UNC / rooted prefixes (also caught by PurePosixPath but
    # be explicit for clear error messages).
    if re.match(r"^[A-Za-z]:", raw):
        raise ValueError("artifact path must be relative (no drive prefix)")
    if raw.startswith("//") or raw.startswith("\\\\"):
        raise ValueError("artifact path must be relative (no UNC prefix)")

    # Normalize via PurePosixPath (does NOT touch the filesystem; rejects
    # '..' traversal and collapses '.', keeps 'a//b' -> 'a/b').
    try:
        pp = PurePosixPath(raw)
    except ValueError as exc:
        raise ValueError(f"invalid artifact path: {exc}") from exc

    if not pp.parts or pp.parts[0] in ("", "/"):
        raise ValueError("artifact path must be relative")

    if ".." in pp.parts:
        raise ValueError("artifact path must not contain '..'")

    if "." == raw:
        raise ValueError("artifact path must point to a file")

    first = pp.parts[0]
    if _WINDOWS_RESERVED.match(first):
        raise ValueError(f"artifact path uses reserved device name: {first}")

    return str(pp)


def validate_artifact_id(artifact_id: str) -> str:
    """Validate a UUID-v4-shaped artifact id (structural, not version-4 bits)."""
    if not _ARTIFACT_ID_RE.match(artifact_id):
        raise ValueError("artifact_id must be a UUID")
    return artifact_id.lower()


def workspace_hash(workspace: Path) -> str:
    """Irreversible short hash of a canonical workspace path (for registry
    keying; never records the raw path)."""
    canon = str(workspace.resolve())
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def normalize_media_type(raw: Optional[str]) -> Optional[str]:
    """Validate/normalize a media type, or None when absent."""
    if raw is None:
        return None
    mt = raw.strip().lower()
    if not mt or "/" not in mt or len(mt) > 127:
        raise ValueError("media_type must be 'type/subtype' (<=127 chars)")
    return mt


@dataclass(frozen=True)
class ArtifactRecord:
    """One authoritative artifact fact (aisc.artifact/v1)."""

    schema_version: int = ARTIFACT_SCHEMA_VERSION
    artifact_id: str = ""
    workspace_relative_path: str = ""
    action: str = ArtifactAction.CREATED
    kind: str = ArtifactKind.DELIVERABLE
    media_type: Optional[str] = None
    label: str = ""
    open_with: str = ArtifactOpenWith.PREVIEW
    producer: Dict[str, Any] = field(default_factory=dict)
    state: str = ArtifactState.PRESENT
    provenance: str = ArtifactProvenance.MANIFEST
    recorded_at: str = ""
    previous_path: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    # -- construction / validation ---------------------------------------

    def validate(self) -> "ArtifactRecord":
        """Validate all fields; returns self (or raises ValueError)."""
        validate_artifact_id(self.artifact_id)
        validate_relative_path(self.workspace_relative_path)
        if self.action not in ArtifactAction.ALL:
            raise ValueError(f"invalid action: {self.action!r}")
        if self.action == ArtifactAction.RENAMED:
            if not self.previous_path:
                raise ValueError("renamed action requires previous_path")
            validate_relative_path(self.previous_path)
        if self.kind not in ArtifactKind.ALL:
            raise ValueError(f"invalid kind: {self.kind!r}")
        if self.state not in ArtifactState.ALL:
            raise ValueError(f"invalid state: {self.state!r}")
        if self.open_with not in ArtifactOpenWith.ALL:
            raise ValueError(f"invalid open_with: {self.open_with!r}")
        if self.provenance != ArtifactProvenance.MANIFEST:
            # The CLI only ever writes authoritative manifest facts. A watcher
            # read model is a separate projection, never stored as manifest.
            raise ValueError(
                f"provenance must be {ArtifactProvenance.MANIFEST!r}"
            )
        if self.schema_version != ARTIFACT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version: {self.schema_version}"
            )
        # producer: agent/session_id/runtime_id are required; never secrets.
        agent = self.producer.get("agent")
        if not agent or agent not in ("claude", "codex", "bash", "cc-switch"):
            raise ValueError(f"producer.agent must be one of claude/codex/bash/cc-switch")
        if not self.producer.get("session_id"):
            raise ValueError("producer.session_id is required")
        if not self.producer.get("runtime_id"):
            raise ValueError("producer.runtime_id is required")
        if self.label and len(self.label) > 256:
            raise ValueError("label must be <= 256 chars")
        if self.media_type:
            normalize_media_type(self.media_type)
        return self

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "workspace_relative_path": self.workspace_relative_path,
            "action": self.action,
            "kind": self.kind,
            "state": self.state,
            "provenance": self.provenance,
            "recorded_at": self.recorded_at,
            "extra": dict(self.extra),
        }
        if self.media_type is not None:
            d["media_type"] = self.media_type
        if self.label:
            d["label"] = self.label
        if self.open_with != ArtifactOpenWith.PREVIEW:
            d["open_with"] = self.open_with
        if self.previous_path is not None:
            d["previous_path"] = self.previous_path
        d["producer"] = dict(self.producer)
        return d

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ArtifactRecord":
        """Build + validate from a dict; unknown fields are preserved in
        ``extra`` (round-trip safe, A-ART01-1)."""
        if not isinstance(raw, dict):
            raise ValueError("artifact record must be a JSON object")
        schema_version = raw.get("schema_version", ARTIFACT_SCHEMA_VERSION)
        if schema_version != ARTIFACT_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {schema_version}")
        known = {
            "schema_version", "artifact_id", "workspace_relative_path",
            "action", "kind", "media_type", "label", "open_with",
            "producer", "state", "provenance", "recorded_at",
            "previous_path", "extra",
        }
        extra = dict(raw.get("extra") or {})
        for k, v in raw.items():
            if k not in known:
                extra[k] = v  # preserve unknown fields on round-trip
        rec = cls(
            schema_version=schema_version,
            artifact_id=raw.get("artifact_id", ""),
            workspace_relative_path=raw.get("workspace_relative_path", ""),
            action=raw.get("action", ArtifactAction.CREATED),
            kind=raw.get("kind", ArtifactKind.DELIVERABLE),
            media_type=raw.get("media_type"),
            label=raw.get("label", ""),
            open_with=raw.get("open_with", ArtifactOpenWith.PREVIEW),
            producer=dict(raw.get("producer") or {}),
            state=raw.get("state", ArtifactState.PRESENT),
            provenance=raw.get("provenance", ArtifactProvenance.MANIFEST),
            recorded_at=raw.get("recorded_at", ""),
            previous_path=raw.get("previous_path"),
            extra=extra,
        )
        return rec.validate()
