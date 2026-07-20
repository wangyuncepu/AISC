"""Provider service — read-only ``provider list`` from canonical catalog.

Reads ``<aisc-root>/container/providers.json`` using the existing strict
catalog loader.  Does NOT read user config, write files, or fall back to
hard-coded data.
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from aisc.application.resources import locate_aisc_root, _RootSourceError


@dataclass
class ProviderListResult:
    """Structured result for ``provider list``."""

    data: Dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0
    error_code: str = ""
    error_message: str = ""


@dataclass
class ProviderShowResult:
    """Structured result for ``provider show``."""

    data: Dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0
    error_code: str = ""
    error_message: str = ""


def run_provider_list(explicit_root: Optional[str] = None) -> ProviderListResult:
    """Read the canonical provider catalog and return a structured result.

    Uses ``locate_aisc_root`` to find the AISC root, then reads
    ``container/providers.json`` with the existing strict catalog loader.
    """
    # Locate root
    try:
        root = locate_aisc_root(explicit_root=explicit_root)
    except _RootSourceError as exc:
        return ProviderListResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=str(exc),
        )

    if root is None:
        return ProviderListResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=(
                "AISC root not found. Use --aisc-root to specify a path, "
                "or run from within an AISC repository."
            ),
        )

    catalog_path = root / "container" / "providers.json"

    # Read raw bytes
    try:
        raw = catalog_path.read_bytes()
    except FileNotFoundError:
        return ProviderListResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Provider catalog not found: {catalog_path}",
        )
    except PermissionError:
        return ProviderListResult(
            data={},
            exit_code=9,
            error_code="AISC_ERR_PERMISSION_DENIED",
            error_message=f"Permission denied reading: {catalog_path}",
        )
    except OSError as exc:
        return ProviderListResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Cannot read provider catalog: {exc}",
        )

    # Use existing strict catalog loader
    from aisc.adapters.config_source import load_provider_catalog

    try:
        catalog = load_provider_catalog(raw)
    except ValueError as exc:
        return ProviderListResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Invalid provider catalog: {exc}",
        )

    # Build result data
    sv = catalog.schema_version
    providers: List[Dict[str, Any]] = []
    for key in sorted(catalog.providers.keys()):
        spec = catalog.providers[key]
        providers.append({
            "id": spec.id,
            "name": spec.name,
            "auth_type": spec.auth_type,
            "auth_key_name": spec.auth_key_name,
            "base_url": spec.base_url,
            "aliases": list(spec.aliases),
        })

    data: Dict[str, Any] = {
        "schema_version": sv,
        "providers": providers,
    }
    return ProviderListResult(data=data, exit_code=0)


def run_provider_show(
    name: str,
    explicit_root: Optional[str] = None,
) -> ProviderShowResult:
    """Look up a single provider by id or alias and return its full details.

    Matches exactly against ``spec.id`` first, then ``spec.aliases``.
    Does NOT read user config, write files, or access secrets.
    """
    # Locate root
    try:
        root = locate_aisc_root(explicit_root=explicit_root)
    except _RootSourceError as exc:
        return ProviderShowResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=str(exc),
        )

    if root is None:
        return ProviderShowResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=(
                "AISC root not found. Use --aisc-root to specify a path, "
                "or run from within an AISC repository."
            ),
        )

    catalog_path = root / "container" / "providers.json"

    # Read raw bytes
    try:
        raw = catalog_path.read_bytes()
    except FileNotFoundError:
        return ProviderShowResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Provider catalog not found: {catalog_path}",
        )
    except PermissionError:
        return ProviderShowResult(
            data={},
            exit_code=9,
            error_code="AISC_ERR_PERMISSION_DENIED",
            error_message=f"Permission denied reading: {catalog_path}",
        )
    except OSError as exc:
        return ProviderShowResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Cannot read provider catalog: {exc}",
        )

    # Load catalog
    from aisc.adapters.config_source import load_provider_catalog

    try:
        catalog = load_provider_catalog(raw)
    except ValueError as exc:
        return ProviderShowResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Invalid provider catalog: {exc}",
        )

    # Search by id first, then by alias
    spec = None
    if name in catalog.providers:
        spec = catalog.providers[name]
    else:
        for key, candidate in catalog.providers.items():
            if name in candidate.aliases:
                spec = candidate
                break

    if spec is None:
        return ProviderShowResult(
            data={},
            exit_code=1,
            error_code="AISC_ERR_GENERAL",
            error_message=f"Provider not found: {name}",
        )

    data: Dict[str, Any] = {
        "id": spec.id,
        "name": spec.name,
        "auth_type": spec.auth_type,
        "auth_key_name": spec.auth_key_name,
        "base_url": spec.base_url,
        "aliases": list(spec.aliases),
    }
    return ProviderShowResult(data=data, exit_code=0)
