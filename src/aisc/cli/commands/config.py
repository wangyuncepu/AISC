"""CLI command implementations for ``aisc config validate`` and ``aisc config effective``.

Thin wrapper — all classification logic lives in config_service.ServiceResult.
"""

from __future__ import annotations

import json as _json
import sys
from typing import Any, Dict, Optional

from aisc.application.config_service import (
    run_config_validate, run_config_effective, ServiceResult,
    ERR_CONFIG_INVALID, ERR_CONFIG_MISSING, ERR_PERMISSION_DENIED, ERR_GENERAL,
)


def cmd_config_validate(*, explicit_config=None, workspace=None, home=None,
                        env=None, platform=None) -> ServiceResult:
    return run_config_validate(explicit_config=explicit_config, workspace=workspace,
                               home=home, env=env, platform_name=platform)


def cmd_config_effective(*, explicit_config=None, workspace=None, home=None,
                         env=None, platform=None) -> ServiceResult:
    return run_config_effective(explicit_config=explicit_config, workspace=workspace,
                                home=home, env=env, platform_name=platform)


# ---------------------------------------------------------------------------
# Text output helpers
# ---------------------------------------------------------------------------

def _escape_path(p: str) -> str:
    """Escape control characters in path for safe text output."""
    if not p:
        return ""
    out = []
    for ch in p:
        cp = ord(ch)
        if cp < 0x20 or cp == 0x7f:
            out.append(f"\\x{cp:02x}")
        elif cp == 0x5c:
            out.append("\\\\")
        else:
            out.append(ch)
    return "".join(out)


def print_validate_text(result: ServiceResult) -> None:
    """Print validate result (stdout).  Non-zero also prints stderr summary."""
    print("=== Config Validate ===")
    print()
    for s in result.data.get("sources", []):
        label = s.get("status", "?").upper()
        print(f"  [{label}] {_escape_path(s.get('path', ''))}")
        if s.get("error"):
            print(f"         {s['error']}")
    print()
    print(f"Valid: {'yes' if result.valid else 'NO'}")
    issues = result.data.get("issues", [])
    if issues:
        print()
        print("Issues:")
        for i in issues:
            sev = i["severity"].upper()
            print(f"  [{sev}] {i['source']}:{i['path']}: {i['message']}")
    print()

    if result.exit_code != 0:
        print(f"Error: {result.error_message}", file=sys.stderr)


def print_effective_text(result: ServiceResult) -> None:
    """Print effective result (stdout).  Non-zero also prints stderr summary."""
    print("=== Config Effective ===")
    print()
    for s in result.data.get("sources", []):
        label = s.get("status", "?").upper()
        print(f"  [{label}] {_escape_path(s.get('path', ''))}")
    print()
    eff = result.data.get("effective")
    if eff is None:
        print("Effective: (none)")
    else:
        print("Effective:")
        print(_json.dumps(eff, indent=2, ensure_ascii=False))
    prov = result.data.get("provenance", {})
    if prov:
        print()
        print("Provenance:")
        for k, v in sorted(prov.items()):
            print(f"  {k}: {v}")
    issues = result.data.get("issues", [])
    if issues:
        print()
        print("Issues:")
        for i in issues:
            sev = i["severity"].upper()
            print(f"  [{sev}] {i['source']}:{i['path']}: {i['message']}")
    print()

    if result.exit_code != 0:
        print(f"Error: {result.error_message}", file=sys.stderr)
