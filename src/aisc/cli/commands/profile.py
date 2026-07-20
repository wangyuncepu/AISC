"""CLI command implementations for ``aisc profile list`` and ``aisc profile show``.

Read-only — returns built-in safe/unsafe profiles only.
No user-defined profiles, no confirmation flow, no run integration.
"""

from __future__ import annotations

from typing import Any, Dict

from aisc.application.profile_service import (
    run_profile_list, ProfileListResult,
    run_profile_show, ProfileShowResult,
)


def cmd_profile_list() -> ProfileListResult:
    """Execute ``profile list``."""
    return run_profile_list()


def cmd_profile_show(name: str) -> ProfileShowResult:
    """Execute ``profile show NAME``."""
    return run_profile_show(name)


def print_profile_list_text(data: Dict[str, Any]) -> None:
    """Print profile list in human-readable format."""
    profiles = data.get("profiles", [])
    print("=== Profile List ===")
    print()
    if not profiles:
        print("No profiles found.")
    else:
        for p in profiles:
            print(f"  {p['name']:12s} dangerously_skip_permissions={p['dangerously_skip_permissions']}")
            print(f"              {p['description']}")
            print()
    print()


def print_profile_show_text(data: Dict[str, Any]) -> None:
    """Print a single profile in human-readable format."""
    if not data:
        print("Profile not found.")
        return
    print("=== Profile Detail ===")
    print()
    for key in ("name", "description"):
        print(f"  {key:30s} {data.get(key, '')}")
    print(f"  dangerously_skip_permissions  {data.get('dangerously_skip_permissions', False)}")
    print()
