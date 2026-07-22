"""CLI command implementations for provider catalog management."""

from __future__ import annotations

import json as _json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from aisc.application.provider_service import (
    run_provider_list, ProviderListResult,
    run_provider_show, ProviderShowResult,
    run_provider_add, ProviderAddResult,
    user_provider_catalog_path,
    ensure_user_provider_catalog,
)


def cmd_provider_list(*, aisc_root: Optional[str] = None) -> ProviderListResult:
    """Execute ``provider list`` — read and return the canonical provider catalog."""
    return run_provider_list(explicit_root=aisc_root)


def cmd_provider_show(name: str, *, aisc_root: Optional[str] = None) -> ProviderShowResult:
    """Execute ``provider show NAME`` — look up a provider by id or alias."""
    return run_provider_show(name, explicit_root=aisc_root)


def cmd_provider_add(
    *, provider_id: str = "", name: str = "", auth_type: str = "", auth_key_name: str = "",
    base_url: str = "", aliases: Any = (), model: str = "", default_opus: str = "",
    default_sonnet: str = "", default_haiku: str = "", subagent: str = "",
    effort: str = "", compact: str = "", overwrite: bool = False,
    aisc_root: Optional[str] = None,
) -> ProviderAddResult:
    """Open providers.json in default editor for manual editing."""
    try:
        # Ensure user catalog exists (initialize from builtin if needed)
        user_catalog = ensure_user_provider_catalog(explicit_root=aisc_root)
    except Exception as e:
        return ProviderAddResult(
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Failed to initialize providers catalog: {e}",
            data={},
        )

    # Open in default editor
    system = platform.system()
    try:
        if system == "Windows":
            # Windows: use start command to open with default editor
            os.startfile(str(user_catalog))
        elif system == "Darwin":
            # macOS: use open command
            subprocess.run(["open", str(user_catalog)], check=True)
        else:
            # Linux: try xdg-open, fallback to common editors
            editor = os.environ.get("EDITOR", "")
            if editor:
                subprocess.run([editor, str(user_catalog)], check=True)
            else:
                try:
                    subprocess.run(["xdg-open", str(user_catalog)], check=True)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Fallback to common editors
                    for editor in ["nano", "vim", "vi"]:
                        try:
                            subprocess.run([editor, str(user_catalog)], check=True)
                            break
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            continue

        return ProviderAddResult(
            exit_code=0,
            data={"message": f"Opened {user_catalog} for editing", "catalog": str(user_catalog)},
        )
    except Exception as e:
        return ProviderAddResult(
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Failed to open editor: {e}",
            data={},
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
    message = data.get("message", "")
    if message:
        print(message)
    catalog = data.get("catalog", "")
    if catalog:
        print(f"\n💡 Tip: After editing, use 'aisc provider list' to verify your changes.")

