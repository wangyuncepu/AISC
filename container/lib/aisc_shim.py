#!/usr/bin/env python3
"""Container-side `aisc` shim — the artifact recording bridge (2.1.9 T3b, R1).

The image deliberately does NOT ship the full aisc CLI (no nesting; see
docs/devlog.md). Until now that meant `aisc artifact record` did not exist
inside the container, so neither claude nor codex could ever register their
deliverables — everything fell to the watcher's unattributed projection
(2.1.9 D-2 root cause). This shim implements exactly the one command the
artifact SKILL needs, writing the SAME JSONL registry the host CLI reads:

    <AISC_ARTIFACT_ROOT>/<workspace-hash16>/<session-id>.jsonl

Compatibility contract (mirrors src/aisc/.../artifact.py + domain/artifacts.py):
- record schema = ArtifactRecord (aisc.artifact/v1); host list/import reads
  these lines unchanged
- workspace hash = sha256(canonical host path)[:16] — the container gets the
  FULL 64-hex via AISC_WORKSPACE_HASH (docker create) and truncates
- idempotency: deterministic artifact_id (uuid5 of session/path/action/kind)
  so re-recording the same fact replaces its line instead of duplicating it
- atomic write (temp + os.replace) under an O_EXCL lock file with 30s stale
  detection, same as the host's cross-process protocol

IDs come from the session env (T3a defaults): AISC_RUNTIME_ID,
AISC_TERMINAL_SESSION_ID, AISC_AGENT — flags win when given.

Fail-open philosophy is NOT used here: a failed registry write must be
visible (exit 1) so the agent can fall back to listing paths in its answer.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_ROOT = "/root/.local/state/aisc-artifacts"
WORKSPACE_MOUNT = "/root/app"
AGENTS = ("claude", "codex", "bash", "cc-switch")
ACTIONS = ("created", "modified", "deleted", "renamed")
KINDS = ("deliverable", "source_change", "generated_output")
OPEN_WITH = ("preview", "system", "reveal", "none")

# uuid5 namespace for deterministic artifact ids (private to this bridge —
# host records use uuid4; both are valid UUID strings to consumers).
_ID_NAMESPACE = uuid.UUID("a15cb120-0000-4000-8000-000000000000")


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fail(message: str, exit_code: int = 2) -> None:
    print(f"aisc: {message}", file=sys.stderr)
    sys.exit(exit_code)


def normalize_path(raw: str) -> str:
    """Workspace-relative path; accepts the container mount prefix agents
    naturally pass (/root/app/...), mirroring the host's
    _normalize_record_path tolerance."""
    p = raw.replace("\\", "/")
    prefix = WORKSPACE_MOUNT + "/"
    if p.startswith(prefix):
        p = p[len(prefix):]
    if p.startswith("/"):
        _fail(f"path must be workspace-relative (got absolute path outside {WORKSPACE_MOUNT}): {raw}")
    if not p or p == "." or p.startswith("../") or ".." in p.split("/"):
        _fail(f"invalid workspace-relative path: {raw}")
    return p


def registry_file(root: Path, workspace_hash: str, session_id: str) -> Path:
    return root / workspace_hash[:16] / f"{session_id}.jsonl"


def _acquire_lock(lock_path: Path, timeout: float = 10.0) -> None:
    import time

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 30:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                _fail(f"registry lock timeout: {lock_path}", 1)
            time.sleep(0.1)


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def do_record(args: argparse.Namespace) -> int:
    runtime_id = args.runtime_id or os.environ.get("AISC_RUNTIME_ID", "")
    session_id = args.session_id or os.environ.get("AISC_TERMINAL_SESSION_ID", "")
    agent = args.agent or os.environ.get("AISC_AGENT", "")
    workspace_hash = os.environ.get("AISC_WORKSPACE_HASH", "")
    root = Path(os.environ.get("AISC_ARTIFACT_ROOT", DEFAULT_ROOT))

    missing = [name for name, val in (
        ("--runtime-id (or env AISC_RUNTIME_ID)", runtime_id),
        ("--session-id (or env AISC_TERMINAL_SESSION_ID)", session_id),
        ("--agent (or env AISC_AGENT)", agent),
        ("env AISC_WORKSPACE_HASH", workspace_hash),
    ) if not val]
    if missing:
        _fail("missing " + ", ".join(missing))
    if agent not in AGENTS:
        _fail(f"invalid agent: {agent}")
    if args.action not in ACTIONS:
        _fail(f"invalid action: {args.action}")
    if args.kind not in KINDS:
        _fail(f"invalid kind: {args.kind}")
    if args.open_with not in OPEN_WITH:
        _fail(f"invalid open_with: {args.open_with}")

    rel = normalize_path(args.path)
    previous = normalize_path(args.previous_path) if args.previous_path else None
    if args.action == "renamed" and not previous:
        _fail("renamed action requires --previous-path")

    artifact_id = str(uuid.uuid5(
        _ID_NAMESPACE, f"{workspace_hash}/{session_id}/{rel}/{args.action}/{args.kind}"))

    record = {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "workspace_relative_path": rel,
        "action": args.action,
        "kind": args.kind,
        "media_type": args.media_type,
        "label": args.label or "",
        "open_with": args.open_with,
        "producer": {
            "agent": agent,
            "session_id": session_id,
            "runtime_id": runtime_id,
        },
        "state": "present",
        "provenance": "manifest",
        "recorded_at": _utc_now(),
        "previous_path": previous,
        "extra": {},
    }

    path = registry_file(root, workspace_hash, session_id)
    lock = path.with_suffix(".lock")
    _acquire_lock(lock)
    try:
        kept = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    existing = json.loads(line)
                except ValueError:
                    continue  # corrupt line: isolate, keep the rest
                if existing.get("artifact_id") == artifact_id:
                    continue  # replace
                kept.append(existing)
        kept.append(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".artifacts_", dir=str(path.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for rec in kept:
                    f.write(json.dumps(rec, ensure_ascii=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    finally:
        _release_lock(lock)

    print(json.dumps({
        "recorded": True,
        "artifact_id": artifact_id,
        "path": rel,
        "agent": agent,
    }, ensure_ascii=True))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="aisc",
        description="Container-side aisc bridge (artifact recording only)",
    )
    sub = parser.add_subparsers(dest="command")

    rec = sub.add_parser("artifact", help="Agent artifact fact protocol")
    rec_sub = rec.add_subparsers(dest="artifact_command")
    rr = rec_sub.add_parser("record", help="Record an agent artifact fact")
    rr.add_argument("--runtime-id", default=None,
                    help="default: env AISC_RUNTIME_ID")
    rr.add_argument("--session-id", default=None,
                    help="default: env AISC_TERMINAL_SESSION_ID")
    rr.add_argument("--agent", default=None, help="default: env AISC_AGENT")
    rr.add_argument("--path", required=True,
                    help="Workspace-relative path (/root/app/ prefix tolerated)")
    rr.add_argument("--action", default="created", choices=list(ACTIONS))
    rr.add_argument("--kind", default="deliverable", choices=list(KINDS))
    rr.add_argument("--media-type", default=None)
    rr.add_argument("--label", default="")
    rr.add_argument("--open-with", default="preview", choices=list(OPEN_WITH))
    rr.add_argument("--previous-path", default=None)

    args = parser.parse_args(argv)
    if getattr(args, "artifact_command", None) == "record":
        return do_record(args)
    parser.print_help()
    return 0 if getattr(args, "command", None) is None else 2


if __name__ == "__main__":
    sys.exit(main())
