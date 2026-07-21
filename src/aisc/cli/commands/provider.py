"""CLI command implementations for provider catalog management."""

from __future__ import annotations

import json as _json
import sys
from typing import Any, Dict, Optional

from aisc.application.provider_service import (
    run_provider_list, ProviderListResult,
    run_provider_show, ProviderShowResult,
    run_provider_add, ProviderAddResult,
)


def cmd_provider_list(*, aisc_root: Optional[str] = None) -> ProviderListResult:
    """Execute ``provider list`` — read and return the canonical provider catalog."""
    return run_provider_list(explicit_root=aisc_root)


def cmd_provider_show(name: str, *, aisc_root: Optional[str] = None) -> ProviderShowResult:
    """Execute ``provider show NAME`` — look up a provider by id or alias."""
    return run_provider_show(name, explicit_root=aisc_root)


def cmd_provider_add(
    *, provider_id: str, name: str, auth_type: str, auth_key_name: str,
    base_url: str, aliases: Any = (), model: str = "", default_opus: str = "",
    default_sonnet: str = "", default_haiku: str = "", subagent: str = "",
    effort: str = "", compact: str = "", overwrite: bool = False,
    aisc_root: Optional[str] = None,
) -> ProviderAddResult:
    return run_provider_add(
        provider_id=provider_id, name=name, auth_type=auth_type,
        auth_key_name=auth_key_name, base_url=base_url, aliases=aliases,
        model=model, default_opus=default_opus, default_sonnet=default_sonnet,
        default_haiku=default_haiku, subagent=subagent, effort=effort,
        compact=compact, overwrite=overwrite, explicit_root=aisc_root,
    )


def print_provider_list_text(data: Dict[str, Any]) -> None:
    """Print provider list in human-readable format."""
    if not data:
        print("=== Provider List ===")
        print()
        print("No providers available.")
        return

    sv = data.get("schema_version", "?")
    providers = data.get("providers", [])

    print("=== Provider List ===")
    print(f"Schema version: {sv}")
    print()
    if not providers:
        print("No providers found.")
    else:
        for p in providers:
            aliases_str = ""
            if p.get("aliases"):
                aliases_str = "  aliases: [" + ", ".join(p["aliases"]) + "]"
            print(f"  {p['id']:12s} {p['name']:30s} auth: {p['auth_type']}{aliases_str}")
    print()


def print_provider_show_text(data: Dict[str, Any]) -> None:
    """Print a single provider in human-readable format."""
    if not data:
        print("Provider not found.")
        return

    print("=== Provider Detail ===")
    print()
    for key in ("id", "name", "auth_type", "auth_key_name", "base_url"):
        val = data.get(key, "")
        if val == "" and key == "base_url":
            val = "(default)"
        print(f"  {key:15s} {val}")
    aliases = data.get("aliases", [])
    if aliases:
        print(f"  aliases         [{', '.join(aliases)}]")
    print()


def print_provider_add_text(data: Dict[str, Any]) -> None:
    action = "updated" if data.get("overwritten") else "added"
    print(f"Provider '{data.get('id', '')}' {action}.")
    print(f"Catalog: {data.get('catalog', '')}")
