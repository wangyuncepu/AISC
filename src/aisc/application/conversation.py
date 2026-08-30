"""Agent conversation discovery (v2.1.8 T3).

Read-only JSONL scanning per docs/plans/2.1.8-dev-plans/01-design.md
§1a-1e. Thin read over provider-native session files — no new storage
(方案 A): Claude ``<ws>/claude/projects/**/*.jsonl`` (filename stem =
conversation id), Codex ``<ws>/codex/sessions/**/*.jsonl`` (rollout
filename carries the id).

Oversized files (>10MB) are never fully parsed: a streaming head scan of
the first 200 parseable lines yields title/time, ``message_count`` stays
``null`` and the entry is annotated ``file_too_large``. Malformed JSON
lines are skipped; a file with at least one parseable user message but
some corrupt lines is annotated ``malformed`` and kept, ``resumable:
false``. Entries with zero parseable user messages are excluded.

D-5 (decisions.md): conversation ids are provider-native — Codex uses
time-ordered UUIDv7 in the wild (see the frozen T0 codex fixtures), so id
validation accepts any RFC-4122 version, not only v4. Non-UUID garbage is
still rejected (the check's stated intent).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aisc.application.data_root import DataRootResolver
from aisc.domain.models import CliError

# ---------------------------------------------------------------------------
# Frozen constants (design §1a/1d/1e)
# ---------------------------------------------------------------------------

MAX_JSONL_BYTES = 10 * 1024 * 1024
HEAD_SCAN_PARSEABLE_LINES = 200
TITLE_MAX_CHARS = 80
UNREADABLE_TITLE = "(无法读取)"

ERROR_INVALID_ID = "AISC_ERR_CONVERSATION_INVALID_ID"
ERROR_INVALID_AGENT = "AISC_ERR_CONVERSATION_INVALID_AGENT"
ERROR_UNRESUMABLE = "AISC_ERR_CONVERSATION_UNRESUMABLE"

# D-5: any RFC-4122 version (provider-native ids; Codex ships v7). The
# design's v4-only pattern predated the T0 probe fixtures and would have
# rejected every real Codex session.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{12}$"
)
_CODEX_FILENAME_RE = re.compile(
    r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{12})\.jsonl$"
)

_AGENTS = ("claude", "codex")


# ---------------------------------------------------------------------------
# Title sanitization (design §1d)
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_REDACT_PATTERNS = (
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+\S+"),
    re.compile(r"api[_-]?key.*['\"]\s*\w{16,}"),
)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_title(text: str) -> str:
    """Sanitize a raw user message into a display title.

    Order: strip ANSI escapes → apply redaction patterns → drop control
    chars (newlines become spaces) → collapse whitespace → truncate to 80
    Unicode scalar values. Empty results degrade to ``UNREADABLE_TITLE``.
    """
    out = _ANSI_RE.sub("", text)
    for pat in _REDACT_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    out = _CONTROL_CHARS_RE.sub(" ", out)
    out = " ".join(out.split())
    out = out[:TITLE_MAX_CHARS]
    return out or UNREADABLE_TITLE


# ---------------------------------------------------------------------------
# Per-provider user-message extraction (design §1a)
# ---------------------------------------------------------------------------

def _extract_claude_user(obj: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Return (is_user_line, extracted_text_or_None) for a Claude line."""
    if obj.get("type") != "user":
        return False, None
    msg = obj.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return False, None
    return True, _text_from_content(msg.get("content"), "text")


def _extract_codex_user(obj: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Return (is_user_line, extracted_text_or_None) for a Codex line."""
    if obj.get("type") != "response_item":
        return False, None
    payload = obj.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "message":
        return False, None
    if payload.get("role") != "user":
        return False, None
    return True, _text_from_content(payload.get("content"), "input_text")


def _text_from_content(content: Any, block_type: str) -> Optional[str]:
    """Content is a string or a list of typed blocks; extract the first
    text block's text (design §1d extraction). Returns None when the line
    is a user line without extractable text (e.g. tool results)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == block_type:
                text = block.get("text")
                if isinstance(text, str):
                    return text
    return None


_EXTRACTORS = {
    "claude": _extract_claude_user,
    "codex": _extract_codex_user,
}


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------

@dataclass
class _FileScan:
    parseable: int = 0
    user_messages: int = 0
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None
    title: Optional[str] = None
    malformed_seen: bool = False


def _scan_file(path: Path, agent: str, head_only: bool) -> _FileScan:
    """Stream a JSONL session file. ``head_only`` (oversized files) stops
    after HEAD_SCAN_PARSEABLE_LINES parseable lines — the file is never
    fully parsed (design §1a max_file_size)."""
    state = _FileScan()
    extract = _EXTRACTORS[agent]
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                state.malformed_seen = True
                continue
            if not isinstance(obj, dict):
                continue
            state.parseable += 1
            ts = obj.get("timestamp")
            if isinstance(ts, str) and ts:
                if state.first_ts is None:
                    state.first_ts = ts
                state.last_ts = ts
            is_user, text = extract(obj)
            if is_user:
                state.user_messages += 1
                if state.title is None and text:
                    state.title = sanitize_title(text)
            if head_only and state.parseable >= HEAD_SCAN_PARSEABLE_LINES:
                break
    return state


def _conversation_id_for(agent: str, filename: str) -> Optional[str]:
    """Derive the conversation id from the filename (design §1a id_source).

    Claude: filename stem IS the id. Codex: ``rollout-<ts>-<uuid>.jsonl``.
    Returns None for files that do not carry a well-formed id — they are
    not sessions and are skipped.
    """
    if agent == "claude":
        stem = filename[:-len(".jsonl")] if filename.endswith(".jsonl") else filename
        return stem if _UUID_RE.match(stem) else None
    m = _CODEX_FILENAME_RE.match(filename)
    return m.group(1) if m else None


def _summarize(agent: str, conv_id: str, file_size: int,
               scan: _FileScan) -> Optional[Dict[str, Any]]:
    """Apply §1e filtering/annotation. Returns None when the entry is
    excluded from the list (zero parseable user messages)."""
    if scan.user_messages == 0:
        return None
    resumable = True
    reason: Optional[str] = None
    message_count: Optional[int] = scan.user_messages
    if file_size > MAX_JSONL_BYTES:
        resumable = False
        reason = "file_too_large"
        message_count = None  # head scan only — a full count was not taken
    elif scan.malformed_seen:
        resumable = False
        reason = "malformed"
    entry: Dict[str, Any] = {
        "conversation_id": conv_id,
        "agent": agent,
        "title": scan.title if scan.title else UNREADABLE_TITLE,
        "started_at": scan.first_ts,
        "last_at": scan.last_ts,
        "message_count": message_count,
        "file_size": file_size,
        "resumable": resumable,
    }
    if not resumable:
        entry["unavailable_reason"] = reason
    return entry


def _scan_agent_dir(base: Path, agent: str) -> List[Dict[str, Any]]:
    if not base.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(base.rglob("*.jsonl")):
        if not path.is_file():
            continue
        conv_id = _conversation_id_for(agent, path.name)
        if conv_id is None:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        scan = _scan_file(path, agent, head_only=(size > MAX_JSONL_BYTES))
        entry = _summarize(agent, conv_id, size, scan)
        if entry is not None:
            out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def _workspace_dir(workspace: str) -> Path:
    """The workspace's data-root dir (read-only resolve — never creates)."""
    ws = Path(workspace).resolve() if workspace else Path.cwd()
    return DataRootResolver().resolve(ws).workspace_dir


def list_conversations(workspace: str) -> Dict[str, Any]:
    """List agent history conversations for a workspace (design §1b).

    Read-only, no Docker. Sorted most-recent-first for the picker UI
    (``last_at`` descending; entries without timestamps sort last).
    """
    ws_dir = _workspace_dir(workspace)
    entries: List[Dict[str, Any]] = []
    entries.extend(_scan_agent_dir(ws_dir / "claude" / "projects", "claude"))
    entries.extend(_scan_agent_dir(ws_dir / "codex" / "sessions", "codex"))
    entries.sort(
        key=lambda e: (e["last_at"] or "", e["conversation_id"]),
        reverse=True,
    )
    return {"schema_version": 1, "conversations": entries}


def preflight_conversation(workspace: str, conversation_id: str,
                           agent: str) -> Dict[str, Any]:
    """Validate a conversation is resumable BEFORE any PTY spawn (design
    §2: sidecar captured preflight). Exact provider-specific file match —
    never glob substring matching."""
    if not isinstance(conversation_id, str) or not _UUID_RE.match(conversation_id):
        raise CliError(
            message=f"Invalid conversation ID: {conversation_id}",
            exit_code=2,
            error_code=ERROR_INVALID_ID,
        )
    if agent not in _AGENTS:
        raise CliError(
            message=f"Unsupported agent for resume: {agent}",
            exit_code=2,
            error_code=ERROR_INVALID_AGENT,
        )

    ws_dir = _workspace_dir(workspace)
    if agent == "claude":
        base = ws_dir / "claude" / "projects"
        # Claude: filename = <conversation_id>.jsonl — exact stem match.
        hit = base.is_dir() and any(
            p.is_file() and p.stem == conversation_id
            for p in base.rglob("*.jsonl")
        )
    else:
        base = ws_dir / "codex" / "sessions"
        # Codex: rollout-<timestamp>-<uuid>.jsonl — parse the trailing id
        # from the filename, case-insensitive equality.
        hit = base.is_dir() and any(
            p.is_file()
            and (m := _CODEX_FILENAME_RE.match(p.name)) is not None
            and m.group(1).lower() == conversation_id.lower()
            for p in base.rglob("*.jsonl")
        )

    if not hit:
        raise CliError(
            message=f"Conversation {conversation_id} not found for agent {agent}",
            exit_code=3,
            error_code=ERROR_UNRESUMABLE,
        )
    return {
        "preflight_ok": True,
        "conversation_id": conversation_id,
        "agent": agent,
    }
