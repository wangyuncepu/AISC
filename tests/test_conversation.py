"""v2.1.8 T3 — conversation list/preflight against the frozen T0 fixtures.

tests/fixtures/conversation/*.jsonl are脱敏 probes of real Claude/Codex
session files (T0). Layout helpers recreate the provider-native directory
structures under a redirectable data root (AISC_DATA_ROOT).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from aisc.application.conversation import (
    MAX_JSONL_BYTES,
    TITLE_MAX_CHARS,
    UNREADABLE_TITLE,
    delete_conversation,
    list_conversations,
    preflight_conversation,
    sanitize_title,
)
from aisc.application.data_root import DataRootResolver
from aisc.domain.models import CliError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "conversation"

# Ids as they appear in the frozen fixtures (claude = v4, codex = v7 in the
# wild — see decisions.md D-5).
CLAUDE_ID = "c8931e67-2321-492d-8557-4158e3ef2ee7"
CODEX_ID = "01a04ca9-d3f6-7021-b9e7-50d48d818c65"


@pytest.fixture
def ws_env(tmp_path, monkeypatch):
    """A workspace + redirected data root; returns (workspace, ws_dir)."""
    data_root = tmp_path / "data-root"
    data_root.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("AISC_DATA_ROOT", str(data_root))
    ws_dir = DataRootResolver(env=os.environ).resolve(ws).workspace_dir
    return ws, ws_dir


def _install_claude(ws_dir: Path, fixture: str, conv_id: str = CLAUDE_ID) -> None:
    dest = ws_dir / "claude" / "projects" / "-"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / fixture, dest / f"{conv_id}.jsonl")


def _install_codex(ws_dir: Path, fixture: str, conv_id: str = CODEX_ID) -> None:
    dest = ws_dir / "codex" / "sessions" / "2026" / "08" / "29"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        FIXTURES / fixture,
        dest / f"rollout-2026-08-29T08-37-50-{conv_id}.jsonl",
    )


def _by_id(data: dict, conv_id: str) -> dict:
    matches = [c for c in data["conversations"] if c["conversation_id"] == conv_id]
    assert len(matches) == 1, f"expected exactly one entry for {conv_id}: {data}"
    return matches[0]


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

class TestConversationList:
    def test_claude_normal(self, ws_env):
        ws, ws_dir = ws_env
        _install_claude(ws_dir, "claude_normal.jsonl")
        data = list_conversations(str(ws))
        entry = _by_id(data, CLAUDE_ID)
        assert entry["agent"] == "claude"
        assert entry["title"] == "init"
        assert entry["message_count"] == 1
        assert entry["resumable"] is True
        assert "unavailable_reason" not in entry
        assert entry["started_at"] == "2026-08-29T08:05:39.519Z"
        assert entry["last_at"] == "2026-08-29T08:05:39.615Z"
        assert entry["file_size"] > 0

    def test_codex_title_is_real_user_text(self, ws_env):
        """Design §1d-6 + 手测反馈 #1: the Codex title must be the REAL user
        input, not the injected AGENTS.md context block recorded as a user
        message before it."""
        ws, ws_dir = ws_env
        _install_codex(ws_dir, "codex_normal.jsonl")
        entry = _by_id(list_conversations(str(ws)), CODEX_ID)
        assert entry["agent"] == "codex"
        # user[0] is the AGENTS.md injection (context-like, skipped);
        # user[1] is what the user actually typed.
        assert entry["title"] == "test"
        assert entry["message_count"] == 2

    def test_codex_single_user_exact_title(self, ws_env):
        ws, ws_dir = ws_env
        _install_codex(ws_dir, "codex_single_user.jsonl")
        entry = _by_id(list_conversations(str(ws)), CODEX_ID)
        assert entry["title"] == "Help me sort an array"
        assert entry["message_count"] == 1
        assert entry["resumable"] is True

    def test_secret_title_redacted(self, ws_env):
        ws, ws_dir = ws_env
        _install_claude(ws_dir, "claude_secret_title.jsonl")
        entry = _by_id(list_conversations(str(ws)), CLAUDE_ID)
        assert entry["title"] == "Use key [REDACTED] to test"
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in entry["title"]

    def test_corrupted_tail_annotated_malformed(self, ws_env):
        ws, ws_dir = ws_env
        _install_claude(ws_dir, "claude_corrupted_tail.jsonl")
        _install_codex(ws_dir, "codex_corrupted_tail.jsonl")
        data = list_conversations(str(ws))
        for conv_id in (CLAUDE_ID, CODEX_ID):
            entry = _by_id(data, conv_id)
            assert entry["resumable"] is False
            assert entry["unavailable_reason"] == "malformed"
            assert entry["message_count"] == 1  # user line survived the corruption
        assert _by_id(data, CODEX_ID)["title"] == "Help me sort an array"

    def test_no_user_and_empty_excluded(self, ws_env):
        ws, ws_dir = ws_env
        _install_claude(ws_dir, "claude_no_user.jsonl")
        _install_codex(ws_dir, "empty.jsonl",
                       conv_id="01a04ca9-d3f6-7021-b9e7-50d48d818c65")
        _install_claude(ws_dir, "claude_single_user.jsonl")
        data = list_conversations(str(ws))
        assert [c["conversation_id"] for c in data["conversations"]] == [CLAUDE_ID]

    def test_sorted_most_recent_first(self, ws_env):
        ws, ws_dir = ws_env
        _install_claude(ws_dir, "claude_normal.jsonl")  # last 08:05
        _install_codex(ws_dir, "codex_normal.jsonl")  # last 08:37:55
        data = list_conversations(str(ws))
        assert [c["agent"] for c in data["conversations"]] == ["codex", "claude"]

    def test_oversized_file_annotated(self, ws_env):
        ws, ws_dir = ws_env
        dest = ws_dir / "claude" / "projects" / "-"
        dest.mkdir(parents=True)
        target = dest / f"{CLAUDE_ID}.jsonl"
        pad = '{"type":"assistant","pad":"' + "a" * 4000 + '"}\n'
        with target.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "type": "user", "timestamp": "2026-08-29T10:00:00Z",
                "message": {"role": "user", "content": "oversized head title"},
            }) + "\n")
            while target.stat().st_size <= MAX_JSONL_BYTES:
                fh.write(pad)
        assert target.stat().st_size > MAX_JSONL_BYTES
        entry = _by_id(list_conversations(str(ws)), CLAUDE_ID)
        assert entry["resumable"] is False
        assert entry["unavailable_reason"] == "file_too_large"
        assert entry["message_count"] is None  # head scan took no full count
        assert entry["title"] == "oversized head title"
        assert entry["file_size"] == target.stat().st_size

    def test_empty_workspace(self, ws_env):
        ws, _ws_dir = ws_env
        data = list_conversations(str(ws))
        assert data == {"schema_version": 1, "conversations": []}

    def test_context_first_session_falls_back(self, ws_env):
        """Every user message context-like → fall back to the first."""
        ws, ws_dir = ws_env
        dest = ws_dir / "claude" / "projects" / "-"
        dest.mkdir(parents=True)
        (dest / f"{CLAUDE_ID}.jsonl").write_text(
            "\n".join([
                json.dumps({"type": "user", "timestamp": "2026-08-29T10:00:00Z",
                            "message": {"role": "user",
                                        "content": "<INSTRUCTIONS>context"}}),
                json.dumps({"type": "user", "timestamp": "2026-08-29T10:00:01Z",
                            "message": {"role": "user",
                                        "content": "<system-reminder>more"}}),
            ]),
            encoding="utf-8",
        )
        entry = _by_id(list_conversations(str(ws)), CLAUDE_ID)
        assert entry["title"].startswith("<INSTRUCTIONS>")

    def test_delete_removes_file(self, ws_env):
        ws, ws_dir = ws_env
        _install_codex(ws_dir, "codex_normal.jsonl")
        result = delete_conversation(str(ws), CODEX_ID, "codex")
        assert result == {"deleted": True, "conversation_id": CODEX_ID, "agent": "codex"}
        assert list_conversations(str(ws))["conversations"] == []
        # Deleting again reports the same not-found anomaly as preflight.
        with pytest.raises(CliError) as exc:
            delete_conversation(str(ws), CODEX_ID, "codex")
        assert exc.value.error_code == "AISC_ERR_CONVERSATION_UNRESUMABLE"

    def test_non_uuid_jsonl_ignored(self, ws_env):
        ws, ws_dir = ws_env
        dest = ws_dir / "claude" / "projects" / "-"
        dest.mkdir(parents=True)
        shutil.copyfile(FIXTURES / "claude_normal.jsonl", dest / "not-a-session.jsonl")
        assert list_conversations(str(ws))["conversations"] == []


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

class TestConversationPreflight:
    def test_claude_hit(self, ws_env):
        ws, ws_dir = ws_env
        _install_claude(ws_dir, "claude_normal.jsonl")
        assert preflight_conversation(str(ws), CLAUDE_ID, "claude") == {
            "preflight_ok": True,
            "conversation_id": CLAUDE_ID,
            "agent": "claude",
        }

    def test_codex_hit_with_v7_id(self, ws_env):
        """D-5: real Codex ids are UUIDv7 — the frozen v4-only regex would
        have rejected every genuine Codex conversation."""
        ws, ws_dir = ws_env
        _install_codex(ws_dir, "codex_normal.jsonl")
        result = preflight_conversation(str(ws), CODEX_ID, "codex")
        assert result["preflight_ok"] is True

    def test_codex_id_case_insensitive(self, ws_env):
        ws, ws_dir = ws_env
        _install_codex(ws_dir, "codex_normal.jsonl")
        result = preflight_conversation(str(ws), CODEX_ID.upper(), "codex")
        assert result["preflight_ok"] is True

    def test_invalid_id(self, ws_env):
        ws, _ws_dir = ws_env
        with pytest.raises(CliError) as exc:
            preflight_conversation(str(ws), "not-a-uuid", "claude")
        assert exc.value.exit_code == 2
        assert exc.value.error_code == "AISC_ERR_CONVERSATION_INVALID_ID"

    def test_invalid_agent(self, ws_env):
        ws, _ws_dir = ws_env
        with pytest.raises(CliError) as exc:
            preflight_conversation(str(ws), CLAUDE_ID, "bash")
        assert exc.value.exit_code == 2
        assert exc.value.error_code == "AISC_ERR_CONVERSATION_INVALID_AGENT"

    def test_not_found(self, ws_env):
        ws, _ws_dir = ws_env
        with pytest.raises(CliError) as exc:
            preflight_conversation(str(ws), CLAUDE_ID, "claude")
        assert exc.value.exit_code == 3
        assert exc.value.error_code == "AISC_ERR_CONVERSATION_UNRESUMABLE"

    def test_agent_mismatch_not_found(self, ws_env):
        """A claude-only file must not satisfy a codex preflight."""
        ws, ws_dir = ws_env
        _install_claude(ws_dir, "claude_normal.jsonl")
        with pytest.raises(CliError) as exc:
            preflight_conversation(str(ws), CLAUDE_ID, "codex")
        assert exc.value.error_code == "AISC_ERR_CONVERSATION_UNRESUMABLE"


# ---------------------------------------------------------------------------
# sanitize_title
# ---------------------------------------------------------------------------

class TestSanitizeTitle:
    def test_truncates_to_80_scalars(self):
        assert len(sanitize_title("字" * 300)) == TITLE_MAX_CHARS

    def test_strips_ansi_and_control_chars(self):
        out = sanitize_title("\x1b[31merr\x1b[0m\n\tmulti\rline\x07")
        assert out == "err multi line"  # \r separates like a newline (CRLF-safe)
        assert "\x1b" not in out and "\n" not in out

    def test_redacts_all_three_patterns(self):
        out = sanitize_title(
            "sk-abcdefghijklmnopqrstuv and Bearer abc.def and "
            "api_key: 'abcdefghijklmnop1234567'"
        )
        assert "[REDACTED]" in out
        assert "sk-abcdefghijklmnopqrstuv" not in out

    def test_empty_falls_back(self):
        assert sanitize_title("   \n\t ") == UNREADABLE_TITLE


class TestConversationRename:
    def test_rename_overrides_list_title(self, ws_env):
        from aisc.application.conversation import rename_conversation
        ws, ws_dir = ws_env
        _install_codex(ws_dir, "codex_single_user.jsonl")
        result = rename_conversation(str(ws), CODEX_ID, "codex", "我的排序任务")
        assert result["renamed"] is True
        assert result["title"] == "我的排序任务"
        entry = _by_id(list_conversations(str(ws)), CODEX_ID)
        assert entry["title"] == "我的排序任务"

    def test_rename_persists_across_calls(self, ws_env):
        from aisc.application.conversation import rename_conversation
        ws, ws_dir = ws_env
        _install_claude(ws_dir, "claude_single_user.jsonl")
        rename_conversation(str(ws), CLAUDE_ID, "claude", "renamed once")
        rename_conversation(str(ws), CLAUDE_ID, "claude", "renamed twice")
        entry = _by_id(list_conversations(str(ws)), CLAUDE_ID)
        assert entry["title"] == "renamed twice"

    def test_delete_clears_override(self, ws_env):
        from aisc.application.conversation import delete_conversation, rename_conversation
        ws, ws_dir = ws_env
        _install_claude(ws_dir, "claude_single_user.jsonl")
        rename_conversation(str(ws), CLAUDE_ID, "claude", "to be deleted")
        delete_conversation(str(ws), CLAUDE_ID, "claude")
        # Recreate the same conversation: no stale override may resurface.
        _install_claude(ws_dir, "claude_single_user.jsonl")
        entry = _by_id(list_conversations(str(ws)), CLAUDE_ID)
        assert entry["title"] == "Hello world test"

    def test_rename_empty_title_rejected(self, ws_env):
        from aisc.application.conversation import rename_conversation
        ws, ws_dir = ws_env
        _install_claude(ws_dir, "claude_single_user.jsonl")
        with pytest.raises(CliError) as exc:
            rename_conversation(str(ws), CLAUDE_ID, "claude", "   ")
        assert exc.value.exit_code == 2

    def test_rename_missing_conversation(self, ws_env):
        from aisc.application.conversation import rename_conversation
        ws, _ws_dir = ws_env
        with pytest.raises(CliError) as exc:
            rename_conversation(str(ws), CLAUDE_ID, "claude", "nope")
        assert exc.value.error_code == "AISC_ERR_CONVERSATION_UNRESUMABLE"
