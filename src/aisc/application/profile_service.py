"""Profile service — read-only ``profile list`` and ``profile show``.

First version: only built-in ``safe`` and ``unsafe``.
No user-defined profiles, no confirmation flow, no run integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Built-in profile definitions (per §9.2 of PLAN-p3-unified-cli.md)
# ---------------------------------------------------------------------------

_BUILTIN_PROFILES: Dict[str, Dict[str, Any]] = {
    "safe": {
        "name": "safe",
        "description": "Secure defaults (default profile)",
        "dangerously_skip_permissions": False,
    },
    "unsafe": {
        "name": "unsafe",
        "description": "Explicit dangerous permissions for trusted projects",
        "dangerously_skip_permissions": True,
    },
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ProfileListResult:
    data: Dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0
    error_code: str = ""
    error_message: str = ""


@dataclass
class ProfileShowResult:
    data: Dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0
    error_code: str = ""
    error_message: str = ""


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

def run_profile_list() -> ProfileListResult:
    """Return all built-in profiles as a list."""
    profiles: List[Dict[str, Any]] = []
    for key in ("safe", "unsafe"):
        profiles.append(dict(_BUILTIN_PROFILES[key]))

    data: Dict[str, Any] = {"profiles": profiles}
    return ProfileListResult(data=data, exit_code=0)


def run_profile_show(name: str) -> ProfileShowResult:
    """Return a single built-in profile by name."""
    profile = _BUILTIN_PROFILES.get(name)
    if profile is None:
        return ProfileShowResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Profile not found: {name}",
        )

    data = dict(profile)
    return ProfileShowResult(data=data, exit_code=0)
