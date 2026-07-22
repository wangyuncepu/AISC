"""Profile service — read-only ``profile list`` and ``profile show``.

Reads profiles from ~/.aisc/profiles.json with fallback to built-in definitions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Built-in profile definitions (fallback when profiles.json not found)
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
# Profile loading from .aisc/profiles.json
# ---------------------------------------------------------------------------

def _profiles_path(home: Optional[str] = None) -> Path:
    """Return the path to profiles.json."""
    home_path = Path(home).expanduser() if home is not None else Path.home()
    return home_path / ".aisc" / "profiles.json"


def _load_profiles(home: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Load profiles from ~/.aisc/profiles.json, fallback to built-in."""
    path = _profiles_path(home)
    try:
        if not path.is_file():
            return _BUILTIN_PROFILES
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
            return _BUILTIN_PROFILES
        return data["profiles"]
    except (OSError, ValueError, json.JSONDecodeError):
        return _BUILTIN_PROFILES


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

def run_profile_list(home: Optional[str] = None) -> ProfileListResult:
    """Return all profiles as a list."""
    profiles_dict = _load_profiles(home)
    profiles: List[Dict[str, Any]] = []
    for key in sorted(profiles_dict.keys()):
        profiles.append(dict(profiles_dict[key]))

    data: Dict[str, Any] = {"profiles": profiles}
    return ProfileListResult(data=data, exit_code=0)


def run_profile_show(name: str, home: Optional[str] = None) -> ProfileShowResult:
    """Return a single profile by name."""
    profiles_dict = _load_profiles(home)
    profile = profiles_dict.get(name)
    if profile is None:
        return ProfileShowResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Profile not found: {name}",
        )

    data = dict(profile)
    return ProfileShowResult(data=data, exit_code=0)
