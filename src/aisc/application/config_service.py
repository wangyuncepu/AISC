"""Config service — read-only validate & effective (S5.2 ora-7 final)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aisc.domain.config import (
    IssueSeverity, PlatformPathConfig, PathPolicy, SchemaIssue,
)
from aisc.schemas.config_schema import validate_config
from aisc.adapters.config_reader import (
    safe_read_config_bytes, parse_config_json, ReadError,
    check_root_exists, check_dir_component,
)

# ---------------------------------------------------------------------------
# Stable status literals — external contract (frozen set)
# ---------------------------------------------------------------------------

STATUS_LOADED = "loaded"
STATUS_MISSING = "missing"
STATUS_PERMISSION_DENIED = "permission_denied"
STATUS_INVALID_SOURCE = "invalid_source"   # structural
STATUS_ERROR = "error"

ERR_CONFIG_INVALID = "AISC_ERR_CONFIG_INVALID"
ERR_CONFIG_MISSING = "AISC_ERR_CONFIG_MISSING"
ERR_PERMISSION_DENIED = "AISC_ERR_PERMISSION_DENIED"
ERR_GENERAL = "AISC_ERR_GENERAL"

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceInfo:
    kind: str; path: str; status: str

@dataclass(frozen=True)
class ConfigIssue:
    severity: str; source: str; path: str; reason_code: str; message: str

@dataclass
class ServiceResult:
    valid: bool = False
    exit_code: int = 0
    error_code: str = ""
    error_message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_src(kind, path, status):
    return SourceInfo(kind=kind, path=path, status=status)

def _early_err(code, errc, msg, user_src, ws_src):
    """Build an early ServiceResult with exactly [user, workspace] sources."""
    return ServiceResult(valid=False, exit_code=code, error_code=errc,
                         error_message=msg,
                         data={"valid": False,
                               "sources": [_src_d(user_src), _src_d(ws_src)],
                               "issues": []})

def _mk_iss(severity, source, path, rc, msg):
    return ConfigIssue(severity=severity, source=source, path=path, reason_code=rc, message=msg)

def _src_d(si): return {"kind": si.kind, "path": si.path, "status": si.status}
def _iss_d(ci): return {"severity": ci.severity, "source": ci.source, "path": ci.path,
                         "reason_code": ci.reason_code, "message": ci.message}


# ---------------------------------------------------------------------------
# Content error types — structured, never echoes input
# ---------------------------------------------------------------------------

class ContentErrorKind:
    INVALID_UTF8 = "invalid_utf8"
    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    CONFIG_NOT_OBJECT = "config_not_object"
    JSON_DEPTH_LIMIT = "json_depth_limit"
    JSON_NODE_LIMIT = "json_node_limit"
    JSON_STRING_LIMIT = "json_string_limit"


_CE_MESSAGES = {
    ContentErrorKind.INVALID_UTF8: "Config file is not valid UTF-8",
    ContentErrorKind.INVALID_JSON: "Invalid JSON in config file",
    ContentErrorKind.DUPLICATE_KEY: "Duplicate key in config JSON",
    ContentErrorKind.CONFIG_NOT_OBJECT: "Config must be a JSON object",
    ContentErrorKind.JSON_DEPTH_LIMIT: "JSON nesting too deep",
    ContentErrorKind.JSON_NODE_LIMIT: "JSON node limit exceeded",
    ContentErrorKind.JSON_STRING_LIMIT: "JSON string too long",
}


def _classify_content_error(exc: Exception) -> Optional[str]:
    """Classify a parser exception into a ContentErrorKind string."""
    msg = str(exc)
    if isinstance(exc, UnicodeDecodeError):
        return ContentErrorKind.INVALID_UTF8
    if "Duplicate key" in msg:
        return ContentErrorKind.DUPLICATE_KEY
    if "not a JSON object" in msg or "not object" in msg.lower() or "Config must be a JSON object" in msg:
        return ContentErrorKind.CONFIG_NOT_OBJECT
    if "too deep" in msg.lower() or "nesting too deep" in msg.lower():
        return ContentErrorKind.JSON_DEPTH_LIMIT
    if "node limit" in msg.lower():
        return ContentErrorKind.JSON_NODE_LIMIT
    if "too long" in msg.lower() or "string too long" in msg.lower():
        return ContentErrorKind.JSON_STRING_LIMIT
    if isinstance(exc, ValueError):
        return ContentErrorKind.INVALID_JSON
    return None


# ---------------------------------------------------------------------------
# Read one layer — returns (data, source_info, content_error_kind)
# ---------------------------------------------------------------------------

def _read_layer(file_path: Path, is_explicit: bool, kind: str) -> Tuple[Optional[dict], SourceInfo, Optional[str]]:
    """Read/parse one config file.  content_error_kind is None on success."""
    fp = str(file_path)
    try:
        raw = safe_read_config_bytes(file_path)
    except FileNotFoundError:
        if is_explicit: raise
        return None, _mk_src(kind, fp, STATUS_MISSING), None
    except PermissionError:
        return None, _mk_src(kind, fp, STATUS_PERMISSION_DENIED), None
    except ReadError:
        return None, _mk_src(kind, fp, STATUS_INVALID_SOURCE), None
    except OSError:
        return None, _mk_src(kind, fp, STATUS_ERROR), None

    try:
        data = parse_config_json(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        ce = _classify_content_error(exc)
        return None, _mk_src(kind, fp, STATUS_LOADED), ce  # external status = loaded
    return data, _mk_src(kind, fp, STATUS_LOADED), None


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------

def _overlay(base: dict, overrides: dict) -> dict:
    result = dict(base)
    if "defaults" in overrides and isinstance(overrides["defaults"], dict):
        od = overrides["defaults"]
        cur = result.get("defaults", {})
        if not isinstance(cur, dict): cur = {}
        result["defaults"] = {**cur}
        for k in ("profile", "network"):
            if k in od: result["defaults"][k] = od[k]
    return result


# ---------------------------------------------------------------------------
# Unified core — validate + effective share reader/validation logic
# ---------------------------------------------------------------------------

def _read_layers(
    explicit_config, workspace, home, env, platform_name,
) -> Tuple[Optional[ServiceResult], Optional[dict], Optional[dict],
           List[SourceInfo], List[ConfigIssue]]:
    """Read both config layers.  Returns early ServiceResult on fatal error,
    else (user_data, ws_data, sources, issues).  Always exactly 2 sources."""
    # --- Establish user_cfg_path before any early return ---
    if explicit_config:
        explicit_config = os.path.abspath(explicit_config)
        user_cfg_path = Path(explicit_config)
        pp = PlatformPathConfig(config_dir="", state_dir="")
        user_status = STATUS_MISSING  # not yet read, but path is known
    else:
        try:
            pp = _resolve_platform(home, env, platform_name)
        except ReadError:
            return (_early_err(1, ERR_GENERAL, "Platform path error",
                               _mk_src("user", "", STATUS_MISSING),
                               _mk_src("workspace", "", STATUS_MISSING)),
                    None, None, [], [])
        except PermissionError:
            return (_early_err(9, ERR_PERMISSION_DENIED, "Permission denied accessing platform",
                               _mk_src("user", "", STATUS_PERMISSION_DENIED),
                               _mk_src("workspace", "", STATUS_MISSING)),
                    None, None, [], [])
        except OSError:
            return (_early_err(1, ERR_GENERAL, "Cannot access platform config root",
                               _mk_src("user", "", STATUS_ERROR),
                               _mk_src("workspace", "", STATUS_MISSING)),
                    None, None, [], [])
        user_cfg_path = Path(os.path.join(pp.config_dir, "config.json"))
    ws_abs = os.path.abspath(workspace) if workspace else os.path.abspath(os.getcwd())
    policy = PathPolicy(platform=pp, workspace=ws_abs, aisc_root=None)

    # --- Validate workspace root ---
    try:
        check_root_exists(ws_abs)
    except FileNotFoundError:
        return (_early_err(7, ERR_CONFIG_MISSING, "Workspace root not found",
                           _mk_src("user", str(user_cfg_path), "missing"),
                           _mk_src("workspace", ws_abs, STATUS_MISSING)),
                None, None, [], [])
    except ReadError:
        return (_early_err(1, ERR_GENERAL, "Workspace root is a symlink",
                           _mk_src("user", str(user_cfg_path), "missing"),
                           _mk_src("workspace", ws_abs, STATUS_INVALID_SOURCE)),
                None, None, [], [])
    except PermissionError:
        return (_early_err(9, ERR_PERMISSION_DENIED, "Permission denied accessing workspace",
                           _mk_src("user", str(user_cfg_path), "missing"),
                           _mk_src("workspace", ws_abs, STATUS_PERMISSION_DENIED)),
                None, None, [], [])
    except OSError:
        return (_early_err(1, ERR_GENERAL, "Cannot access workspace root",
                           _mk_src("user", str(user_cfg_path), "missing"),
                           _mk_src("workspace", ws_abs, STATUS_ERROR)),
                None, None, [], [])
    # check_root_exists already verified existence + directory — no second check needed

    # --- Platform config root (only when auto-detecting user config) ---
    if not explicit_config:
        try:
            check_root_exists(pp.config_dir)
        except FileNotFoundError:
            pass  # auto-detected platform root missing → user config will be missing, OK
        except ReadError:
            return (_early_err(1, ERR_GENERAL, "Platform config root is a symlink",
                               _mk_src("user", str(user_cfg_path), STATUS_INVALID_SOURCE),
                               _mk_src("workspace", _ws_path_str(ws_abs), STATUS_MISSING)),
                    None, None, [], [])
        except PermissionError:
            return (_early_err(9, ERR_PERMISSION_DENIED, "Permission denied accessing platform config root",
                               _mk_src("user", str(user_cfg_path), STATUS_PERMISSION_DENIED),
                               _mk_src("workspace", _ws_path_str(ws_abs), STATUS_MISSING)),
                    None, None, [], [])
        except OSError:
            return (_early_err(1, ERR_GENERAL, "Cannot access platform config root",
                               _mk_src("user", str(user_cfg_path), STATUS_ERROR),
                               _mk_src("workspace", _ws_path_str(ws_abs), STATUS_MISSING)),
                    None, None, [], [])

    # --- Read user layer ---
    try:
        user_data, user_src, user_ce = _read_layer(user_cfg_path, bool(explicit_config), "user")
    except FileNotFoundError:
        return (ServiceResult(valid=False, exit_code=7, error_code=ERR_CONFIG_MISSING,
                error_message="Explicit config file not found",
                data={"valid": False, "sources": [
                    _src_d(_mk_src("user", str(user_cfg_path), "missing")),
                    _src_d(_mk_src("workspace", _ws_path_str(ws_abs), STATUS_MISSING)),
                ], "issues": []}), None, None, [], [])
    except PermissionError:
        return (ServiceResult(valid=False, exit_code=9, error_code=ERR_PERMISSION_DENIED,
                error_message="Permission denied reading user config",
                data={"valid": False, "sources": [
                    _src_d(_mk_src("user", str(user_cfg_path), STATUS_PERMISSION_DENIED)),
                    _src_d(_mk_src("workspace", _ws_path_str(ws_abs), STATUS_MISSING)),
                ], "issues": []}), None, None, [], [])

    # --- Read workspace layer ---
    ws_path = _ws_path_str(ws_abs)
    ws_file_path = Path(ws_path)
    legacy_ws_file = Path(ws_abs) / ".aisc" / "config.json"
    if ws_file_path == legacy_ws_file:
        # Structural reparse check only applies to the legacy layout; the
        # data-root path was validated by the resolver at resolve time.
        try:
            check_dir_component(str(ws_file_path.parent.parent), ".aisc")
        except FileNotFoundError:
            pass  # .aisc doesn't exist → config.json will be missing (handled by _read_layer)
        except ReadError:
            return (_early_err(1, ERR_GENERAL, "Workspace config component is a symlink",
                               user_src,
                               _mk_src("workspace", ws_path, STATUS_INVALID_SOURCE)),
                    None, None, [], [])
        except PermissionError:
            return (_early_err(9, ERR_PERMISSION_DENIED, "Permission denied accessing workspace config",
                               user_src,
                               _mk_src("workspace", ws_path, STATUS_PERMISSION_DENIED)),
                    None, None, [], [])
        except OSError:
            return (_early_err(1, ERR_GENERAL, "Cannot access workspace config component",
                               user_src,
                               _mk_src("workspace", ws_path, STATUS_ERROR)),
                    None, None, [], [])

    ws_data, ws_src, ws_ce = _read_layer(ws_file_path, False, "workspace")

    # Build sources and issues
    sources = [user_src, ws_src]
    issues: List[ConfigIssue] = []

    # Content errors for user
    if user_ce:
        issues.append(_mk_iss("error", "user", "(root)", user_ce,
                              _CE_MESSAGES.get(user_ce, "Content error")))
    # Content errors for workspace
    if ws_ce:
        issues.append(_mk_iss("error", "workspace", "(root)", ws_ce,
                              _CE_MESSAGES.get(ws_ce, "Content error")))

    return None, user_data, ws_data, sources, issues


def _ws_path_str(ws_abs: str) -> str:
    """Workspace config layer path (Stage 7).

    Canonical: ``<data-root>/workspaces/<hash>/config.json``. The legacy
    ``<ws>/.aisc/config.json`` remains the read fallback until migrations
    catch up. This is a read-only layer — if the data root is unusable we
    degrade to the legacy path instead of failing the whole command
    (writes go through ``workspace_state_dir`` and fail closed there).
    """
    canonical = None
    try:
        from aisc.application.data_root import DataRootResolver

        resolved = DataRootResolver().resolve(Path(ws_abs))
        canonical = resolved.workspace_dir / "config.json"
        if canonical.is_file():
            return str(canonical)
    except Exception:
        canonical = None
    legacy = Path(ws_abs) / ".aisc" / "config.json"
    # Existing legacy wins over an absent canonical (transition read);
    # otherwise report the canonical location (honest fresh state).
    if legacy.is_file():
        return str(legacy)
    return str(canonical) if canonical is not None else str(legacy)


def _finalize_classify(valid, sources, issues, effective=None, provenance=None):
    """Determine exit code and build ServiceResult."""
    has_error = any(i.severity == "error" for i in issues)
    structural = any(s.status in (STATUS_INVALID_SOURCE, STATUS_ERROR) for s in sources)
    perm = any(s.status == STATUS_PERMISSION_DENIED for s in sources)

    if structural:
        ec, errc, msg = 1, ERR_GENERAL, "Structural error reading config"
    elif perm:
        ec, errc, msg = 9, ERR_PERMISSION_DENIED, "Permission denied"
    elif has_error:
        ec, errc, msg = 6, ERR_CONFIG_INVALID, "Config validation failed"
    else:
        ec, errc, msg = 0, "", ""

    d: dict = {"valid": not (has_error or structural or perm),
               "sources": [_src_d(s) for s in sources],
               "issues": [_iss_d(i) for i in issues]}
    if provenance is not None:
        d["effective"] = effective
        d["provenance"] = provenance
    return ServiceResult(valid=d["valid"], exit_code=ec, error_code=errc,
                         error_message=msg, data=d)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def run_config_validate(*, explicit_config=None, workspace=None, home=None,
                        env=None, platform_name=None) -> ServiceResult:
    early, user_data, ws_data, sources, issues = _read_layers(
        explicit_config, workspace, home, env, platform_name)
    if early: return early

    if user_data is not None:
        for si in validate_config(user_data, is_workspace=False):
            issues.append(ConfigIssue(severity=si.severity.value, source="user",
                          path=si.path, reason_code=si.reason_code, message=si.message))
    if ws_data is not None:
        for si in validate_config(ws_data, is_workspace=True):
            issues.append(ConfigIssue(severity=si.severity.value, source="workspace",
                          path=si.path, reason_code=si.reason_code, message=si.message))
    return _finalize_classify(True, sources, issues)


def run_config_effective(*, explicit_config=None, workspace=None, home=None,
                         env=None, platform_name=None) -> ServiceResult:
    early, user_data, ws_data, sources, issues = _read_layers(
        explicit_config, workspace, home, env, platform_name)
    if early:
        # Early result from validate path — add effective/provenance fields
        early.data["effective"] = None
        early.data["provenance"] = {}
        return early

    if user_data is not None:
        for si in validate_config(user_data, is_workspace=False):
            issues.append(ConfigIssue(severity=si.severity.value, source="user",
                          path=si.path, reason_code=si.reason_code, message=si.message))
    if ws_data is not None:
        for si in validate_config(ws_data, is_workspace=True):
            issues.append(ConfigIssue(severity=si.severity.value, source="workspace",
                          path=si.path, reason_code=si.reason_code, message=si.message))

    has_any = any(s.status not in (STATUS_LOADED, STATUS_MISSING) for s in sources) or \
              any(i.severity == "error" for i in issues)
    if has_any:
        return _finalize_classify(False, sources, issues, effective=None, provenance={})

    effective = {
        "schema_version": 1,
        "defaults": {"profile": "safe", "network": "direct"},
    }
    provenance: dict = {"defaults.profile": "default", "defaults.network": "default"}

    if user_data is not None:
        effective = _overlay(effective, user_data)
        if "defaults" in user_data and isinstance(user_data["defaults"], dict):
            ud = user_data["defaults"]
            if "profile" in ud: provenance["defaults.profile"] = "user"
            if "network" in ud: provenance["defaults.network"] = "user"
    if ws_data is not None:
        effective = _overlay(effective, ws_data)
        if "defaults" in ws_data and isinstance(ws_data["defaults"], dict):
            wd = ws_data["defaults"]
            if "profile" in wd: provenance["defaults.profile"] = "workspace"
            if "network" in wd: provenance["defaults.network"] = "workspace"
    return _finalize_classify(True, sources, issues, effective=effective, provenance=provenance)


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------

def _user_config_path(policy: PathPolicy) -> Path:
    return Path(os.path.join(policy.platform.config_dir, "config.json"))

def _resolve_platform(home=None, env=None, platform=None):
    if home is None: home = os.path.expanduser("~")
    if env is None: env = dict(os.environ)
    if platform is None: import sys; platform = sys.platform
    if platform == "win32":
        appdata = env.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        config_dir = os.path.join(appdata, "aisc")
    elif platform == "darwin":
        config_dir = os.path.join(home, "Library", "Application Support", "aisc")
    else:
        xdg = env.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
        if not os.path.isabs(xdg):
            raise ReadError("structural_error", "XDG_CONFIG_HOME must be absolute")
        config_dir = os.path.join(xdg, "aisc")
    return PlatformPathConfig(config_dir=config_dir, state_dir="")
