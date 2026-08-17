"""Legacy-layout migration contract (Stage 7, 7c, DATA-02/D7-03).

Pure tables and schema for migrating the pre-Stage-7 workspace layout (see
the measured fresh-init inventory in stage-7/02-domain-contract.md) into the
data root. The walker lives in ``application/legacy_scan.py``; execution
(prepare/commit/rollback/quarantine) is 7d.

Classification (D7-03 — protect user files, migrate only the known):
- ``owned``     allowlisted AISC/agent state → migratable, hashed, mapped;
- ``transient`` locks, pid files, live-SQLite sidecars' init locks, daemon
                logs — coordination/bounded artifacts, left in place, never
                migrated (cc-switch.db itself IS owned; -shm/-wal migrate as
                a set with it so an un-checkpointed WAL loses nothing);
- ``unknown``   inside an AISC namespace but not allowlisted (likely the
                user's own file) → quarantine candidate, never deleted;
- ``conflict``  owned but the target already exists with a different hash
                → fail closed, user decision;
- namespace ``foreign``: e.g. a user's own ``.claude`` predating AISC — no
  AISC-init marker anywhere → reported, not migrated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

MIGRATION_PROTOCOL = "aisc.data-migration/v1"
MIGRATION_SCHEMA_VERSION = 1

# Manifest lifecycle states (closed set, 02-domain-contract.md).
STATE_PREPARED = "prepared"
STATE_COMMITTED = "committed"
STATE_ROLLED_BACK = "rolled_back"
STATE_QUARANTINED = "quarantined"
MANIFEST_STATES = (STATE_PREPARED, STATE_COMMITTED, STATE_ROLLED_BACK, STATE_QUARANTINED)

ENTRY_OWNED = "owned"
ENTRY_TRANSIENT = "transient"
ENTRY_UNKNOWN = "unknown"
ENTRY_CONFLICT = "conflict"
ENTRY_CLASSIFICATIONS = (ENTRY_OWNED, ENTRY_TRANSIENT, ENTRY_UNKNOWN, ENTRY_CONFLICT)

# Per-entry migration status (7d sets these; scan drafts stay "pending").
STATUS_PENDING = "pending"
STATUS_COPIED = "copied"
STATUS_SKIPPED = "skipped"
STATUS_QUARANTINED = "quarantined"

NAMESPACE_FOREIGN = "foreign"
NAMESPACE_AISC = "aisc"

# -- allowlist ---------------------------------------------------------------
# Keys are workspace-relative namespaces; values: (exact_files, dir_prefixes,
# transient_files, transient_prefixes). Everything else inside the namespace
# classifies as ``unknown`` (quarantine candidate, never deleted).

ALLOWLIST: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]] = {
    ".aisc": (
        # containers.json/state.env → runtime/; config.json → workspace config
        ("containers.json", "state.env", "config.json"),
        (),
        (".containers.lock",),
        ("workspace-locks/",),
    ),
    ".claude": (
        # .claude.json (agent runtime config) and .factory-version (factory
        # marker) are hidden dotfiles found by the real-workspace scan.
        ("CLAUDE.md", "config.json", "settings.json", "settings.local.json",
         ".claude.json", ".factory-version"),
        ("backups/", "commands/", "plugins/", "projects/", "sessions/", "skills/"),
        (),
        (),
    ),
    ".codex": (
        ("config.toml", "AGENTS.md", ".factory-version"),
        ("skills/",),
        (),
        (),
    ),
    ".cc-switch": (
        # db migrates together with -shm/-wal (un-checkpointed WAL safety).
        ("cc-switch.db", "cc-switch.db-shm", "cc-switch.db-wal", "settings.json",
         "session-scan-cache.db", ".aisc-bundled-skills.sha256",
         ".aisc-preset-providers-claude.sha256", ".aisc-preset-providers-codex.sha256"),
        ("skills/",),
        ("cc-switch.db.init.lock", "state-mutation.lock", ".aisc-bundled-skills.lock"),
        (),
    ),
    # daemon runtime only: logs/pids are transient, anything else → unknown
    ".local": ((), (), (), ("state/cc-switch/",)),
}

# Namespace → target layout under workspaces/<hash>/ ("" = file at the
# workspace-dir root). Only used for ``owned`` entries.
TARGET_DIRS: Dict[str, str] = {
    ".claude": "claude",
    ".codex": "codex",
    ".cc-switch": "cc-switch",
}
TARGET_FILES: Dict[str, str] = {
    ".aisc/containers.json": "runtime/containers.json",
    ".aisc/state.env": "runtime/state.env",
    ".aisc/config.json": "config.json",
}

# A workspace is "AISC-initialized" when at least one of these exists; a
# namespace dir without any marker classifies as the user's own (foreign).
AISC_INIT_MARKERS: Tuple[str, ...] = (
    ".aisc",
    ".codex/.factory-version",
    ".cc-switch/.aisc-bundled-skills.sha256",
    ".cc-switch/.aisc-preset-providers-claude.sha256",
)


def classify(namespace: str, rel: str) -> Tuple[str, str]:
    """Pure classification of one namespace-relative file →
    ``(classification, target_rel_under_workspace_dir)``.

    ``rel`` is POSIX-style, relative to the namespace root (e.g.
    ``skills/caveman/SKILL.md``); for ``.local`` it carries the ``state/…``
    tail (e.g. ``state/cc-switch/cc-switchd.log``).
    """
    files, prefixes, transient_files, transient_prefixes = ALLOWLIST[namespace]
    name = rel.rsplit("/", 1)[-1]

    if name in transient_files or any(rel.startswith(p) for p in transient_prefixes):
        return ENTRY_TRANSIENT, ""

    if namespace == ".local":
        # Only the cc-switch daemon subtree is in scope; its allowlist is all
        # transient, so anything else here is unknown.
        return ENTRY_UNKNOWN, ""

    if namespace == ".aisc":
        # Explicit file map only (state → runtime/, config → ws-dir root).
        exact = TARGET_FILES.get(f".aisc/{rel}", "")
        if exact:
            return ENTRY_OWNED, exact
        return ENTRY_UNKNOWN, ""

    # Agent namespaces (.claude/.codex/.cc-switch): exact root files plus
    # allowlisted subtrees map under workspaces/<hash>/<namespace-dir>/.
    target_dir = TARGET_DIRS.get(namespace, "")
    if not target_dir:
        return ENTRY_UNKNOWN, ""
    if (name in files and "/" not in rel) or any(rel.startswith(p) for p in prefixes):
        return ENTRY_OWNED, f"{target_dir}/{rel}"
    return ENTRY_UNKNOWN, ""


@dataclass(frozen=True)
class MigrationEntry:
    """One classified file (scan draft) / migrated file (7d status update)."""

    relative: str            # workspace-relative POSIX path, e.g. ".cc-switch/settings.json"
    classification: str      # ENTRY_*
    sha256: str = ""
    size: int = 0
    target: str = ""         # rel path under workspaces/<hash>/ ("" = not migrated)
    status: str = STATUS_PENDING

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "relative": self.relative,
            "classification": self.classification,
            "size": self.size,
            "status": self.status,
        }
        if self.sha256:
            d["sha256"] = self.sha256
        if self.target:
            d["target"] = self.target
        return d

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MigrationEntry":
        if not isinstance(raw, dict):
            raise ValueError("migration entry must be a JSON object")
        classification = raw.get("classification", "")
        if classification not in ENTRY_CLASSIFICATIONS:
            raise ValueError(f"unsupported entry classification: {classification!r}")
        return cls(
            relative=raw.get("relative", ""),
            classification=classification,
            sha256=raw.get("sha256", ""),
            size=int(raw.get("size", 0)),
            target=raw.get("target", ""),
            status=raw.get("status", STATUS_PENDING),
        )


@dataclass
class MigrationManifest:
    """``aisc.data-migration/v1`` — the migration boundary: rollback only
    touches what this manifest lists; unknown fields fail closed."""

    schema: str = MIGRATION_PROTOCOL
    schema_version: int = MIGRATION_SCHEMA_VERSION
    workspace_hash: str = ""
    source: str = ""         # legacy workspace root (abs)
    target: str = ""         # data-root workspaces/<hash>/ (abs)
    entries: List[MigrationEntry] = field(default_factory=list)
    state: str = STATE_PREPARED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "workspace_hash": self.workspace_hash,
            "source": self.source,
            "target": self.target,
            "entries": [e.to_dict() for e in self.entries],
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MigrationManifest":
        if not isinstance(raw, dict):
            raise ValueError("migration manifest must be a JSON object")
        if raw.get("schema") != MIGRATION_PROTOCOL:
            raise ValueError(f"unsupported manifest schema: {raw.get('schema')!r}")
        version = raw.get("schema_version", MIGRATION_SCHEMA_VERSION)
        if version != MIGRATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {version}")
        state = raw.get("state", STATE_PREPARED)
        if state not in MANIFEST_STATES:
            raise ValueError(f"unsupported manifest state: {state!r}")
        return cls(
            schema=MIGRATION_PROTOCOL,
            schema_version=version,
            workspace_hash=raw.get("workspace_hash", ""),
            source=raw.get("source", ""),
            target=raw.get("target", ""),
            entries=[MigrationEntry.from_dict(e) for e in raw.get("entries", [])],
            state=state,
        )
