#!/usr/bin/env python3
"""CLI-A07 sidecar verification: clean-room smoke, manifest, atomic upgrade.

A PyInstaller one-file sidecar must be verifiable standalone (clean-room: no
source checkout, no deps) and its replacement must be atomic — a failed
upgrade must leave the previous version runnable and roll back.

Operations
----------
smoke <binary> [--triple T]
    Run ``<binary> version --format json`` in a clean subprocess, assert the
    aisc.cli/v1 envelope (protocol, exit 0, capabilities), and print a manifest
    entry::

        {"schema_version": 1, "triple": T, "arch": ..., "version": ...,
         "sha256": ..., "size": ...}

check <manifest.json> <binary>
    Validate a binary against a manifest: sha256, size, arch, version.

atomic-upgrade <new-manifest.json> <new-binary> <target-binary> [--keep-backup]
    Simulate the release-time upgrade with rollback:
      1. verify new-binary against new-manifest (hash + it runs);
      2. copy target -> <target>.bak (the runnable previous version);
      3. atomically replace target with new-binary (os.replace);
      4. re-verify target; if verification fails, restore .bak and FAIL.
    Proves a bad upgrade leaves the old version runnable and rolls back.
    With --keep-backup the .bak is left for inspection.

Exit 0 on PASS; non-zero with a diagnostic on any failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = 1
PROTOCOL = "aisc.cli/v1"


# ---------------------------------------------------------------------------
# Pure, testable pieces
# ---------------------------------------------------------------------------

def arch_of_triple(triple: str) -> str:
    return "arm64" if triple.startswith("aarch64") else "x86_64"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_manifest(path: Path, version: str, triple: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "triple": triple,
        "arch": arch_of_triple(triple),
        "version": version,
        "sha256": sha256_of(path),
        "size": path.stat().st_size,
    }


def check_manifest(binary: Path, manifest: dict) -> tuple[bool, str]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        return False, f"unsupported manifest schema_version {manifest.get('schema_version')!r}"
    if sha256_of(binary) != manifest.get("sha256"):
        return False, f"sha256 mismatch: {binary.name}"
    if binary.stat().st_size != manifest.get("size"):
        return False, f"size mismatch: {binary.name} != {manifest.get('size')}"
    return True, "ok"


def run_smoke(binary: Path) -> dict:
    proc = subprocess.run(
        [str(binary), "version", "--format", "json"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sidecar exited {proc.returncode}: {proc.stderr[:200]}")
    env = json.loads(proc.stdout)
    if env.get("meta", {}).get("protocol") != PROTOCOL:
        raise RuntimeError(f"wrong protocol: {env.get('meta', {}).get('protocol')!r}")
    caps = env.get("data", {}).get("capabilities") or {}
    for required in ("runtime", "session", "providerStatus", "buildEvents"):
        if required not in caps:
            raise RuntimeError(f"missing capability {required}")
    version = env.get("data", {}).get("cli_version")
    if not version:
        raise RuntimeError("missing cli_version in version envelope")
    return {"version": version, "env": env}


def verify_version(binary: Path, manifest: dict) -> tuple[bool, str]:
    """Run the binary and confirm it reports the manifest's version."""
    try:
        smoke = run_smoke(binary)
    except Exception as exc:  # noqa: BLE001 - surfaced as a check failure
        return False, str(exc)
    if smoke["version"] != manifest.get("version"):
        return False, f"reported {smoke['version']!r} != manifest {manifest.get('version')!r}"
    return True, f"runs and reports {smoke['version']}"


def atomic_upgrade(new_binary: Path, new_manifest: dict, target: Path) -> tuple[bool, str]:
    """Replace *target* with *new_binary* after verifying the new binary, and
    restore the previous version if the swap does not verify. Returns
    (ok, reason). On success the previous version lives at <target>.bak."""
    # 1. verify the incoming binary before touching anything.
    ok, reason = check_manifest(new_binary, new_manifest)
    if not ok:
        return False, f"reject new binary before swap: {reason}"
    ok, reason = verify_version(new_binary, new_manifest)
    if not ok:
        return False, f"reject new binary before swap: {reason}"

    backup = target.with_name(target.name + ".bak")
    backup.write_bytes(target.read_bytes())  # runnable previous version

    os.replace(new_binary, target)  # atomic on same filesystem
    ok, reason = check_manifest(target, new_manifest)
    if not ok:
        os.replace(backup, target)  # roll back to the previous version
        return False, f"post-swap verification failed, rolled back: {reason}"
    ok, reason = verify_version(target, new_manifest)
    if not ok:
        os.replace(backup, target)
        return False, f"post-swap run failed, rolled back: {reason}"
    return True, f"upgraded to {new_manifest.get('version')} (backup kept at {backup.name})"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_smoke = sub.add_parser("smoke", help="clean-room smoke + manifest")
    p_smoke.add_argument("binary", type=Path)
    p_smoke.add_argument("--triple", default=None, help="target triple (default: none)")

    p_check = sub.add_parser("check", help="validate binary against manifest")
    p_check.add_argument("manifest", type=Path)
    p_check.add_argument("binary", type=Path)

    p_up = sub.add_parser("atomic-upgrade", help="atomic replace with rollback")
    p_up.add_argument("manifest", type=Path)
    p_up.add_argument("new_binary", type=Path)
    p_up.add_argument("target", type=Path)
    p_up.add_argument("--keep-backup", action="store_true")

    args = ap.parse_args()

    if args.cmd == "smoke":
        smoke = run_smoke(args.binary)
        triple = args.triple
        manifest = make_manifest(args.binary, smoke["version"], triple or "unknown-unknown")
        print(json.dumps(manifest, ensure_ascii=True, indent=2))
        return

    manifest = _load_manifest(args.manifest)

    if args.cmd == "check":
        ok, reason = check_manifest(args.binary, manifest)
        print(reason)
        raise SystemExit(0 if ok else 1)

    if args.cmd == "atomic-upgrade":
        ok, reason = atomic_upgrade(args.new_binary, manifest, args.target)
        print(reason)
        if ok and not args.keep_backup:
            args.target.with_name(args.target.name + ".bak").unlink(missing_ok=True)
        raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
