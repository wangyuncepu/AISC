"""State file adapter — read/write ``.aisc/state.env`` for container discovery.

Provides atomic writes via temp-file + rename. Only allows known safe keys.
Preserves existing keys, comments, and blank lines where practical.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Known safe keys — only these may be written to state.env.
# Container-name keys (CONTAINER_NAME, IMAGE) live in containers.json now;
# state.env retains only boolean flag keys.
_KNOWN_KEYS = frozenset({
    "DO_RUN",
    "PROXY_ENABLED",
})

# Regex for valid key names: uppercase alphanumeric + underscore, starts with letter
_VALID_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Shell metacharacters / injection characters rejected from all values
_SHELL_META_RE = re.compile(r'[\r\n\0`$\'";&|<>]')

# Boolean flags
_BOOL_VALUES = frozenset({"0", "1"})


def _validate_value(key: str, value: str) -> None:
    """Validate *value* against field-specific rules plus shell-metacharacter ban.

    Raises ValueError with a descriptive message on any violation.
    """
    if not value:
        return

    # --- shell metacharacter / whitespace / control check (all keys) ---
    if _SHELL_META_RE.search(value) or " " in value or "\t" in value:
        raise ValueError(
            f"State value for '{key}' contains prohibited characters "
            f"(shell metacharacters, whitespace, or control chars)"
        )

    # --- field-specific checks ---
    if key in ("DO_RUN", "PROXY_ENABLED"):
        if value not in _BOOL_VALUES:
            raise ValueError(
                f"{key} must be 0 or 1, got: {value!r}"
            )


def _parse_state_file(path: Path) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Parse state.env into (key, value, raw_comment) triples.

    Returns a list of (key, value, comment) where:
    - key: the KEY name (empty string for comment/blank lines)
    - value: the value after '=' (None for comments)
    - comment: full raw line text for comments/blanks (None for key=value lines)

    Duplicate keys use deterministic **last-wins** semantics (consistent with
    shell ``source`` / ``set -a`` behaviour).
    """
    entries: List[Tuple[str, Optional[str], Optional[str]]] = []
    if not path.is_file():
        return entries

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.rstrip("\n\r")
            # Comments and blank lines preserved as-is
            if not stripped or stripped.startswith("#"):
                entries.append(("", None, stripped))
                continue
            # Parse KEY=VALUE
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                if _VALID_KEY_RE.match(key):
                    # Last-wins: replace previous entry for same key
                    for i in range(len(entries) - 1, -1, -1):
                        if entries[i][0] == key:
                            entries[i] = (key, value, None)
                            break
                    else:
                        entries.append((key, value, None))
                else:
                    # Malformed key — preserve as comment to avoid corruption
                    entries.append(("", None, stripped))
            else:
                # Line without '=' — treat as comment
                entries.append(("", None, stripped))
    return entries


def read_state_key(root: Path, key: str) -> Optional[str]:
    """Read a single key from ``<root>/state.env`` (Stage 7: *root* is the
    state directory itself — data-root ``workspaces/<hash>/runtime`` or the
    legacy ``<workspace>/.aisc``; resolved by callers, never appended here).

    Returns the value string, or ``None`` if the key or file is absent.
    Duplicate keys resolve to last occurrence (shell-consistent).
    """
    state_path = root / "state.env"
    entries = _parse_state_file(state_path)
    # Walk backwards to find last occurrence (last-wins)
    for entry_key, value, _comment in reversed(entries):
        if entry_key == key:
            return value
    return None


def write_state_keys(root: Path, updates: Dict[str, str]) -> None:
    """Atomically write key=value pairs into ``<root>/.aisc/state.env``.

    Preserves existing keys and comments. Only writes keys that are in
    ``_KNOWN_KEYS``.  Raises ``ValueError`` for unknown keys or values
    containing ``\\r``, ``\\n``, or NUL.  Silently skips keys with empty values.

    Uses temp-file + rename for atomicity.
    Errors during write do not corrupt the existing file.
    """
    for k in updates:
        if k not in _KNOWN_KEYS:
            raise ValueError(
                f"Unknown state key '{k}'. Allowed: {sorted(_KNOWN_KEYS)}"
            )

    # Validate values before touching filesystem
    for k, v in updates.items():
        _validate_value(k, v)

    state_dir = root  # Stage 7: root IS the state directory
    state_dir.mkdir(parents=True, exist_ok=True)

    state_path = state_dir / "state.env"

    # Read existing entries
    existing = _parse_state_file(state_path) if state_path.is_file() else []

    # Build merged: last-wins for duplicate keys, update existing, keep others
    new_entries: List[Tuple[str, Optional[str], Optional[str]]] = []
    seen_keys: set = set()

    for entry_key, value, comment in existing:
        if entry_key and entry_key in updates:
            new_val = updates[entry_key]
            if new_val:
                new_entries.append((entry_key, new_val, None))
            else:
                new_entries.append((entry_key, value, None))
            seen_keys.add(entry_key)
        else:
            new_entries.append((entry_key, value, comment))

    # Append any new keys not already present
    for k, v in updates.items():
        if k not in seen_keys and v:
            new_entries.append((k, v, None))

    # Write atomically via temp file
    fd, tmp_path = tempfile.mkstemp(
        prefix=".state_", dir=str(state_dir), text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for entry_key, value, comment in new_entries:
                if comment is not None:
                    f.write(comment + "\n")
                elif entry_key:
                    f.write(f"{entry_key}={value}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(state_path))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
