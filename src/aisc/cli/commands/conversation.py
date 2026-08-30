"""Conversation commands implementation (v2.1.8 T3).

Implements ``aisc conversation`` subcommands: list, preflight.
Per docs/plans/2.1.8-dev-plans/01-design.md §1b. Both are captured,
read-only commands — ``conversation resume`` deliberately does NOT exist
as a CLI command (方案 B 冻结): resume is the Workbench two-call
orchestration (preflight IPC + open_session --resume-id).
"""

from __future__ import annotations

from typing import Any, Dict

from aisc.application.conversation import (
    list_conversations,
    preflight_conversation,
)


def cmd_conversation_list(workspace: str) -> Dict[str, Any]:
    """Execute ``aisc conversation list`` per design §1b."""
    return list_conversations(workspace)


def cmd_conversation_preflight(workspace: str, conversation_id: str,
                               agent: str) -> Dict[str, Any]:
    """Execute ``aisc conversation preflight`` per design §2."""
    return preflight_conversation(workspace, conversation_id, agent)


def print_conversation_text(subcommand: str, data: Any, errors: list) -> None:
    """Minimal human-readable output for ``aisc conversation`` text mode."""
    if errors:
        for e in errors:
            print(f"Error: {e.get('message', '')}")
        return
    if not isinstance(data, dict):
        return
    if subcommand == "list":
        conversations = data.get("conversations", [])
        if not conversations:
            print("(no conversations)")
            return
        for c in conversations:
            line = (f"{c.get('conversation_id', '')}  agent={c.get('agent', '')}  "
                    f"{c.get('last_at') or '-'}  {c.get('title', '')}")
            if not c.get("resumable", True):
                line += f"  [unresumable: {c.get('unavailable_reason', '')}]"
            print(line)
    elif subcommand == "preflight":
        print(f"preflight ok: {data.get('conversation_id', '')} "
              f"agent={data.get('agent', '')}")
